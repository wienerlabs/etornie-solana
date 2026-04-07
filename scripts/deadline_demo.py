"""
IP Agent Deadline Demo — Minute-level WhatsApp notifications.

Usage:
    python scripts/deadline_demo.py --deadline 17:10 --phone 905528144977

Sends WhatsApp messages at 30, 7, and 1 minutes before the deadline.
Reads WhatsApp credentials from .env file.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from project root
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v22.0")
WHATSAPP_DEMO_TEMPLATE = os.getenv("WHATSAPP_DEMO_TEMPLATE", "")
WHATSAPP_DEMO_LANGUAGE = os.getenv("WHATSAPP_DEMO_LANGUAGE", "en_US")

REMINDER_INTERVALS = [30, 7, 1]  # minutes before deadline

MESSAGES = {
    30: (
        "REMINDER: Dear {name}, there are 30 minutes remaining until the deadline. "
        "Please complete the necessary actions. "
        "Deadline: {deadline}"
    ),
    7: (
        "WARNING: Dear {name}, there are 7 minutes remaining until the deadline. "
        "Urgent action is required. "
        "Deadline: {deadline}"
    ),
    1: (
        "URGENT: Dear {name}, there is 1 minute remaining until the deadline! "
        "Deadline: {deadline}"
    ),
}


async def send_whatsapp_message(phone: str, _message: str) -> dict:
    """Send a template message via WhatsApp Business Cloud API.

    Uses the template specified by WHATSAPP_DEMO_TEMPLATE env var.
    """
    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": WHATSAPP_DEMO_TEMPLATE,
            "language": {"code": WHATSAPP_DEMO_LANGUAGE},
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        return response.json()


async def run_demo(deadline_str: str, phone: str, name: str) -> None:
    """Run the deadline demo scheduler."""
    if not WHATSAPP_API_TOKEN or not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_DEMO_TEMPLATE:
        print("ERROR: WHATSAPP_API_TOKEN, WHATSAPP_PHONE_NUMBER_ID, and WHATSAPP_DEMO_TEMPLATE must be set in .env")
        sys.exit(1)

    # Parse deadline time (today's date + given time)
    now = datetime.now()
    hour, minute = map(int, deadline_str.split(":"))
    deadline = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if deadline <= now:
        print(f"ERROR: Deadline ({deadline_str}) is in the past. Enter a future time.")
        sys.exit(1)

    # Calculate send times
    send_times = {}
    for interval in REMINDER_INTERVALS:
        send_at = deadline - timedelta(minutes=interval)
        if send_at > now:
            send_times[interval] = send_at

    if not send_times:
        print("ERROR: All reminder times have passed. Enter a later deadline.")
        sys.exit(1)

    print(f"=== IP Agent Deadline Demo ===")
    print(f"Deadline: {deadline.strftime('%H:%M')}")
    print(f"Phone: {phone}")
    print(f"Recipient: {name}")
    print()
    for interval, send_at in sorted(send_times.items(), reverse=True):
        print(f"  {interval} min before -> message will be sent at {send_at.strftime('%H:%M:%S')}")
    print()
    print("Waiting...\n")

    sent = set()

    while send_times:
        now = datetime.now()

        for interval, send_at in sorted(send_times.items(), reverse=True):
            if interval in sent:
                continue

            if now >= send_at:
                message = MESSAGES[interval].format(
                    name=name,
                    deadline=deadline.strftime("%H:%M"),
                )
                print(f"[{now.strftime('%H:%M:%S')}] Sending message for {interval} min before...")

                try:
                    result = await send_whatsapp_message(phone, message)
                    messages = result.get("messages", [])
                    if messages:
                        msg_id = messages[0].get("id", "unknown")
                        print(f"[{now.strftime('%H:%M:%S')}] SUCCESS — Message ID: {msg_id}")
                    else:
                        error = result.get("error", {}).get("message", str(result))
                        print(f"[{now.strftime('%H:%M:%S')}] ERROR — {error}")
                except Exception as exc:
                    print(f"[{now.strftime('%H:%M:%S')}] ERROR — {exc}")

                sent.add(interval)

        # Remove sent intervals
        send_times = {k: v for k, v in send_times.items() if k not in sent}

        if send_times:
            await asyncio.sleep(10)  # Check every 10 seconds

    print(f"\n=== Completed. {len(sent)} messages sent. ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="IP Agent Deadline Demo")
    parser.add_argument("--deadline", required=True, help="Deadline time (HH:MM format, e.g.: 17:10)")
    parser.add_argument("--phone", required=True, help="Phone number (with country code, e.g.: 905528144977)")
    parser.add_argument("--name", default="Muhammed Akinci", help="Recipient name")
    args = parser.parse_args()

    asyncio.run(run_demo(args.deadline, args.phone, args.name))


if __name__ == "__main__":
    main()
