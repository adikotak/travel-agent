from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models, transaction

from travel.decisions import DecisionKind, DirectionDecision, decide_direction
from travel.models import (
    ActionKind,
    Cabin,
    DisruptionEvent,
    DisruptionKind,
    Flight,
    Itinerary,
    ItineraryStatus,
)
from travel.policy import DisruptedBooking, approval_rules, effective_rules, evaluate_options
from travel.ranking import rank
from travel.schemas import TripConstraints
from travel.search import MIN_CONNECTION, TravelOption, find_options
from travel.services.actions import log_action
from travel.services.booking import rebook_itinerary, split_directions


class DisruptionResponse(models.TextChoices):
    """How the agent responded to a disruption for one itinerary."""

    NOTIFY_ONLY = "notify-only", "Notify only"
    REBOOKED = "rebooked", "Rebooked"
    NEEDS_TRAVELER = "needs-traveler", "Needs traveler"


@dataclass(frozen=True)
class DisruptionOutcome:
    """What happened to one affected itinerary; the orchestrator turns this into an email."""

    itinerary: Itinerary
    response: DisruptionResponse
    disrupted_legs: list[Flight]
    summary: str
    decision: DirectionDecision | None = None
    rebooked_itinerary: Itinerary | None = None


def _delay_breaks_plans(
    flight: Flight, delay: timedelta, direction: list[Flight], arrive_by: datetime | None
) -> str | None:
    """Why a delay forces a rebooking, or None if the traveler only needs a heads-up."""
    new_arrival = flight.arrives_at + delay
    position = direction.index(flight)
    if position + 1 < len(direction):
        next_leg = direction[position + 1]
        if next_leg.departs_at < new_arrival + MIN_CONNECTION:
            return f"the delay breaks the connection to {next_leg.flight_number}"
        return None
    if arrive_by is not None and new_arrival > arrive_by:
        return f"the delayed arrival at {new_arrival:%-I:%M%p} misses {arrive_by:%a %-I:%M%p}"
    return None


def _alternatives(direction: list[Flight], disrupted: Flight) -> list[TravelOption]:
    origin, destination = direction[0].origin, direction[-1].destination
    day = direction[0].departs_at.date()
    options = find_options(origin, destination, day) + find_options(
        origin, destination, day + timedelta(days=1)
    )
    return [option for option in options if disrupted not in option.legs]


def _respond(itinerary: Itinerary, event: DisruptionEvent, now: datetime) -> DisruptionOutcome:
    flight = event.flight
    intent = itinerary.booking_intent
    constraints = TripConstraints.model_validate(intent.constraints)
    outbound, inbound = split_directions(itinerary.legs(), constraints.destination)
    is_outbound = flight in outbound
    direction = outbound if is_outbound else inbound
    arrive_by = constraints.arrive_outbound_by if is_outbound else None

    if event.kind == DisruptionKind.DELAY:
        delay = timedelta(minutes=event.delay_minutes)
        broken = _delay_breaks_plans(flight, delay, direction, arrive_by)
        if broken is None:
            summary = f"{flight.flight_number} is delayed {event.delay_minutes} minutes; plans hold"
            log_action(intent, ActionKind.HANDLED_DISRUPTION, summary, disruption_event=event)
            return DisruptionOutcome(itinerary, DisruptionResponse.NOTIFY_ONLY, direction, summary)
        reason = broken
    else:
        reason = f"{flight.flight_number} was cancelled"

    rules = effective_rules(itinerary.policy, intent.billable_code)
    original = DisruptedBooking(
        cabin=Cabin(direction[0].cabin),
        price=sum((leg.price for leg in direction), Decimal("0")),
    )
    evaluations = evaluate_options(
        _alternatives(direction, flight), intent.traveler.seniority, rules, now.date(), original
    )
    decision = decide_direction(
        rank(evaluations, intent.traveler, arrive_by=arrive_by),
        approval_rules(itinerary.policy),
    )
    if decision.kind == DecisionKind.AUTO_BOOK:
        summary = f"{reason}; rebooked automatically: {decision.reasoning}"
        rebooked = rebook_itinerary(
            itinerary, direction, list(decision.chosen.evaluation.option.legs), now, summary
        )
        log_action(intent, ActionKind.HANDLED_DISRUPTION, summary, disruption_event=event)
        return DisruptionOutcome(
            itinerary, DisruptionResponse.REBOOKED, direction, summary, decision, rebooked
        )
    summary = f"{reason}; traveler needs to choose: {decision.reasoning}"
    log_action(intent, ActionKind.HANDLED_DISRUPTION, summary, disruption_event=event)
    return DisruptionOutcome(
        itinerary, DisruptionResponse.NEEDS_TRAVELER, direction, summary, decision
    )


@transaction.atomic
def process_event(event: DisruptionEvent, now: datetime) -> list[DisruptionOutcome]:
    """Respond to a disruption for every active itinerary on the affected flight."""
    if event.kind == DisruptionKind.CANCELLATION:
        Flight.objects.filter(pk=event.flight_id).update(seats_left=0)
    affected = Itinerary.objects.filter(flights=event.flight, status=ItineraryStatus.ACTIVE)
    outcomes = [_respond(itinerary, event, now) for itinerary in affected]
    event.processed_at = now
    event.save(update_fields=["processed_at", "updated_at"])
    return outcomes
