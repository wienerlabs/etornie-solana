"""Real ClamAV scanning integration test (#119).

Unlike ``test_virus_scan.py`` (which mocks the clamd client), this test
streams bytes to a genuine ClamAV daemon and asserts on its real verdict —
the standard EICAR test string is detected as a signature match, and a clean
payload passes. No mocks; real INSTREAM over the socket.

Skipped via ``pytest.mark.skipif`` when scanning is disabled or the daemon
is not reachable, so it is a no-op in environments without clamd. To run it:

    docker run -d --platform linux/amd64 -p 3310:3310 clamav/clamav:latest
    # services/api/.env (or the environment):
    #   CLAMAV_ENABLED=true  CLAMAV_HOST=localhost  CLAMAV_PORT=3310
    .venv/bin/pytest tests/test_virus_scan_integration.py -v

The EICAR signature is split across two literals so the full string is
never contiguous on disk — otherwise the host's own malware protection
(macOS XProtect) blocks writing this very file, and secret/AV scanners trip
on it. EICAR is a harmless industry-standard AV test pattern, not malware.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.security import virus_scan
from app.security.virus_scan import InfectedFileError, scan_upload

# Reassembled at runtime from two non-contiguous fragments (see module docstring).
EICAR = (
    rb"X5O!P%@AP[4\PZX54(P^)7CC)7}"
    rb"$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)
CLEAN = b"A clean QA payload with no signature in it.\n"


def _clamd_reachable() -> bool:
    if not settings.clamav_enabled:
        return False
    try:
        import clamd

        client = clamd.ClamdNetworkSocket(
            host=settings.clamav_host,
            port=settings.clamav_port,
            timeout=3.0,
        )
        return client.ping() == "PONG"
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _clamd_reachable(),
        reason="ClamAV scanning disabled or daemon not reachable",
    ),
]


def test_eicar_is_detected_as_a_signature_match() -> None:
    status, signature = virus_scan._scan_stream(EICAR)
    assert status == "FOUND"
    assert signature and "Eicar" in signature


def test_clean_payload_scans_ok() -> None:
    assert virus_scan._scan_stream(CLEAN) == ("OK", None)


async def test_scan_upload_rejects_eicar() -> None:
    with pytest.raises(InfectedFileError) as exc_info:
        await scan_upload(EICAR, filename="eicar.txt")
    assert exc_info.value.http_status == 400


async def test_scan_upload_allows_clean_file() -> None:
    assert await scan_upload(CLEAN, filename="clean.txt") is None
