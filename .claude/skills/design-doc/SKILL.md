---
name: design-doc
description: Write an engineering design doc under docs/designs/<slug>/ — a short README.md reviewers read and a full-design.md implementers build from. Use before a non-trivial build or when the user asks for a design doc.
---

# Design Doc

## Output

`docs/designs/<kebab-case-slug>/` containing exactly:

1. **`README.md`** — short, opinionated, human-readable (≈200–600 lines).
2. **`full-design.md`** — superset for implementers: full data model,
   signatures, API surface, state machine, UX mockups, edge-case stress test,
   test list, tickets, rollout. It expands the README; it never contradicts it.

## Process

1. Gather context: existing code, `AGENTS.md`, relevant skills, prior docs.
2. Ask clarifying questions up front: slug, scope edges (anything that could
   mean two things), and 3–5 concrete edge cases — in or out?
3. Write `README.md`, then `full-design.md`.
4. Verify both exist, README is shorter, and problem/scope sections match.

## README.md shape

```markdown
# <Project Title>

Status: Draft | Active | Implemented | Archived

## Problem statement / BLUF
## Context
## Requirements
### In scope
### Out of scope (v1)
## Design
### High level
#### Data model (sketch)   <!-- mark new fields `# NEW` -->
### Lifecycle / state transitions
### Key flows
## Tradeoffs and rejected alternatives
## Rollout
## Open questions
```

## full-design.md additions

Data model (full, with constraints and indexes) · class and method signatures
(typed, async-first) · API surface (verb, path, schemas, auth, errors) ·
background jobs/workflows (inputs, retries, idempotency key) · ASCII UX mockups
with owning component names, including empty/loading/error states · detailed
state machine (diagram + transition table) · edge-case stress test (25+
scenarios with verdicts) · migration plan · test list · implementation tickets
(each ≤1 week) · detailed rollout.

## Voice

- **Decide things.** One design; alternatives go in Tradeoffs with the reason
  they lost. An empty "Open questions" section is a good sign.
- **No deferral without a plan.** Every out-of-scope item says what it will
  look like when it ships. Never bare "TBD".
- **Concrete over abstract.** Real flows, real file paths, real examples.
- **Active, declarative voice.** No LLM-speak: "leverage", "robust",
  "seamless", "we propose", "this document outlines", "going forward",
  "fundamentally".
- **Stress-test edge cases.** A reader shouldn't be able to think of a case the
  doc didn't consider.
