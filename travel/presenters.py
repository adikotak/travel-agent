"""Display data for the inbox UI, kept out of views and templates."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings

from travel.agent.compose import ReplyPurpose
from travel.models import (
    Approval,
    ApprovalStatus,
    BookingIntent,
    BookingIntentStatus,
    Email,
    EmailDirection,
    EmailThread,
    Flight,
    ItineraryStatus,
    User,
)
from travel.schemas import OfferedOption

AGENT_NAME = "Travel Agent"

PURPOSE_STYLE: dict[str, tuple[str, str, str]] = {
    # purpose: (title, tone, icon)
    ReplyPurpose.CLARIFICATION: ("A few details needed", "info", "message-circle-question"),
    ReplyPurpose.OPTIONS: ("Flight options", "info", "plane"),
    ReplyPurpose.BOOKED: ("Trip booked", "success", "circle-check"),
    ReplyPurpose.APPROVAL_PENDING: ("Waiting on approval", "warning", "hourglass"),
    ReplyPurpose.APPROVAL_REQUEST: ("Approval needed", "warning", "shield-check"),
    ReplyPurpose.APPROVAL_REJECTED: ("Approval declined", "danger", "circle-x"),
    ReplyPurpose.DISRUPTION_NOTICE: ("Flight delayed", "warning", "clock-alert"),
    ReplyPurpose.DISRUPTION_REBOOKED: ("Rebooked after disruption", "success", "refresh-cw"),
    ReplyPurpose.DISRUPTION_OPTIONS: (
        "Disruption: choose a new flight",
        "danger",
        "triangle-alert",
    ),
    ReplyPurpose.NO_OPTIONS: ("No flights found", "neutral", "search-x"),
    ReplyPurpose.CANCELLED: ("Trip cancelled", "neutral", "ban"),
    ReplyPurpose.OTHER: ("", "neutral", "mail"),
}

STATUS_TONE = {
    BookingIntentStatus.OPEN: "info",
    BookingIntentStatus.PENDING_APPROVAL: "warning",
    BookingIntentStatus.BOOKED: "success",
    BookingIntentStatus.CANCELLED: "neutral",
}


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
    tone: str
    options: list[OptionCard]


@dataclass
class EmailCard:
    email: Email
    sender_name: str
    to_names: list[str]
    is_agent: bool
    title: str = ""
    tone: str = "neutral"
    icon: str = "mail"
    prose: str = ""
    questions: list[str] = field(default_factory=list)
    option_groups: list[OptionGroup] = field(default_factory=list)
    directions: list[str] = field(default_factory=list)
    itinerary: list[Flight] = field(default_factory=list)
    can_choose: bool = False
    can_decide: bool = False

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
    status: str = ""
    status_tone: str = "neutral"


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
        intent = thread.booking_intent
        rows.append(
            ThreadRow(
                thread=thread,
                sender_name=_name_for(latest.from_address, users),
                latest=latest,
                preview=_preview(latest),
                status=intent.get_status_display() if intent else "",
                status_tone=STATUS_TONE.get(intent.status, "neutral") if intent else "neutral",
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
        OptionGroup("Book now · within policy", "success", [c for c in cards if c.can_book_now]),
        OptionGroup("Needs manager approval", "warning", [c for c in cards if not c.can_book_now]),
    ]
    return [g for g in groups if g.options], directions


def email_cards(thread: EmailThread, viewer: User) -> list[EmailCard]:
    """Every email in the thread, with agent emails expanded into structured cards."""
    users = _users_by_email()
    emails = list(thread.emails.order_by("sent_at", "pk"))
    intent = thread.booking_intent
    latest_offer = next((e for e in reversed(emails) if e.options), None)
    pending = _pending_approval(intent)
    cards = []
    for email in emails:
        is_agent = email.direction == EmailDirection.OUTBOUND
        card = EmailCard(
            email=email,
            sender_name=_name_for(email.from_address, users),
            to_names=[_name_for(address, users) for address in email.to_addresses],
            is_agent=is_agent,
        )
        if is_agent and email.card:
            title, tone, icon = PURPOSE_STYLE[email.card["purpose"]]
            card.title, card.tone, card.icon = title, tone, icon
            card.prose = email.card["prose"]
            card.questions = email.card["questions"]
            ids = email.card["itinerary_flight_ids"]
            card.itinerary = list(Flight.objects.filter(pk__in=ids).order_by("departs_at"))
            card.option_groups, card.directions = _option_groups(email)
            card.can_choose = (
                email == latest_offer
                and intent is not None
                and intent.traveler == viewer
                and intent.status != BookingIntentStatus.CANCELLED
            )
            card.can_decide = (
                pending is not None
                and pending.request_email_id == email.pk
                and pending.approver == viewer
            )
        cards.append(card)
    return cards


def _pending_approval(intent: BookingIntent | None) -> Approval | None:
    if intent is None:
        return None
    return intent.approvals.filter(status=ApprovalStatus.PENDING).first()


@dataclass
class TripPanel:
    intent: BookingIntent
    status_tone: str
    origin: str
    destination: str
    depart_date: date | None
    return_date: date | None
    arrive_by: datetime | None
    cabin: str
    notes: str
    itinerary: list[Flight]
    itinerary_total: Decimal
    approvals: list[Approval]
    actions: list


def trip_panel(intent: BookingIntent | None) -> TripPanel | None:
    if intent is None:
        return None
    constraints = intent.constraints
    itinerary = intent.itineraries.filter(status=ItineraryStatus.ACTIVE).first()
    legs = itinerary.legs() if itinerary else []
    return TripPanel(
        intent=intent,
        status_tone=STATUS_TONE[intent.status],
        origin=constraints.get("origin", "—"),
        destination=constraints.get("destination", "—"),
        depart_date=date.fromisoformat(d) if (d := constraints.get("depart_date")) else None,
        return_date=date.fromisoformat(d) if (d := constraints.get("return_date")) else None,
        arrive_by=datetime.fromisoformat(a)
        if (a := constraints.get("arrive_outbound_by"))
        else None,
        cabin=constraints.get("requested_cabin") or "",
        notes=constraints.get("notes", ""),
        itinerary=legs,
        itinerary_total=sum((leg.price for leg in legs), Decimal("0")),
        approvals=list(intent.approvals.select_related("approver").order_by("created_at")),
        actions=list(intent.actions.order_by("created_at", "pk")),
    )
