# Email Travel Agent

An agent that lives in an inbox and handles employee travel requests end to end:
it parses freeform emails, applies a travel policy, books or proposes flights,
routes approvals to managers, follows the thread as plans change, and emails
travelers on its own when a flight is cancelled or delayed.

## Run it

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY
uv run python3 manage.py migrate
uv run python3 manage.py seed_demo
uv run python3 manage.py runserver
```

Open http://localhost:8000. Switch mailboxes on the left to act as any demo
employee (or their manager), write to the agent, and reply in threads.
**Disruption control** cancels or delays any booked flight.

| User | Role | Notes |
|---|---|---|
| Priya Shah | Analyst | Prefers nonstop, no red-eyes, United (MileagePlus) |
| Sam Rivera | Analyst | No preferences |
| Jordan Kim | Consultant on the Acme engagement | Bills `ACME-001` |
| Morgan Lee | Engineering Manager | Approves for Priya, Sam, Jordan |
| Victoria Chen | VP Sales | Business on long haul; British Airways loyalty |
| Daniel Park | CEO | Approves for Victoria |

## How it works

```
email ─► parse (LLM → typed intent) ─► search ─► policy ─► rank ─► decide ─► book / propose / approve
                                                                           └► reply (LLM prose + exact options)
disruption ─► affected itineraries ─► re-search under rebooking rules ─► rebook or ask ─► email traveler
```

The LLM only reads emails and writes prose. Policy, ranking, and the
book-vs-approve decision are deterministic code, so every decision is
explainable (see the **Agent reasoning** panel) and an email can't talk its way
past a rule. Prices, flights, and questions in replies are rendered from data,
never generated.

- **Policy** — [docs/travel-policy.md](docs/travel-policy.md): per-direction
  budgets by total travel time, cabin rules with a VP tier, lowest logical fare,
  booking window, client contract overrides, and disruption rebooking limits.
- **Preferences rank, policy filters.** Preferences pick among compliant
  options; if a preference can only be met out of policy, the email splits
  options into "can book now" and "needs approval."
- **Threads and trips.** Each trip is a `TRIP-<id>`; mention it in a new email
  to pick the trip back up.
- **Inventory** — a seeded generator covers ~14 airports for 45 days, plus a
  fixed daily SFO↔JFK and JFK↔LHR schedule that guarantees the interesting
  policy conflicts on any date.

## Code map

| Path | What |
|---|---|
| `travel/models.py` | Data model |
| `travel/search.py`, `policy.py`, `ranking.py`, `decisions.py` | Deterministic core |
| `travel/agent/` | LLM parsing and reply composition (Pydantic AI, OpenAI) |
| `travel/services/` | Inbox intake, intent handlers, booking, approvals, disruptions |
| `travel/inventory.py`, `demo.py` | Mock flights and demo users |
| `travel/views.py`, `templates/` | Fake inbox UI |

## Test

```bash
uv run pytest       # no network; the LLM is faked
uv run ruff check . && uv run ruff format --check .
```
