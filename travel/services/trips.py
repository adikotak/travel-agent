from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from travel.agent.compose import ReplyFacts, ReplyPurpose
from travel.agent.parse import (
    ApprovalDecision,
    CancelTrip,
    EmailIntent,
    OptionSelection,
    Other,
    ParseContext,
    TripDetails,
    parse_email,
)
from travel.decisions import DecisionKind, DirectionDecision, combine, decide_direction
from travel.models import (
    ActionKind,
    Approval,
    ApprovalStatus,
    BillableCode,
    BookingIntent,
    BookingIntentStatus,
    Email,
    EmailDirection,
    EmailThread,
    Flight,
    Itinerary,
    ItineraryStatus,
    TravelPolicy,
    User,
)
from travel.policy import approval_rules, effective_rules, evaluate_options
from travel.ranking import RankedOption, rank
from travel.schemas import OfferedOption, TripConstraints
from travel.search import find_options
from travel.services.actions import log_action
from travel.services.approvals import ApprovalError, record_decision, request_approval
from travel.services.booking import book_itinerary, rebook_itinerary, split_directions
from travel.services.disruptions import DisruptionOutcome, DisruptionResponse
from travel.services.replies import (
    display_name,
    itinerary_lines,
    offer,
    option_facts,
    send_email,
    trip_tag,
)

OUTBOUND = "Outbound"
RETURN = "Return"
TRIP_FIELDS = (
    "origin",
    "destination",
    "depart_date",
    "return_date",
    "arrive_outbound_by",
    "requested_cabin",
    "airlines",
    "is_client_billable",
)


@dataclass(frozen=True)
class DirectionPlan:
    direction: str
    decision: DirectionDecision
    ranked_shown: list[RankedOption]


def handle_email(email: Email, sender: User, now: datetime) -> None:
    """Parse an inbound email from a known user and act on it."""
    intent = email.thread.booking_intent
    pending = _pending_approval(intent)
    context = ParseContext(
        today=now.date(),
        sender_name=display_name(sender),
        sender_is_approver=pending is not None and pending.approver == sender,
        current_trip=_describe_constraints(intent),
        offered_options=[
            f"{o.number}. [{o.direction}] {o.label} — ${o.price:,.0f}"
            f"{'' if o.can_book_now else ' (needs approval)'}"
            for o in _last_offer(email.thread)
        ],
    )
    parsed: EmailIntent = parse_email(email.subject, email.body, context)
    match parsed:
        case TripDetails():
            _handle_trip_details(email, sender, intent, parsed, now)
        case OptionSelection():
            _handle_selection(email, sender, intent, parsed, now)
        case ApprovalDecision():
            _handle_approval_decision(email, sender, intent, parsed, now)
        case CancelTrip():
            _handle_cancel(email, sender, intent, now)
        case Other():
            _reply(
                email,
                sender,
                ReplyPurpose.OTHER,
                now,
                points=[f"the sender wrote: {parsed.summary}", "no changes were made to the trip"],
            )


def _reply(
    email: Email,
    recipient: User,
    purpose: ReplyPurpose,
    now: datetime,
    *,
    points: list[str] | None = None,
    questions: list[str] | None = None,
    offered: list[OfferedOption] | None = None,
    itinerary: list[Flight] | None = None,
    thread: EmailThread | None = None,
) -> Email:
    thread = thread or email.thread
    facts = ReplyFacts(
        purpose=purpose,
        recipient_name=display_name(recipient),
        trip_tag=trip_tag(thread.booking_intent),
        points=points or [],
        questions=questions or [],
        options=option_facts(offered or []),
        itinerary=itinerary_lines(itinerary or []),
    )
    return send_email(thread, recipient, facts, now, offered, itinerary)


def _pending_approval(intent: BookingIntent | None) -> Approval | None:
    if intent is None:
        return None
    return intent.approvals.filter(status=ApprovalStatus.PENDING).order_by("-created_at").first()


def _last_offer(thread: EmailThread) -> list[OfferedOption]:
    last = thread.emails.exclude(options=[]).order_by("-sent_at", "-pk").first()
    return [OfferedOption.model_validate(o) for o in last.options] if last else []


def _describe_constraints(intent: BookingIntent | None) -> str | None:
    if intent is None or not intent.constraints:
        return None
    return ", ".join(f"{key}={value}" for key, value in intent.constraints.items())


def _traveler_thread(intent: BookingIntent) -> EmailThread:
    return intent.threads.order_by("created_at").first()


def _active_policy() -> TravelPolicy:
    return TravelPolicy.objects.get(is_active=True)


def _handle_trip_details(
    email: Email,
    sender: User,
    intent: BookingIntent | None,
    details: TripDetails,
    now: datetime,
) -> None:
    if intent is None:
        intent = BookingIntent.objects.create(traveler=sender)
        email.thread.booking_intent = intent
        email.thread.save(update_fields=["booking_intent", "updated_at"])
        log_action(intent, ActionKind.PARSED_REQUEST, "new trip request", email=email)
    if intent.traveler != sender:
        _reply(
            email,
            sender,
            ReplyPurpose.OTHER,
            now,
            points=["only the traveler can change this trip"],
        )
        return

    stated = {f: v for f in TRIP_FIELDS if (v := getattr(details, f)) is not None}
    if details.notes:
        stated["notes"] = "; ".join(filter(None, [intent.constraints.get("notes"), details.notes]))
    changed = {k: v for k, v in stated.items() if intent.constraints.get(k) != _jsonable(v)}
    if changed and intent.constraints:
        intent.constraint_revisions = [
            *intent.constraint_revisions,
            {"constraints": intent.constraints, "replaced_by_email": email.pk},
        ]
        log_action(
            intent,
            ActionKind.UPDATED_CONSTRAINTS,
            "changed " + ", ".join(sorted(changed)),
            email=email,
        )
    intent.constraints = {**intent.constraints, **{k: _jsonable(v) for k, v in changed.items()}}

    questions = []
    if details.billable_code:
        code = BillableCode.objects.filter(
            code__iexact=details.billable_code.strip(), is_active=True
        ).first()
        if code is None:
            questions.append(
                f"I couldn't find billable code {details.billable_code}; can you check it?"
            )
        else:
            intent.billable_code = code
            intent.constraints["is_client_billable"] = code.is_client_billable
    intent.save()

    questions += _missing_details(intent)
    if questions:
        _reply(email, sender, ReplyPurpose.CLARIFICATION, now, questions=questions)
        return
    plan_trip(intent, email, now)


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date | datetime) else value


def _missing_details(intent: BookingIntent) -> list[str]:
    constraints = intent.constraints
    questions = [
        question
        for key, question in (
            ("origin", "Where are you flying from?"),
            ("destination", "Where are you flying to?"),
            ("depart_date", "What date do you need to leave?"),
        )
        if not constraints.get(key)
    ]
    if constraints.get("is_client_billable") and intent.billable_code is None:
        questions.append("This looks like client travel. What's the client billable code?")
    return questions


def plan_trip(intent: BookingIntent, email: Email, now: datetime) -> None:
    """Search, evaluate, rank, and decide each direction, then book, propose, or escalate."""
    try:
        constraints = TripConstraints.model_validate(intent.constraints)
    except ValidationError as error:
        problems = "; ".join(e["msg"] for e in error.errors())
        _reply(email, intent.traveler, ReplyPurpose.CLARIFICATION, now, questions=[problems])
        return
    policy = _active_policy()
    rules = effective_rules(policy, intent.billable_code)
    legs = [(OUTBOUND, constraints.origin, constraints.destination, constraints.depart_date)]
    if constraints.return_date is not None:
        legs.append((RETURN, constraints.destination, constraints.origin, constraints.return_date))

    plans = []
    for direction, origin, destination, day in legs:
        options = [
            option
            for option in find_options(origin, destination, day)
            if not constraints.airlines or set(option.airlines) <= set(constraints.airlines)
        ]
        evaluations = evaluate_options(options, intent.traveler.seniority, rules, now.date())
        ranked = rank(
            evaluations,
            intent.traveler,
            arrive_by=constraints.arrive_outbound_by if direction == OUTBOUND else None,
            requested_cabin=constraints.requested_cabin,
        )
        decision = decide_direction(ranked, approval_rules(policy))
        plans.append(
            DirectionPlan(direction, decision, decision.can_book_now + decision.needs_approval)
        )
        log_action(
            intent,
            ActionKind.PROPOSED_OPTIONS,
            f"{direction}: {decision.kind.label} — {decision.reasoning}",
            email=email,
        )
    _act_on_plans(intent, email, plans, policy, now)


def _act_on_plans(
    intent: BookingIntent,
    email: Email,
    plans: list[DirectionPlan],
    policy: TravelPolicy,
    now: datetime,
) -> None:
    traveler = intent.traveler
    kind = combine([p.decision for p in plans])
    if kind == DecisionKind.NO_OPTIONS:
        empty = [p.direction for p in plans if p.decision.kind == DecisionKind.NO_OPTIONS]
        _reply(
            email,
            traveler,
            ReplyPurpose.NO_OPTIONS,
            now,
            points=[f"no bookable {d.lower()} flights on that date" for d in empty],
            questions=["Would a different date or nearby airport work?"],
        )
        return
    chosen = [leg for p in plans for leg in p.decision.chosen.evaluation.option.legs]
    reasoning = "; ".join(f"{p.direction}: {p.decision.reasoning}" for p in plans)
    if kind == DecisionKind.AUTO_BOOK:
        itinerary = book_for_intent(intent, chosen, policy, now, f"auto-booked — {reasoning}")
        _reply(
            email,
            traveler,
            ReplyPurpose.BOOKED,
            now,
            points=[f"booked automatically because {reasoning}"],
            itinerary=itinerary.legs(),
        )
        return
    if kind == DecisionKind.REQUEST_APPROVAL:
        reasons = [r for p in plans for r in p.decision.chosen.evaluation.reasons]
        _escalate(intent, email, chosen, reasons, now)
        return
    offered: list[OfferedOption] = []
    for plan in plans:
        offered += offer(plan.direction, plan.ranked_shown, start=len(offered) + 1)
    _reply(
        email,
        traveler,
        ReplyPurpose.OPTIONS,
        now,
        points=[reasoning],
        offered=offered,
    )


def _escalate(
    intent: BookingIntent, email: Email, flights: list[Flight], reasons: list[str], now: datetime
) -> None:
    traveler = intent.traveler
    try:
        approval = request_approval(intent, flights, "; ".join(reasons))
    except ApprovalError as error:
        _reply(email, traveler, ReplyPurpose.OTHER, now, points=[str(error)])
        return
    manager_thread = EmailThread.objects.create(
        booking_intent=intent,
        subject=f"Approval needed: {display_name(traveler)} {trip_tag(intent)}",
    )
    request_email = _reply(
        email,
        approval.approver,
        ReplyPurpose.APPROVAL_REQUEST,
        now,
        points=[f"{display_name(traveler)} needs approval because: {'; '.join(reasons)}"],
        questions=["Do you approve this booking?"],
        itinerary=flights,
        thread=manager_thread,
    )
    approval.request_email = request_email
    approval.save(update_fields=["request_email", "updated_at"])
    _reply(
        email,
        traveler,
        ReplyPurpose.APPROVAL_PENDING,
        now,
        points=[
            f"sent to {display_name(approval.approver)} for approval because: {'; '.join(reasons)}"
        ],
        itinerary=flights,
        thread=_traveler_thread(intent),
    )


def book_for_intent(
    intent: BookingIntent,
    flights: list[Flight],
    policy: TravelPolicy,
    now: datetime,
    reasoning: str,
) -> Itinerary:
    """Book `flights`; if the trip is already booked, replace only the direction(s) they cover."""
    active = intent.itineraries.filter(status=ItineraryStatus.ACTIVE).first()
    if active is None:
        return book_itinerary(intent, flights, policy, now, reasoning)
    destination = intent.constraints["destination"]
    new_outbound, new_return = split_directions(flights, destination)
    if new_outbound and new_return:
        replaced = active.legs()
    else:
        old_outbound, old_return = split_directions(active.legs(), destination)
        replaced = old_outbound if new_outbound else old_return
    return rebook_itinerary(active, replaced, flights, now, reasoning)


def _handle_selection(
    email: Email,
    sender: User,
    intent: BookingIntent | None,
    selection: OptionSelection,
    now: datetime,
) -> None:
    offered = {o.number: o for o in _last_offer(email.thread)}
    new_picks = [offered[n] for n in selection.option_numbers if n in offered]
    if intent is None or not new_picks or len(new_picks) != len(selection.option_numbers):
        _reply(
            email,
            sender,
            ReplyPurpose.CLARIFICATION,
            now,
            questions=[
                f"I don't have those options on file. Which of {sorted(offered)} did you mean?"
            ],
        )
        return
    # Picks can arrive over several replies; a newer pick replaces an older one per direction.
    by_direction = {o.direction: o for o in [*_earlier_picks(email.thread, offered), *new_picks]}
    picked = list(by_direction.values())
    missing = {o.direction for o in offered.values()} - set(by_direction)
    if missing:
        clarification = _reply(
            email,
            sender,
            ReplyPurpose.CLARIFICATION,
            now,
            points=[f"noted option {o.number} for {o.direction.lower()}" for o in picked],
            questions=[f"Which {d.lower()} option would you like?" for d in sorted(missing)],
        )
        clarification.card["picked"] = [o.number for o in picked]
        clarification.save(update_fields=["card", "updated_at"])
        return
    flight_ids = [fid for o in picked for fid in o.flight_ids]
    flights = sorted(Flight.objects.filter(pk__in=flight_ids), key=lambda f: f.departs_at)
    log_action(
        intent,
        ActionKind.PARSED_REQUEST,
        f"selected options {sorted(o.number for o in picked)}",
        email=email,
    )
    if all(o.can_book_now for o in picked):
        policy = _active_policy()
        itinerary = book_for_intent(
            intent, flights, policy, now, f"traveler picked {sorted(o.number for o in picked)}"
        )
        _reply(
            email,
            sender,
            ReplyPurpose.BOOKED,
            now,
            points=["booked the options you picked; they're within policy"],
            itinerary=itinerary.legs(),
        )
        return
    reasons = [r for o in picked for r in o.reasons]
    _escalate(intent, email, flights, reasons, now)


def _earlier_picks(thread: EmailThread, offered: dict[int, OfferedOption]) -> list[OfferedOption]:
    """Options already picked in replies since the latest offer, recorded on our follow-ups."""
    offer_email = thread.emails.exclude(options=[]).order_by("-sent_at", "-pk").first()
    if offer_email is None:
        return []
    follow_ups = thread.emails.filter(
        direction=EmailDirection.OUTBOUND, pk__gt=offer_email.pk
    ).order_by("pk")
    numbers = [n for e in follow_ups for n in e.card.get("picked", [])]
    return [offered[n] for n in numbers if n in offered]


def _handle_approval_decision(
    email: Email,
    sender: User,
    intent: BookingIntent | None,
    decision: ApprovalDecision,
    now: datetime,
) -> None:
    approval = _pending_approval(intent)
    if intent is None or approval is None:
        _reply(
            email,
            sender,
            ReplyPurpose.OTHER,
            now,
            points=["there's no pending approval on this trip"],
        )
        return
    try:
        record_decision(approval, sender, decision.approved, email, now)
    except ApprovalError as error:
        _reply(email, sender, ReplyPurpose.OTHER, now, points=[str(error)])
        return
    traveler_thread = _traveler_thread(intent)
    if not decision.approved:
        log_action(
            intent, ActionKind.REQUESTED_APPROVAL, f"rejected: {decision.comment}", email=email
        )
        _reply(email, sender, ReplyPurpose.OTHER, now, points=["recorded your rejection"])
        _reply(
            email,
            intent.traveler,
            ReplyPurpose.APPROVAL_REJECTED,
            now,
            points=[f"{display_name(sender)} declined: {decision.comment or 'no reason given'}"],
            questions=["Would you like different options?"],
            thread=traveler_thread,
        )
        return
    flights = list(approval.flights.order_by("departs_at"))
    itinerary = book_for_intent(
        intent, flights, _active_policy(), now, f"approved by {sender.email}"
    )
    legs = itinerary.legs()
    _reply(email, sender, ReplyPurpose.BOOKED, now, points=["approved and booked"], itinerary=legs)
    _reply(
        email,
        intent.traveler,
        ReplyPurpose.BOOKED,
        now,
        points=[f"{display_name(sender)} approved it, so it's booked"],
        itinerary=legs,
        thread=traveler_thread,
    )


def _handle_cancel(email: Email, sender: User, intent: BookingIntent | None, now: datetime) -> None:
    if intent is None or intent.traveler != sender:
        _reply(
            email,
            sender,
            ReplyPurpose.OTHER,
            now,
            points=["there's no trip of yours to cancel here"],
        )
        return
    intent.itineraries.filter(status=ItineraryStatus.ACTIVE).update(
        status=ItineraryStatus.CANCELLED
    )
    intent.status = BookingIntentStatus.CANCELLED
    intent.save(update_fields=["status", "updated_at"])
    log_action(intent, ActionKind.CANCELLED, "traveler cancelled the trip", email=email)
    _reply(email, sender, ReplyPurpose.CANCELLED, now, points=["the trip is cancelled"])


def notify_disruption(outcome: DisruptionOutcome, now: datetime) -> Email:
    """Email the traveler, unprompted, about what a disruption means for their trip."""
    intent = outcome.itinerary.booking_intent
    thread = _traveler_thread(intent)
    anchor = thread.emails.order_by("-sent_at", "-pk").first()
    if outcome.response == DisruptionResponse.NOTIFY_ONLY:
        return _reply(
            anchor, intent.traveler, ReplyPurpose.DISRUPTION_NOTICE, now, points=[outcome.summary]
        )
    if outcome.response == DisruptionResponse.REBOOKED:
        return _reply(
            anchor,
            intent.traveler,
            ReplyPurpose.DISRUPTION_REBOOKED,
            now,
            points=[outcome.summary],
            itinerary=outcome.rebooked_itinerary.legs(),
        )
    decision = outcome.decision
    plan = DirectionPlan("Rebooking", decision, decision.can_book_now + decision.needs_approval)
    return _reply(
        anchor,
        intent.traveler,
        ReplyPurpose.DISRUPTION_OPTIONS,
        now,
        points=[outcome.summary],
        offered=offer(plan.direction, plan.ranked_shown, start=1),
    )
