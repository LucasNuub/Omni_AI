# AI Gateway — Build Spec

**Scope:** Personal use + a handful of friends/family. One backend, one PWA frontend.
**Guiding rule:** Build the *shape* of a production system (clean adapter pattern, typed, tested) but size every piece for ~5-15 concurrent users, not millions. Swapping SQLite→Postgres or dict-cache→Redis later should be a config change, not a rewrite.

---

## 1. Goal

A single OpenAI-compatible endpoint that routes chat/image requests across multiple free AI providers, with automatic fallback when one is rate-limited or down, a shared pool for no-signup providers, optional personal API keys per user, a self-updating **Model Registry** that picks the best model per task, zero-config onboarding when a key is added, and a PWA usable on desktop and Android.

---

## 2. Architecture

```
                    ┌─────────────────────┐
   Browser/PWA ───▶ │   SvelteKit PWA      │
   (desktop/Android) │ (chat/compare/models/│
                     │  providers/admin)    │
                     └──────────┬───────────┘
                                │ REST + SSE
                     ┌──────────▼───────────┐
                     │   FastAPI Gateway     │
                     │  ┌─────────────────┐  │
                     │  │ Routing Engine   │  │
                     │  │ (profiles +      │  │
                     │  │  circuit breaker)│  │
                     │  └────────┬─────────┘  │
                     │  ┌────────▼─────────┐  │
                     │  │ Model Registry    │  │
                     │  │ (ratings, caps)   │  │
                     │  └────────┬─────────┘  │
                     │  ┌────────▼─────────┐  │
                     │  │ Discovery Service │  │
                     │  │ (verify/scan/     │  │
                     │  │  benchmark)       │  │
                     │  └────────┬─────────┘  │
                     │  ┌────────▼─────────┐  │
                     │  │ Provider Adapters │  │
                     │  └────────┬─────────┘  │
                     └───────────┼────────────┘
                                 │
        ┌───────┬───────┬───────┼───────┬───────┬────────┐
        ▼       ▼       ▼       ▼       ▼       ▼        ▼
      Groq   Gemini  OpenRouter Pollinations HF  DeepSeek Ollama(local)

   SQLite (users, keys, models, requests, quota) via SQLAlchemy + Alembic
```

---

## 3. Tech Stack

**Backend:** Python 3.12, FastAPI, Pydantic v2, httpx (async), SQLAlchemy 2 + Alembic, SQLite, LiteLLM (used inside adapters where it saves work, not as the whole system), `cryptography` (Fernet, for key-at-rest encryption), Structlog (JSON logs to file), pytest + pytest-asyncio, Ruff + Black + MyPy.

**Frontend:** SvelteKit (PWA), TypeScript, Tailwind. Service worker for installability/offline shell.

**Deployment:** Docker Compose (gateway + web + optional `cloudflared` tunnel container). No Nginx, no Postgres, no Redis, no Prometheus stack — not yet.

**CI:** One GitHub Actions workflow — lint + test on push.

---

## 4. Folder Structure

```
ai-gateway/
├── backend/
│   ├── app/
│   │   ├── api/                # route handlers
│   │   │   ├── chat.py
│   │   │   ├── images.py
│   │   │   ├── compare.py
│   │   │   ├── providers.py    # key add/list/rescan/delete
│   │   │   ├── models.py       # Model Registry endpoints
│   │   │   ├── auth.py
│   │   │   ├── admin.py
│   │   │   └── health.py
│   │   ├── core/
│   │   │   ├── config.py       # env/YAML settings
│   │   │   ├── security.py     # JWT, password hashing, Fernet key encryption
│   │   │   └── logging.py
│   │   ├── providers/
│   │   │   ├── base.py         # ProviderAdapter interface
│   │   │   ├── model_capabilities.json  # curated seed table (coding/reasoning tags)
│   │   │   ├── groq.py
│   │   │   ├── gemini.py
│   │   │   ├── openrouter.py
│   │   │   ├── pollinations.py
│   │   │   ├── huggingface.py
│   │   │   ├── deepseek.py
│   │   │   └── ollama.py
│   │   ├── discovery/
│   │   │   └── scanner.py      # verify key -> discover models -> benchmark -> save
│   │   ├── router/
│   │   │   ├── engine.py       # profile + capability selection, fallback chain
│   │   │   └── circuit_breaker.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte            # chat
│   │   │   ├── compare/+page.svelte
│   │   │   ├── models/+page.svelte     # Model Registry catalog
│   │   │   ├── providers/+page.svelte  # quota traffic lights
│   │   │   ├── settings/+page.svelte   # Add Provider wizard + key list
│   │   │   ├── admin/+page.svelte
│   │   │   ├── login/+page.svelte
│   │   │   └── invite/[code]/+page.svelte
│   │   └── lib/
│   ├── static/manifest.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 5. Provider Adapter Interface

Every provider implements the same contract — adding a new one later is one file:

```python
class ProviderAdapter(Protocol):
    name: str
    auth_type: Literal["api_key", "none", "local"]

    async def validate_key(self, api_key: str | None) -> bool: ...
    async def discover_models(self, api_key: str | None) -> list[DiscoveredModel]: ...
    async def benchmark(self, model_id: str, api_key: str | None) -> BenchmarkResult: ...

    async def chat(self, messages: list[Message], model_id: str, **kwargs) -> AsyncIterator[ChatChunk]: ...
    async def generate_image(self, prompt: str, **kwargs) -> ImageResult: ...
    async def health_check(self) -> HealthStatus: ...
    def remaining_quota(self, usage_row: QuotaUsage) -> QuotaStatus: ...
```

`discover_models` calls the provider's own model-list endpoint where one exists; falls back to a static known list in the adapter for providers that don't expose one. `benchmark` sends one short fixed prompt (e.g. "Reply with the word OK.") and times it — this is what the scanner uses to compute the speed rating.

---

## 6. Initial Provider Set (MVP)

| Provider | Auth | Chat | Vision | Image | Notes |
|---|---|---|---|---|---|
| Groq | API key (user or shared) | done | - | - | Fast, tight per-minute limits |
| Google Gemini API | API key | done | done | - | Generous free tier |
| OpenRouter | API key | done (:free models) | some | - | Widest model variety |
| Pollinations | none | done | - | done | Shared pool by default, no signup |
| HuggingFace Inference | API key | done | some | some | Free serverless tier |
| DeepSeek Platform | API key | done | - | - | Strong reasoning model |
| Ollama | none (local) | done | model-dependent | - | Always-available fallback, runs on your host |

Every provider except Pollinations and Ollama needs a *user's own* key — the app never bundles working credentials for those.

---

## 7. Model Registry

The catalog that makes the UI say "Llama 4 - Groq - speed 5/5 - Free - Vision: No - Coding: 4/5" instead of a bare provider name. Each `Model` row is built from two merged sources:

**Live-detected (from the Discovery Service):**
- `context_length` — from the provider's model metadata when exposed
- `supports_vision` — from provider metadata when exposed
- `speed_rating` (1-5 stars) — bucketed from the benchmarked latency, refreshed on every rescan
- `free` — static per provider (all MVP providers are free; field exists so a paid provider can be added later without a schema change)

**Curated (from `model_capabilities.json`, matched by model-family name pattern):**
- `supports_coding_hint`, `supports_reasoning_hint` — star ratings, seeded from public leaderboards (LMArena, Artificial Analysis, OpenRouter rankings) at build time, hand-editable, not live-queried
- Unmatched models get `quality_source: "unrated"` rather than a guessed rating

The router (section 8) reads this table to pick models by capability, not just by provider.

---

## 8. Routing Engine

Three profiles, resolved at the **model** level via the Model Registry, not just provider level:

- **Fast** — lowest recent `speed_rating`/latency among currently healthy, enabled models.
- **Balanced** (default) — priority-ordered list, first healthy model with matching required capability.
- **Best quality** — highest coding/reasoning/vision rating (whichever the request needs) among healthy, enabled models, regardless of which provider it's on.

**Fallback:** on failure, retry once, then move to the next model in the resolved chain — which may mean switching providers entirely. Never surface raw provider errors to the client — return a normalized error and log the real one.

**Circuit breaker (lazy, not polling):** no background workers pinging providers constantly. On a failed request, mark the provider `cooling_down_until = now + backoff`. Next request just skips it until that time passes, then tries again and either clears the flag or doubles the backoff. Costs zero quota when nobody's using the app.

---

## 9. Provider Onboarding & Auto-Discovery

The "add provider" flow — zero manual config after pasting a key.

**Trigger:** `POST /providers/keys {provider_name, api_key, nickname}` — runs as an async background job; frontend polls (or gets pushed) status.

**Pipeline:**
1. `validate_key` — adapter's lightweight check (list-models call or 1-token completion). Fail -> `status: invalid_key`, stop here, nothing saved as if it worked.
2. `discover_models` — fetch the live model list for that provider/key.
3. `benchmark` — one short test prompt per discovered model (capped at a sane sample size so this doesn't itself burn the day's quota) -> speed rating.
4. `merge_capabilities` — join live-detected fields with `model_capabilities.json` by model-family match.
5. `save` — upsert into `Model`, set `ProviderKey.status = active`, `health_status = green`.

**Frontend (`/settings`):** select provider -> paste key -> optional nickname -> submit -> live checklist:
`Verifying key [done] -> Discovering models [done] -> Benchmarking [done] -> Done — 6 models added`
Any step failing shows exactly which one and why. A **Rescan** button re-runs the same pipeline for an existing key (useful after a provider adds new models).

---

## 10. Key Storage & Encryption

`ProviderKey.encrypted_key` is stored via Fernet symmetric encryption (`cryptography` package), using a `MASTER_ENCRYPTION_KEY` held only in `.env` (already git-ignored, never committed). Auto-generated on first run if absent, printed once with a warning to back it up — losing it means every stored key needs to be re-entered, there's no recovery path by design.

Decryption happens only in-memory, at the moment an adapter needs to make a call — never logged, never sent to the frontend. The frontend only ever sees the nickname and a masked tail (`sk-...ab12`) plus metadata, never the full key after initial entry.

**Honest scope of this protection:** it stops keys from leaking via git history, casual DB backups, or someone glancing at a DB dump. It does *not* protect against a fully compromised host with access to both the database and the running process's environment/memory — that's not solvable without a real secrets manager, which is overkill for a small trusted-group deployment sitting behind a Cloudflare Tunnel with no open ports.

---

## 11. Database Schema

```python
User(id, email, password_hash, is_admin, created_at)
Invite(id, code, created_by_user_id, used_by_user_id, expires_at)

ProviderKey(
    id, user_id_or_null, provider_name, nickname,
    encrypted_key, is_shared,
    added_at, last_used_at,
    daily_usage_count, daily_usage_reset_at,
    health_status,      # green | yellow | red
    status,             # pending | active | invalid_key | revoked
)

Provider(id, name, base_url, auth_type, priority, enabled, cooling_down_until)

Model(
    id, provider_name, model_id, display_name,
    supports_vision, supports_coding_hint, supports_reasoning_hint,
    context_length,
    speed_rating,        # 1-5, benchmarked
    free,                # bool, static
    quality_source,      # "benchmarked" | "curated" | "unrated"
    enabled,
    last_scanned_at,
)

RequestLog(id, user_id, provider_name, model_id, endpoint, latency_ms, tokens_in, tokens_out,
           status, fallback_count, trace_id, created_at)

QuotaUsage(id, user_id_or_null, provider_name, date, request_count, daily_limit)
```

`user_id_or_null` on `ProviderKey`/`QuotaUsage` distinguishes shared-pool rows from personal-key rows.

---

## 12. API Contract

```
POST /v1/chat/completions      # OpenAI-compatible, SSE streaming
POST /v1/images/generations    # OpenAI-compatible shape
POST /v1/compare               # {prompt, providers[]} -> [{provider, response}]

GET    /models                          # Model Registry, with ratings — powers /models UI + router
POST   /providers/keys                  # add a key, kicks off discovery pipeline (async)
GET    /providers/keys                  # list your keys (masked) + status
GET    /providers/keys/{id}/status      # poll discovery pipeline progress
POST   /providers/keys/{id}/rescan      # re-run discovery manually
DELETE /providers/keys/{id}

GET  /health                   # liveness
GET  /status                   # per-provider health + quota (drives traffic lights)

POST /auth/login
POST /auth/invite/redeem

POST /admin/invite             # generate invite link
POST /admin/provider/enable
POST /admin/provider/disable
GET  /admin/usage              # per-user usage table
```

Any existing OpenAI-SDK-based app can point at this gateway by changing only `base_url` and `api_key`.

---

## 13. Auth Model

Invite-link only — no public signup form. Admin generates a link (`/invite/{code}`), recipient sets a password, gets a JWT session. Single `is_admin` boolean; no granular RBAC needed for this group size.

---

## 14. Frontend Routes

- `/` — chat (model picker shows profile: Fast/Balanced/Best quality)
- `/compare` — same prompt to 2-3 providers side by side
- `/models` — Model Registry catalog: filterable/sortable, e.g. "Llama 4 - Groq - speed 5/5 - Free - Vision: No - Coding: 4/5"
- `/providers` — traffic-light grid (green/yellow/red per provider, remaining quota)
- `/settings` — **Add Provider wizard** (select -> paste key -> live discovery checklist) + list of existing keys with nickname/health/status/rescan/delete
- `/admin` — invites, per-user usage, enable/disable providers
- `/login`, `/invite/[code]`

---

## 15. Quota Traffic Lights

`/status` returns per-provider `{healthy, remaining_today, reset_at}`. Frontend renders a dot: green (plenty left), yellow (near limit), red (exhausted/cooling down). Cheap to compute from `QuotaUsage` + the circuit breaker state — no extra polling needed.

---

## 16. Ollama Fallback Tier

If every configured provider is unhealthy or exhausted at once, the router's last hop is always local Ollama (if the host running the gateway has it installed) — so chat degrades to "smaller local model" instead of a hard failure. Optional at setup, but recommended.

---

## 17. Deployment

`docker-compose.yml` with three services: `gateway` (FastAPI/uvicorn), `web` (SvelteKit, static or node adapter), `cloudflared` (tunnel — no port forwarding, no exposed IP). `.env.example` lists provider keys, `JWT_SECRET`, `MASTER_ENCRYPTION_KEY`, `DB_PATH`. One command: `docker compose up -d`.

**Frontend adapter decision:** `@sveltejs/adapter-static` with `fallback: 'index.html'`. Everything dynamic in this app is a client-side fetch to the FastAPI backend — nothing needs SvelteKit's own server routes or secrets — so this is architecturally a SPA/PWA, not an SSR app. Static output served via a minimal static server (e.g. `sirv`), not a full Node process.

---

## 18. Testing

- Adapter tests with mocked HTTP responses (success, rate-limit, timeout)
- Discovery pipeline tests: valid key, invalid key, provider with no model-list endpoint, benchmark timeout
- Router tests simulating provider/model failures -> confirm correct fallback order and circuit-breaker behavior
- FastAPI `TestClient` contract tests for each endpoint
- GitHub Actions: `ruff check`, `mypy`, `pytest` on every push

---

## 19. Phased Roadmap

1. **MVP spine** *(done)* — adapter interface, DB, router, circuit breaker, invite auth, key encryption. No real adapters yet, so no live endpoints.
2. **Provider adapters + frontend shell** *(parallel)* — real adapters built against the interface; PWA routes scaffolded against the documented API contract.
3. **API surface wiring** — `/v1/chat/completions` (SSE streaming), `/health`, `/status`, `/admin/provider/enable`, `/admin/provider/disable` actually wired to the router + whatever real adapters exist. This is what turns the spine into a working chat gateway.
4. **Auto-discovery + Model Registry** *(independent of phase 3, can run in parallel)* — key-add wizard, discovery pipeline, benchmarking, `model_capabilities.json` seed table, `/models` UI, router upgraded to resolve at model level.
5. **Media** — `/v1/images/generations`, `/compare` mode.
6. **Resilience** — quota traffic lights, Ollama fallback tier, `/admin/usage`.
7. **Polish** — PWA install prompts, offline shell, more providers as wanted.

Sequenced this way: prove router/circuit-breaker logic against fakes first (done), then real adapters, then wire the actual API surface on top of both. Auto-discovery layers on afterward instead of competing for the same files at the same time as the wiring work.

---

## 20. Suggested Task Split

**Claude Code** — the spine: routing engine + circuit breaker, DB schema/migrations, auth flow, the `ProviderAdapter` interface, the discovery pipeline (`discovery/scanner.py`) and key encryption (both security/correctness-sensitive and sequential — not a good parallelization target), final integration.

**Antigravity (parallel agents)** — the repeatable parts: one adapter per provider against the fixed interface, and the SvelteKit screens (including `/models` and the `/settings` wizard) against the fixed API contract once it exists.

**This chat** — spec upkeep, resolving ambiguities either tool hits, reviewing anything you want a second opinion on before it merges.

---

## 21. Current Status

*Update this table as work lands — it's the source of truth, not phase numbers in chat scrollback.*

| Tool | Task | Status |
|---|---|---|
| Claude Code | Spine — interface, DB, router, circuit breaker, auth, encryption | Done |
| Antigravity | Provider adapters (Groq, Gemini, OpenRouter, Pollinations, HF, DeepSeek, Ollama) | Done — 7/7, 145 tests passing |
| Antigravity | Frontend shell (SvelteKit PWA routes) | Done — adapter-static pinned, build validated |
| Claude Code | Model Registry & Discovery (scanner, `model_capabilities.json`, model-level routing, `/models` + key endpoints) | Done — 208/216 tests passing, 8 expected failures are chat.py's pending patch |
| Claude Code | API Surface Wiring (`/v1/chat/completions`, `/health`, `/status`, admin toggles) | Done, chat.py needs the model-level patch — prompt ready, run now |
| Claude Code | Patch `chat.py` onto model-level routing | Done — 219/219 tests, ruff/mypy clean |
| Antigravity | Fix `ollama.py` sync/async streaming bug | Done — 219/219 tests, ruff/mypy clean |

**Known issue:** none currently open.

**Next up:** real end-to-end smoke test via `docker compose up` before starting Phase 5 (images/compare).