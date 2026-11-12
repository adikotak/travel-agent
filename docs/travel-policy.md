# Travel Policy (v1)

The policy is data, not prompt text: `TravelPolicy.rules` holds company
defaults, `TravelPolicy.approval_rules` says what happens on a violation, and
each client `BillableCode.policy_overrides` replaces specific keys for trips
billed to that client. The agent's LLM reads emails and writes replies; it
never decides compliance. Evaluation is deterministic code, so every decision
is explainable and an email can't argue its way past a rule.

## Rules

| Rule | Value | Why |
|---|---|---|
| Budget per direction | ≤ $400 under 6h, ≤ $1,500 at 6h+ | Per direction is easy to reason about and to explain in an email. |
| Duration basis | Total travel time, including connections | Long flights get a bigger budget because they're more tiring; total time measures that. |
| Cabin, under 6h | Economy | Short flights don't justify upgrades. |
| Cabin, 6h+ | Economy or premium economy | Comfort on long flights within the same $1,500 cap. |
| VP+, 6h+ | Business allowed, up to $3,000 | Seniority benefit, capped. |
| Lowest logical fare | ≤ 20% above the cheapest compliant option, unless it saves ≥ 2h | Stops "$395 nonstop when a $210 one-stop exists"; also bounds loyalty and preference choices. |
| Booking window | ≥ 7 days in advance | Last-minute fares are where spend leaks. |
| Never allowed | First class | A hard no, not an approval request. |
| Disruption rebooking | Same cabin or lower, ≤ $200 more; exempt from the booking window | Disruptions are always last-minute; the traveler shouldn't wait on approval to get home. |

## Preferences vs. policy

Policy is hard; preferences are soft. Preferences (no red-eyes, seat type,
nonstop only, preferred airline for miles) choose *among* compliant options and
never override a rule. If the only option matching a preference violates
policy, the agent offers the best compliant option and the preferred option
marked "needs approval."

## Approval

- **Manager approval:** over budget, cabin not allowed, inside the booking
  window, above lowest logical fare, disruption rebooking over the limit.
- **Always rejected:** never-allowed cabins.
- **Auto-book** only when the option is in policy, a billable code is present
  for client-billable travel, and the request is unambiguous.

## Client contracts

Overrides replace matching keys of the company rules (deep-merged).

| Code | Client | Contract |
|---|---|---|
| `ACME-001` | Acme Corp (strict) | Economy only at every length and seniority; $350 / $900; 14-day window |
| `GLOBEX-001` | Globex (loose) | Long haul starts at 4h; business allowed on long haul for everyone; $2,000 long-haul cap |
| `INITECH-001` | Initech (standard) | Company policy; code still required for bill-back |
