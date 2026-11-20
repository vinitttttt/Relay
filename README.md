# Relay — Real-Time Messaging Platform

Relay is a full-stack messaging application for account registration, finding people by username, and having direct conversations. Messages are persisted through a REST API and delivered to connected participants over authenticated WebSockets.

**Live demo: [Try Relay](https://relay-1f.onrender.com)**

## Try Relay

1. Open the [live application](https://relay-1f.onrender.com) and register with a username, email address, and password.
2. Sign in, then search for the public username **`vinit`**.
3. Select the matching user to start or open a direct conversation, then send a message.
4. To experience live message delivery between participants, use two separate accounts in two browser sessions (for example, a regular window and a private window). Register both accounts and open the same conversation.

The hosted service may take a short time to respond after inactivity because it runs on free hosting.

## Screenshots

### Sign-in screen

![Relay sign-in screen](screenshots/Screenshot%202026-11-20%20132341.png)

### Workspace and username search

![Relay workspace with username search](screenshots/Screenshot%202026-11-20%20132438.png)

### Direct conversation

![Relay direct conversation and message composer](screenshots/Screenshot%202026-11-20%20132458.png)

## Features

- Account registration and password authentication.
- Username search to find other Relay users.
- One-to-one direct conversations.
- Real-time message delivery over authenticated WebSockets.
- Paginated message history, with forward recovery after reconnecting.
- Retry-safe message sending using client message IDs to prevent duplicate delivery when a request is retried.
- WebSocket reconnection and recovery of missed messages from persisted history.
- Configurable rate limits and exact-origin CORS and WebSocket origin checks.

## Technology stack

- **Frontend:** React, Vite, JavaScript.
- **Backend:** Python, FastAPI, SQLAlchemy, Pydantic, Uvicorn.
- **Data and migrations:** PostgreSQL for hosted deployments, SQLite for local development, Alembic.
- **Live communication:** WebSockets, with REST endpoints for authentication, conversation management, and message history.
- **Hosting:** Render for the live application and Neon for managed PostgreSQL.

## Architecture

The React client uses the versioned FastAPI REST API for authentication, username search, direct-conversation setup, and paginated message history. SQLAlchemy persists users, conversations, memberships, and messages in PostgreSQL or SQLite; Alembic manages schema migrations. For live messaging, the client requests a short-lived, one-use WebSocket ticket over REST and presents it when connecting. The backend checks the ticket, browser origin, and conversation membership before accepting the connection, then broadcasts persisted message events to connected participants on that backend process.

## Local setup

### Prerequisites

- Python 3.10 or newer.
- Node.js 20.19 or newer and npm.
- Git.
- SQLite (included with Python) for local development. PostgreSQL is optional locally.

### Backend — Windows PowerShell

Run from the repository root:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Set the generated value as JWT_SECRET_KEY in .env. Keep .env private.
python -m venv backend/.venv
./backend/.venv/Scripts/Activate.ps1
python -m pip install -e "./backend[dev]"
Set-Location backend
alembic upgrade head
uvicorn app.main:app --reload
```

If PowerShell blocks activation, use the virtual environment's Python directly to install: `./backend/.venv/Scripts/python.exe -m pip install -e "./backend[dev]"`. Then, from `backend/`, start the API with `../backend/.venv/Scripts/python.exe -m uvicorn app.main:app --reload`.

### Backend — macOS, Linux, or another shell

Run from the repository root:

```sh
test -f .env || cp .env.example .env
python -c 'import secrets; print(secrets.token_urlsafe(48))'
# Set the generated value as JWT_SECRET_KEY in .env. Keep .env private.
python -m venv backend/.venv
. backend/.venv/bin/activate
python -m pip install -e 'backend[dev]'
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`.

### Frontend

In a second terminal, from the repository root:

```sh
cd frontend
npm install
npm run dev
```

Vite serves the app at `http://localhost:5173` and proxies `/api` and `/ws` to `http://127.0.0.1:8000` by default. To use a different local API address, set `VITE_DEV_API_PROXY_TARGET` in `frontend/.env` (see `frontend/.env.example`).

### Environment configuration

The root `.env` configures the backend. Start with `.env.example` and set a private `JWT_SECRET_KEY` of at least 32 bytes. `DATABASE_URL` defaults to local SQLite; use a PostgreSQL SQLAlchemy URL when connecting to PostgreSQL. Set `CORS_ALLOWED_ORIGINS` to the exact browser origins allowed to use the API. Frontend build variables belong in `frontend/.env`; only `VITE_` variables are exposed to browser code, so never put secrets there. See `.env.example` and `frontend/.env.example` for available settings and defaults. Never commit either `.env` file.

### Database migrations

Apply the checked-in migrations from `backend/` before starting the API:

```sh
cd backend
alembic upgrade head
```

When changing database models, generate and review a migration with `alembic revision --autogenerate -m "describe the change"`, then apply it with `alembic upgrade head`.

## Limitations

- Relay supports direct text conversations. It does not currently include group messaging, file sharing, read receipts, or notifications.
- WebSocket connections, one-use tickets, and rate-limit counters are held in memory. They reset on restart and are not shared across workers, so the current backend requires a single process.
- Free hosting may introduce cold starts.

## Future improvements

- Group conversations.
- File sharing.
- Read receipts and notifications.
- Persistent storage for pending messages.
