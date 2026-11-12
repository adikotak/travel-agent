from dataclasses import dataclass, field
from decimal import Decimal

from django.db import models
from pydantic_ai import Agent, RunContext

from travel.agent.llm import chat_model


class ReplyPurpose(models.TextChoices):
    """Why the agent is writing; steers tone and what the prose must cover."""

    CLARIFICATION = "clarification", "Ask for missing details"
    OPTIONS = "options", "Offer options"
    BOOKED = "booked", "Confirm a booking"
    APPROVAL_PENDING = "approval-pending", "Tell the traveler approval was requested"
    APPROVAL_REQUEST = "approval-request", "Ask a manager to approve"
    APPROVAL_REJECTED = "approval-rejected", "Tell the traveler approval was rejected"
    DISRUPTION_NOTICE = "disruption-notice", "Heads-up about a delay"
    DISRUPTION_REBOOKED = "disruption-rebooked", "Explain an automatic rebooking"
    DISRUPTION_OPTIONS = "disruption-options", "Disruption needs the traveler's choice"
    NO_OPTIONS = "no-options", "Nothing bookable found"
    CANCELLED = "cancelled", "Confirm a cancellation"
    OTHER = "other", "General reply"


@dataclass(frozen=True)
class OptionFact:
    """One numbered option exactly as shown in the email."""

    number: int
    direction: str
    flights: str
    price: Decimal
    can_book_now: bool
    policy_notes: list[str] = field(default_factory=list)
    preference_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplyFacts:
    """Everything the reply may state; the model writes prose around these, never beyond them."""

    purpose: ReplyPurpose
    recipient_name: str
    trip_tag: str | None = None
    points: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    options: list[OptionFact] = field(default_factory=list)
    itinerary: list[str] = field(default_factory=list)


compose_agent = Agent(
    output_type=str,
    deps_type=ReplyFacts,
    instructions=(
        "You are a corporate travel agent writing an email reply. Write a short, warm, "
        "plain-text message (2-5 sentences) covering the purpose and points provided. "
        "Do not list flights, prices, itinerary details, or the questions: those are "
        "appended below your text automatically, so refer to them as 'below'. "
        "Never state a fact that isn't in the points. No subject line, no signature."
    ),
)


@compose_agent.instructions
def _facts(ctx: RunContext[ReplyFacts]) -> str:
    facts = ctx.deps
    lines = [f"Purpose: {facts.purpose.label}.", f"Recipient: {facts.recipient_name}."]
    lines += [f"Point: {point}" for point in facts.points]
    if facts.questions:
        lines.append(f"{len(facts.questions)} question(s) for the recipient are listed below.")
    if facts.options:
        lines.append(f"{len(facts.options)} numbered options are listed below the message.")
    if not facts.options and not facts.itinerary and not facts.questions:
        lines.append(
            "Nothing is attached below this message: do not mention options, flights, or "
            "details 'below', and do not imply any action was taken beyond the points."
        )
    return "\n".join(lines)


def render_options(options: list[OptionFact]) -> str:
    """The options block, split into what can be booked now and what needs approval."""
    sections = []
    for heading, can_book_now in (
        ("Can book now (within policy)", True),
        ("Needs manager approval", False),
    ):
        group = [o for o in options if o.can_book_now is can_book_now]
        if not group:
            continue
        lines = [heading + ":"]
        for option in group:
            lines.append(
                f"  {option.number}. [{option.direction}] {option.flights} — ${option.price:,.0f}"
            )
            lines += [f"       ✓ {note}" for note in option.preference_notes]
            lines += [f"       ⚠ {note}" for note in option.policy_notes]
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def render_body(prose: str, facts: ReplyFacts) -> str:
    """Assemble the email: model prose, then exact options/itinerary, then the trip tag."""
    parts = [prose.strip()]
    if facts.questions:
        parts.append("\n".join(f"• {question}" for question in facts.questions))
    if facts.options:
        parts.append(render_options(facts.options))
        parts.append("Reply with the option number(s) you'd like.")
    if facts.itinerary:
        parts.append("Itinerary:\n" + "\n".join(f"  {line}" for line in facts.itinerary))
    signature = "— Travel Agent"
    if facts.trip_tag:
        signature += (
            f"\nReference: {facts.trip_tag} (include this to pick the trip up in a new email)"
        )
    parts.append(signature)
    return "\n\n".join(parts)


def write_prose(facts: ReplyFacts) -> str:
    """The model-written message for these facts; structured parts are rendered separately."""
    result = compose_agent.run_sync("Write the email message.", deps=facts, model=chat_model())
    return result.output.strip()
