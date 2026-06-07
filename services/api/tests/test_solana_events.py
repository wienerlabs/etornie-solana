"""Tests for the Helius event decoder + reconciler (#19).

Real decoding (bytes built exactly as the on-chain program emits them) and real
DB reconciliation (the test session + a Case fixture). No mocks except patching
the webhook auth secret. A cross-check asserts the embedded event schemas still
match the committed IDLs, so they cannot silently drift.
"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import base58
import pytest

from app.cases.models import CaseNftState
from app.solana.events import (
    EVENT_SCHEMAS,
    DecodedEvent,
    decode_log_events,
    reconcile_events,
)

_MINTED_DISCRIMINATOR = bytes((251, 117, 139, 107, 151, 7, 234, 115))


def _program_data_line(payload: bytes) -> str:
    return "Program data: " + base64.b64encode(payload).decode("ascii")


@pytest.mark.unit
class TestDecode:
    def test_decode_minted_event(self) -> None:
        case_id = uuid.uuid4()
        mint = bytes(range(32))
        wallet = bytes(range(32, 64))
        operator = bytes([7] * 32)
        meta_hash = bytes([9] * 32)
        ts = 1_700_000_000
        payload = (
            _MINTED_DISCRIMINATOR
            + case_id.bytes
            + mint
            + wallet
            + operator
            + meta_hash
            + ts.to_bytes(8, "little", signed=True)
        )
        events = decode_log_events(
            ["Program log: noise", _program_data_line(payload), "not data"]
        )
        assert len(events) == 1
        event = events[0]
        assert event.name == "CaseNftMinted"
        assert event.program == "etornie_ip_token"
        assert event.case_id == case_id
        assert event.values["mint"] == base58.b58encode(mint).decode("ascii")
        assert event.values["client_wallet"] == base58.b58encode(wallet).decode("ascii")
        assert event.values["metadata_uri_hash"] == meta_hash.hex()
        assert event.values["timestamp"] == ts

    def test_unknown_discriminator_ignored(self) -> None:
        payload = bytes(range(8)) + bytes(64)  # not one of ours
        assert decode_log_events([_program_data_line(payload)]) == []

    def test_non_event_lines_ignored(self) -> None:
        assert decode_log_events(["Program log: hi", "Program invoke [1]"]) == []


@pytest.mark.unit
class TestSchemasMatchIDL:
    def test_discriminators_match_committed_idls(self) -> None:
        idl_dir = Path(__file__).resolve().parents[3] / "idl"
        if not idl_dir.exists():
            pytest.skip("idl/ not present in this checkout")
        from_idl: dict[tuple[str, str], list[int]] = {}
        for fname, program in (
            ("etornie_attestation.json", "etornie_attestation"),
            ("etornie_ip_token.json", "etornie_ip_token"),
        ):
            idl = json.loads((idl_dir / fname).read_text())
            for event in idl.get("events", []):
                from_idl[(program, event["name"])] = event["discriminator"]
        for schema in EVENT_SCHEMAS:
            key = (schema.program, schema.name)
            assert key in from_idl, f"{key} missing from committed IDL"
            assert from_idl[key] == list(schema.discriminator), (
                f"discriminator drift for {key}"
            )


@pytest.mark.integration
class TestReconcile:
    async def test_mint_reconciles_and_is_idempotent(
        self, db_session, case_fixture
    ) -> None:
        mint = base58.b58encode(bytes([3] * 32)).decode("ascii")
        event = DecodedEvent(
            program="etornie_ip_token",
            name="CaseNftMinted",
            case_id=case_fixture.id,
            values={
                "case_id": case_fixture.id,
                "mint": mint,
                "client_wallet": base58.b58encode(bytes([4] * 32)).decode("ascii"),
                "operator": base58.b58encode(bytes([5] * 32)).decode("ascii"),
                "metadata_uri_hash": "00" * 32,
                "timestamp": 1_700_000_000,
            },
        )
        result = await reconcile_events(db_session, [event], "sig-mint-1")
        assert result.reconciled == 1

        await db_session.refresh(case_fixture)
        assert case_fixture.nft_state == CaseNftState.minted
        assert case_fixture.nft_mint == mint
        assert case_fixture.nft_mint_tx == "sig-mint-1"

        # Re-delivery must not change anything.
        again = await reconcile_events(db_session, [event], "sig-mint-1")
        assert again.reconciled == 0
        assert again.skipped == 1

    async def test_unknown_case_is_skipped(self, db_session) -> None:
        event = DecodedEvent(
            program="etornie_ip_token",
            name="CaseNftBurned",
            case_id=uuid.uuid4(),  # no such case
            values={"case_id": uuid.uuid4(), "mint": "x", "timestamp": 1},
        )
        result = await reconcile_events(db_session, [event], "sig-x")
        assert result.reconciled == 0
        assert result.skipped == 1


@pytest.mark.integration
class TestWebhookAuth:
    async def test_rejects_wrong_auth(self, client) -> None:
        from app.config import settings

        with patch.object(settings, "helius_webhook_auth", "secret-xyz"):
            resp = await client.post(
                "/solana/webhooks/helius",
                json=[],
                headers={"Authorization": "wrong"},
            )
        assert resp.status_code == 401

    async def test_rejects_when_unconfigured(self, client) -> None:
        from app.config import settings

        with patch.object(settings, "helius_webhook_auth", ""):
            resp = await client.post(
                "/solana/webhooks/helius",
                json=[],
                headers={"Authorization": "anything"},
            )
        assert resp.status_code == 401

    async def test_accepts_correct_auth(self, client) -> None:
        from app.config import settings

        with patch.object(settings, "helius_webhook_auth", "secret-xyz"):
            resp = await client.post(
                "/solana/webhooks/helius",
                json=[],
                headers={"Authorization": "secret-xyz"},
            )
        assert resp.status_code == 200
        assert resp.json()["received"] == 0
