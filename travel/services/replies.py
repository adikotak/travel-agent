from datetime import datetime

from django.conf import settings

from travel.agent.compose import OptionFact, ReplyFacts, compose_reply
from travel.models import (
    ActionKind,
    BookingIntent,
    Email,
    EmailDirection,
    EmailThread,
    Flight,
    User,
)
from travel.ranking import RankedOption
from travel.schemas import OfferedOption
from travel.search import TravelOption
from travel.services.actions import log_action


def display_name(user: User) -> str:
    return user.get_full_name() or user.username


def trip_tag(booking_intent: BookingIntent | None) -> str | None:
    return f"TRIP-{booking_intent.pk}" if booking_intent is not None else None


def describe_option(option: TravelOption) -> str:
    """One line a traveler can scan: flights, route, times, stops, duration, cabin."""
    first, last = option.first_leg, option.last_leg
    flights = " + ".join(f"{leg.airline} {leg.flight_number}" for leg in option.legs)
    route = "→".join([first.origin, *(leg.destination for leg in option.legs)])
    stops = "nonstop" if option.stops == 0 else f"{option.stops} stop"
    hours, minutes = divmod(option.total_minutes, 60)
    red_eye = ", red-eye" if option.is_red_eye else ""
    return (
        f"{flights} {route}, {first.departs_at:%a %b %-d %H:%M}–{last.arrives_at:%H:%M} "
        f"({stops}, {hours}h{minutes:02d}m{red_eye}), {option.cabin.label}"
    )


def describe_leg(flight: Flight) -> str:
    return (
        f"{flight.departs_at:%a %b %-d} · {flight.airline} {flight.flight_number} "
        f"{flight.origin} {flight.departs_at:%H:%M} → {flight.destination} "
        f"{flight.arrives_at:%H:%M} · {flight.get_cabin_display()} · ${flight.price:,.0f}"
    )


def offer(direction: str, ranked: list[RankedOption], start: int) -> list[OfferedOption]:
    return [
        OfferedOption(
            number=start + i,
            direction=direction,
            flight_ids=r.evaluation.option.flight_ids,
            price=r.evaluation.option.price,
            can_book_now=r.evaluation.is_compliant,
            reasons=r.evaluation.reasons,
        )
        for i, r in enumerate(ranked)
    ]


def option_facts(offered: list[OfferedOption], ranked: list[RankedOption]) -> list[OptionFact]:
    """Pair offered options with their ranking to show policy and preference notes."""
    return [
        OptionFact(
            number=o.number,
            direction=o.direction,
            flights=describe_option(r.evaluation.option),
            price=o.price,
            can_book_now=o.can_book_now,
            policy_notes=o.reasons,
            preference_notes=[p.label for p in r.matches],
        )
        for o, r in zip(offered, ranked, strict=True)
    ]


def send_email(
    thread: EmailThread,
    recipient: User,
    facts: ReplyFacts,
    sent_at: datetime,
    offered: list[OfferedOption] | None = None,
) -> Email:
    """Compose and store an outbound email from the agent on `thread`."""
    email = Email.objects.create(
        thread=thread,
        direction=EmailDirection.OUTBOUND,
        from_address=settings.AGENT_EMAIL,
        to_addresses=[recipient.email],
        subject=thread.subject if thread.subject.startswith("Re:") else f"Re: {thread.subject}",
        body=compose_reply(facts),
        sent_at=sent_at,
        options=[o.model_dump(mode="json") for o in offered or []],
    )
    log_action(
        thread.booking_intent,
        ActionKind.SENT_EMAIL,
        f"{facts.purpose.label} → {recipient.email}",
        email=email,
    )
    return email
