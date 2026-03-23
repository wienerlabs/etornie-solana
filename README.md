# Etornie Backend

Backend API for Etornie -- IP and patent services platform. Built with FastAPI, PostgreSQL, and async Python.

## Features

- **Authentication & RBAC** -- JWT-based auth with role-based access control (admin, lawyer, client). Self-registration for clients; admin endpoint for creating lawyer/admin accounts.
- **User Management** -- Full CRUD with soft delete. Admins manage all users; users can view/update their own profile.
- **Case Management** -- IP case tracking for trademark, patent, design, and copyright matters. Auto-numbered case references, case notes, status workflows, and role-based filtering (admins see all, lawyers see assigned, clients see own).
- **Document Management** -- File upload and download scoped to cases. Role-based access; only admins or uploaders can delete.
- **EtornieGPT / AI** -- AI-powered features module. Together AI integration for LLM chat, embeddings, and RAG pipeline (document indexing, semantic search, augmented chat) backed by pgvector.
- **Notifications** -- WhatsApp Business Cloud API integration for case notifications. Scheduled and immediate message sending, retry logic, and template listing.
- **IP Agent** -- Automatic IP deadline tracking agent. Scans cases for upcoming deadlines (30/7/1 day intervals), auto-creates WhatsApp notifications for assigned lawyers and clients, with configurable reminder intervals and duplicate prevention.

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
| Notifications    | WhatsApp Business Cloud API         |
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
├── notifications/     # Notifications -- WhatsApp Business Cloud API, scheduling, retry
└── agents/
    └── ip_agent/      # IP Agent -- deadline scanning, auto-notifications
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

### AI / EtornieGPT (`/ai`)

| Method | Path                      | Description                  | Auth           |
|--------|---------------------------|------------------------------|----------------|
| POST   | `/ai/index/{document_id}` | Index document for RAG       | Admin, Lawyer  |
| POST   | `/ai/search`              | Search similar content       | Logged in      |
| POST   | `/ai/chat`                | RAG-augmented chat           | Logged in      |

### Notifications (`/notifications`)

| Method | Path                            | Description                   | Auth                       |
|--------|---------------------------------|-------------------------------|----------------------------|
| POST   | `/notifications`                | Create scheduled notification | Admin, Lawyer              |
| GET    | `/notifications`                | List notifications            | Admin (all), Lawyer (own)  |
| GET    | `/notifications/{id}`           | Get notification detail       | Admin, Lawyer              |
| PATCH  | `/notifications/{id}`           | Update/cancel notification    | Admin, Lawyer              |
| DELETE | `/notifications/{id}`           | Cancel notification           | Admin, Lawyer              |
| POST   | `/notifications/send`           | Send message immediately      | Admin, Lawyer              |
| POST   | `/notifications/process`        | Trigger scheduler             | Admin                      |
| GET    | `/notifications/templates/list` | List WhatsApp templates       | Admin, Lawyer              |

### IP Agent (`/agents/ip`)

| Method | Path                            | Description              | Auth           |
|--------|---------------------------------|--------------------------|----------------|
| POST   | `/agents/ip/scan-deadlines`     | Run deadline scanner     | Admin          |
| GET    | `/agents/ip/upcoming-deadlines` | List upcoming deadlines  | Admin, Lawyer  |
| POST   | `/agents/ip/configure`          | Configure agent settings | Admin          |

## Testing

Run the full test suite:

```bash
pytest tests/ -v
```

There are currently 94 tests covering authentication, user management, case management, document handling, AI/RAG, notifications, and IP agent deadline tracking.

## Docker

Run the full stack (app + database) with Docker Compose:

```bash
docker-compose up
```

This starts PostgreSQL with pgvector and the FastAPI application. See `docker-compose.yml` for service configuration.

## License

Proprietary. All rights reserved.
