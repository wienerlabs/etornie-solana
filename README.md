# Etornie Solana

Full-stack intellectual property and Real-World-Asset (RWA) platform — forked from Etornie and being rebuilt for Solana blockchain integration. FastAPI backend with PostgreSQL + pgvector, Next.js 16 frontend with TypeScript and Tailwind CSS v4.

> This repository is the Solana-integrated variant of the original Etornie Platform. Branding, database, docker resources, and frontend theme have been forked under the `etornie-solana` namespace. On-chain (Solana) integration is the upcoming phase.

## Tech Stack

| Component        | Technology                                    |
|------------------|-----------------------------------------------|
| Backend          | FastAPI (Python 3.12+)                        |
| Frontend         | Next.js 16 + React 19, TypeScript, Tailwind v4|
| ORM              | SQLAlchemy 2.0 (async)                        |
| Database         | PostgreSQL 16 + pgvector                      |
| Cache / Queue    | Redis 7                                       |
| Migrations       | Alembic                                       |
| Auth             | JWT via python-jose, passlib + bcrypt         |
| LLM              | Groq (Llama 3.3 70B Versatile)                |
| Embeddings       | Together AI (multilingual-e5-large-instruct)  |
| WhatsApp         | WhatsApp Business Cloud API (Meta)            |
| Email            | EmailJS (OTP verification + case alerts)      |
| Blockchain       | Solana (integration in progress)              |
| Containerization | Docker, Docker Compose                        |

## Frontend — Beige / RWA Theme

The frontend is themed around a cream/bronze/gold (bej) palette with subtle Solana purple/green accents for on-chain cues:

- Landing page (`/`) with hybrid crypto-native + enterprise-trust positioning
- Login (`/login`) with role selection (Admin / Lawyer / Client) and Solana chain badge
- Dashboard stats cards mapped to semantic warm tones per case status (Open / In Progress / Under Review / Completed)
- Global Tailwind gray/blue token overrides for a unified beige system across all pages
- WCAG AA contrast-tuned muted color

## Features

### Authentication and Authorization
- JWT-based authentication with access and refresh tokens
- Role-based access control (RBAC) with three roles: admin, lawyer, client
- Email verification on registration via EmailJS with 6-digit OTP
- Solana wallet sign-in (Phantom and Solflare) with ed25519 nonce challenge,
  single-use Redis-backed nonces, and short public handles (`etornie_<8char>`)
- Wallet sign-up is restricted to `client` and `lawyer` roles; the admin
  role cannot be self-assigned through the wallet flow
- Guest client auto-linking on registration (matches by email or phone)

## Features

### Authentication and Authorization
- JWT-based authentication with access and refresh tokens
- Role-based access control (RBAC) with three roles: admin, lawyer, client
- Email verification on registration via EmailJS with 6-digit OTP
- Solana wallet sign-in (Phantom and Solflare) with ed25519 nonce challenge,
  single-use Redis-backed nonces, and short public handles (`etornie_<8char>`)
- Wallet sign-up is restricted to `client` and `lawyer` roles; the admin
  role cannot be self-assigned through the wallet flow
- Guest client auto-linking on registration (matches by email or phone)

### User Management
- Full CRUD with pagination
- Soft delete (deactivation)
- Phone number field
- Profile self-service (users update own profile; admins manage all)

### Case Management
- IP case tracking for trademark, patent, design, and copyright matters
- Auto-numbered case references (ETR-YYYY-NNNN format)
- Status workflow: open, in_progress, under_review, closed
- Case notes with create, list, and delete operations
- Guest client support: create cases for unregistered clients with name, email, and phone
- Auto-linking: guest cases are linked to the client account upon registration
- Role-based filtering: admins see all, lawyers see assigned, clients see own
- Jurisdiction, filing date, and deadline tracking

### Document Management
- File upload and download scoped to cases
- Role-based access (case participants only)
- Delete restricted to admin or original uploader
- Stored on filesystem with unique filenames

### Notifications
- WhatsApp Business Cloud API (Meta) integration
- Template and text message support
- Scheduled notifications with retry logic
- Immediate send endpoint
- Notification scheduler with manual trigger
- Template listing from WhatsApp Business Account
- Email notifications via EmailJS for case creation alerts (registered and guest clients)

### EtornieGPT -- AI Assistant
- Groq LLM integration (Llama 3.3 70B Versatile)
- Specialized IP law system prompt
- Two chat modes: simple chat and RAG-augmented chat
- RAG pipeline: document indexing, similarity search, augmented responses
- Together AI embeddings with pgvector storage
- RBAC-filtered search results

### IP Agent
- Automatic deadline tracking agent
- Day-based reminders (configurable intervals, default 30/7/1 days)
- Minute-based reminders for same-day deadlines
- Auto-creates WhatsApp notifications for assigned lawyers and clients
- Duplicate prevention
- Configurable reminder intervals via admin endpoint
- Enable/disable toggle

### Frontend (Next.js)
- Role-based login with role enforcement (Admin, Lawyer, Client)
- Registration with email OTP verification flow
- Dashboard with summary statistics
- Cases: list with status filters, create (registered or guest client), detail view, status update, notes, documents, print/PDF/Excel export
- Users management (admin only)
- Notifications: create, send now, process pending, list WhatsApp templates
- AI Chat: EtornieGPT IP law assistant interface
- IP Agent: scan deadlines, view upcoming deadlines, configure intervals
- Role-based sidebar navigation

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- Docker and Docker Compose

### Backend Setup

1. Copy the environment file and configure values:
   ```bash
   cp .env.example .env
   ```

2. Start PostgreSQL and Redis (Etornie Solana containers — namespaced to avoid collision with the original `etornie` stack):
   ```bash
   docker compose up -d etornie-solana-db etornie-solana-redis
   ```

   Ports are intentionally shifted so both stacks can run side-by-side:
   - Postgres: host `5433` → container `5432`
   - Redis:    host `6380` → container `6379`

3. Install dependencies (Python 3.12 venv recommended):
   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   .venv/bin/pip install together groq
   ```

4. Run database migrations:
   ```bash
   .venv/bin/alembic upgrade head
   ```

5. Start the backend:
   ```bash
   .venv/bin/uvicorn app.main:app --reload
   ```

6. Verify the server is running:
   ```bash
   curl http://localhost:8000/health
   # {"status":"ok"}
   ```

API docs are available at `http://localhost:8000/docs` (Swagger) and `http://localhost:8000/redoc`.

### Frontend Setup

1. Install dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Create `.env.local` with the API URL:
   ```bash
   echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
   ```

3. Start the development server on your preferred port:
   ```bash
   npx next dev --port 5171
   ```

The frontend is available at `http://localhost:5171`.

### Frontend Routes

| Route         | Purpose                                              |
|---------------|------------------------------------------------------|
| `/`           | Marketing landing page (hybrid crypto-native + enterprise) |
| `/login`      | Role-based login (Admin / Lawyer / Client)          |
| `/register`   | Registration with email OTP verification            |
| `/dashboard`  | Authenticated workspace                              |

## Project Structure

### Backend

```
app/
├── main.py              # FastAPI application entry point
├── config.py            # Settings via pydantic-settings
├── database.py          # SQLAlchemy async engine and session
├── auth/                # Authentication -- JWT, RBAC, email verification, dependencies
├── users/               # User module -- model, schemas, CRUD service, router
├── cases/               # Case module -- models, auto-numbering, guest linking, router
├── documents/           # Document module -- file upload/download, router
├── ai/                  # EtornieGPT -- Groq client, Together AI client, RAG pipeline
├── notifications/       # Notifications -- WhatsApp client, EmailJS, scheduler, case alerts
└── agents/
    └── ip_agent/        # IP Agent -- deadline scanning, config, auto-notifications
```

### Frontend

```
frontend/
├── src/
│   ├── app/             # Next.js pages and layouts
│   ├── components/      # Reusable UI components
│   ├── lib/             # API client, auth utilities
│   └── types/           # TypeScript type definitions
├── public/              # Static assets
└── tailwind.config.ts   # Tailwind CSS configuration
```

## API Endpoints

### Health

| Method | Path      | Description  | Auth   |
|--------|-----------|--------------|--------|
| GET    | `/health` | Health check | Public |

### Authentication (`/auth`)

| Method | Path                   | Description                              | Auth      |
|--------|------------------------|------------------------------------------|-----------|
| POST   | `/auth/register`       | Register account (direct, no OTP)        | Public    |
| POST   | `/auth/register/request` | Request email verification (send OTP)  | Public    |
| POST   | `/auth/register/verify`  | Verify OTP and create account          | Public    |
| POST   | `/auth/register/admin` | Register any role (admin-only)           | Admin     |
| POST   | `/auth/login`          | Login, receive JWT tokens                | Public    |
| POST   | `/auth/refresh`        | Refresh access token                     | Public    |
| GET    | `/auth/me`             | Get current user profile                 | Logged in |

### Users (`/users`)

| Method | Path           | Description      | Auth          |
|--------|----------------|------------------|---------------|
| GET    | `/users`       | List all users   | Admin         |
| GET    | `/users/{id}`  | Get user by ID   | Admin or self |
| PATCH  | `/users/{id}`  | Update user      | Admin or self |
| DELETE | `/users/{id}`  | Soft-delete user | Admin         |

### Cases (`/cases`)

| Method | Path                           | Description            | Auth                      |
|--------|--------------------------------|------------------------|---------------------------|
| POST   | `/cases`                       | Create a new case      | Admin, Lawyer             |
| GET    | `/cases`                       | List cases (filtered)  | Logged in (role-filtered) |
| GET    | `/cases/{id}`                  | Get case detail        | Admin, assigned, client   |
| PATCH  | `/cases/{id}`                  | Update case            | Admin, assigned lawyer    |
| POST   | `/cases/{id}/notes`            | Add a note to a case   | Admin, assigned, client   |
| GET    | `/cases/{id}/notes`            | List notes for a case  | Admin, assigned, client   |
| DELETE | `/cases/{id}/notes/{note_id}`  | Delete a note          | Admin, assigned, author   |

### Documents

| Method | Path                            | Description         | Auth              |
|--------|---------------------------------|---------------------|-------------------|
| POST   | `/cases/{id}/documents`         | Upload a document   | Case participants |
| GET    | `/cases/{id}/documents`         | List case documents | Case participants |
| GET    | `/documents/{id}/download`      | Download a document | Case participants |
| DELETE | `/documents/{id}`               | Delete a document   | Admin or uploader |

### AI / EtornieGPT (`/ai`)

| Method | Path                      | Description            | Auth          |
|--------|---------------------------|------------------------|---------------|
| POST   | `/ai/index/{document_id}` | Index document for RAG | Admin, Lawyer |
| POST   | `/ai/search`              | Search similar content | Logged in     |
| POST   | `/ai/chat`                | EtornieGPT chat (simple or RAG) | Logged in |

### Notifications (`/notifications`)

| Method | Path                            | Description                   | Auth                      |
|--------|---------------------------------|-------------------------------|---------------------------|
| POST   | `/notifications`                | Create scheduled notification | Admin, Lawyer             |
| GET    | `/notifications`                | List notifications            | Admin (all), Lawyer (own) |
| GET    | `/notifications/{id}`           | Get notification detail       | Admin, Lawyer             |
| PATCH  | `/notifications/{id}`           | Update/reschedule notification| Admin, Lawyer             |
| DELETE | `/notifications/{id}`           | Cancel notification           | Admin, Lawyer             |
| POST   | `/notifications/send`           | Send message immediately      | Admin, Lawyer             |
| POST   | `/notifications/process`        | Trigger notification scheduler| Admin                     |
| GET    | `/notifications/templates/list` | List WhatsApp templates       | Admin, Lawyer             |

### IP Agent (`/agents/ip`)

| Method | Path                            | Description              | Auth          |
|--------|---------------------------------|--------------------------|---------------|
| POST   | `/agents/ip/scan-deadlines`     | Run deadline scanner     | Admin         |
| GET    | `/agents/ip/upcoming-deadlines` | List upcoming deadlines  | Admin, Lawyer |
| POST   | `/agents/ip/configure`          | Configure agent settings | Admin         |

## Frontend Pages

| Page               | Path               | Access         | Description                                     |
|--------------------|--------------------|----------------|-------------------------------------------------|
| Login              | `/login`           | Public         | Role-based login form                           |
| Register           | `/register`        | Public         | Registration with email OTP verification        |
| Dashboard          | `/dashboard`       | Logged in      | Summary statistics and overview                 |
| Cases List         | `/cases`           | Logged in      | Cases with status filters and search            |
| Create Case        | `/cases/new`       | Admin, Lawyer  | Create case for registered or guest client      |
| Case Detail        | `/cases/[id]`      | Participants   | Status update, notes, documents, export         |
| Users Management   | `/users`           | Admin          | User list, create, edit, deactivate             |
| Notifications      | `/notifications`   | Admin, Lawyer  | Create, send, process, template list            |
| AI Chat            | `/ai`              | Logged in      | EtornieGPT IP law assistant                     |
| IP Agent           | `/agents/ip`       | Admin, Lawyer  | Scan deadlines, view upcoming, configure        |

## Testing

Run the full test suite:

```bash
pytest tests/ -v
```

There are currently 132 tests covering:

- Authentication (JWT, registration, email verification, refresh tokens)
- User management (CRUD, soft delete, role enforcement)
- Case management (CRUD, auto-numbering, status workflows, guest clients)
- Case notifications (WhatsApp and email on case creation)
- Document handling (upload, download, delete, access control)
- AI/RAG (Groq chat, document indexing, similarity search)
- Notifications (WhatsApp scheduling, retry, templates)
- IP Agent (deadline scanning, upcoming deadlines, configuration)
- Guest linking (auto-link guest cases on registration)

## Environment Variables

| Variable                     | Required | Default                                       | Description                                |
|------------------------------|----------|-----------------------------------------------|--------------------------------------------|
| `DATABASE_URL`               | Yes      | --                                            | PostgreSQL connection string (asyncpg)     |
| `JWT_SECRET`                 | Yes      | --                                            | Secret key for JWT signing                 |
| `JWT_ALGORITHM`              | No       | `HS256`                                       | JWT signing algorithm                      |
| `ACCESS_TOKEN_EXPIRE_MINUTES`| No       | `30`                                          | Access token TTL in minutes                |
| `REFRESH_TOKEN_EXPIRE_DAYS`  | No       | `7`                                           | Refresh token TTL in days                  |
| `CORS_ORIGINS`               | Yes      | --                                            | Allowed CORS origins (JSON array)          |
| `UPLOAD_DIR`                 | No       | `./uploads`                                   | File upload storage directory              |
| `DEBUG`                      | No       | `false`                                       | Enable debug mode                          |
| `GROQ_API_KEY`               | No       | --                                            | Groq API key for EtornieGPT                |
| `GROQ_MODEL`                 | No       | `llama-3.3-70b-versatile`                     | Groq model identifier                     |
| `TOGETHER_API_KEY`           | No       | --                                            | Together AI API key for embeddings/RAG     |
| `TOGETHER_MODEL`             | No       | `meta-llama/Llama-3-70b-chat-hf`             | Together AI model identifier               |
| `TOGETHER_EMBEDDING_MODEL`   | No       | `togethercomputer/m2-bert-80M-8k-retrieval`  | Together AI embedding model                |
| `WHATSAPP_API_TOKEN`         | No       | --                                            | WhatsApp Business API bearer token         |
| `WHATSAPP_PHONE_NUMBER_ID`   | No       | --                                            | WhatsApp sender phone number ID            |
| `WHATSAPP_BUSINESS_ACCOUNT_ID`| No      | --                                            | WhatsApp Business Account ID               |
| `EMAILJS_PUBLIC_KEY`         | No       | --                                            | EmailJS public API key                     |
| `EMAILJS_SERVICE_ID`         | No       | --                                            | EmailJS service identifier                 |
| `EMAILJS_TEMPLATE_ID`       | No       | --                                            | EmailJS template for OTP verification      |
| `EMAILJS_CASE_TEMPLATE_ID`  | No       | --                                            | EmailJS template for case creation alerts  |
| `AGENT_LOOP_ADMIN_EMAIL`    | No       | --                                            | Admin email for agent loop authentication  |
| `AGENT_LOOP_ADMIN_PASSWORD` | No       | --                                            | Admin password for agent loop auth         |

## Docker

The compose project is named `etornie-solana`. All services, volumes, and host ports are namespaced under `etornie-solana` so the stack can coexist with the original `etornie` stack on the same machine.

| Service                 | Host port | Container port |
|-------------------------|-----------|----------------|
| `etornie-solana-db`     | 5433      | 5432           |
| `etornie-solana-redis`  | 6380      | 6379           |
| `etornie-solana-app`    | 8001      | 8000           |

Run the full stack (app + database + redis):

```bash
docker compose up
```

Uploaded files are mounted from `./uploads`. Data is persisted in the `etornie_solana_pgdata` and `etornie_solana_redisdata` named volumes.

To run only the infrastructure (db + redis) for local development:

```bash
docker compose up -d etornie-solana-db etornie-solana-redis
```

## Roadmap

- [x] Fork and rebrand to `etornie-solana` namespace
- [x] Beige / RWA theme across frontend
- [x] Landing page (`/`) with hybrid crypto-native + enterprise positioning
- [x] Login (`/login`) with role selection and chain badge
- [x] Dashboard stats semantic mapping (Open / In Progress / Under Review / Completed)
- [x] Public `/docs` page
- [x] Wallet sign-in with Phantom and Solflare (ed25519 nonce flow, Redis-backed, single-use)
- [x] ZK toolchain bootstrap (Circom + snarkjs pipeline, hello-world circuit)
- [ ] AI-agent payment compliance circuit (zk + x402 for EtornieGPT pay-per-query)
- [ ] File ownership attestation circuit with Light Protocol compressed mint
- [ ] Solana on-chain integration: SPL-based IP tokenization, attestation mint, lifecycle events
- [ ] Programmable licensing and collateralization primitives

## License

Proprietary. All rights reserved.
