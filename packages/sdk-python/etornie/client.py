"""Synchronous client for the Etornie API."""
from __future__ import annotations

from typing import Any, Literal

import httpx

from .errors import EtornieApiError, EtornieAuthError
from .models import (
    CalendarFeedStatus,
    Case,
    CaseDocument,
    RenewalStatus,
    TokenResponse,
    User,
)

DataExportFormat = Literal["json", "pdf", "docx", "xlsx"]
CaseStatus = Literal["open", "in_progress", "under_review", "closed"]


class EtornieClient:
    """Typed client for the Etornie API.

    >>> etornie = EtornieClient("https://api.etornie.com")
    >>> etornie.auth.login("you@example.com", "password")
    >>> cases = etornie.cases.list(status="open")
    """

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self._http = http_client or httpx.Client(timeout=timeout)

        self.auth = AuthResource(self)
        self.cases = CasesResource(self)
        self.documents = DocumentsResource(self)
        self.renewals = RenewalsResource(self)
        self.calendar = CalendarResource(self)
        self.data_export = DataExportResource(self)

    # -- token -----------------------------------------------------------
    def set_token(self, token: str | None) -> None:
        self._token = token

    @property
    def token(self) -> str | None:
        return self._token

    # -- context manager -------------------------------------------------
    def __enter__(self) -> "EtornieClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # -- low-level request ----------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        auth: bool = True,
        raw: bool = False,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if auth:
            if not self._token:
                raise EtornieAuthError()
            headers["Authorization"] = f"Bearer {self._token}"

        clean_params = (
            {k: v for k, v in params.items() if v is not None}
            if params
            else None
        )

        resp = self._http.request(
            method,
            self.base_url + path,
            params=clean_params,
            json=json,
            headers=headers,
        )

        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except Exception:  # noqa: BLE001 - non-JSON error body
                detail = resp.text
            raise EtornieApiError(resp.status_code, detail)

        if raw:
            return resp.content
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()


class AuthResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def login(self, email: str, password: str) -> TokenResponse:
        """Exchange email + password for tokens; stores the access token."""
        data = self._c.request(
            "POST", "/auth/login", json={"email": email, "password": password}, auth=False
        )
        tokens = TokenResponse.from_dict(data)
        self._c.set_token(tokens.access_token)
        return tokens

    def me(self) -> User:
        return User.from_dict(self._c.request("GET", "/auth/me"))


class CasesResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def list(
        self,
        *,
        skip: int | None = None,
        limit: int | None = None,
        status: CaseStatus | None = None,
    ) -> tuple[list[Case], int]:
        """Return (cases, total)."""
        data = self._c.request(
            "GET", "/cases", params={"skip": skip, "limit": limit, "status": status}
        )
        return [Case.from_dict(c) for c in data["cases"]], int(data["total"])

    def get(self, case_id: str) -> Case:
        return Case.from_dict(self._c.request("GET", f"/cases/{case_id}"))

    def create(self, **fields: Any) -> Case:
        """Create a case (requires an admin token)."""
        data = self._c.request("POST", "/cases", json=fields)
        return Case.from_dict(data["case"])

    def update(self, case_id: str, **fields: Any) -> Case:
        return Case.from_dict(
            self._c.request("PATCH", f"/cases/{case_id}", json=fields)
        )


class DocumentsResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def list(self, case_id: str) -> tuple[list[CaseDocument], int]:
        data = self._c.request("GET", f"/cases/{case_id}/documents")
        return (
            [CaseDocument.from_dict(d) for d in data["documents"]],
            int(data["total"]),
        )

    def download(self, document_id: str) -> bytes:
        return self._c.request(
            "GET", f"/documents/{document_id}/download", raw=True
        )


class RenewalsResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def status(self, case_id: str) -> RenewalStatus:
        return RenewalStatus.from_dict(
            self._c.request("GET", f"/cases/{case_id}/renewal-status")
        )


class CalendarResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def status(self) -> CalendarFeedStatus:
        return CalendarFeedStatus.from_dict(self._c.request("GET", "/calendar/feed"))

    def enable(self) -> CalendarFeedStatus:
        return CalendarFeedStatus.from_dict(
            self._c.request("POST", "/calendar/feed")
        )

    def rotate(self) -> CalendarFeedStatus:
        return CalendarFeedStatus.from_dict(
            self._c.request("POST", "/calendar/feed/rotate")
        )

    def disable(self) -> None:
        self._c.request("DELETE", "/calendar/feed")


class DataExportResource:
    def __init__(self, client: EtornieClient) -> None:
        self._c = client

    def download(self, fmt: DataExportFormat = "json") -> bytes:
        """Download the authenticated user's GDPR data export (Article 20)."""
        return self._c.request(
            "GET", "/users/me/export", params={"format": fmt}, raw=True
        )
