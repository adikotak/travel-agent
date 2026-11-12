from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from travel.models import (
    ActionKind,
    BookingIntent,
    BookingIntentStatus,
    Flight,
    Itinerary,
    ItineraryStatus,
    TravelPolicy,
)
from travel.services.actions import log_action


class SoldOutError(Exception):
    """A flight lost its last seat between search and booking."""


def _hold_seats(flights: list[Flight]) -> None:
    for flight in Flight.objects.select_for_update().filter(pk__in=[f.pk for f in flights]):
        if flight.seats_left == 0:
            raise SoldOutError(str(flight))
    Flight.objects.filter(pk__in=[f.pk for f in flights]).update(seats_left=F("seats_left") - 1)


@transaction.atomic
def book_itinerary(
    booking_intent: BookingIntent,
    flights: list[Flight],
    policy: TravelPolicy,
    booked_at: datetime,
    reasoning: str,
) -> Itinerary:
    """Book `flights` for the intent, taking one seat on each; fails whole if any is sold out."""
    _hold_seats(flights)
    itinerary = Itinerary.objects.create(
        booking_intent=booking_intent,
        total_price=sum((f.price for f in flights), Decimal("0")),
        policy=policy,
        booked_at=booked_at,
    )
    itinerary.flights.set(flights)
    booking_intent.status = BookingIntentStatus.BOOKED
    booking_intent.save(update_fields=["status", "updated_at"])
    log_action(booking_intent, ActionKind.BOOKED, reasoning)
    return itinerary


@transaction.atomic
def rebook_itinerary(
    itinerary: Itinerary,
    replaced: list[Flight],
    replacements: list[Flight],
    booked_at: datetime,
    reasoning: str,
) -> Itinerary:
    """Replace some legs of an active itinerary, keeping the rest and the original policy.

    Seats are taken only on the replacement legs; the old itinerary is cancelled
    so the trip's history stays visible.
    """
    _hold_seats(replacements)
    kept = [f for f in itinerary.legs() if f not in replaced]
    flights = kept + replacements
    itinerary.status = ItineraryStatus.CANCELLED
    itinerary.save(update_fields=["status", "updated_at"])
    rebooked = Itinerary.objects.create(
        booking_intent=itinerary.booking_intent,
        total_price=sum((f.price for f in flights), Decimal("0")),
        policy=itinerary.policy,
        booked_at=booked_at,
    )
    rebooked.flights.set(flights)
    log_action(itinerary.booking_intent, ActionKind.BOOKED, reasoning)
    return rebooked
