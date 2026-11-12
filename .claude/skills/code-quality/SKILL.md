---
name: code-quality
description: Mandatory style rules for every code change — control flow, error handling, structure, types, naming, imports. Read before editing any Python or TypeScript.
---

# Code Quality

Rules for every code change. Not linter-enforced. Where exceptions are listed,
the default is still the rule.

## Control flow

- **No nested ifs.** Early returns and guard clauses; keep the happy path flat.
  Use combined conditions or named booleans instead of nesting.
- **Fail fast.** Don't wrap code in try/except "to be safe". try/except only
  for: a specific exception from an external call (HTTP, DB, LLM provider), an
  expected condition you actually handle, or a durable-workflow boundary. Never
  bare `except:` or broad `except Exception`.
- **No silent no-ops.** `if not thing: return` when a caller contract was
  violated hides bugs. Raise an error that names the violated contract.
- **No defensive checks for impossible states.** No `or ""` / `or []`
  fallbacks or null-guards for values the schema, Pydantic/Zod model, DB
  constraint, or upstream validation already guarantees. Trust a guarantee once.

## Structure

- **One job per class; depend on abstractions.**
- **Don't over-build.** No abstraction, option, or config knob the task doesn't
  need. Promote a helper into a service only when a real domain operation
  appears.
- **Reuse before writing.** Search the module and shared utils first; move a
  buried helper to a shared location instead of duplicating it.
- **Separate transport from queries.** A client owns connection/execution; a
  repository owns named queries, bound parameters, and row parsing. No SQL
  strings or query-param construction inline in endpoints or services.
  Untrusted values are always bound, never interpolated.
- **Leave no dead code.** Any change that removes, replaces, or reroutes a
  caller can orphan its callees. Search every touched symbol and delete what
  has no remaining non-test caller — a symbol reachable only from its own
  tests is dead.

## Types

- **Type hints** on every signature, return, and non-obvious variable. Fix type
  errors as you write them.
- **Most specific type wins.** Concrete model, schema, `TypedDict`, `Literal`,
  precise containers (`dict[str, FlightOffer]`, not `dict`). `Any`/`object`/
  untyped containers only when the value is genuinely unconstrained — and say
  why.
- **Name your fields.** No loose positional tuples returned from helpers; use a
  `NamedTuple`, dataclass, or model so adding a field doesn't shift callers.
- **Discriminated unions over bags of optionals** (Python and TypeScript).
- **Required means required.** Don't make a field optional if every consumer
  dereferences it.
- **Prefer `isinstance` over `getattr`/`setattr`.** Dynamic access needs a real
  metaprogramming reason.
- **Enums:** one string-valued enum type per concept, kebab-case values
  (`"pending-confirmation"`); pass members directly rather than `.value`.

## Naming, imports, strings

- **Descriptive names:** `itinerary`, `booking`, `traveler` — never `data`,
  `result`, `item`, `obj`. Well-known domain abbreviations are fine.
- **Search before naming helpers**; name a helper for the specific capability
  it provides, not an umbrella.
- **`logger = logging.getLogger(__name__)`** — never `log`.
- **Absolute imports, all at file top.** Fix circular imports by restructuring,
  not by deferring imports.
- **Double quotes.** Timezone-aware datetimes: `datetime.now(UTC)`.

## Comments

Follow the **comment-patterns** skill. Comments carry durable intent — a
non-obvious why, invariant, constraint, quirk, operator warning, ordering
requirement, or test intent. Never narrate history or restate code.
