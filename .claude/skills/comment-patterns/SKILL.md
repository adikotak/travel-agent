---
name: comment-patterns
description: Code comment and docstring conventions. Use before writing any comment or docstring, and as a checklist before opening a PR.
---

# Comment Patterns

## Two questions every comment must pass

1. **Will it still be true and useful a year from now?** If it describes how
   the code got here ("previously…", "refactored from…", "replaces the old…"),
   no — that belongs in the commit message.
2. **Does it say something the code doesn't?** If it restates the code or
   summarizes the diff, delete it.

Fails either → don't write it. Passes → keep it. The goal is high-signal
comments, not comment scarcity; don't delete a useful comment just to have
fewer.

## Never

- **Ticket references for completed work** (`# See TICKET-123`). Tickets go in
  commit messages and PR descriptions.
- **History / migration narrative** (`# Was sync; converted in the refactor`).
- **Restated mechanics** (`# Increment the counter`).
- **Filler or authorship markers** (`# Now handle the duplicate case`,
  `# AI-generated helper`, `# Per the user's request`).
- **Banner comments** that only act as section dividers.

## Worth writing

| Reason | Example |
|---|---|
| Non-obvious invariant | "Fares are quoted per traveler; totals multiply here, never upstream." |
| Surprising constraint | "Provider holds a fare for 15 min; confirm must happen inside that window." |
| Subtle ordering | "Release the hold only after the booking row commits." |
| External quirk | "Provider returns 200 with an empty body when the PNR is unknown." |
| Operator warning | "Rewrites local state only; does not cancel with the airline." |
| Test intent | "Same city name in a different country is a distinct destination." |

If a comment prevents a future reader from "simplifying" away an important
edge case, keep it.

## TODOs

Only `TODO(<open-ticket>): <concrete change>` — the ticket is open, the comment
names the change, and removing it is part of that ticket's done. Delete it in
the same diff that closes the ticket.

## Docstrings

Describe what the symbol is and how to use it *today*, not a changelog. One
line for obvious helpers; keep a multi-line docstring when it carries a
contract, invariant, or external constraint. Don't restate argument types the
hints already give.

## Pre-PR checklist

- [ ] No ticket refs or TODOs for tickets this PR closes.
- [ ] No "previously / used to / replaces" narrative.
- [ ] No comment paraphrasing the next line.
- [ ] Every remaining comment explains a why, invariant, constraint, quirk, or
      test intent.
