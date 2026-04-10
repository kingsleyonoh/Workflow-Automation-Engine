# Workflow Automation Engine — Coding Standards: Testing (Core TDD)

> Part 2 of 4. Also loaded: `CODING_STANDARDS.md`, `CODING_STANDARDS_TESTING_LIVE.md`, `CODING_STANDARDS_DOMAIN.md`
> This file covers core TDD discipline. For mock policy, integration, and E2E testing → see `CODING_STANDARDS_TESTING_LIVE.md`.

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

> **Integration, Mock Policy, and E2E rules** → see `CODING_STANDARDS_TESTING_LIVE.md` (Part 3 of 4).
