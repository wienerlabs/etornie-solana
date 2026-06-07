"""Register the Helius webhook for on-chain reconciliation (#19).

Run from ``services/api`` with the backend env loaded:

    python scripts/register_helius_webhook.py

Requires ``HELIUS_API_KEY`` and ``HELIUS_WEBHOOK_AUTH``. Registers a *raw*
webhook for the three program IDs, pointing at
``<HELIUS_WEBHOOK_URL or API_PUBLIC_URL>/solana/webhooks/helius`` with the
shared secret as the ``Authorization`` header. Skips creation if a webhook
already targets that URL. See docs/HELIUS_WEBHOOK.md.
"""

from __future__ import annotations

import sys

import httpx

from app.config import settings

_HELIUS_API: str = "https://api.helius.xyz/v0/webhooks"


def _webhook_url() -> str:
    if settings.helius_webhook_url:
        return settings.helius_webhook_url.rstrip("/")
    return settings.api_public_url.rstrip("/") + "/solana/webhooks/helius"


def main() -> int:
    if not settings.helius_api_key:
        print(
            "HELIUS_API_KEY is not set. Set it (plus HELIUS_WEBHOOK_AUTH and "
            "API_PUBLIC_URL or HELIUS_WEBHOOK_URL), then re-run.\n"
            "Get an API key at https://dashboard.helius.dev."
        )
        return 1
    if not settings.helius_webhook_auth:
        print(
            "HELIUS_WEBHOOK_AUTH is empty — refusing to register an "
            "unauthenticated webhook (the receiving endpoint is fail-closed)."
        )
        return 1

    program_ids = [
        settings.solana_attestation_program_id,
        settings.solana_nft_program_id,
        settings.solana_zk_verifier_program_id,
    ]
    url = _webhook_url()
    params = {"api-key": settings.helius_api_key}
    body = {
        "webhookURL": url,
        "transactionTypes": ["Any"],
        "accountAddresses": program_ids,
        "webhookType": "raw",
        "authHeader": settings.helius_webhook_auth,
    }

    with httpx.Client(timeout=30.0) as client:
        existing = client.get(_HELIUS_API, params=params)
        existing.raise_for_status()
        for hook in existing.json():
            if hook.get("webhookURL") == url:
                print(
                    f"A webhook already targets {url} "
                    f"(id {hook.get('webhookID')}). Delete it in the Helius "
                    "dashboard to re-create."
                )
                return 0
        resp = client.post(_HELIUS_API, params=params, json=body)
        resp.raise_for_status()
        created = resp.json()

    print(f"Registered Helius webhook {created.get('webhookID')} -> {url}")
    print(f"  programs: {', '.join(program_ids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
