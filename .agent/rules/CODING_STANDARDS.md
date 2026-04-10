# Workflow Automation Engine — Coding Standards

> Part 1 of 4. Also loaded: `CODING_STANDARDS_TESTING.md`, `CODING_STANDARDS_TESTING_LIVE.md`, `CODING_STANDARDS_DOMAIN.md`

These rules are ALWAYS ACTIVE. Follow them on every response without being asked.

## Workflow Pipeline Awareness
- After completing ANY workflow, **read `.agent/workflows/PIPELINE.md`** and suggest the NEXT logical workflow based on the current context.
- **PIPELINE.md is the single source of truth** for "what comes next." Individual workflows do NOT hardcode their next step — they defer to PIPELINE.md.
- Never leave the user guessing what to do next. Always end with a clear next step.
- **When creating a NEW workflow file**, ALWAYS add it to `PIPELINE.md` with its "When Done, Suggest" message.
- **When deleting a workflow file**, ALWAYS remove it from `PIPELINE.md`.
- `PIPELINE.md` must ALWAYS match the actual files in `.agent/workflows/`. If they're out of sync, fix `PIPELINE.md` immediately.

## Workflow Approval Gates (CRITICAL — Prevents Plan Mode Errors)
When a workflow step says "present to user", "wait for approval", or "approve before proceeding":
1. Present the content directly as **formatted text in the conversation**.
2. End with a clear question: `Approve? [yes / no / edit]`
3. Wait for the user's response before proceeding to the next step.
4. **NEVER call `ExitPlanMode` or `EnterPlanMode`** during workflow execution. These are Claude Code built-in tools for a separate system (toggled via `Shift+Tab`). Workflow approval gates are handled through direct conversation.
5. **NEVER write to `.claude/plans/`** during workflow execution — that directory is reserved for Claude Code's built-in plan mode.

This applies to ALL approval gates: batch selection, implementation plans, RED/GREEN/REGRESSION evidence, commit approval, refactor plans, and any other "present and wait" step in any workflow.

## Domain-Specific Rules

If your task touches any of the domains below, **also read the corresponding rules file before starting**. These files contain deeper conventions than fit here.

| When working on... | Also read |
|--------------------|-----------|
| Authentication / sessions / permissions | `.agent/rules/auth_rules.md` (if exists) |
| Database / migrations / queries | `.agent/rules/db_rules.md` (if exists) |
| Background jobs / queues / scheduling | `.agent/rules/jobs_rules.md` (if exists) |
| API endpoints / serializers / validation | `.agent/rules/api_rules.md` (if exists) |
| Module dependencies / multi-tenant / framework patterns | `.agent/rules/architecture_rules.md` |

> These files are created by `/bootstrap` when a domain has 5+ concentrated conventions. If a file doesn't exist for a domain, the relevant rules are here in CODING_STANDARDS.md.


## Skill Selection & Orchestration
- **Before starting any task**, scan available skills for matches. If one exists, read its SKILL.md first.
- **Announce your choice**: *"Using skill: [skill-name] for this task."*
- When multiple skills apply, invoke the most specific one.
- **When in doubt, invoke the skill.** Reading a SKILL.md costs 30 seconds. Getting it wrong costs hours.
- **Non-negotiable triggers:** framework/library work, security, tests, schema/API design, debugging, deployment, integrations, AI/LLM features.
- ❌ Never skip skills because "I already know this" — the skill may have guardrails you'd miss.

## Git Commit Convention

**Format:** `type(scope): descriptive message`

| Type | When to use |
|------|------------|
| `feat` | New feature or functionality |
| `fix` | Bug fix |
| `refactor` | Code restructuring without behavior change |
| `test` | Adding or updating tests |
| `docs` | Documentation changes |
| `chore` | Tooling, workflows, config, dependencies |
| `style` | Formatting, whitespace, no logic change |

**Scope** = the module or area affected. Valid scopes: `engine`, `steps`, `triggers`, `queue`, `replay`, `tenants`, `api`, `db`, `lib`, `config`.

**Rules:**
- Subject line max 72 characters.
- Use imperative mood: "add filter" not "added filter".
- Reference the `[BUG]`/`[FIX]`/`[FEATURE]` from `progress.md` when applicable.
- One commit per completed item. Don't bundle unrelated changes.

**Examples:**
```
feat(tenants): implement tenant registration with bcrypt API keys
feat(engine): add DAG parser with cycle detection
fix(steps): guard against timeout in http step executor
refactor(db): extract connection pool config into postgres module
test(engine): add 8 tests for conditional branching edge cases
docs(context): update CODEBASE_CONTEXT.md with new schema tables
chore(config): add arq worker settings to .env.example
```

## AI Discipline Rules (Prevent Common AI Failures)

### No Scope Creep
- **ONLY implement what's asked or what's next in `docs/progress.md`.** Do not add features, helpers, utilities, or "nice-to-haves" that aren't in the spec.
- If you think something SHOULD be added, ASK the user first. Never add it silently.

### No Phantom Dependencies
- **NEVER import a package that isn't in the dependency file** (requirements.txt / package.json / etc). Add it FIRST, then use it.
- Before using any library method, **verify it exists** in that version. Don't hallucinate API methods.

### No Placeholder Code
- **NEVER write `# TODO`, `pass`, `...`, or `NotImplementedError`** as final code. Every function must be fully implemented before marking the task done.

### No Hallucinated APIs
- Before calling any external library method, **verify the method exists** by checking docs or the installed package.
- If unsure, say so and check rather than assuming.

### No Silent Failures
- **NEVER write code that swallows errors silently.** Every `except`/`catch` block must either re-raise, log, or return a meaningful error.
- `except: pass` / `catch {}` is permanently BANNED.

### No Over-Engineering
- Match the spec's complexity level. No abstractions without 2+ concrete implementations.
- Build for the scale defined in the spec, not 100x that.

### Verify Before Claiming
- **NEVER say "done" or "all tests pass" without actually running the tests** and showing the output.
- **NEVER say "this follows the spec" without having read the relevant section** in this session.
- If you haven't read a file in this conversation, you don't know what's in it. Read it first.

### Respect .gitignore (CRITICAL — Prevents Accidental Exposure)
- **NEVER run `git add -f` on ANY file.** If a file is gitignored, it is gitignored ON PURPOSE.
- `docs/progress.md`, `docs/build-journal.md`, `docs/architect_journal.md`, `.agent/workflows/`, `.agent/guides/`, `.agent/agents/`, `.agent/.last-sync`, `.yolo/`, and PRD files are LOCAL working files. They must NEVER be committed.
- **Proprietary files are tracked during development** so all platforms can reference them. `.gitignore` has commented-out entries marked `⚠️ TRACKED DURING DEV` — this is the default. Run `/prepare-public` before making the repo public.
- If `git status` doesn't show a file as staged after `git add .`, that means `.gitignore` is working correctly. **Do not "fix" it.**
- The ONLY acceptable staging command is `git add .` (which respects `.gitignore`).

### Full Read Rule (CRITICAL — Prevents Context Loss)
- **When ANY workflow instructs you to "read" a file, you MUST read the ENTIRE file from first line to last line.**
- If the file is longer than your read limit, make multiple sequential read calls (e.g., lines 1–200, 201–400, 401–end) until **every line has been read.**
- Do NOT read a partial subset and assume you understand the rest. Critical rules, patterns, and constraints are often buried later in the file.
- This applies universally to: PRD, `progress.md`, `CODING_STANDARDS.md`, `CODEBASE_CONTEXT.md`, Shared Foundation files, source files referenced in tasks, and any other file a workflow tells you to read.

### Read Shared Foundation Before Coding (CRITICAL — Prevents Duplication)
- Before writing ANY new utility, helper, middleware, handler, component, or shared pattern, read every file listed in the **Shared Foundation** table in `CODEBASE_CONTEXT.md`.
- If a pattern, function, or module already exists there — **USE IT.** Do not recreate it.
- This applies to EVERY implementation task, regardless of which workflow triggered it.

### Workflow Discipline
- **Max 25 workflow files** in `.agent/workflows/`. If approaching 25, retire rarely-used workflows or convert procedural knowledge to reusable global skills.
- Before creating a new workflow, check if an existing one can be extended.

### Search Before Creating (CRITICAL — Prevents Duplicate Code)
- **Before creating ANY new file, function, class, or utility**, search the codebase first:
  1. Search file contents for the function/class name
  2. Search for the file by name
  3. Check relevant module exports / `__init__` files
- If it already exists, **USE IT**. Do not recreate it.
- If a similar function exists, **extend it** — don't create a parallel version.
- When in doubt, **ASK the user**: "I can't find X — does it exist, or should I create it?"

### Use Skills When Available (Skills > Pre-trained Knowledge)
- Before implementing any task, scan your available skills list for domain matches.
- If a matching skill exists (e.g., database → `postgresql`, auth → `auth-implementation-patterns`, payments → `stripe-integration`), read its `SKILL.md` and follow its instructions.
- **CRITICAL:** The patterns, architectures, and rules defined in a `SKILL.md` STRICTLY OVERRIDE your general pre-trained knowledge. Always choose the skill's approach over what you "think you know."
- **Always announce:** *"Using skill: [skill-name] for this task."* so the user knows which patterns are being applied.
- If no skill matches, proceed normally.

## File Size Limits
- **Max 300 lines** per source file. If approaching 250, plan to split.
- **Max 50 lines** per function/method.
- **Max 200 lines** per class.

## PowerShell Environment
- **ALWAYS activate the virtual environment before ANY `python` or `pip` command:**
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
- **NEVER run `pip install` without the venv active.** This installs to system Python and breaks other projects.
- Verify venv is active: prompt shows `(venv)` prefix. If not, activate first.
- Use `;` to chain commands, **NEVER** `&&`
- **NEVER use inline `python -c "..."`** for complex code. Write a `.py` file instead.
- Special characters that break PowerShell: `|`, `>`, `<`, `$`, `()`, `{}`
- Write Python scripts to files instead of inline commands.

## Git Branching Strategy

### Two-Branch Model
- **`main`** — Production only. Code merges here when ready to deploy.
- **`dev`** — Active development. All work happens here.
- `/implement-next` always runs on `dev`.
- Tests always run against local dev services on `dev` branch.
- Merge `dev` → `main` only when all tests pass and feature is complete.
- After merge, run migrations against production.

## Architecture Rules

> Module dependencies, multi-tenant isolation, and framework conventions are in `.agent/rules/architecture_rules.md`. Read it before any structural work.
