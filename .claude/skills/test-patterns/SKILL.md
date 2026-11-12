---
name: test-patterns
description: Testing conventions — coverage expectations, test docstrings, structure, fixtures, and aggressive parametrization. Use when writing or modifying tests.
---

# Test Patterns

## When to run tests

Tests are a checkpoint, not the inner loop. While iterating, use lint + type
check. Run the relevant (scoped) tests once the change is complete, before
pushing, while fixing a failure the suite already reported, or when asked. Fix
every reported failure before rerunning. Don't rerun to re-confirm a pass you
haven't invalidated.

## Coverage expectations (mandatory)

Every behavior change ships with tests in the same change. For each unit of
new logic, cover what actually exists:

- **Happy path** — assert the real effect (rows written, response shape,
  derived values), not just a status code.
- **Validation & errors** — bad/missing/duplicate input, unknown IDs, malformed
  config. Assert the error *and* that no partial side effect leaked.
- **Authorization** — one test per distinct guard (wrong user, wrong tenant,
  unauthenticated).
- **Idempotency / retry** — a rerun creates no duplicates; also cover partial
  reruns where some records exist and others don't.
- **Boundaries** — zero, empty, off-by-one, clamps, date/timezone edges
  (DST, date line, overnight flights).
- **Round trips** — a non-default value survives request → service → storage
  → API response.
- **Branches** — every `if`/fallback you add has a test for each side.
- **LLM-backed paths** — use a deterministic fake model for orchestration
  tests; malformed tool args, retries exhausted, and no-result cases must not
  record success.

When you finish, list the code paths you added and map each to a test; if one
genuinely can't be tested, say so and why.

## Test docstrings (mandatory)

Each test's docstring states the **scenario** and the **guaranteed outcome** —
the rule it proves, not the mechanics.

```python
# WRONG
def test_rejects_past_departure(self):
    """Calls create_trip with yesterday and asserts error."""

# RIGHT
def test_rejects_past_departure(self):
    """A departure date before today is rejected with a validation error,
    and no Trip row is written."""
```

## Structure

- Test directory mirrors the source tree.
- Arrange / Act / Assert.
- Factories with overridable defaults (`defaults.update(kwargs)`); fixed IDs as
  constants for determinism; fixture composition to build context.
- Mock at the boundary (HTTP clients, LLM provider, clock), not internals.

## DRY & parametrization

The bar is low: **two near-duplicate tests is enough** — parametrize when
adding the second, not the third.

Parametrize when tests differ only in inputs/expected values, when names look
like `test_x_with_a` / `test_x_with_b`, or when covering each enum variant /
branch with the same assertion shape. Use `pytest.param(..., id="...")` (or
`it.each` in Vitest) for readable case names.

Repeated arrange blocks → fixture or factory defaults. Repeated mock setup →
shared/autouse fixture. A `_run_case(input, expected)` helper called from N
tests → just parametrize.

Don't parametrize tests that differ meaningfully in setup, mocks, or assertion
shape.
