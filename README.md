# Etornie Backend

Backend API for Etornie -- IP and patent services platform. Built with FastAPI, PostgreSQL, and async Python.

## Features

- **Authentication & RBAC** -- JWT-based auth with role-based access control (admin, lawyer, client). Self-registration for clients; admin endpoint for creating lawyer/admin accounts.
- **User Management** -- Full CRUD with soft delete. Admins manage all users; users can view/update their own profile.
- **Case Management** -- IP case tracking for trademark, patent, design, and copyright matters. Auto-numbered case references, case notes, status workflows, and role-based filtering (admins see all, lawyers see assigned, clients see own).
- **Document Management** -- File upload and download scoped to cases. Role-based access; only admins or uploaders can delete.
- **EtornieGPT** (in progress) -- AI-powered features module. Together AI integration for LLM inference and RAG pipeline with pgvector embeddings.
- **Notifications** (planned) -- Notification interfaces for case updates and system events.

## Tech Stack

| Component        | Technology                          |
|------------------|-------------------------------------|
| Framework        | FastAPI                             |
| ORM              | SQLAlchemy 2.0 (async)              |
| Database         | PostgreSQL 16 + pgvector            |
| Migrations       | Alembic                             |
| Validation       | Pydantic v2                         |
| Auth             | JWT via python-jose, passlib+bcrypt |
| AI               | Together AI (LLM + embeddings)      |
| Containerization | Docker, Docker Compose              |

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose

### Setup

1. Copy the environment file and adjust as needed:
   ```bash
   cp .env.example .env
   ```

2. Start PostgreSQL:
   ```bash
   docker-compose up -d db
   ```

3. Install dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

4. Run database migrations:
   ```bash
   alembic upgrade head
   ```

5. Start the application:
   ```bash
   uvicorn app.main:app --reload
   ```

6. Verify the server is running:
   ```bash
   curl http://localhost:8000/health
   # {"status":"ok"}
   ```

API docs are available at `http://localhost:8000/docs` (Swagger) and `http://localhost:8000/redoc`.

## Project Structure

```
app/
├── main.py            # FastAPI application entry point
├── config.py          # Settings via pydantic-settings
├── database.py        # SQLAlchemy async engine & session
├── auth/              # Authentication -- JWT, RBAC, dependencies
├── users/             # User module -- model, schemas, CRUD service, router
├── cases/             # Case module -- case & note models, auto-numbering, router
├── documents/         # Document module -- file upload/download, router
├── ai/                # EtornieGPT module -- Together AI client, RAG pipeline
└── notifications/     # Notification interfaces (planned)
```

## API Endpoints

### Health

| Method | Path      | Description   | Auth     |
|--------|-----------|---------------|----------|
| GET    | `/health` | Health check  | Public   |

### Authentication (`/auth`)

| Method | Path                  | Description                        | Auth       |
|--------|-----------------------|------------------------------------|------------|
| POST   | `/auth/register`      | Register a client account          | Public     |
| POST   | `/auth/register/admin`| Register any role (admin-only)     | Admin      |
| POST   | `/auth/login`         | Login, receive JWT tokens          | Public     |
| POST   | `/auth/refresh`       | Refresh access token               | Public     |
| GET    | `/auth/me`            | Get current user profile           | Logged in  |

### Users (`/users`)

| Method | Path             | Description               | Auth               |
|--------|------------------|---------------------------|--------------------|
| GET    | `/users`         | List all users            | Admin              |
| GET    | `/users/{id}`    | Get user by ID            | Admin or self      |
| PATCH  | `/users/{id}`    | Update user               | Admin or self      |
| DELETE | `/users/{id}`    | Soft-delete user          | Admin              |

### Cases (`/cases`)

| Method | Path                     | Description              | Auth                      |
|--------|--------------------------|--------------------------|---------------------------|
| POST   | `/cases`                 | Create a new case        | Admin, Lawyer             |
| GET    | `/cases`                 | List cases (filtered)    | Logged in (role-filtered) |
| GET    | `/cases/{id}`            | Get case detail          | Admin, assigned, client   |
| PATCH  | `/cases/{id}`            | Update case              | Admin, assigned lawyer    |
| POST   | `/cases/{id}/notes`      | Add a note to a case     | Admin, assigned, client   |
| GET    | `/cases/{id}/notes`      | List notes for a case    | Admin, assigned, client   |

### Documents

| Method | Path                              | Description           | Auth                    |
|--------|-----------------------------------|-----------------------|-------------------------|
| POST   | `/cases/{id}/documents`           | Upload a document     | Case participants       |
| GET    | `/cases/{id}/documents`           | List case documents   | Case participants       |
| GET    | `/documents/{id}/download`        | Download a document   | Case participants       |
| DELETE | `/documents/{id}`                 | Delete a document     | Admin or uploader       |

## Testing

Run the full test suite:

```bash
pytest tests/ -v
```

There are currently 52 tests covering authentication, user management, case management, and document handling.

## Docker

Run the full stack (app + database) with Docker Compose:

```bash
docker-compose up
```

This starts PostgreSQL with pgvector and the FastAPI application. See `docker-compose.yml` for service configuration.

## License

Proprietary. All rights reserved.
