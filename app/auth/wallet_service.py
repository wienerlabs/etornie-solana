"""Solana wallet authentication service.

Implements a nonce-based challenge/response flow using ed25519 signatures:

1. Client requests a nonce for a given base58 wallet pubkey.
2. Server generates a cryptographically random 32 byte nonce, builds a
   deterministic sign-in message that includes the nonce, and stores the
   entire message in Redis with a 5 minute TTL keyed by the pubkey.
3. Client signs the exact message bytes with the wallet's private key.
4. Client POSTs the message and the base58 signature.
5. Server looks up the cached message, verifies that the submitted message
   matches (prevents message-swapping attacks), verifies the ed25519
   signature against the wallet pubkey, then consumes the nonce.

On a successful verification, a user is fetched or created and a JWT is
issued. Wallet-only users are assigned a short public_handle derived from
the first eight characters of the base58 pubkey, with a numeric counter
fallback if the deterministic candidate is already taken.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import base58
import nacl.exceptions
import nacl.signing
import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.users.models import AuthMethod, User, UserRole


logger = logging.getLogger(__name__)


NONCE_TTL_SECONDS = 300  # 5 minutes
NONCE_BYTES = 32
PUBKEY_MIN_LEN = 32
PUBKEY_MAX_LEN = 44
ED25519_PUBKEY_LEN = 32
ED25519_SIG_LEN = 64
HANDLE_PREFIX = "etornie_"
HANDLE_SLUG_LEN = 8
HANDLE_MAX_COUNTER_RETRIES = 100

_KEY_PREFIX = "wallet_nonce:"

_redis: redis.Redis | None = None


class WalletAuthError(Exception):
    """Base class for wallet authentication errors."""


class InvalidWalletAddress(WalletAuthError):
    pass


class NonceNotFound(WalletAuthError):
    pass


class MessageMismatch(WalletAuthError):
    pass


class InvalidSignature(WalletAuthError):
    pass


class HandleGenerationFailed(WalletAuthError):
    pass


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def decode_pubkey(wallet_address: str) -> bytes:
    """Decode a base58 Solana pubkey into exactly 32 bytes.

    Raises InvalidWalletAddress on any decode or length error.
    """
    if not wallet_address:
        raise InvalidWalletAddress("wallet_address is empty")
    try:
        raw = base58.b58decode(wallet_address)
    except ValueError as exc:
        raise InvalidWalletAddress(f"not valid base58: {exc}") from exc
    if len(raw) != ED25519_PUBKEY_LEN:
        raise InvalidWalletAddress(
            f"pubkey must be {ED25519_PUBKEY_LEN} bytes, got {len(raw)}"
        )
    return raw


def _build_sign_in_message(
    wallet_address: str,
    nonce_b58: str,
    issued_at: datetime,
    expires_at: datetime,
) -> str:
    """Produce the human-readable message that the wallet will sign.

    The exact bytes of this string must be submitted back. We fix the layout
    with stable field ordering and ISO-8601 timestamps so the client and
    server can reproduce the same bytes deterministically.
    """
    lines = [
        "Etornie Solana Authentication",
        "",
        "Sign this message to verify ownership of this wallet.",
        "You will be signed in if the wallet already has an account.",
        "A new account will be created otherwise.",
        "",
        f"Wallet: {wallet_address}",
        f"Nonce: {nonce_b58}",
        f"Issued: {issued_at.astimezone(timezone.utc).isoformat()}",
        f"Expires: {expires_at.astimezone(timezone.utc).isoformat()}",
    ]
    return "\n".join(lines)


def generate_nonce(wallet_address: str) -> tuple[str, str, datetime]:
    """Generate a fresh single-use nonce for the given wallet.

    Returns (nonce_b58, message, expires_at). The full message is cached in
    Redis under the wallet address. Any prior pending nonce for the same
    wallet is overwritten.
    """
    decode_pubkey(wallet_address)  # validates format early, raises if bad

    nonce_bytes = secrets.token_bytes(NONCE_BYTES)
    nonce_b58 = base58.b58encode(nonce_bytes).decode("ascii")

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=NONCE_TTL_SECONDS)

    message = _build_sign_in_message(wallet_address, nonce_b58, issued_at, expires_at)

    cache_payload = {
        "message": message,
        "nonce": nonce_b58,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    _get_redis().set(
        f"{_KEY_PREFIX}{wallet_address}",
        json.dumps(cache_payload),
        ex=NONCE_TTL_SECONDS,
    )

    return nonce_b58, message, expires_at


def _consume_cached_nonce(wallet_address: str) -> dict:
    """Fetch and atomically delete the cached nonce entry.

    Using a pipeline with GETDEL semantics: in redis-py, we do GET + DELETE
    in a MULTI/EXEC so a concurrent request cannot replay the same message.
    """
    r = _get_redis()
    key = f"{_KEY_PREFIX}{wallet_address}"
    pipe = r.pipeline()
    pipe.get(key)
    pipe.delete(key)
    raw, _deleted = pipe.execute()
    if raw is None:
        raise NonceNotFound("no pending nonce for this wallet, or it expired")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - cache corruption
        raise NonceNotFound("cached nonce payload is corrupt") from exc


def verify_signature(
    wallet_address: str,
    submitted_message: str,
    signature_b58: str,
) -> None:
    """Verify a signed sign-in message. Consumes the cached nonce.

    Raises specific WalletAuthError subclasses. On success, returns None.
    """
    pubkey_bytes = decode_pubkey(wallet_address)
    cached = _consume_cached_nonce(wallet_address)

    if cached["message"] != submitted_message:
        raise MessageMismatch(
            "submitted message does not match the one issued for this nonce"
        )

    try:
        signature_bytes = base58.b58decode(signature_b58)
    except ValueError as exc:
        raise InvalidSignature(f"signature not valid base58: {exc}") from exc

    if len(signature_bytes) != ED25519_SIG_LEN:
        raise InvalidSignature(
            f"signature must be {ED25519_SIG_LEN} bytes, got {len(signature_bytes)}"
        )

    verify_key = nacl.signing.VerifyKey(pubkey_bytes)
    try:
        verify_key.verify(submitted_message.encode("utf-8"), signature_bytes)
    except nacl.exceptions.BadSignatureError as exc:
        raise InvalidSignature("ed25519 verification failed") from exc


async def _candidate_handle_exists(db: AsyncSession, candidate: str) -> bool:
    result = await db.execute(
        select(User.id).where(User.public_handle == candidate)
    )
    return result.first() is not None


async def allocate_public_handle(db: AsyncSession, wallet_address: str) -> str:
    """Return a unique public_handle for the given wallet.

    Deterministic first choice is HANDLE_PREFIX + first 8 base58 chars. If
    that is already assigned to some other user, we append a two-digit
    counter starting at 2 until a free slot is found. Falls back to a
    secrets-based suffix after HANDLE_MAX_COUNTER_RETRIES.
    """
    slug = wallet_address[:HANDLE_SLUG_LEN]
    primary = f"{HANDLE_PREFIX}{slug}"
    if not await _candidate_handle_exists(db, primary):
        return primary

    for counter in range(2, HANDLE_MAX_COUNTER_RETRIES + 2):
        candidate = f"{HANDLE_PREFIX}{slug}_{counter}"
        if not await _candidate_handle_exists(db, candidate):
            return candidate

    for _attempt in range(8):
        random_suffix = secrets.token_urlsafe(4).replace("-", "").replace("_", "")[:6]
        candidate = f"{HANDLE_PREFIX}{slug}_{random_suffix}"
        if not await _candidate_handle_exists(db, candidate):
            return candidate

    raise HandleGenerationFailed(
        "could not allocate a unique public handle after many attempts"
    )


async def get_user_by_wallet(
    db: AsyncSession, wallet_address: str
) -> User | None:
    result = await db.execute(
        select(User).where(User.wallet_address == wallet_address)
    )
    return result.scalar_one_or_none()


async def authenticate_or_create(
    db: AsyncSession,
    wallet_address: str,
    full_name_hint: str | None = None,
) -> tuple[User, bool]:
    """Fetch the user for this wallet, or create one.

    Returns (user, created). Role is always UserRole.client for new wallet
    accounts. The auth_method of a new wallet-only user is AuthMethod.wallet.
    The caller is expected to have successfully verified a signature before
    calling this.
    """
    existing = await get_user_by_wallet(db, wallet_address)
    if existing is not None:
        if not existing.is_active:
            raise WalletAuthError("user is deactivated")
        return existing, False

    handle = await allocate_public_handle(db, wallet_address)
    full_name = (full_name_hint or handle).strip() or handle

    user = User(
        email=None,
        hashed_password=None,
        full_name=full_name,
        role=UserRole.client,
        wallet_address=wallet_address,
        public_handle=handle,
        auth_method=AuthMethod.wallet.value,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    logger.info(
        "wallet-only user created",
        extra={
            "user_id": str(user.id),
            "wallet_address": wallet_address,
            "public_handle": handle,
        },
    )
    return user, True


def pick_jwt_subject(user: User) -> str:
    """The JWT 'sub' claim. Always the UUID so case refs stay stable even
    if a user later links or unlinks a wallet/email."""
    return str(user.id)


def user_uuid_from_sub(sub: str) -> uuid.UUID:
    return uuid.UUID(sub)
