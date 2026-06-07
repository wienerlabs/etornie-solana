# Etornie SDKs

Official client libraries for integrating against the Etornie IP platform API.

| Language | Package | Source | Install |
|----------|---------|--------|---------|
| TypeScript / JavaScript | `@etornie/sdk` | [`packages/sdk-typescript`](../../packages/sdk-typescript) | `npm install @etornie/sdk` |
| Python | `etornie` | [`packages/sdk-python`](../../packages/sdk-python) | `pip install etornie` |

Both SDKs are hand-written, typed, and cover the core public resources:

- **auth** — `login`, `me`
- **cases** — list, get, create *(admin)*, update *(admin)*
- **documents** — list, download
- **renewals** — status
- **calendar** — feed enable / rotate / disable / status
- **data export** — GDPR Article 20 export download

## Authentication

The API uses bearer tokens. Authenticate with email + password (the client
stores the access token), or construct the client with a token you already
hold.

```ts
// TypeScript
import { EtornieClient } from "@etornie/sdk";
const etornie = new EtornieClient({ baseUrl: "https://api.etornie.com" });
await etornie.auth.login("you@example.com", "password");
const { cases } = await etornie.cases.list({ status: "open" });
```

```python
# Python
from etornie import EtornieClient
with EtornieClient("https://api.etornie.com") as etornie:
    etornie.auth.login("you@example.com", "password")
    cases, total = etornie.cases.list(status="open")
```

See each package's README for the full method reference and error handling.

## Tests

Both packages ship unit tests plus credential-gated integration tests that
run against a live API when these environment variables are set (otherwise
they are skipped, never mocked):

```
ETORNIE_API_URL, ETORNIE_TEST_EMAIL, ETORNIE_TEST_PASSWORD
```
