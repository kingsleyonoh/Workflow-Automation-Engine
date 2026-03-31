# Workflow Automation Engine — Coding Standards: Testing

> Part 2 of 3. Also loaded: `CODING_STANDARDS.md`, `CODING_STANDARDS_DOMAIN.md`

## Testing Rules — Anti-Cheat (CRITICAL)

### Never Do These
- **NEVER modify a test to make it pass.** Fix the IMPLEMENTATION, not the test.
- **NEVER use `pass` or empty test bodies.**
- **NEVER hardcode return values** just to satisfy a test.
- **NEVER use broad exception handlers** to swallow errors that would make tests fail.
- **NEVER mock the thing being tested.** Only mock external dependencies.
- **NEVER skip or mark tests as expected failures** without explicit user approval.
- **NEVER weaken a test assertion** to make it pass.
- **NEVER delete a failing test.** Failing tests are bugs. Fix them.

### TDD Sequence is Non-Negotiable
- Tests FIRST, then implementation. Never the reverse.
- You MUST create test files BEFORE creating implementation files.
- You MUST run tests and see RED (failures) before writing any implementation.
- You MUST show the RED PHASE EVIDENCE output (as defined in `implement-next.md` Step 5) before proceeding to Green Phase.
- The ONLY exception: `[SETUP]` items (scaffolding, config, infrastructure) where no testable behavior exists yet.
- If you catch yourself implementing without tests — STOP, delete the implementation, write the tests first.

### Always Do These
- **Test BEHAVIOR, not implementation.**
- **Test edge cases:** empty inputs, None, zero, negative, missing, duplicate.
- **Test sad paths:** API errors, timeouts, invalid data.
- **Assertions must be specific:** `assertEqual(result, expected)`, not `assertIsNotNone(result)`.

## Test Quality Checklist (Anti-False-Confidence)

Before moving from RED → GREEN, verify ALL applicable categories have tests:

| # | Category | What to Test |
|---|----------|-------------|
| 1 | Happy path | Does it work with valid, normal input? |
| 2 | Required fields | Does it reject None/blank for required fields? |
| 3 | Uniqueness | Does it enforce unique constraints? |
| 4 | Defaults | Do default values apply correctly when field is omitted? |
| 5 | FK relationships | Do foreign keys enforce CASCADE/PROTECT correctly? |
| 6 | Tenant isolation | Can Tenant A see Tenant B's data? (if multi-tenant) |
| 7 | Edge cases | Empty strings, zero, negative, very long strings, special chars |
| 8 | Error paths | What happens when external APIs fail, DB is down, input is malformed? |
| 9 | String representation | Does `__str__` / `__repr__` return something meaningful? |
| 10 | Meta options | Are ordering, indexes, and constraints working? |

**If a category applies and you skip it, you're cheating.** If RED phase shows fewer than 2 failures, add more tests — you're probably not testing enough.

### Performance Awareness
- Correctness tests alone don't catch latency regressions — a page can pass all tests while making 10× the necessary network calls
- When a single page/endpoint triggers 3+ backend operations, consider asserting call count or response time
- After every batch of 5+ features, do a compound load check: load real pages and verify total I/O matches expectations

## Edge Case Coverage Guide

### Models
- Every field from the spec → at least 1 test per constraint
- Every FK → test CASCADE behavior
- Every choice field → test all valid values + 1 invalid value

### Services (when applicable)
- Boundary values (min, max, zero, negative)
- Invalid input types
- Idempotency (running twice = same result)
- Mock external API failures

### Views/Pages (when applicable)
- Authenticated vs unauthenticated access
- Correct HTTP methods (GET/POST/PUT/DELETE)
- Response format validation
- Tenant scoping (if multi-tenant)

## Test Modularity Rules
1. **One test class per model/service** — never mix models in one class
2. **Max 300 lines per test file** — split if larger
3. **`setUp` creates only what that class needs** — no global fixtures
4. **Tests are independent** — no shared state, no ordering dependency
5. **Any single test can run in isolation** — `python -m pytest tests/test_x.py::TestClass::test_method`
6. **Test names describe business behavior** — not technical actions
7. **No test helpers longer than 10 lines** — extract to a `tests/factories.py` if needed

## Business-Context Testing
- Tests must reflect the BUSINESS PURPOSE described in the spec.
- Every test must answer: Does this protect data? Apply rules correctly? Handle failure? Match the spec?
- Test names must describe business behavior, not technical actions.

## Live Integration Testing (Mock Policy)

### The Rule: Don't Mock What You Own
If you control the service and can run it locally → test against the real thing.

### Service Fallback Hierarchy
When deciding how to test a service, follow this order:
1. **Local instance** (best) — Docker, CLI, emulator on your machine
2. **Cloud dev instance** (good) — dedicated test project / staging environment
3. **Mock** (last resort) — only when options 1 and 2 are impossible

### Test LIVE (Never Mock)
- Your database ({{LOCAL_SERVICES}}) — validates schema, column names, constraints, query behavior
- Your own API endpoints — call the actual route, not a stub
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
A mock that returns `{ user_id: 1 }` will pass even when the real column is `userId`. A mock that returns success will pass even when the real constraint rejects your data. Mocks test your ASSUMPTIONS about the service. Live tests test REALITY.

### Common Mock Violations (DO NOT DO THESE)
- ❌ Mocking your database client to return fake rows — hit the real database
- ❌ Mocking your own API routes with `nock`/`msw` — call the real endpoint via test client
- ❌ Using an in-memory SQLite when production uses PostgreSQL — use the real PostgreSQL
- ❌ Mocking Redis/cache when it's running in Docker — connect to the real instance
- ✅ Mocking Stripe's charge API — you don't want to charge real money in tests
- ✅ Mocking SendGrid — you don't want to send real emails in tests
- ✅ Mocking an external API with rate limits — you don't control their uptime

### Test Cleanup
- Each test MUST clean up after itself (delete rows, reset state)
- Use transactions with rollback when possible for speed

<!-- CONDITIONAL: FRONTEND_FRAMEWORK=React — Bootstrap Step 5c: KEEP this section for React frontend projects, REMOVE for backend-only -->
## Component Testing (React Testing Library)

> This section applies to projects with a React frontend. If the project has no UI, skip this section entirely.

### When to Write Component Tests
- Every **interactive component**: forms, dialogs, accordions, dropdowns, buttons with click handlers
- Every component with **conditional rendering** (show/hide logic, loading states, error states)
- Any component where a bug would **block user interaction** (can't type, can't click, can't submit)
- **Not required for**: pure display components with no interactivity (static text, icons, layout wrappers)

### What to Test
| Priority | Test This | Example |
|----------|-----------|---------|
| 1 | User interactions | Click button → dialog opens; type in input → value updates |
| 2 | Conditional rendering | Error state shows message; loading state shows spinner |
| 3 | Form validation feedback | Submit empty form → validation errors appear |
| 4 | Accessible roles & labels | Button has correct label; form inputs are labeled |
| 5 | Callback invocation | onSubmit called with correct data; onCancel fires |

### What NOT to Test
- **Styling** — don't assert on classNames, colors, or CSS
- **Internal state** — don't reach into `useState` values; test what the USER sees
- **Snapshot tests** — they create noise and break on every minor change. Test behavior instead.
- **Implementation details** — don't test that a specific hook was called; test the outcome

### RTL Query Priority (follow this order)
1. `getByRole` — accessible role (button, textbox, dialog) — **always prefer this**
2. `getByLabelText` — form inputs with labels
3. `getByText` — visible text content
4. `getByPlaceholderText` — placeholder fallback
5. `getByTestId` — **last resort only** — used when no semantic query works

### RTL Best Practices
- Use `userEvent` over `fireEvent` — it simulates real browser behavior (focus, blur, keyboard)
- Use `screen` for queries — not destructured render result
- Use `waitFor` for async operations — never `setTimeout`
- Use `within` to scope queries inside a container (e.g., within a specific dialog)
- Wrap state updates in `act()` only if React warns you — RTL handles this automatically in most cases

### File Naming & Location
- Name: `ComponentName.test.tsx` — co-located next to the component file
- Example: `src/components/ProductFormDialog.test.tsx`
- Group test utilities in `src/test/helpers.ts` if shared across component tests

### Minimum Coverage Rule
Every interactive React component MUST have at least:
- **1 happy-path interaction test** (user performs the primary action successfully)
- **1 error/edge-case test** (empty submission, missing data, disabled state)
- If a component has 0 tests and it has click/type/submit handlers → it's a bug waiting to happen

### Setup (Vitest + jsdom)
Component tests run in Node.js with a simulated DOM — no browser needed. Typical setup:
- `vitest` as test runner (or `jest` if the project already uses it)
- `@testing-library/react` for component rendering and queries
- `@testing-library/user-event` for simulating user interactions
- `jsdom` or `happy-dom` as the test environment
- Configure in `vitest.config.ts`: `environment: 'jsdom'`
<!-- END CONDITIONAL: FRONTEND_FRAMEWORK=React -->

<!-- CONDITIONAL: BACKEND_ONLY — Bootstrap Step 5c: KEEP this section for backend-only projects (API, CLI, worker), REMOVE for React frontend -->
## Backend API & Integration Testing

> This section applies to backend-only projects (APIs, workers, CLI tools). If the project has a React frontend, use the Component Testing section above instead.

### When to Write API Integration Tests
- Every **API endpoint**: test request → response cycle with real HTTP semantics
- Every **message consumer/handler**: test event processing with real or local message broker
- Every **background job/worker**: test job execution with actual service dependencies
- Every **middleware**: test request interception, auth guards, validation layers

### What to Test
| Priority | Test This | Example |
|----------|-----------|---------|
| 1 | Request/response cycle | POST /api/users → 201, returns created user |
| 2 | Input validation | Missing required field → 400 with specific error |
| 3 | Auth & authorization | No token → 401; wrong role → 403 |
| 4 | Error handling | Invalid ID → 404; DB constraint → 409 |
| 5 | Edge cases | Empty body, oversized payload, duplicate submission |

### API Testing Patterns
- Use the framework's built-in test client (e.g., Fastify `inject()`, Express `supertest`, FastAPI `TestClient`)
- Test full request lifecycle — serialization, middleware, handler, response
- Assert on status codes, response body structure, AND headers where relevant
- Test pagination, filtering, and sorting with real DB rows

### Message/Event Consumer Testing
- Publish test events to a local broker (Kafka/Redpanda, RabbitMQ, Redis Streams)
- Assert the consumer processes them correctly (DB writes, side effects)
- Test error handling: malformed events, duplicate events, consumer restart

### File Naming & Location
- Name: `module-name.test.ts` or `test_module_name.py` — co-located or in `tests/` mirror
- Group shared test helpers in `tests/helpers/` or `tests/factories/`
<!-- END CONDITIONAL: BACKEND_ONLY -->
