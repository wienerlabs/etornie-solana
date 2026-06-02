"""Anchor event decoding for on-chain reconciliation (#19).

Helius delivers the log messages of every transaction touching our three
program IDs. Anchor programs emit events as ``Program data: <base64>`` log
lines, where the bytes are an 8-byte event discriminator followed by the
Borsh-serialized event fields. We decode the three events our programs emit so
the webhook consumer can reconcile DB rows against the chain.

The schemas below mirror the committed IDLs (``idl/etornie_attestation.json``,
``idl/etornie_ip_token.json``) — discriminators and field layouts are taken
verbatim from them, and ``test_solana_events.py`` cross-checks them against the
IDLs so the two cannot silently drift. They are embedded (rather than loading
the IDL at runtime) so decoding has no filesystem dependency and behaves
identically in the container, in CI and in tests — ``idl/`` lives at the repo
root and is not shipped inside the backend image.

The event fields are all fixed-size (no Borsh var-length types), so decoding is
a straight walk over byte offsets.
"""

from __future__ import annotations

import base64
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final

import base58
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.models import Case, CaseEvent, CaseNftState

logger = logging.getLogger(__name__)

_LOG_PREFIX: Final = "Program data: "

# field kind -> byte width
_KIND_SIZE: Final[dict[str, int]] = {
    "bytes16": 16,  # [u8; 16]  — a UUID (case_id)
    "hash32": 32,  # [u8; 32]  — a SHA-256 / metadata hash
    "pubkey": 32,  # Pubkey    — base58-encoded on decode
    "u8": 1,
    "i64": 8,
}


@dataclass(frozen=True)
class _Field:
    name: str
    kind: str

    @property
    def size(self) -> int:
        return _KIND_SIZE[self.kind]


@dataclass(frozen=True)
class EventSchema:
    program: str
    name: str
    discriminator: bytes
    fields: tuple[_Field, ...]


# Mirrors idl/*.json (cross-checked in test_solana_events.py).
EVENT_SCHEMAS: Final[tuple[EventSchema, ...]] = (
    EventSchema(
        program="etornie_attestation",
        name="CaseAttestationUpdated",
        discriminator=bytes((242, 135, 167, 44, 46, 36, 234, 172)),
        fields=(
            _Field("case_id", "bytes16"),
            _Field("old_metadata_hash", "hash32"),
            _Field("new_metadata_hash", "hash32"),
            _Field("event_type", "u8"),
            _Field("actor", "pubkey"),
            _Field("operator", "pubkey"),
            _Field("timestamp", "i64"),
        ),
    ),
    EventSchema(
        program="etornie_ip_token",
        name="CaseNftMinted",
        discriminator=bytes((251, 117, 139, 107, 151, 7, 234, 115)),
        fields=(
            _Field("case_id", "bytes16"),
            _Field("mint", "pubkey"),
            _Field("client_wallet", "pubkey"),
            _Field("operator", "pubkey"),
            _Field("metadata_uri_hash", "hash32"),
            _Field("timestamp", "i64"),
        ),
    ),
    EventSchema(
        program="etornie_ip_token",
        name="CaseNftBurned",
        discriminator=bytes((65, 120, 160, 68, 228, 3, 113, 138)),
        fields=(
            _Field("case_id", "bytes16"),
            _Field("mint", "pubkey"),
            _Field("operator", "pubkey"),
            _Field("timestamp", "i64"),
        ),
    ),
)

_BY_DISCRIMINATOR: Final[dict[bytes, EventSchema]] = {
    s.discriminator: s for s in EVENT_SCHEMAS
}


@dataclass(frozen=True)
class DecodedEvent:
    """One decoded Anchor event. ``case_id`` is pulled out because every event
    carries it and the reconciler keys off it; ``values`` holds all fields
    (UUID / hex / base58 / int) by name."""

    program: str
    name: str
    case_id: uuid.UUID
    values: dict[str, object]


def _decode_value(kind: str, raw: bytes) -> object:
    if kind == "bytes16":
        return uuid.UUID(bytes=raw)
    if kind == "hash32":
        return raw.hex()
    if kind == "pubkey":
        return base58.b58encode(raw).decode("ascii")
    if kind == "u8":
        return raw[0]
    if kind == "i64":
        return int.from_bytes(raw, "little", signed=True)
    raise ValueError(f"unknown field kind: {kind}")


def decode_event(payload: bytes) -> DecodedEvent | None:
    """Decode one event payload (8-byte discriminator + Borsh fields).

    Returns ``None`` when the discriminator is not one of ours or the payload
    is truncated — both are normal (we see every event from the programs, not
    just the ones we model).
    """
    if len(payload) < 8:
        return None
    schema = _BY_DISCRIMINATOR.get(payload[:8])
    if schema is None:
        return None

    offset = 8
    values: dict[str, object] = {}
    for fld in schema.fields:
        chunk = payload[offset : offset + fld.size]
        if len(chunk) != fld.size:
            return None  # truncated / malformed
        values[fld.name] = _decode_value(fld.kind, chunk)
        offset += fld.size

    case_id = values["case_id"]
    assert isinstance(case_id, uuid.UUID)  # noqa: S101 — layout guarantees it
    return DecodedEvent(
        program=schema.program,
        name=schema.name,
        case_id=case_id,
        values=values,
    )


def decode_log_events(log_messages: list[str]) -> list[DecodedEvent]:
    """Decode every event we recognise from a transaction's log messages."""
    decoded: list[DecodedEvent] = []
    for line in log_messages:
        if not line.startswith(_LOG_PREFIX):
            continue
        encoded = line[len(_LOG_PREFIX) :].strip()
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            continue
        event = decode_event(payload)
        if event is not None:
            decoded.append(event)
    return decoded


# ---------------------------------------------------------------------------
# Reconciliation — apply decoded events to the DB, idempotently.
# ---------------------------------------------------------------------------

# Per-program counters, accumulated across webhook deliveries (#19 AC: "per
# program reconciliation metrics"). Surfaced via reconciliation_metrics() and
# logged per delivery by the webhook handler.
_METRIC_KEYS: Final = ("received", "reconciled", "skipped", "failed")
_metrics: dict[str, dict[str, int]] = {}


def _bump(program: str, key: str) -> None:
    _metrics.setdefault(program, dict.fromkeys(_METRIC_KEYS, 0))[key] += 1


def reconciliation_metrics() -> dict[str, dict[str, int]]:
    """Snapshot of cumulative per-program reconciliation counters."""
    return {program: dict(counts) for program, counts in _metrics.items()}


@dataclass
class ReconcileResult:
    received: int = 0
    reconciled: int = 0
    skipped: int = 0
    failed: int = 0
    by_program: dict[str, dict[str, int]] = field(default_factory=dict)


async def reconcile_events(
    db: AsyncSession, events: list[DecodedEvent], signature: str
) -> ReconcileResult:
    """Apply each decoded event to its Case row, idempotently.

    ``reconciled`` counts events that changed DB state, ``skipped`` those
    already in sync (or for an unknown case), ``failed`` those that raised. A
    single bad event never aborts the batch. The session is committed once at
    the end.
    """
    result = ReconcileResult()
    for event in events:
        result.received += 1
        _bump(event.program, "received")
        try:
            changed = await _reconcile_one(db, event, signature)
        except Exception:
            logger.exception(
                "reconcile failed: event=%s case=%s tx=%s",
                event.name,
                event.case_id,
                signature,
            )
            result.failed += 1
            _bump(event.program, "failed")
            continue
        if changed:
            result.reconciled += 1
            _bump(event.program, "reconciled")
        else:
            result.skipped += 1
            _bump(event.program, "skipped")

    if result.reconciled:
        await db.commit()
    result.by_program = reconciliation_metrics()
    return result


async def _reconcile_one(db: AsyncSession, event: DecodedEvent, signature: str) -> bool:
    """Reconcile one event. Returns True when it changed DB state."""
    case = (
        await db.execute(select(Case).where(Case.id == event.case_id))
    ).scalar_one_or_none()
    if case is None:
        logger.warning(
            "reconcile: no case %s for %s (tx %s)",
            event.case_id,
            event.name,
            signature,
        )
        return False

    if event.name == "CaseAttestationUpdated":
        return await _reconcile_attestation(db, case, event, signature)
    if event.name == "CaseNftMinted":
        return _reconcile_nft_minted(case, event, signature)
    if event.name == "CaseNftBurned":
        return _reconcile_nft_burned(case, event, signature)
    return False


async def _reconcile_attestation(
    db: AsyncSession, case: Case, event: DecodedEvent, signature: str
) -> bool:
    """Back-fill a missing attestation tx and record the lifecycle event.

    Idempotent on (case, tx, event_type): a re-delivered webhook does not
    duplicate the CaseEvent row.
    """
    event_type = int(event.values["event_type"])  # type: ignore[call-overload]
    already = (
        await db.execute(
            select(CaseEvent.id).where(
                CaseEvent.case_id == case.id,
                CaseEvent.tx_signature == signature,
                CaseEvent.event_type == event_type,
            )
        )
    ).first()
    if already is not None:
        return False

    db.add(
        CaseEvent(
            case_id=case.id,
            event_type=event_type,
            tx_signature=signature,
            actor_wallet=str(event.values["actor"]),
            metadata_hash=str(event.values["new_metadata_hash"]),
        )
    )
    if not case.attestation_tx:
        case.attestation_tx = signature
    return True


def _reconcile_nft_minted(case: Case, event: DecodedEvent, signature: str) -> bool:
    mint = str(event.values["mint"])
    if case.nft_state == CaseNftState.minted and case.nft_mint == mint:
        return False
    case.nft_mint = mint
    case.nft_state = CaseNftState.minted
    case.nft_mint_tx = signature
    if not case.client_wallet:
        case.client_wallet = str(event.values["client_wallet"])
    return True


def _reconcile_nft_burned(case: Case, event: DecodedEvent, signature: str) -> bool:
    if case.nft_state == CaseNftState.burned:
        return False
    case.nft_state = CaseNftState.burned
    case.nft_burn_tx = signature
    raw_ts = event.values.get("timestamp")
    case.nft_burned_at = (
        datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)  # type: ignore[arg-type]
        if raw_ts
        else datetime.now(timezone.utc)
    )
    return True
