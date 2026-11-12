# AGENTS.md — Travel Agent

Canonical working guidance for AI coding agents (Claude Code reads it via
`CLAUDE.md`; Codex reads this file directly).

## Project

An email-based travel agent: employees email trip requests; the agent parses
them, applies the travel policy, proposes or books flights, routes approvals,
and handles disruptions.

**Stack:** Python 3.12+, Django, SQLite, managed with `uv`.

```
config/    # Django project settings and URLs
travel/    # the app: models, admin, agent logic
```

## Commands

```bash
uv sync                                   # install
uv run python3 manage.py migrate          # apply migrations
uv run python3 manage.py makemigrations --check --dry-run   # verify models match migrations
uv run python3 manage.py runserver        # admin at http://localhost:8000/admin
```

Lint, type check, and test commands: add them here when those tools are set up.

## Always-on skills

Before writing code, read and follow:

- @.claude/skills/code-quality/SKILL.md
- @.claude/skills/comment-patterns/SKILL.md

Consult on demand:

| Skill | When |
|---|---|
| **logging-and-error-handling** | Adding logging, error handling, or external calls |
| **test-patterns** | Writing or modifying tests |
| **agent-patterns** | Building or changing LLM agents, tools, delegation, or evals |
| **review-feedback** | Responding to PR review comments (human or bot) |
| **design-doc** | Writing a design doc before a non-trivial build |

## Critical rules (not linter-enforceable)

1. **Ask before large or irreversible changes.** Database schema/migrations,
   data lifecycle, product semantics, public API contracts, and broad
   behavior changes: present the proposal and wait for explicit approval, even
   if other categories of fixes were pre-approved.
2. **Confirm before outward-facing actions.** Do not commit, push, open PRs, or
   call external services unless the user asked for that specific action.
   "Make a change" is not "commit and push it."
3. **Never fabricate identifiers.** Ticket IDs, UUIDs, API keys, URLs, resume
   IDs — ask if you don't have them.
4. **Secrets stay out of the repo and out of prompts.** Read config from `.env`
   (gitignored). Never print, log, commit, or paste secret values.
5. **Verify before calling it done.** "Done" means the whole task, not each
   edit. Run lint + type check freely while iterating; run the relevant tests
   once when the change is complete; fix *all* reported failures before
   rerunning. Never report a check as passing that did not actually run (a test
   command that collected zero tests is not a pass).
6. **Every behavior change ships with tests in the same change** — happy path,
   error paths, auth denials, empty/duplicate input, idempotency/retry,
   boundaries. If something genuinely can't be unit-tested, say so and why.
7. **Leave no dead code.** After a removal, rename, or reroute, search every
   touched symbol and delete what now has no non-test caller. Check
   `git status --short` for stray files.
8. **Never edit migrations that already exist on `main`.** Add a new one.
9. **Sync with `main` before pushing.** `git fetch origin main`, merge, sanity
   check the merged result (diff, stale symbols, focused tests, lint).
10. **Call things explicitly.** Prefer a direct call from each known trigger
    over implicit hooks/signals/event magic. Reach for implicit dispatch only
    when the triggers are genuinely unknowable.
11. **Aggregations belong on the server.** If the frontend needs every row to
    draw what it shows, the endpoint returns the wrong shape. Business
    definitions live in one place, server-side, under test.
12. **Prefer async** for I/O-bound code unless a dependency forces sync.
13. **Use `python3`**, never bare `python`.
14. **Spawn subagents only when the user asks** for parallel agent work.

## Write code as if review already ran

- Flat control flow: guard clauses and early returns, no nested `if`.
- Fail fast: no broad `except`, no `or ""` / `or []` fallbacks for values the
  schema already guarantees, no silent skip paths.
- Structured logging from the first draft (static event name + `extra`).
- Imports at module top; absolute imports.
- Descriptive domain names (`itinerary`, `flight_offer`, `traveler`) — never
  `data`, `result`, `item`, `obj`.
- Parametrize the second near-duplicate test immediately.
- Comments only for durable intent (why, invariant, quirk, ordering).

## Pull requests

- Title: `<short imperative description>`; add a ticket ID only if the user
  provides one.
- Description states what ships *now*; rewrite it in place when review fixes
  change behavior — no "Updates since review" changelog sections.
- One review-comment fix = one commit.
- Any visual change ships with a screenshot of the real app (before/after for
  bug fixes, same build and data, conditions stated).
