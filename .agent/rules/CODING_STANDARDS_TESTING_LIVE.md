# Workflow Automation Engine — Coding Standards: Live & E2E Testing

> Part 3 of 4. Also loaded: `CODING_STANDARDS.md`, `CODING_STANDARDS_TESTING.md` (core TDD), `CODING_STANDARDS_DOMAIN.md`
> This file covers mock policy, integration testing, and E2E testing.

## Live Integration Testing (Mock Policy)

### The Rule: Don't Mock What You Own
If you control the service and can run it locally → test against the real thing.

### Service Fallback Hierarchy
When deciding how to test a service, follow this order:
1. **Local instance** (best) — Docker, CLI, emulator on your machine
2. **Cloud dev instance** (good) — dedicated test project / staging environment
3. **Mock** (last resort) — only when options 1 and 2 are impossible

### Test LIVE (Never Mock)
- Your database (local PostgreSQL, local Redis) — validates schema, column names, constraints, query behavior
- Your own API endpoints — call the actual FastAPI route via `httpx.AsyncClient`, not a stub
- Your own server actions / business logic — test the real function
- File storage you control (local filesystem, local object storage)

### Mock ONLY These
- Third-party payment APIs (Stripe charges money)
- Email/SMS delivery (SendGrid/Twilio sends messages)
- Rate-limited external APIs you don't control
- Services with irreversible side effects
- Cloud-only services with no local emulator AND no dev tier

### No Services? No Problem
If the project has no external services (CLI tool, library, static site), this policy doesn't apply — just write standard unit tests.

### Why This Matters
A mock that returns `{ user_id: 1 }` will pass even when the real column is `user_id`. A mock that returns success will pass even when the real constraint rejects your data. Mocks test your ASSUMPTIONS about the service. Live tests test REALITY.

### Common Mock Violations (DO NOT DO THESE)
- ❌ Mocking your database client to return fake rows — hit the real database
- ❌ Mocking your own API routes with `httpx_mock` — call the real endpoint via `TestClient` / `AsyncClient`
- ❌ Using an in-memory SQLite when production uses PostgreSQL — use the real PostgreSQL
- ❌ Mocking Redis/cache when it's running in Docker — connect to the real instance
- ✅ Mocking Stripe's charge API — you don't want to charge real money in tests
- ✅ Mocking SendGrid — you don't want to send real emails in tests
- ✅ Mocking an external API with rate limits — you don't control their uptime

### Test Cleanup
- Each test MUST clean up after itself (delete rows, reset state)
- Use transactions with rollback when possible for speed (pytest-asyncio + SAVEPOINT)

## Backend API & Integration Testing

### When to Write API Integration Tests
- Every **API endpoint**: test request → response cycle with real HTTP semantics
- Every **arq task / message handler**: test job execution with real Redis + service dependencies
- Every **trigger handler** (webhook, cron, manual): test event processing end-to-end
- Every **middleware** (auth, rate limit, errors): test request interception, auth guards, validation layers

### What to Test
| Priority | Test This | Example |
|----------|-----------|---------|
| 1 | Request/response cycle | POST /api/workflows → 201, returns created workflow |
| 2 | Input validation | Missing required field → 400 with specific error code |
| 3 | Auth & authorization | No API key → 401; wrong tenant → 403 |
| 4 | Error handling | Invalid ID → 404; DB constraint → 409 |
| 5 | Tenant isolation | Tenant A cannot read/write Tenant B rows |
| 6 | Edge cases | Empty body, oversized payload, duplicate submission |

### API Testing Patterns
- Use FastAPI's `TestClient` (sync) or `httpx.AsyncClient` via `pytest-asyncio` for async routes
- Test full request lifecycle — serialization, middleware, handler, response
- Assert on status codes, response body structure, AND headers where relevant
- Test pagination (cursor-based), filtering, and sorting with real DB rows

### arq Task / Queue Testing
- Use a local Redis instance (Docker) — `arq.create_pool()` against the real service
- Enqueue jobs via the queue and assert on DB side effects after the worker processes them
- Test retry behavior, timeout behavior, and dead-letter paths with real failures
- Test error handling: malformed job payloads, worker restart, cancellation

### File Naming & Location
- Name: `test_module_name.py` — in `tests/unit/` or `tests/integration/` mirror
- Integration tests go under `tests/integration/` with pytest marker `@pytest.mark.integration`
- Group shared test helpers in `tests/fixtures/` or a `conftest.py`

## E2E Testing (Real Endpoints)

> E2E tests hit a RUNNING server over HTTP — not in-process test clients like `TestClient`.
> The point is testing the deployed stack: server startup, middleware chain, database, cache, and response serialization.
> These catch issues that unit/integration tests miss: port binding, CORS headers, middleware ordering, connection pool behavior under load.

### When E2E is Required
- **Any batch that creates or modifies an API endpoint** → E2E MUST hit the running server
- **Any batch that adds a new trigger type or queue task** → E2E MUST exercise the trigger → execution path
- **Pure utility/library/config batches with no endpoints** → E2E not required (skip with note)
- **`[SETUP]` items** → E2E not required unless the setup itself starts a server

### E2E Test Architecture

**Backend E2E (this project):**
1. Start the actual server: `uvicorn src.main:app` (NOT a test-mode in-process server)
2. Wait for ready signal (`GET /api/health` returns 200)
3. Hit real endpoints via HTTP (`httpx` or `curl`)
4. Assert on status codes, response bodies, headers
5. Stop the server after tests complete

**Required local services:** local PostgreSQL 16 and local Redis 7 must be running (via Docker Compose) — this aligns with the existing mock policy ("Don't Mock What You Own").

### E2E Test File Structure
```
tests/e2e/
  api/                        ← Backend E2E tests
    test_workflows.e2e.py
    test_executions.e2e.py
    test_webhooks.e2e.py
  helpers/
    server.py                 ← Start/stop uvicorn utilities
    seed.py                   ← Test data seeding (tenants, workflows)
```

### E2E vs Integration Tests
| Aspect | Integration (TestClient) | E2E (running server) |
|--------|-------------------------|---------------------|
| Server | In-process, no real HTTP | Real HTTP, real port |
| Speed | Fast (~1ms per test) | Slower (~100ms+ per test) |
| What it catches | Handler logic, validation, DB | Middleware ordering, CORS, startup, ports, arq worker |
| When to use | Every endpoint (RED/GREEN phase) | After REGRESSION passes (Step 7d) |
| Run command | `python -m pytest tests/integration/ -m integration` | `python -m pytest tests/e2e/ -m e2e` |

**Both are required.** Integration tests are your fast feedback loop (TDD). E2E tests are your deployment confidence check.

### E2E Test Cleanup
- Each E2E test must clean up its own data (delete created records, reset state)
- Use a dedicated test database or schema to avoid polluting dev data
- Kill the uvicorn process reliably in the `teardown`/`finalizer` — leaked processes block ports

### Bootstrap Setup for E2E
During `/bootstrap` Phase 0, a `[SETUP]` item should configure the E2E framework:
- Create `tests/e2e/` directory structure
- Add `test:e2e` (or `pytest -m e2e`) configuration
- Add server start/stop helper script
- Verify the E2E command runs and exits cleanly (even with 0 tests)
