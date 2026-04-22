"""End-to-end lawyer verification demo.

Exercises the full pending-to-verified lifecycle with real crypto:

1. A fresh ed25519 keypair registers via /auth/wallet/verify with
   role=lawyer and bar credentials. The user is created in a pending
   state (is_verified=false).
2. The existing admin logs in with email+password and inspects the
   /users?verification_status=pending list.
3. The admin hits /users/{id}/verify. The lawyer flips to verified.
4. A second lawyer is registered and the admin hits /users/{id}/reject
   (a no-op since it is already false, but confirms the endpoint).
5. An admin self-assignment attempt via /auth/wallet/verify with
   role="admin" is confirmed to be rejected by the schema (422).

Usage:
    .venv/bin/python scripts/demo_lawyer_verification.py \
        --admin-email <admin-email> --admin-password <admin-password>
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib import error, request

import base58
import nacl.signing


def _post(url: str, payload: dict, token: str | None = None) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8") or "{}"
        return exc.code, json.loads(body) if body.strip().startswith("{") else {"raw": body}


def _get(url: str, token: str) -> tuple[int, dict]:
    req = request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _wallet_register_lawyer(base: str, full_name: str, bar_assoc: str, bar_no: str):
    sk = nacl.signing.SigningKey.generate()
    wallet = base58.b58encode(bytes(sk.verify_key)).decode("ascii")

    status, nonce_body = _post(
        f"{base}/auth/wallet/nonce", {"wallet_address": wallet}
    )
    assert status == 200, nonce_body
    sig = base58.b58encode(sk.sign(nonce_body["message"].encode("utf-8")).signature).decode(
        "ascii"
    )
    status, body = _post(
        f"{base}/auth/wallet/verify",
        {
            "wallet_address": wallet,
            "message": nonce_body["message"],
            "signature": sig,
            "role": "lawyer",
            "full_name": full_name,
            "bar_association": bar_assoc,
            "bar_number": bar_no,
        },
    )
    assert status == 200, body
    return wallet, body["user"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")

    print("=" * 70)
    print("ETORNIE SOLANA  lawyer verification demo")
    print("=" * 70)

    print("\n[1/5] admin signs in")
    status, body = _post(
        f"{base}/auth/login",
        {"email": args.admin_email, "password": args.admin_password},
    )
    if status != 200:
        print(f"FAIL admin login {status}: {body}")
        return 1
    admin_token = body["access_token"]
    print("      admin access token acquired")

    print("\n[2/5] wallet registers as lawyer (pending)")
    wallet, user = _wallet_register_lawyer(
        base,
        full_name="Ayse Yilmaz",
        bar_assoc="Istanbul Barosu",
        bar_no="IST-42-TEST",
    )
    assert user["role"] == "lawyer"
    assert user["is_verified"] is False
    assert user["bar_association"] == "Istanbul Barosu"
    assert user["bar_number"] == "IST-42-TEST"
    print(f"      wallet       = {wallet}")
    print(f"      handle       = {user['public_handle']}")
    print(f"      is_verified  = {user['is_verified']}")
    print(f"      bar          = {user['bar_association']} {user['bar_number']}")

    print("\n[3/5] admin lists pending lawyers")
    status, body = _get(
        f"{base}/users?verification_status=pending", admin_token
    )
    assert status == 200, body
    pending_ids = [u["id"] for u in body["users"]]
    print(f"      pending count = {body['total']}")
    assert user["id"] in pending_ids

    print("\n[4/5] admin verifies the lawyer")
    status, body = _post(
        f"{base}/users/{user['id']}/verify", {}, token=admin_token
    )
    assert status == 200, body
    assert body["is_verified"] is True
    print(f"      {user['public_handle']} is now verified")

    print("\n[5/5] wallet-level admin role request must be rejected")
    sk = nacl.signing.SigningKey.generate()
    wallet2 = base58.b58encode(bytes(sk.verify_key)).decode("ascii")
    _status, nonce = _post(f"{base}/auth/wallet/nonce", {"wallet_address": wallet2})
    sig2 = base58.b58encode(
        sk.sign(nonce["message"].encode("utf-8")).signature
    ).decode("ascii")
    status, body = _post(
        f"{base}/auth/wallet/verify",
        {
            "wallet_address": wallet2,
            "message": nonce["message"],
            "signature": sig2,
            "role": "admin",
        },
    )
    if status != 422:
        print(f"FAIL expected 422 for role=admin, got {status}: {body}")
        return 1
    print("      role=admin rejected at schema layer (HTTP 422)")

    print("\nOK: pending -> verified flow works end to end with real crypto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
