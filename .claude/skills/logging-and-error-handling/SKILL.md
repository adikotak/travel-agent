---
name: logging-and-error-handling
description: Logging and error-handling conventions. Use when adding logging, handling errors, or wrapping external calls.
---

# Logging & Error Handling

## Logging

- `logger = logging.getLogger(__name__)` at module level — never `log`.
- **Structured only.** The message is a static, dot-delimited event name; all
  dynamic values go in `extra`. Never f-string or `%`-formatted messages.

```python
# RIGHT
logger.info(
    "itinerary.generated",
    extra={
        "itinerary_id": str(itinerary.id),
        "destination_count": len(itinerary.destinations),
    },
)
logger.exception("booking.provider_error", extra={"booking_id": str(booking.id)})

# WRONG
logger.info(f"Generated itinerary {itinerary.id}")
```

- Levels: `info` for start/end of significant operations and state changes;
  `warning` for unexpected-but-handled states; `exception` inside an `except`
  (includes the stack trace); `debug` for diagnostics.
- Log identifiers, never secrets, tokens, payment data, or full PII payloads.

## Error handling

Fail-fast rules live in the **code-quality** skill. The patterns:

- **Catch specific exceptions at the boundary** where you can actually do
  something (translate to a 4xx, retry, fall back by design).
- **Re-raise with cause:** `raise BookingFailed(...) from exc` — never lose the
  original traceback.
- **Validate at the edge** (request schemas, LLM tool arguments, config) so the
  interior can trust its inputs.
- **Concurrency:** state transitions that must not race happen inside a
  transaction with a row lock (`SELECT ... FOR UPDATE`) or an idempotency key.
- **Idempotency:** anything that can be retried (webhooks, workflow steps,
  bookings) must be safe to run twice; treat "already done" as success, not an
  error.

## Silent-failure patterns to never introduce

- `except Exception:` that only logs and continues or returns a default.
- Ignored return values / exit codes from operations that can fail.
- `asyncio.create_task(...)` with no reference kept and no done-callback.
- `dict.get(key, default)` / `getattr(obj, name, default)` for a *required*
  key — a missing key should be a loud error, not a wrong value.
- Workflow or job code that logs an error but reports success (no retry
  happens).
- Diagnostic scripts that print a failure but exit 0.
