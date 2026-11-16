"""Wallet sign-in must issue a DB-backed refresh token (issue #35 review).

/auth/wallet/verify used to mint the old stateless JWT refresh token.
/auth/refresh only accepts tokens persisted in refresh_tokens, so every
wallet session failed its first refresh and the user was logged out when
the 30-minute access token expired. This test runs the real
nonce -> sign -> verify -> refresh flow with an ed25519 keypair.
"""
from __future__ import annotations

import base58
import nacl.signing
from httpx import AsyncClient


async def _wallet_sign_in(client: AsyncClient) -> dict:
    signing_key = nacl.signing.SigningKey.generate()
    wallet_address = base58.b58encode(
        bytes(signing_key.verify_key)
    ).decode("ascii")

    nonce_resp = await client.post(
        "/auth/wallet/nonce", json={"wallet_address": wallet_address}
    )
    assert nonce_resp.status_code == 200
    message = nonce_resp.json()["message"]

    signature = signing_key.sign(message.encode("utf-8")).signature
    verify_resp = await client.post(
        "/auth/wallet/verify",
        json={
            "wallet_address": wallet_address,
            "message": message,
            "signature": base58.b58encode(signature).decode("ascii"),
        },
    )
    assert verify_resp.status_code == 200
    return verify_resp.json()


async def test_wallet_refresh_token_can_be_refreshed(
    client: AsyncClient,
) -> None:
    tokens = await _wallet_sign_in(client)
    assert tokens["refresh_token"]

    refresh_resp = await client.post(
        "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_resp.status_code == 200
    rotated = refresh_resp.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    assert rotated["access_token"]


async def test_wallet_refresh_token_is_single_use(
    client: AsyncClient,
) -> None:
    tokens = await _wallet_sign_in(client)
    old_refresh = tokens["refresh_token"]

    first = await client.post(
        "/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert replay.status_code == 401
