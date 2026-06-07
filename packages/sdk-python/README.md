# etornie

Official Python SDK for the [Etornie](https://etornie.com) intellectual-property platform API.

## Install

```bash
pip install etornie
```

Requires Python 3.10+.

## Quick start

```python
from etornie import EtornieClient

with EtornieClient("https://api.etornie.com") as etornie:
    # Authenticate (stores the access token on the client)
    etornie.auth.login("you@example.com", "your-password")
    # ...or: EtornieClient("https://api.etornie.com", token="...")

    me = etornie.auth.me()

    cases, total = etornie.cases.list(status="open", limit=20)
    detail = etornie.cases.get(cases[0].id)

    renewal = etornie.renewals.status(detail.id)
    docs, _ = etornie.documents.list(detail.id)
```

## Resources

| Namespace | Methods |
|-----------|---------|
| `auth` | `login(email, password)`, `me()` |
| `cases` | `list(skip=, limit=, status=)`, `get(id)`, `create(**fields)` *(admin)*, `update(id, **fields)` *(admin)* |
| `documents` | `list(case_id)` → `(docs, total)`, `download(id)` → `bytes` |
| `renewals` | `status(case_id)` |
| `calendar` | `status()`, `enable()`, `rotate()`, `disable()` |
| `data_export` | `download(fmt)` → `bytes` (`json` \| `pdf` \| `docx` \| `xlsx`) |

## Errors

Non-2xx responses raise `EtornieApiError` (`.status_code`, `.detail`).
Calling an authenticated method without a token raises `EtornieAuthError`.

```python
from etornie import EtornieApiError

try:
    etornie.cases.get("missing")
except EtornieApiError as err:
    print(err.status_code, err.detail)
```

## Development

```bash
pip install -e ".[dev]"
pytest            # integration tests run only when ETORNIE_API_URL,
                  # ETORNIE_TEST_EMAIL and ETORNIE_TEST_PASSWORD are set
```
