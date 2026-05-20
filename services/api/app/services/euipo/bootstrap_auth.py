"""One-off CLI helper to bootstrap the EUIPO authorization_code session.

Run from ``services/api`` with the venv activated::

    .venv/bin/python -m app.services.euipo.bootstrap_auth

The script:
1. Builds the EUIPO authorize URL with the configured client_id.
2. Spins up a tiny local HTTP server on ``localhost:8765/callback``
   to catch the authorization code EUIPO redirects with.
3. Opens the URL in the default browser (you can also paste manually).
4. Exchanges the code for access + refresh tokens via
   ``exchange_authorization_code`` (which persists to
   ``euipo_oauth_token``).

Prerequisites:
- ``http://localhost:8765/callback`` must be registered as a valid
  redirect URI on the EUIPO sandbox developer portal for the
  ``EUIPO_API_KEY`` client.
- ``EUIPO_API_KEY`` and ``EUIPO_API_SECRET`` must be set in .env.

After this lands once, the singleton row keeps refreshing itself —
re-run only if EUIPO revokes the refresh_token (rare).
"""
from __future__ import annotations

import asyncio
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from app.config import settings
from app.services.euipo.auth import exchange_authorization_code, get_authorize_url


# EUIPO sandbox rejects ``localhost`` as a redirect host but accepts the
# RFC 8252 loopback IP — match what is actually registered on the app
# in the dev-sandbox portal (Etornie / Application OAuth Redirect URL).
_REDIRECT_HOST = "127.0.0.1"
_REDIRECT_PORT = 8765
_REDIRECT_PATH = "/callback"
_REDIRECT_URI = f"http://{_REDIRECT_HOST}:{_REDIRECT_PORT}{_REDIRECT_PATH}"

_SCOPES = [
    "eutm-filing.application.read",
    "eutm-filing.application.write",
    "design-filing.application.read",
    "design-filing.application.write",
    "document-repository.documents.read",
    "document-repository.documents.write",
    "me.portfolio.read",
    "me.applicants.read",
    "me.account.read",
]


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence the default access log so the CLI output stays clean.
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != _REDIRECT_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        if "code" in params:
            _CallbackHandler.code = params["code"][0]
            body = (
                b"<html><body><h1>OK</h1>"
                b"<p>Authorization code received. You can close this tab "
                b"and return to the CLI.</p></body></html>"
            )
        else:
            _CallbackHandler.error = params.get("error_description", ["unknown"])[0]
            body = (
                f"<html><body><h1>EUIPO returned an error</h1>"
                f"<pre>{_CallbackHandler.error}</pre>"
                f"</body></html>"
            ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def _run_callback_server(stop: threading.Event) -> None:
    server = HTTPServer((_REDIRECT_HOST, _REDIRECT_PORT), _CallbackHandler)
    server.timeout = 0.5
    while not stop.is_set():
        server.handle_request()
    server.server_close()


async def _main() -> int:
    if not settings.euipo_api_key or not settings.euipo_api_secret:
        print(
            "[ERROR] EUIPO_API_KEY / EUIPO_API_SECRET are not set in .env. "
            "Bootstrap aborted.",
            file=sys.stderr,
        )
        return 1

    authorize_url = get_authorize_url(_REDIRECT_URI, _SCOPES)
    print("EUIPO OIDC bootstrap")
    print("====================")
    print(f"redirect_uri : {_REDIRECT_URI}")
    print(f"scope        : {' '.join(_SCOPES)}")
    print()
    print("Open this URL in your browser to authenticate with EUIPO:")
    print()
    print(authorize_url)
    print()
    print(
        "If the browser does not open automatically, copy the URL above. "
        "Listening on localhost:8765 for the callback..."
    )

    stop_event = threading.Event()
    server_thread = threading.Thread(
        target=_run_callback_server, args=(stop_event,), daemon=True
    )
    server_thread.start()

    try:
        webbrowser.open(authorize_url, new=1)
    except Exception:  # noqa: BLE001
        pass

    try:
        while _CallbackHandler.code is None and _CallbackHandler.error is None:
            await asyncio.sleep(0.5)
    finally:
        stop_event.set()
        server_thread.join(timeout=2)

    if _CallbackHandler.error:
        print(f"\n[ERROR] EUIPO returned an error: {_CallbackHandler.error}")
        return 2

    assert _CallbackHandler.code is not None
    print("\n[OK] Authorization code received. Exchanging for tokens...")
    try:
        data = await exchange_authorization_code(
            _CallbackHandler.code, _REDIRECT_URI
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n[ERROR] Token exchange failed: {exc}")
        return 3

    expires_in = data.get("expires_in", 28800)
    scope = data.get("scope", "")
    print(
        f"[OK] EUIPO user session persisted. "
        f"access_token expires in {expires_in}s. scope={scope}"
    )
    print(
        "Next backend restart will pick up the saved refresh_token "
        "automatically; auto-submit can now POST to EUIPO."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
