# Build context must be the repo root so we can include the root-level
# package.json + scripts/ that the NFT subprocess needs. On Railway, set:
#   Root Directory   = /
#   Dockerfile Path  = services/api/Dockerfile
# Optionally restrict rebuild triggers via Watch Paths (services/api/**,
# scripts/nft/**, package.json, yarn.lock).

# ── Stage 1: install Node deps for the NFT subprocess ─────────────────
FROM node:20-slim AS node-deps
WORKDIR /repo
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 make g++ git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile --network-timeout 600000

# ── Stage 2: Python runtime base ──────────────────────────────────────
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy the API service first so 'pip install ./services/api' can build the
# 'etornie-backend' wheel from the bundled app/ package (hatch needs it).
COPY services/api ./services/api
RUN pip install --no-cache-dir ./services/api

RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 3: assemble runtime image ───────────────────────────────────
FROM base AS runtime

# Node deps + repo-level files needed for NFT subprocess (ts-node + scripts)
COPY --from=node-deps /repo/node_modules ./node_modules
COPY package.json yarn.lock tsconfig.json ./
COPY scripts ./scripts

# Run from the API service directory so app.* imports resolve and
# alembic.ini / data/* / scripts/seed_required_documents.py default paths
# all keep working as before.
WORKDIR /app/services/api

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
