# Workflow Automation Engine — Codebase Context

> Last updated: 2026-04-10
> Template synced: 2026-04-10

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12 |
| Framework | FastAPI 0.115+ |
| Database | PostgreSQL 16 |
| Queue | Redis 7 + arq |
| Validation | Pydantic v2 |
| Expression Engine | Jinja2 (SandboxedEnvironment) |
| Test Runner | pytest + httpx + pytest-asyncio |
| ORM | SQLAlchemy (async) |
| Migrations | Alembic |
| HTTP Client | httpx (async) |
| Logging | structlog |
| Containerization | Docker + Docker Compose |
| Hosting | Docker on Hetzner VPS behind Traefik |

## Project Structure

```
workflow-automation-engine/
├── src/
│   ├── main.py            # FastAPI app entry point
│   ├── config.py          # Environment config loader
│   ├── engine/            # orchestrator, parser, state, context
│   ├── steps/             # base, http, transform, condition, delay, sub_workflow
│   ├── triggers/          # webhook, cron, manual
│   ├── queue/             # worker, tasks (arq)
│   ├── replay/            # service
│   ├── tenants/           # service, models, seed
│   ├── api/               # workflows, executions, webhooks, tenants, metrics, health
│   │   └── middleware/    # auth, rate_limit, errors
│   ├── db/                # postgres, redis, migrations/alembic
│   └── lib/               # logger, expressions, utils
├── tests/                 # unit/, integration/, e2e/, fixtures/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
└── .env.example
```

## Key Modules

| Module | Purpose | Key Files |
|--------|---------|-----------|
| Engine | DAG execution orchestrator, parser, state machine | `src/engine/` |
| Steps | Step type executors (http, transform, condition, delay, sub_workflow) | `src/steps/` |
| Triggers | Webhook, cron, manual execution triggers | `src/triggers/` |
| Queue | arq worker + async job dispatch for step execution | `src/queue/` |
| Replay | Execution replay with original/modified trigger data | `src/replay/` |
| Tenants | Multi-tenant lifecycle — registration, key validation, seed | `src/tenants/` |
| API | FastAPI route handlers + middleware (auth, rate limit, errors) | `src/api/` |
| DB | Async SQLAlchemy (PostgreSQL) + Redis client | `src/db/` |
| Lib | Shared utilities — Jinja2 sandboxed expressions, structlog, helpers | `src/lib/` |

## Database Schema

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| tenants | Tenant accounts with API key auth | id, name, api_key_hash, api_key_prefix, is_active |
| workflows | DAG workflow definitions with trigger config | id, tenant_id, name, trigger_type, steps (JSONB), webhook_path |
| executions | Workflow execution runs with shared context | id, tenant_id, workflow_id, status, context (JSONB), replayed_from |
| step_executions | Individual step runs within an execution | id, tenant_id, execution_id, step_id, step_type, status, input/output (JSONB) |
| execution_logs | Structured logs per execution/step | id, tenant_id, execution_id, step_id, level, message |
| webhook_deliveries | Inbound webhook request log | id, tenant_id, workflow_id, execution_id, method, payload (JSONB), status |

## External Integrations

| Service | Purpose | Auth Method |
|---------|---------|------------|
| PostgreSQL 16 | Durable state, JSONB for step data, RLS for tenant isolation | Connection string |
| Redis 7 | arq task queue for async step execution | Connection string |
| External APIs (via http steps) | User-configured HTTP calls in workflow steps | Per-step config (headers/tokens) |
| BetterStack | Uptime monitoring via /api/health | N/A |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| DATABASE_URL | PostgreSQL connection (asyncpg) |
| REDIS_URL | Redis connection |
| SELF_REGISTRATION_ENABLED | Allow public tenant registration |
| DEFAULT_TENANT_NAME | Name for auto-created first-run tenant |
| MAX_STEPS_PER_WORKFLOW | Workflow complexity limit (default 50) |
| EXECUTION_TIMEOUT_SECONDS | Max execution time (default 300) |
| HTTP_STEP_TIMEOUT | HTTP step timeout (default 30s) |
| ARQ_CONCURRENCY | Worker concurrency (default 10) |
| CRON_TIMEZONE | Scheduler timezone (default UTC) |

## Commands

| Action | Command |
|--------|---------|
| Dev server | `uvicorn src.main:app --reload` |
| Run tests | `python -m pytest` |
| Run unit tests | `python -m pytest tests/unit/` |
| Run integration tests | `python -m pytest tests/integration/ -m integration` |
| E2E tests | `python -m pytest tests/e2e/ -m e2e` |
| Lint/check | `ruff check .` |
| Format | `ruff format .` |
| Type check | `mypy src/` |
| Migrate DB | `alembic upgrade head` |
| New migration | `alembic revision --autogenerate -m "description"` |
| Start worker | `arq src.queue.worker.WorkerSettings` |
| Seed tenant | `python -m src.tenants.seed` |

## Tenant Model

- **Strategy:** API key per tenant (`X-API-Key` header)
- **Table:** `tenants` (id, name, api_key_hash, api_key_prefix, is_active)
- **Key format:** `wae_live_<random 32 hex chars>`
- **Middleware:** `src/api/middleware/auth.py` — validates key, injects tenant_id into request state
- **Isolation:** All queries scoped by tenant_id + PostgreSQL RLS as safety net

## Key Patterns & Conventions

- File naming: `snake_case.py`
- Async everywhere: all handlers, DB, HTTP calls use async/await
- Import order: stdlib → third-party → local (blank lines between)
- Error format: `{ "error": { "code": "...", "message": "...", "details": [...] } }`
- Pagination: cursor-based (`cursor` + `limit` params, default 25, max 100)
- Jinja2: always SandboxedEnvironment, never default Environment
- State transitions: persist to DB before execution proceeds

## Gotchas & Lessons Learned

> Discovered during implementation. Added automatically by `/implement-next` Step 9.3.

| Date | Area | Gotcha | Discovered In |
|------|------|--------|---------------|
| 2026-04-01 | testing | Session-scoped async fixtures (asyncpg pool) fail with pytest-asyncio — event loop mismatch. Use function-scoped fixtures for async DB/Redis connections. | Phase 0: Testing infrastructure |
| 2026-04-01 | infra | Ports 5432/6379 conflict with other ecosystem projects. This project uses 5435 (PG) and 6380 (Redis). | Phase 0: Local service infrastructure |
| 2026-04-10 | alembic | Alembic autogenerate uses `typing.Union`/`Sequence` — must update generated files to Python 3.12 `X | Y` syntax to pass ruff UP007/UP035. Updated script.py.mako template. | Phase 1: DB migrations |
| 2026-04-10 | alembic | Migration tests use subprocess to run `alembic upgrade head` with `DATABASE_URL` env override to target test DB. The env.py reads `os.getenv("DATABASE_URL")` first, falling back to settings. | Phase 1: DB migrations |
| 2026-04-10 | alembic | Migration integration tests are slow (~5s each due to subprocess + migration) — consider session-scoped fixture or running migrations once per test class in future batches. | Phase 1: DB migrations |

## Shared Foundation (MUST READ before any implementation)

> These files define the project's shared patterns, configuration, and utilities.
> The AI MUST read these **in full** before writing ANY new code.

| Category | File(s) | What it establishes |
|----------|---------|-------------------|
| Config | `src/config.py` | Environment variable loading with defaults |
| DB models | `src/db/models.py` | SQLAlchemy ORM models (Base, Tenant, Workflow) |
| DB connection | `src/db/postgres.py` | Async SQLAlchemy engine + session factory |
| Redis connection | `src/db/redis.py` | Redis client for arq + caching |
| Logging | `src/lib/logger.py` | structlog JSON logging configuration |
| Expressions | `src/lib/expressions.py` | Jinja2 SandboxedEnvironment evaluator |
| Auth middleware | `src/api/middleware/auth.py` | API key validation + tenant context injection |
| Error handling | `src/api/middleware/errors.py` | Consistent error response format |
| Tenant models | `src/tenants/models.py` | Pydantic models for tenant data |
| Step base | `src/steps/base.py` | Abstract base class for all step executors |
| Test fixtures | `tests/conftest.py` | db_session (transactional rollback), redis_client, pg_pool fixtures |

## Deep References

> For detailed implementation patterns, read the source directly.

| Topic | Where to look |
|-------|--------------|
| DAG execution | `src/engine/` |
| Step executors | `src/steps/` |
| Trigger handlers | `src/triggers/` |
| Queue/workers | `src/queue/` |
| API routes | `src/api/` |
| Migrations | `src/db/migrations/alembic/` |
| Test patterns | `tests/` |
| Test fixtures | `tests/fixtures/` |
