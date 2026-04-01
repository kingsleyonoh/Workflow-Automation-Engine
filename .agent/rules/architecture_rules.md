# Workflow Automation Engine — Architecture Rules

> Domain rules for module dependencies, multi-tenant isolation, and framework conventions.
> Referenced from `CODING_STANDARDS.md` Domain-Specific Rules table.

## Module Dependency Hierarchy (ENFORCED)

Apps import DOWN only. Never import upward.

```
lib/       → nothing
db/        → lib/
tenants/   → db/, lib/
queue/     → db/ (Redis), lib/
steps/     → lib/, db/ (for sub_workflow)
engine/    → steps/, queue/, db/, lib/
triggers/  → engine/, db/, lib/
replay/    → engine/, db/, lib/
api/       → engine/, triggers/, replay/, tenants/, db/, lib/
main.py    → api/, db/, queue/, tenants/, config
```

**Violations are bugs.** If `lib/` imports from `engine/`, that's a circular dependency. Fix immediately.

## Multi-Tenant Isolation Rules

- **Every database query MUST be scoped by `tenant_id`.** No exceptions.
- **Every new table MUST include `tenant_id UUID NOT NULL FK → tenants.id`.**
- PostgreSQL Row-Level Security (RLS) enforces isolation at the DB layer as a safety net.
- API key middleware injects `tenant_id` into request state — all downstream code reads from there.
- **Never trust tenant_id from the request body.** Always use the middleware-injected value.
- Sub-workflows cannot cross tenant boundaries.

## Framework Conventions (FastAPI + Python 3.12)

- **Async everywhere** — all route handlers, DB queries, and HTTP calls use `async/await`.
- **Pydantic v2** for all request/response models and workflow definitions.
- **SQLAlchemy async** for database access — no raw SQL except in Alembic migrations.
- **httpx** for async HTTP client (step executors).
- **structlog** for structured JSON logging.
- **Jinja2 SandboxedEnvironment** for all user-provided expressions — NEVER use default Environment.
- **arq** for async task queue — steps dispatched as arq jobs.
- Import order: stdlib → third-party → local (with blank lines between groups).
- File naming: `snake_case.py` for all Python files.
