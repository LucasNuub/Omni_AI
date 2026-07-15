# Omni AI — Personal AI Gateway

A single OpenAI-compatible endpoint that routes chat requests across multiple
free AI providers (Groq, Gemini, OpenRouter, Pollinations, HuggingFace,
DeepSeek, Ollama), with automatic provider/model fallback, a self-updating
Model Registry, and a PWA frontend. Built for personal use plus a handful of
friends and family — sized for ~5-15 concurrent users, not millions.

Full design spec: [`SPEC.md`](./SPEC.md).

## Architecture

```
Browser/PWA (SvelteKit) ──▶ FastAPI Gateway ──▶ Groq / Gemini / OpenRouter /
                              │                  Pollinations / HuggingFace /
                              ├─ Routing Engine   DeepSeek / Ollama (local)
                              ├─ Model Registry
                              ├─ Discovery Service
                              └─ Provider Adapters
                              SQLite (users, keys, models, requests, quota)
```

- **Routing Engine** — three profiles (Fast / Balanced / Best quality),
  resolved at the model level via the Model Registry, capability-aware
  (vision / coding / reasoning). Lazy circuit breaker per provider — no
  background polling.
- **Model Registry** — a catalog of every discovered model merged from
  live provider metadata and a curated capability seed table.
- **Discovery Service** — onboarding pipeline that validates a pasted API
  key, discovers its models, benchmarks them, and saves them to the
  registry, all as an async background job.
- **Provider Adapters** — one file per provider behind a common interface,
  so adding a new provider doesn't touch the router.

## Repo layout

```
Omni AI/
├── SPEC.md                  # full design spec
└── ai-gateway/
    ├── backend/              # FastAPI + SQLAlchemy 2 + Alembic (Python 3.12)
    │   ├── app/
    │   │   ├── api/          # route handlers (auth, chat, providers, models, admin, health)
    │   │   ├── core/         # config, JWT/Fernet security, logging
    │   │   ├── providers/    # ProviderAdapter interface + one adapter per provider
    │   │   ├── discovery/    # key validation → model discovery → benchmark → save
    │   │   ├── router/       # routing engine + circuit breaker
    │   │   └── db/           # SQLAlchemy models + session
    │   ├── alembic/          # DB migrations
    │   └── tests/
    └── frontend/             # SvelteKit PWA (chat / compare / models / providers / settings / admin)
```

## Status

Backend: auth (invite + JWT), key encryption, routing engine + circuit
breaker, full DB schema, Model Registry, discovery pipeline, and the
`/v1/chat/completions`, `/providers/keys`, `/models`, `/status`, `/admin/*`
endpoints are built and tested. Image generation, `/v1/compare`, and
Docker Compose deployment are not built yet (see section 19, "Phased
Roadmap", in `SPEC.md`).

Frontend: SvelteKit routes scaffolded (chat, compare, models, providers,
settings, admin, login, invite) against the API contract in `SPEC.md`
section 12.

## Getting started

### Backend

```sh
cd ai-gateway/backend
python -m venv .venv
./.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"

alembic upgrade head             # creates ./data/gateway.db
uvicorn app.main:app --reload    # http://localhost:8000
```

`MASTER_ENCRYPTION_KEY` (for encrypting stored provider keys) is
auto-generated into `backend/.env` on first run if not already set — back
it up, there's no recovery path if it's lost. See `SPEC.md` section 10.

Run the checks:

```sh
pytest
ruff check .
mypy app tests
```

### Frontend

```sh
cd ai-gateway/frontend
npm install
npm run dev                      # http://localhost:5173
```

Expects the backend at `http://localhost:8000` by default
(`src/lib/api.ts`).

## Tech stack

**Backend:** Python 3.12, FastAPI, Pydantic v2, httpx, SQLAlchemy 2 +
Alembic, SQLite, `cryptography` (Fernet), Structlog, pytest, Ruff, mypy
(strict).

**Frontend:** SvelteKit, TypeScript, Tailwind CSS, installable as a PWA.

**Deployment (planned):** Docker Compose — gateway + web + `cloudflared`
tunnel, no exposed ports.
