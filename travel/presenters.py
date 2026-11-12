"""Display data for the inbox UI, kept out of views and templates."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from travel.models import (
    Email,
    EmailDirection,
    EmailThread,
    Flight,
    User,
)
from travel.schemas import OfferedOption

AGENT_NAME = "Travel Agent"


def initials(name: str) -> str:
    return "".join(part[0] for part in name.split()[:2]).upper()


def _name_for(address: str, users_by_email: dict[str, User]) -> str:
    if address == settings.AGENT_EMAIL:
        return AGENT_NAME
    user = users_by_email.get(address)
    return user.get_full_name() if user else address


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest:02d}m"


@dataclass
class OptionCard:
    number: int
    direction: str
    legs: list[Flight]
    price: Decimal
    can_book_now: bool
    reasons: list[str]
    preferences: list[str]

    @property
    def first(self) -> Flight:
        return self.legs[0]

    @property
    def last(self) -> Flight:
        return self.legs[-1]

    @property
    def flight_numbers(self) -> str:
        return " · ".join(leg.flight_number for leg in self.legs)

    @property
    def stops_label(self) -> str:
        if len(self.legs) == 1:
            return "Nonstop"
        return "1 stop · " + ", ".join(leg.destination for leg in self.legs[:-1])

    @property
    def duration(self) -> str:
        layovers = sum(
            int((b.departs_at - a.arrives_at).total_seconds() // 60)
            for a, b in zip(self.legs, self.legs[1:], strict=False)
        )
        return _duration(sum(leg.duration_minutes for leg in self.legs) + layovers)

    @property
    def cabin(self) -> str:
        return self.first.get_cabin_display()

    @property
    def is_red_eye(self) -> bool:
        return self.first.is_red_eye


@dataclass
class OptionGroup:
    title: str
    options: list[OptionCard]


@dataclass
class EmailCard:
    email: Email
    sender_name: str
    to_names: list[str]
    is_agent: bool
    trip_tag: str = ""
    prose: str = ""
    questions: list[str] = field(default_factory=list)
    option_groups: list[OptionGroup] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    itinerary: list[Flight] = field(default_factory=list)

    @property
    def initials(self) -> str:
        return initials(self.sender_name)

    @property
    def itinerary_total(self) -> Decimal:
        return sum((leg.price for leg in self.itinerary), Decimal("0"))


@dataclass
class ThreadRow:
    thread: EmailThread
    sender_name: str
    latest: Email
    preview: str


def _users_by_email() -> dict[str, User]:
    return {user.email: user for user in User.objects.all()}


def _preview(email: Email) -> str:
    text = email.card.get("prose") or email.body
    return next((line for line in text.splitlines() if line.strip()), "")


def thread_rows(user: User) -> list[ThreadRow]:
    """The user's threads (sent or received), newest activity first."""
    users = _users_by_email()
    rows = []
    threads = EmailThread.objects.select_related("booking_intent").prefetch_related("emails")
    for thread in threads:
        emails = sorted(thread.emails.all(), key=lambda e: (e.sent_at, e.pk))
        if not any(e.from_address == user.email or user.email in e.to_addresses for e in emails):
            continue
        latest = emails[-1]
        rows.append(
            ThreadRow(
                thread=thread,
                sender_name=_name_for(latest.from_address, users),
                latest=latest,
                preview=_preview(latest),
            )
        )
    return sorted(rows, key=lambda row: (row.latest.sent_at, row.latest.pk), reverse=True)


def _option_groups(email: Email) -> tuple[list[OptionGroup], list[str]]:
    offered = [OfferedOption.model_validate(o) for o in email.options]
    flights = Flight.objects.in_bulk([fid for o in offered for fid in o.flight_ids])
    cards = [
        OptionCard(
            number=o.number,
            direction=o.direction,
            legs=[flights[fid] for fid in o.flight_ids],
            price=o.price,
            can_book_now=o.can_book_now,
            reasons=o.reasons,
            preferences=o.preferences,
        )
        for o in offered
    ]
    directions = list(dict.fromkeys(card.direction for card in cards))
    groups = [
        OptionGroup("Can book now (within policy)", [c for c in cards if c.can_book_now]),
        OptionGroup("Needs manager approval", [c for c in cards if not c.can_book_now]),
    ]
    return [g for g in groups if g.options], directions


def email_cards(thread: EmailThread) -> list[EmailCard]:
    """Every email in the thread; agent emails expose their structured parts for rendering."""
    users = _users_by_email()
    intent = thread.booking_intent
    cards = []
    for email in thread.emails.order_by("sent_at", "pk"):
        is_agent = email.direction == EmailDirection.OUTBOUND
        card = EmailCard(
            email=email,
            sender_name=_name_for(email.from_address, users),
            to_names=[_name_for(address, users) for address in email.to_addresses],
            is_agent=is_agent,
        )
        if is_agent and email.card:
            card.trip_tag = f"TRIP-{intent.pk}" if intent else ""
            card.prose = email.card["prose"]
            card.questions = email.card["questions"]
            ids = email.card["itinerary_flight_ids"]
            card.itinerary = list(Flight.objects.filter(pk__in=ids).order_by("departs_at"))
            card.option_groups, card.directions = _option_groups(email)
        cards.append(card)
    return cards
