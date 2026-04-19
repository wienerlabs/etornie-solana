"""End-to-end wallet sign-in demo against a live backend.

Generates a real ed25519 keypair, requests a nonce, signs the challenge,
verifies it, and prints the resulting JWT + user record. Fails loudly if
any step does not behave correctly.

Usage:
    .venv/bin/python scripts/demo_wallet_auth.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from urllib import error, request

import base58
import nacl.signing
from jose import jwt


def _http_post(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _http_get(url: str, token: str) -> tuple[int, dict]:
    req = request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _decode_jwt_unverified(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a valid JWT")
    pad = "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(parts[1] + pad))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    print("=" * 70)
    print("ETORNIE SOLANA  wallet sign-in demo")
    print("=" * 70)

    signing_key = nacl.signing.SigningKey.generate()
    pubkey_bytes = bytes(signing_key.verify_key)
    wallet_address = base58.b58encode(pubkey_bytes).decode("ascii")
    print(f"\n[1/5] fresh ed25519 keypair")
    print(f"      wallet_address = {wallet_address}")

    print(f"\n[2/5] POST {base}/auth/wallet/nonce")
    status, body = _http_post(
        f"{base}/auth/wallet/nonce", {"wallet_address": wallet_address}
    )
    if status != 200:
        print(f"FAIL: status {status}: {body}")
        return 1
    nonce = body["nonce"]
    message = body["message"]
    print(f"      nonce      = {nonce}")
    print(f"      expires_at = {body['expires_at']}")

    print(f"\n[3/5] sign message with the wallet's private key (ed25519)")
    signature_bytes = signing_key.sign(message.encode("utf-8")).signature
    signature_b58 = base58.b58encode(signature_bytes).decode("ascii")
    print(f"      signature  = {signature_b58[:32]}...  ({len(signature_bytes)} bytes)")

    print(f"\n[4/5] POST {base}/auth/wallet/verify")
    status, body = _http_post(
        f"{base}/auth/wallet/verify",
        {
            "wallet_address": wallet_address,
            "message": message,
            "signature": signature_b58,
        },
    )
    if status != 200:
        print(f"FAIL: status {status}: {body}")
        return 1

    access = body["access_token"]
    user = body["user"]
    claims = _decode_jwt_unverified(access)
    print(f"      access_token  = {access[:40]}...")
    print(f"      refresh_token = {body['refresh_token'][:40]}...")
    print(f"      user.id       = {user['id']}")
    print(f"      user.role     = {user['role']}")
    print(f"      user.handle   = {user['public_handle']}")
    print(f"      user.wallet   = {user['wallet_address']}")
    print(f"      user.email    = {user['email']}")
    print(f"      user.auth     = {user['auth_method']}")
    print(f"      jwt.sub       = {claims['sub']}")
    print(f"      jwt.role      = {claims['role']}")
    print(f"      jwt.type      = {claims['type']}")

    assert user["wallet_address"] == wallet_address
    assert user["email"] is None
    assert user["auth_method"] == "wallet"
    assert user["public_handle"].startswith("etornie_")
    assert claims["sub"] == user["id"]

    print(f"\n[5/5] replay the SAME nonce (must be rejected)")
    status, body = _http_post(
        f"{base}/auth/wallet/verify",
        {
            "wallet_address": wallet_address,
            "message": message,
            "signature": signature_b58,
        },
    )
    if status != 401:
        print(f"FAIL: expected 401 replay reject, got {status}: {body}")
        return 1
    print(f"      replay rejected: {status}  {body.get('detail')}")

    print("\nOK: all 5 steps succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
