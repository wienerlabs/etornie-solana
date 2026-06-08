"""Tests for ClamAV upload scanning (#55).

``_scan_stream`` (the blocking clamd INSTREAM call) is mocked, so these run
without a daemon or the ``clamd`` package installed. They pin the contract the
upload handlers depend on:

- disabled            -> no-op, daemon never touched;
- clean ("OK")        -> passes;
- infected ("FOUND")  -> InfectedFileError (400);
- daemon error / bad status -> VirusScanUnavailableError (503, fail-closed).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.security import virus_scan
from app.security.virus_scan import (
    InfectedFileError,
    VirusScanUnavailableError,
    scan_upload,
)


@pytest.mark.unit
class TestScanUpload:
    async def test_disabled_is_noop(self) -> None:
        mock_scan = MagicMock()
        with (
            patch.object(virus_scan.settings, "clamav_enabled", False),
            patch.object(virus_scan, "_scan_stream", mock_scan),
        ):
            result = await scan_upload(b"anything", filename="x.pdf")
        assert result is None
        mock_scan.assert_not_called()

    async def test_clean_passes(self) -> None:
        with (
            patch.object(virus_scan.settings, "clamav_enabled", True),
            patch.object(
                virus_scan, "_scan_stream", MagicMock(return_value=("OK", None))
            ),
        ):
            assert await scan_upload(b"clean bytes", filename="ok.pdf") is None

    async def test_infected_raises_400(self) -> None:
        with (
            patch.object(virus_scan.settings, "clamav_enabled", True),
            patch.object(
                virus_scan,
                "_scan_stream",
                MagicMock(return_value=("FOUND", "Eicar-Test-Signature")),
            ),
            pytest.raises(InfectedFileError) as excinfo,
        ):
            await scan_upload(b"X5O!P%@AP[4...", filename="evil.pdf")
        assert excinfo.value.http_status == 400
        assert excinfo.value.signature == "Eicar-Test-Signature"

    async def test_daemon_error_fails_closed_503(self) -> None:
        with (
            patch.object(virus_scan.settings, "clamav_enabled", True),
            patch.object(
                virus_scan,
                "_scan_stream",
                MagicMock(side_effect=ConnectionError("clamd unreachable")),
            ),
            pytest.raises(VirusScanUnavailableError) as excinfo,
        ):
            await scan_upload(b"bytes", filename="x.pdf")
        assert excinfo.value.http_status == 503

    async def test_unexpected_status_fails_closed(self) -> None:
        with (
            patch.object(virus_scan.settings, "clamav_enabled", True),
            patch.object(
                virus_scan, "_scan_stream", MagicMock(return_value=("ERROR", "boom"))
            ),
            pytest.raises(VirusScanUnavailableError),
        ):
            await scan_upload(b"bytes", filename="x.pdf")
