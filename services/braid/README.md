# Etornie BRAID Agent

OpenServ BRAID reasoning agent — bounded, auditable reasoning for Etornie's
compliance, ZK file ownership, and x402 micropayment flows.

## Setup

```bash
cd services/braid
npm install
cp .env.example .env
# edit .env and set OPENSERV_API_KEY (from https://platform.openserv.ai)
```

## Run

```bash
npm run dev      # tsx watch — hot reload during development
npm run start    # tsx — single run
npm run typecheck
```

## Notes

- The agent is **isolated from root yarn workspace** on purpose; it manages
  its own `package.json` and `node_modules` so root Anchor/ZK tests aren't
  perturbed.
- Agent registration on `platform.openserv.ai` is manual. The endpoint URL
  configured in the OpenServ dashboard must point at this service.
- Default port: **7378**. Override with `PORT` env var.
