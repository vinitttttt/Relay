# Relay

Relay is a full-stack real-time messaging application built with FastAPI, React, SQLAlchemy, and SQLite. It includes user registration and login, conversation and message REST APIs, paginated history, and authenticated real-time messaging over WebSockets.

## Repository layout

```text
backend/
  alembic/              Database migration environment and revisions
  app/
    api/                Routes and reusable request dependencies
    core/               Environment-based configuration
    db/                 SQLAlchemy base, engine, and session dependency
    models/             SQLAlchemy ORM models
    schemas/             Validated request and response models
    security/            Argon2 password and JWT helpers
    services/            Authentication and persistence logic
    main.py              FastAPI application
  data/                  Local SQLite database file
  tests/                 Pytest tests
frontend/                 React + Vite application
.env.example              Local configuration template
```

## Requirements

- Python 3.10 or newer
- Node.js 20.19 or newer and npm

No database server or Docker is required for local development. SQLite creates `backend/data/relay.db` automatically; the database and sidecar files are ignored by Git.

## Configure and run the backend

From the repository root, create `.env` from the template only if you do not already have one. Set `JWT_SECRET_KEY` to a random value of at least 32 bytes. Generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Create the virtual environment once, activate it, and install the backend with development dependencies:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -e "./backend[dev]"
```

Apply the initial database migration and start the API from `backend/`:

```powershell
Set-Location backend
alembic upgrade head
uvicorn app.main:app --reload
```

The API is available at <http://localhost:8000>; interactive documentation is at <http://localhost:8000/docs>.

## Authentication API

- `POST /api/v1/auth/register` accepts `username`, `email`, and `password`, and returns a public user profile.
- `POST /api/v1/auth/login` accepts `identifier` (username or email) and `password`, and returns a bearer access token.
- `GET /api/v1/auth/me` returns the current user's public profile and requires `Authorization: Bearer <access_token>`.

Emails are trimmed and normalized to lowercase. Passwords are hashed with Argon2 before storage. Login failures use the same response for unknown accounts and incorrect passwords. Public responses never include password hashes.

`JWT_SECRET_KEY` is required for token creation and must be at least 32 bytes. `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` controls access-token lifetime and defaults to 30 minutes. Tokens use HS256 and are checked for signature, expiration, token type, and an existing user.

The frontend obtains a short-lived, single-use WebSocket ticket through `POST /api/v1/auth/websocket-ticket`. The WebSocket endpoint consumes the ticket and binds the connection lifetime to the authenticated JWT expiration. Tickets and active connection state are stored in process memory. This is suitable only for a single backend process; multiple workers or replicas need a shared ticket store and cross-process WebSocket broadcast mechanism.

For deployment, serve the frontend and API on the same origin or configure a strict CORS allowlist at FastAPI or the reverse proxy. The reverse proxy must forward WebSocket upgrades from `/ws` and use WSS when serving the site over HTTPS. Do not log the `Sec-WebSocket-Protocol` request header because it carries the temporary ticket.

Run backend tests from `backend/` with:

```powershell
python -m pytest tests
```

## Database models and migrations

- `User` stores usernames, normalized emails, password hashes, and creation times.
- `Conversation` represents a direct or group conversation.
- `ConversationMember` links users to conversations and records when they joined.
- `Message` stores content, its conversation, sender, and creation time.

The models use SQLAlchemy relationships, foreign keys, unique constraints, and indexes. Alembic uses the same `DATABASE_URL` as the application. After changing models, create and review a revision with `alembic revision --autogenerate -m "describe the change"`, then apply it with `alembic upgrade head`. To roll back one revision, use `alembic downgrade -1`.

## PostgreSQL later

The application uses a configurable SQLAlchemy URL and can use PostgreSQL without application code changes. Set `DATABASE_URL` in `.env` to a PostgreSQL URL, for example:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/relay
```

The PostgreSQL server must be available separately. Keep real credentials out of source control and URL-encode reserved characters in credentials.

## Run the frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

Vite prints the local development URL after it starts.
