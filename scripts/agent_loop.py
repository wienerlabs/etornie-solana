"""
IP Agent Continuous Loop — Runs the IP agent scan every 30 seconds.

Usage:
    python scripts/agent_loop.py

Continuously polls the backend's /agents/ip/scan-deadlines endpoint
and sends any due notifications via /notifications/process.
Reads credentials from .env file.
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

BASE_URL = os.getenv("AGENT_LOOP_BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("AGENT_LOOP_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("AGENT_LOOP_ADMIN_PASSWORD", "")
POLL_INTERVAL = int(os.getenv("AGENT_LOOP_INTERVAL", "30"))

if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    print("ERROR: AGENT_LOOP_ADMIN_EMAIL and AGENT_LOOP_ADMIN_PASSWORD must be set in .env")
    sys.exit(1)


async def login(client: httpx.AsyncClient) -> str:
    """Login and return access token."""
    resp = await client.post(f"{BASE_URL}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


async def run_loop() -> None:
    """Main agent loop."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Login once
        try:
            token = await login(client)
        except Exception as exc:
            print(f"Login failed: {exc}")
            sys.exit(1)

        headers = {"Authorization": f"Bearer {token}"}
        print(f"=== IP Agent Loop Started ===")
        print(f"Polling every {POLL_INTERVAL} seconds")
        print(f"Backend: {BASE_URL}")
        print()

        while True:
            now = datetime.now()
            try:
                # Scan deadlines
                scan_resp = await client.post(
                    f"{BASE_URL}/agents/ip/scan-deadlines",
                    headers=headers,
                )
                scan_resp.raise_for_status()
                scan_data = scan_resp.json()

                deadlines_found = scan_data.get("deadlines_found", 0)
                notifications_created = scan_data.get("notifications_created", 0)

                if deadlines_found > 0 or notifications_created > 0:
                    print(f"[{now.strftime('%H:%M:%S')}] Deadlines: {deadlines_found}, Notifications created: {notifications_created}")
                    for alert in scan_data.get("alerts", []):
                        print(f"  → {alert.get('case_number')}: {alert.get('interval_value')} {alert.get('interval_type')} kala")

                    # Process pending notifications (send via WhatsApp)
                    process_resp = await client.post(
                        f"{BASE_URL}/notifications/process",
                        headers=headers,
                    )
                    process_resp.raise_for_status()
                    process_data = process_resp.json()
                    sent = process_data.get("sent", 0)
                    failed = process_data.get("failed", 0)
                    print(f"[{now.strftime('%H:%M:%S')}] Processed: {sent} sent, {failed} failed")
                else:
                    print(f"[{now.strftime('%H:%M:%S')}] No deadlines matched. Waiting...")

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    print(f"[{now.strftime('%H:%M:%S')}] Token expired, re-logging in...")
                    try:
                        token = await login(client)
                        headers = {"Authorization": f"Bearer {token}"}
                    except Exception:
                        print(f"[{now.strftime('%H:%M:%S')}] Re-login failed, retrying next cycle...")
                else:
                    print(f"[{now.strftime('%H:%M:%S')}] HTTP error: {exc.response.status_code} — {exc.response.text}")
            except Exception as exc:
                print(f"[{now.strftime('%H:%M:%S')}] Error: {exc}")

            await asyncio.sleep(POLL_INTERVAL)


def main() -> None:
    asyncio.run(run_loop())


if __name__ == "__main__":
    main()
