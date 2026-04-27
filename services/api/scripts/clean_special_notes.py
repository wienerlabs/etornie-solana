"""Re-translate the bilingual/corrupted special_notes field in
services/api/data/countries_parsed.json into clean English using Together AI.

Background
----------
The special_notes field in countries_parsed.json is the result of a
naive find-and-replace pass over an originally Turkish dataset. It
emits text like ``"Tam class and genel emtilalar içeren applicationlar
for uygunsuzluk kararı andrilmektedir."`` that is unusable in the UI.
This script asks an LLM to recover the underlying meaning and rewrite
each entry as clean professional English suitable for trademark
filing context.

Usage
-----
    cd services/api
    python -m scripts.clean_special_notes              # process all entries
    python -m scripts.clean_special_notes --limit 5    # smoke-test on a few
    python -m scripts.clean_special_notes --dry-run    # preview only

The script is idempotent: it skips entries whose special_notes already
look like clean English (heuristic — see _looks_clean). Override with
--force to re-translate everything.

Configuration
-------------
Reads TOGETHER_API_KEY from app.config (i.e. the same .env / env vars
the API service uses).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from together import Together  # type: ignore[import-untyped]

# Allow running both as a script and via `python -m`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "countries_parsed.json"

_MODEL = settings.together_model or "openai/gpt-oss-20b"

_SYSTEM_PROMPT = (
    "You are a translator that fixes corrupted Turkish/English mixed text "
    "about trademark filing requirements and rewrites it as clean, "
    "professional English. The input was produced by a naive word-by-word "
    "substitution from Turkish, so it contains broken hybrids like "
    "'applicationlar', 'andrilmektedir' (originally 'verilmektedir'), or "
    "'sonrasınalso' (originally 'sonrasında'). Recover the intended legal "
    "meaning and write a clear paragraph suitable for an IP attorney "
    "audience. Keep specifics: classes, deadlines, language requirements, "
    "registration steps, fees. Do not invent facts; if a phrase is "
    "unrecoverable, omit it. Output English text only — no headings, "
    "no bullet points, no Turkish words, no quotation marks."
)


def _looks_clean(text: str) -> bool:
    """Heuristic: text appears to be already clean English.

    Triggers if there are no obvious Turkish-origin substrings AND the
    common corruption artifacts are absent.
    """
    if not text:
        return True
    lowered = text.lower()
    artifacts = (
        "applicationlar",
        "andrilmek",
        "sonrasınalso",
        "alsorıca",
        "feene",
        "alsohil",
        "saalsoce",
        "registrationi",
        "için",
        "ayrıca",
        "kullanım",
        "ürettiği",
        "müşteri",
        "evrak",
    )
    if any(a in lowered for a in artifacts):
        return False
    # If it contains common Turkish suffix patterns that survived, treat as dirty.
    if re.search(r"\b\w+(?:nın|nin|nun|nün|den|dan|ile|ler|lar)\b", lowered):
        return False
    return True


def translate(client: Client, raw: str) -> str:
    """Call Together AI to clean a single special_notes string."""
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": raw.strip()},
        ],
        temperature=0.0,
        max_tokens=600,
    )
    cleaned = response.choices[0].message.content or ""
    return cleaned.strip().strip('"').strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=_DATA_PATH,
        help="Path to countries_parsed.json (default: bundled data)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N entries (for smoke testing)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rewrites but do not save the JSON",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-translate even entries that already look clean",
    )
    args = parser.parse_args()

    if not settings.together_api_key:
        print("ERROR: TOGETHER_API_KEY is not set", file=sys.stderr)
        return 2

    data = json.loads(args.path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("ERROR: expected JSON list at root", file=sys.stderr)
        return 2

    targets = [
        (idx, entry)
        for idx, entry in enumerate(data)
        if isinstance(entry.get("special_notes"), str)
        and entry["special_notes"].strip()
        and (args.force or not _looks_clean(entry["special_notes"]))
    ]
    if args.limit is not None:
        targets = targets[: args.limit]

    print(
        f"Found {len(targets)} entries to clean "
        f"(model={_MODEL}, dry_run={args.dry_run})"
    )

    client = Together(api_key=settings.together_api_key)
    cleaned_count = 0
    failed: list[tuple[int, str]] = []

    for n, (idx, entry) in enumerate(targets, start=1):
        country = entry.get("country", "?")
        code = entry.get("country_code") or "??"
        raw = entry["special_notes"]
        try:
            cleaned = translate(client, raw)
        except Exception as exc:  # noqa: BLE001
            failed.append((idx, str(exc)))
            print(f"[{n}/{len(targets)}] {code} {country}: FAILED ({exc})")
            continue

        if not cleaned:
            failed.append((idx, "empty response"))
            print(f"[{n}/{len(targets)}] {code} {country}: empty response")
            continue

        print(f"[{n}/{len(targets)}] {code} {country}:")
        print(f"  before: {raw[:120]}{'...' if len(raw) > 120 else ''}")
        print(f"  after : {cleaned[:120]}{'...' if len(cleaned) > 120 else ''}")

        if not args.dry_run:
            data[idx]["special_notes"] = cleaned
        cleaned_count += 1

        # Periodic checkpoint save to survive Ctrl-C / network blips.
        if not args.dry_run and cleaned_count % 25 == 0:
            args.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  ↳ checkpoint saved at {cleaned_count} entries")

        # Light rate limit cushion.
        time.sleep(0.2)

    if not args.dry_run and cleaned_count > 0:
        args.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nSaved {cleaned_count} cleaned entries to {args.path}")
    elif args.dry_run:
        print(f"\nDry run — {cleaned_count} entries would have been updated.")

    if failed:
        print(f"\n{len(failed)} entries failed:", file=sys.stderr)
        for idx, msg in failed[:20]:
            print(f"  index {idx}: {msg}", file=sys.stderr)
        return 1

    return 0


# Type alias to avoid importing Together's internal types.
Client = Any


if __name__ == "__main__":
    sys.exit(main())
