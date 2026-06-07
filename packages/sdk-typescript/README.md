# @etornie/sdk

Official TypeScript SDK for the [Etornie](https://etornie.com) intellectual-property platform API.

## Install

```bash
npm install @etornie/sdk
```

Requires Node.js 18+ (uses the global `fetch`). Works in the browser and in modern runtimes too.

## Quick start

```ts
import { EtornieClient } from "@etornie/sdk";

const etornie = new EtornieClient({ baseUrl: "https://api.etornie.com" });

// Authenticate (stores the access token on the client)
await etornie.auth.login("you@example.com", "your-password");

// ...or pass a token you already have
// const etornie = new EtornieClient({ baseUrl, token });

const me = await etornie.auth.me();

const { cases, total } = await etornie.cases.list({ status: "open", limit: 20 });
const detail = await etornie.cases.get(cases[0].id);

const renewal = await etornie.renewals.status(detail.id);
const docs = await etornie.documents.list(detail.id);
```

## Resources

| Namespace | Methods |
|-----------|---------|
| `auth` | `login(email, password)`, `me()` |
| `cases` | `list(params?)`, `get(id)`, `create(input)` *(admin)*, `update(id, input)` *(admin)* |
| `documents` | `list(caseId)`, `download(id)` → `ArrayBuffer` |
| `renewals` | `status(caseId)` |
| `calendar` | `status()`, `enable()`, `rotate()`, `disable()` |
| `dataExport` | `download(format)` → `ArrayBuffer` (`json` \| `pdf` \| `docx` \| `xlsx`) |

## Errors

Non-2xx responses throw `EtornieApiError` (`.status`, `.detail`). Calling an
authenticated method without a token throws `EtornieAuthError`.

```ts
import { EtornieApiError } from "@etornie/sdk";

try {
  await etornie.cases.get("missing");
} catch (err) {
  if (err instanceof EtornieApiError) {
    console.error(err.status, err.detail);
  }
}
```

## Development

```bash
npm install
npm run typecheck
npm run build
npm test            # integration tests run only when ETORNIE_API_URL,
                    # ETORNIE_TEST_EMAIL and ETORNIE_TEST_PASSWORD are set
```
