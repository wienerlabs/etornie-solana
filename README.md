# EtornieGPT Platform

IP services platform backend built with FastAPI, PostgreSQL, and Together AI.

## Prerequisites

- Python 3.12+
- Docker & Docker Compose

## Quick Start

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Start PostgreSQL:**
   ```bash
   docker-compose up -d db
   ```

3. **Install dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

5. **Start the app:**
   ```bash
   uvicorn app.main:app --reload
   ```

6. **Verify:**
   ```bash
   curl http://localhost:8000/health
   # {"status":"ok"}
   ```

## Docker (full stack)

```bash
docker-compose up
```

## Project Structure

```
app/
├── main.py          # FastAPI app entry point
├── config.py        # Settings via pydantic-settings
├── database.py      # SQLAlchemy async engine & session
├── users/           # User model & endpoints
├── cases/           # Case, CaseNote models & endpoints
├── documents/       # Document model & endpoints
├── auth/            # JWT auth & RBAC
├── ai/              # Together AI client & RAG
└── notifications/   # Notification interfaces
```
