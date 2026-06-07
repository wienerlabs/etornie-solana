"""EVM (Ethereum/Moca) wallet identity: nonce + EIP-191 verification.

Unified identity (#74): a user proves ownership of an EVM address by
signing a nonce message (``personal_sign`` / EIP-191). The same nonce
flow backs two endpoints:

* **link**  — an authenticated user binds the EVM address to their
  account.
* **login** — an unauthenticated request resolves the EVM address to the
  already-linked account, so signing in with the EVM wallet reaches the
  same etornie handle (never a second one).

Mirrors :mod:`app.auth.wallet_service` (Solana) — same Redis-cached,
single-use nonce design.
"""
from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import redis
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.users.models import User

NONCE_TTL_SECONDS = 300
_KEY_PREFIX = "evm_nonce:"
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

_redis: redis.Redis | None = None


class EvmAuthError(Exception):
    """Base class for EVM identity errors."""


class InvalidEvmAddress(EvmAuthError):
    pass


class NonceNotFound(EvmAuthError):
    pass


class MessageMismatch(EvmAuthError):
    pass


class InvalidSignature(EvmAuthError):
    pass


class EvmAlreadyLinked(EvmAuthError):
    """The EVM address is already linked to a different account."""


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def normalize_address(address: str) -> str:
    """Validate + lowercase an EVM address."""

    if not address or not _ADDRESS_RE.match(address.strip()):
        raise InvalidEvmAddress(f"not a valid EVM address: {address!r}")
    return address.strip().lower()


def _build_message(
    address: str, nonce: str, issued_at: datetime, expires_at: datetime
) -> str:
    return "\n".join(
        [
            "Etornie EVM Identity",
            "",
            "Sign this message to link or sign in with this EVM wallet.",
            "This proves you control the address. No transaction is sent.",
            "",
            f"Address: {address}",
            f"Nonce: {nonce}",
            f"Issued: {issued_at.astimezone(timezone.utc).isoformat()}",
            f"Expires: {expires_at.astimezone(timezone.utc).isoformat()}",
        ]
    )


def generate_nonce(address: str) -> tuple[str, str, datetime]:
    """Issue a single-use nonce + message for an EVM address."""

    addr = normalize_address(address)
    nonce = secrets.token_hex(16)
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=NONCE_TTL_SECONDS)
    message = _build_message(addr, nonce, issued_at, expires_at)

    _get_redis().set(
        f"{_KEY_PREFIX}{addr}",
        json.dumps({"message": message, "nonce": nonce}),
        ex=NONCE_TTL_SECONDS,
    )
    return nonce, message, expires_at


def _consume_nonce(address: str) -> dict:
    r = _get_redis()
    key = f"{_KEY_PREFIX}{address}"
    pipe = r.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _ = pipe.execute()
    if raw is None:
        raise NonceNotFound("no pending nonce for this address, or it expired")
    return json.loads(raw)


def verify_signature(address: str, submitted_message: str, signature: str) -> str:
    """Verify an EIP-191 signature. Consumes the nonce. Returns the address.

    Raises an :class:`EvmAuthError` subclass on any failure.
    """

    addr = normalize_address(address)
    cached = _consume_nonce(addr)
    if submitted_message != cached["message"]:
        raise MessageMismatch("submitted message does not match the issued challenge")

    try:
        recovered = Account.recover_message(
            encode_defunct(text=submitted_message), signature=signature
        )
    except Exception as exc:  # noqa: BLE001 — any recovery failure is invalid
        raise InvalidSignature(f"could not recover signer: {exc}") from exc

    if recovered.lower() != addr:
        raise InvalidSignature("signature does not match the address")
    return addr


async def get_user_by_evm(db: AsyncSession, address: str) -> User | None:
    addr = normalize_address(address)
    return (
        await db.execute(select(User).where(func.lower(User.evm_address) == addr))
    ).scalar_one_or_none()


async def link_evm_address(db: AsyncSession, user: User, address: str) -> None:
    """Bind a verified EVM address to ``user``. Caller verifies first."""

    addr = normalize_address(address)
    existing = await get_user_by_evm(db, addr)
    if existing is not None and existing.id != user.id:
        raise EvmAlreadyLinked("this EVM wallet is already linked to another account")
    user.evm_address = addr
    await db.flush()


async def unlink_evm_address(db: AsyncSession, user: User) -> None:
    user.evm_address = None
    await db.flush()
