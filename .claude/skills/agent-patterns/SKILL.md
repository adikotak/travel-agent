---
name: agent-patterns
description: Conventions for building LLM agents — framework-native first, typed dependencies, tool design, delegation, deadlines, observability, and testing. Use when adding or changing an agent, its tools, sub-agent delegation, or evals.
---

# Agent Patterns

## Native framework first

- Build on the agent framework's own primitives (typed deps/run context, tool
  schemas, output types and validators, hooks, usage limits) before writing
  custom glue.
- Before concluding the framework can't do something, read the *installed*
  version's signatures/source and its docs. Don't infer APIs from memory or
  invent a gap to justify a custom executor, scheduler, or retry loop.
- One shared runtime owns execution, persistence, tracing, and deadlines. No
  per-agent copies of that machinery and no `if agent_name == ...` branches in
  shared routes.

## State and dependencies

- Build a fresh, typed dependency object per run. Mutable run state never lives
  on a shared agent instance or module global — runs execute concurrently.
- Caller identity and authorization scope travel in server-side context, never
  in model-authored arguments. A model-supplied ID narrows a request; it never
  grants access. Re-check permissions in backend code.

## Tool design

- Give the model arguments only for choices it is actually making. Values the
  server already knows (the validated request, the user's trip, frozen
  snapshots) are bound server-side — don't ask the model to retype them and
  then check for equality.
- Model-facing lookups use human/business identifiers (city, IATA code, hotel
  name); resolve them to internal IDs in backend code and validate the result.
  Keep internal UUIDs out of model-facing contracts unless a task needs an
  exact handle.
- Let schema validation (Pydantic/Zod) enforce shape. Add hand-written checks
  only for rules schemas can't express: authorization, provenance, required
  completeness, business policy.
- Mark tools sequential via the framework when ordering matters.
- **Side-effecting tools (book, pay, cancel, email) require an explicit
  confirmation step** and an idempotency key. Read-only tools can run freely.

## Delegation

- A sub-agent gets a standalone brief, a fresh history, and the smallest typed
  deps it needs — not the parent's whole context.
- If every specialist result is required, validate that all exist before the
  parent proceeds; never let the parent model fill in missing specialist work.
- Deterministic policy gates (budget caps, visa rules, availability) run in
  domain code after the model, not as instructions the model may ignore.

## Deadlines and limits

- One root deadline per run, shared by delegated work; enforce with a real
  timeout. Keep it under the HTTP/hosting request limit with margin.
- Watch for implicit framework defaults (e.g. request-count caps) that
  silently truncate valid runs; set them deliberately.

## Observability

- Trace every run; one trace per root invocation, delegates nested beneath it.
- Group related traces with a session ID; keep trace IDs out of prompts.
- Exclude binary payloads and secrets from traces.

## Testing

- Deterministic fake models for orchestration contracts (tool routing,
  delegation briefs, required-result gates, concurrent-run isolation). These
  prove wiring, not model quality.
- Assert the child's actual brief matches validated request data.
- Exercise malformed, duplicate, and retry-exhausted tool calls; they must not
  record completion.
- For prompt or provider changes, run a small real-provider eval within budget
  and say when you didn't. "HTTP 200" is not evidence the agent did the right
  thing.
