import importlib
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')

import pytest
from solders.hash import Hash
from solders.instruction import CompiledInstruction
from solders.message import MessageHeader, MessageV0
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID

import app.config as app_config
import app.solana.client as client


OPERATOR = Pubkey.from_string("11111111111111111111111111111112")
USER = Pubkey.from_string("11111111111111111111111111111113")
TREASURY = Pubkey.from_string("11111111111111111111111111111114")
OTHER_PROGRAM = Pubkey.from_string("11111111111111111111111111111115")

FEE = 10_000_000


def _transfer_data(lamports: int) -> bytes:
    return (2).to_bytes(4, "little") + lamports.to_bytes(8, "little")


def _build_message(instructions, account_keys, num_required_signatures):
    header = MessageHeader(
        num_required_signatures=num_required_signatures,
        num_readonly_signed_accounts=0,
        num_readonly_unsigned_accounts=0,
    )
    return MessageV0(
        header=header,
        account_keys=account_keys,
        recent_blockhash=Hash.default(),
        instructions=instructions,
        address_table_lookups=[],
    )


def _message_with_user_transfer(lamports: int) -> MessageV0:
    account_keys = [OPERATOR, USER, TREASURY, SYSTEM_PROGRAM_ID]
    transfer = CompiledInstruction(
        program_id_index=3,
        accounts=bytes([1, 2]),
        data=_transfer_data(lamports),
    )
    return _build_message([transfer], account_keys, num_required_signatures=2)


def _message_with_operator_transfer(lamports: int) -> MessageV0:
    account_keys = [OPERATOR, USER, TREASURY, SYSTEM_PROGRAM_ID]
    transfer = CompiledInstruction(
        program_id_index=3,
        accounts=bytes([0, 2]),
        data=_transfer_data(lamports),
    )
    return _build_message([transfer], account_keys, num_required_signatures=2)


def _message_without_transfer() -> MessageV0:
    account_keys = [OPERATOR, USER, OTHER_PROGRAM]
    unrelated = CompiledInstruction(
        program_id_index=2,
        accounts=bytes([1]),
        data=bytes([9, 9, 9, 9]),
    )
    return _build_message([unrelated], account_keys, num_required_signatures=2)


@pytest.fixture
def treasury_set(monkeypatch):
    monkeypatch.setattr(
        app_config.settings, "fee_treasury_vault", str(TREASURY), raising=False
    )
    monkeypatch.setattr(client.settings, "fee_treasury_vault", str(TREASURY), raising=False)


def test_sum_counts_exact_user_transfer():
    message = _message_with_user_transfer(FEE)
    total = client.sum_user_transfers_to_treasury(message, OPERATOR, TREASURY)
    assert total == FEE


def test_sum_ignores_operator_transfer():
    message = _message_with_operator_transfer(FEE)
    total = client.sum_user_transfers_to_treasury(message, OPERATOR, TREASURY)
    assert total == 0


def test_exact_user_fee_passes(treasury_set):
    message = _message_with_user_transfer(FEE)
    client.assert_treasury_fee_paid(message, OPERATOR, FEE)


def test_absent_transfer_raises(treasury_set):
    message = _message_without_transfer()
    with pytest.raises(client.SolanaClientError):
        client.assert_treasury_fee_paid(message, OPERATOR, FEE)


def test_insufficient_amount_raises(treasury_set):
    message = _message_with_user_transfer(FEE - 1)
    with pytest.raises(client.SolanaClientError):
        client.assert_treasury_fee_paid(message, OPERATOR, FEE)


def test_operator_transfer_does_not_count(treasury_set):
    message = _message_with_operator_transfer(FEE)
    with pytest.raises(client.SolanaClientError):
        client.assert_treasury_fee_paid(message, OPERATOR, FEE)


def test_treasury_unset_is_noop(monkeypatch):
    monkeypatch.setattr(client.settings, "fee_treasury_vault", "", raising=False)
    message = _message_without_transfer()
    client.assert_treasury_fee_paid(message, OPERATOR, FEE)


ATTESTATION = Pubkey.from_string("11111111111111111111111111111116")
NFT_PROGRAM = Pubkey.from_string(client._NFT_PROGRAM_ID)
ATA_PROGRAM = Pubkey.from_string(client._ASSOCIATED_TOKEN_PROGRAM_ID)


class _FakeMessageWithLookupTables:
    address_table_lookups = [object()]


def test_allowlist_accepts_program_plus_user_fee():
    account_keys = [OPERATOR, USER, TREASURY, SYSTEM_PROGRAM_ID, ATTESTATION]
    fee = CompiledInstruction(
        program_id_index=3, accounts=bytes([1, 2]), data=_transfer_data(FEE)
    )
    prog = CompiledInstruction(
        program_id_index=4, accounts=bytes([0, 1]), data=bytes([7, 7, 7, 7])
    )
    message = _build_message([fee, prog], account_keys, num_required_signatures=2)
    client.assert_only_expected_programs(
        message, OPERATOR, {ATTESTATION}, TREASURY
    )


def test_allowlist_rejects_operator_drain():
    account_keys = [OPERATOR, USER, TREASURY, SYSTEM_PROGRAM_ID, ATTESTATION]
    fee = CompiledInstruction(
        program_id_index=3, accounts=bytes([1, 2]), data=_transfer_data(FEE)
    )
    drain = CompiledInstruction(
        program_id_index=3, accounts=bytes([0, 1]), data=_transfer_data(5_000_000_000)
    )
    prog = CompiledInstruction(
        program_id_index=4, accounts=bytes([0, 1]), data=bytes([7])
    )
    message = _build_message(
        [fee, drain, prog], account_keys, num_required_signatures=2
    )
    with pytest.raises(client.SolanaClientError):
        client.assert_only_expected_programs(
            message, OPERATOR, {ATTESTATION}, TREASURY
        )


def test_allowlist_rejects_unexpected_program():
    account_keys = [OPERATOR, USER, OTHER_PROGRAM]
    ix = CompiledInstruction(
        program_id_index=2, accounts=bytes([1]), data=bytes([9, 9, 9, 9])
    )
    message = _build_message([ix], account_keys, num_required_signatures=2)
    with pytest.raises(client.SolanaClientError):
        client.assert_only_expected_programs(
            message, OPERATOR, {ATTESTATION}, TREASURY
        )


def test_allowlist_event_rejects_system_instruction():
    account_keys = [OPERATOR, USER, TREASURY, SYSTEM_PROGRAM_ID, ATTESTATION]
    fee = CompiledInstruction(
        program_id_index=3, accounts=bytes([1, 2]), data=_transfer_data(FEE)
    )
    prog = CompiledInstruction(
        program_id_index=4, accounts=bytes([0, 1]), data=bytes([7])
    )
    message = _build_message([fee, prog], account_keys, num_required_signatures=2)
    with pytest.raises(client.SolanaClientError):
        client.assert_only_expected_programs(message, OPERATOR, {ATTESTATION}, None)


def test_allowlist_event_accepts_program_only():
    account_keys = [OPERATOR, USER, ATTESTATION]
    prog = CompiledInstruction(
        program_id_index=2, accounts=bytes([0, 1]), data=bytes([7])
    )
    message = _build_message([prog], account_keys, num_required_signatures=2)
    client.assert_only_expected_programs(message, OPERATOR, {ATTESTATION}, None)


def test_allowlist_accepts_mint_instruction_set():
    account_keys = [
        OPERATOR,
        USER,
        TREASURY,
        SYSTEM_PROGRAM_ID,
        NFT_PROGRAM,
        ATA_PROGRAM,
    ]
    fee = CompiledInstruction(
        program_id_index=3, accounts=bytes([1, 2]), data=_transfer_data(FEE)
    )
    ata = CompiledInstruction(
        program_id_index=5, accounts=bytes([0, 1]), data=bytes([1])
    )
    mint = CompiledInstruction(
        program_id_index=4, accounts=bytes([0, 1]), data=bytes([7])
    )
    message = _build_message(
        [fee, ata, mint], account_keys, num_required_signatures=2
    )
    client.assert_only_expected_programs(
        message, OPERATOR, {NFT_PROGRAM, ATA_PROGRAM}, TREASURY
    )


def test_allowlist_rejects_address_lookup_tables():
    with pytest.raises(client.SolanaClientError):
        client.assert_only_expected_programs(
            _FakeMessageWithLookupTables(), OPERATOR, {ATTESTATION}, TREASURY
        )
