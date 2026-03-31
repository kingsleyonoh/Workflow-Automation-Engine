# Workflow Automation Engine — Codebase Context

> **This is the TEMPLATE version of `CODEBASE_CONTEXT.md`** — a blueprint with empty tables and `{{PLACEHOLDER}}` tokens.
>
> When a new project is created via `/bootstrap` or `/retrofit`, this file is copied and populated with real project data (tech stack, modules, schema, etc.). Once populated, it becomes the AI's primary source of truth for understanding that project. Updated by `/sync-context`.
>
> **Do NOT fill in the tables here.** They are intentionally empty — workflows fill them per-project.
>
> Last updated: {{DATE}}
> Template synced: {{DATE}}

<template_manager_warning>
⚠️ **TEMPLATE MANAGER — MANDATORY PROCESS FOR EVERY CHANGE:**
1. **BEFORE modifying any file** in this template, open `MAINTAINING.md` and find the matching checklist.
2. **AFTER modifying the file**, walk through every item in that checklist and apply each one.
3. **AFTER all checklist items are done**, check the "After ANY Template Change" section at the bottom.
4. Do NOT commit until all propagation steps are complete.

This is not optional. Skipping this causes sync failures across all downstream projects.
(Note: bootstrap/retrofit workflows will delete this block when creating a new project.)
</template_manager_warning>

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | |
| Framework | |
| Database | |
| Hosting | |
| Package Manager | |
| Test Runner | |
| Build Tool | |

## Project Structure

```
project-name/
├── [populated by bootstrap/retrofit from PRD Section 9 or codebase scan]
```

## Key Modules

| Module | Purpose | Key Files |
|--------|---------|-----------|
| | | |

## Database Schema

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| | | |

## External Integrations

| Service | Purpose | Auth Method |
|---------|---------|------------|
| | | |

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| | | |

## Commands

| Action | Command |
|--------|---------|
| Dev server | |
| Run tests | |
| Lint/check | |
| Build | |
| Migrate DB | |

## Key Patterns & Conventions

- File naming: 
- Component structure: 
- Import conventions: 
- Error handling approach: 

## Gotchas & Lessons Learned

> Discovered during implementation. Added automatically by `/implement-next` Step 9.3.
> These prevent the same mistakes from being repeated across sessions.

| Date | Area | Gotcha | Discovered In |
|------|------|--------|---------------|
| | | | |

## Shared Foundation (MUST READ before any implementation)

> These files define the project's shared patterns, configuration, and utilities.
> The AI MUST read these **in full** before writing ANY new code. Never recreate what exists here.
> Populated by `/bootstrap` (from PRD) or `/retrofit` (from codebase scan). Updated by `/sync-context`.

| Category | File(s) | What it establishes |
|----------|---------|-------------------|
| | | |

## Deep References

> For detailed implementation patterns, read the source directly — don't embed here. Keeps this file lean. When `/deep-study` or `/sync-context` runs, it populates this table and **trims** the corresponding embedded sections above to one-line summaries.

| Topic | Where to look |
|-------|--------------|
| [module name] | `src/[module]/` |
| Test patterns | `tests/` |
