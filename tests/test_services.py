from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import TODAY, active_policy, at, make_flight, make_user
from travel.models import (
    ActionKind,
    ApprovalStatus,
    BookingIntent,
    BookingIntentStatus,
    DisruptionEvent,
    DisruptionKind,
    Email,
    EmailDirection,
    EmailThread,
    Flight,
    Itinerary,
    ItineraryStatus,
)
from travel.schemas import TripConstraints
from travel.services.approvals import ApprovalError, record_decision, request_approval
from travel.services.booking import SoldOutError, book_itinerary
from travel.services.disruptions import DisruptionResponse, process_event

NOW = at(0, 12)


@pytest.fixture
def manager():
    return make_user(save=True, email="manager@example.com")


@pytest.fixture
def intent(manager):
    traveler = make_user(save=True, email="traveler@example.com", manager=manager)
    constraints = TripConstraints(
        origin="SFO", destination="JFK", depart_date=TODAY + timedelta(days=10)
    )
    return BookingIntent.objects.create(
        traveler=traveler, constraints=constraints.model_dump(mode="json")
    )


def make_email(sender) -> Email:
    thread = EmailThread.objects.create(subject="Trip")
    return Email.objects.create(
        thread=thread,
        direction=EmailDirection.INBOUND,
        from_address=sender.email,
        subject="Re: Trip",
        body="Approved",
        sent_at=NOW,
    )


@pytest.mark.django_db
class TestBooking:
    """Booking takes a seat on every leg atomically."""

    def test_books_and_takes_seats(self, intent):
        """A successful booking creates an active itinerary, takes one seat per leg, marks the
        intent booked, and logs why."""
        flight = make_flight(origin="SFO", destination="JFK", seats_left=3, save=True)
        itinerary = book_itinerary(intent, [flight], active_policy(), NOW, "in policy")
        flight.refresh_from_db()
        intent.refresh_from_db()
        assert itinerary.status == ItineraryStatus.ACTIVE
        assert itinerary.total_price == flight.price
        assert flight.seats_left == 2
        assert intent.status == BookingIntentStatus.BOOKED
        assert intent.actions.get().action == ActionKind.BOOKED

    def test_sold_out_leg_books_nothing(self, intent):
        """If any leg has no seats, no itinerary is created and no other leg loses a seat."""
        open_leg = make_flight(origin="SFO", destination="ORD", seats_left=3, save=True)
        full_leg = make_flight(origin="ORD", destination="JFK", seats_left=0, save=True)
        with pytest.raises(SoldOutError):
            book_itinerary(intent, [open_leg, full_leg], active_policy(), NOW, "in policy")
        open_leg.refresh_from_db()
        assert open_leg.seats_left == 3
        assert not Itinerary.objects.exists()


@pytest.mark.django_db
class TestApprovals:
    """Approval requests pin flights and price; only the manager decides, once."""

    def test_request_pins_flights_and_price(self, intent, manager):
        """The request goes to the traveler's manager at the current total price and marks
        the intent pending approval."""
        flights = [
            make_flight(price=Decimal("300"), save=True),
            make_flight(price=Decimal("250"), save=True),
        ]
        approval = request_approval(intent, flights, "inside the 14-day window")
        intent.refresh_from_db()
        assert approval.approver == manager
        assert approval.quoted_price == Decimal("550")
        assert set(approval.flights.all()) == set(flights)
        assert intent.status == BookingIntentStatus.PENDING_APPROVAL

    def test_request_without_manager_fails(self, intent):
        """A traveler with no manager can't be routed for approval, so nothing is created."""
        intent.traveler.manager = None
        intent.traveler.save()
        with pytest.raises(ApprovalError):
            request_approval(intent, [make_flight(save=True)], "over budget")
        assert not intent.approvals.exists()

    def test_only_approver_can_decide(self, intent):
        """An approval reply from anyone but the assigned manager is refused and changes nothing."""
        approval = request_approval(intent, [make_flight(save=True)], "over budget")
        imposter = intent.traveler
        with pytest.raises(ApprovalError):
            record_decision(approval, imposter, True, make_email(imposter), NOW)
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.PENDING

    def test_cannot_decide_twice(self, intent, manager):
        """Once decided, a second reply can't flip the decision."""
        approval = request_approval(intent, [make_flight(save=True)], "over budget")
        record_decision(approval, manager, True, make_email(manager), NOW)
        with pytest.raises(ApprovalError):
            record_decision(approval, manager, False, make_email(manager), NOW)

    def test_rejection_reopens_intent(self, intent, manager):
        """A rejected approval returns the intent to open so the traveler can pick again."""
        approval = request_approval(intent, [make_flight(save=True)], "over budget")
        record_decision(approval, manager, False, make_email(manager), NOW)
        intent.refresh_from_db()
        assert approval.status == ApprovalStatus.REJECTED
        assert intent.status == BookingIntentStatus.OPEN


@pytest.mark.django_db
class TestDisruptions:
    """Disruptions notify, rebook automatically, or hand the choice to the traveler."""

    DINNER = at(1, 19)

    @pytest.fixture
    def booked(self, intent):
        """A booked SFO->JFK trip tomorrow arriving 3pm, with a 7pm dinner deadline."""
        constraints = TripConstraints.model_validate(intent.constraints)
        constraints.depart_date = TODAY + timedelta(days=1)
        constraints.arrive_outbound_by = self.DINNER
        intent.constraints = constraints.model_dump(mode="json")
        intent.save()
        flight = make_flight(
            origin="SFO",
            destination="JFK",
            departs_at=at(1, 9),
            duration_minutes=360,
            price=Decimal("320"),
            save=True,
        )
        itinerary = book_itinerary(intent, [flight], active_policy(), NOW, "in policy")
        return itinerary, flight

    def fire(self, flight: Flight, kind: DisruptionKind, delay_minutes: int | None = None):
        event = DisruptionEvent.objects.create(
            flight=flight, kind=kind, delay_minutes=delay_minutes, occurred_at=NOW
        )
        return event, process_event(event, NOW)

    def test_small_delay_only_notifies(self, booked):
        """A 30-minute delay still lands before dinner, so the trip is untouched."""
        itinerary, flight = booked
        event, [outcome] = self.fire(flight, DisruptionKind.DELAY, 30)
        itinerary.refresh_from_db()
        assert outcome.response == DisruptionResponse.NOTIFY_ONLY
        assert itinerary.status == ItineraryStatus.ACTIVE
        assert event.processed_at == NOW

    def test_cancellation_rebooks_option_that_makes_deadline(self, booked):
        """The cheapest alternative lands after dinner; one $150 more lands in time and is within
        the $200 rebooking limit, so it is booked automatically."""
        itinerary, flight = booked
        make_flight(
            origin="SFO",
            destination="JFK",
            departs_at=at(1, 14, 30),
            duration_minutes=360,
            price=Decimal("320"),
            save=True,
        )
        on_time = make_flight(
            origin="SFO",
            destination="JFK",
            departs_at=at(1, 10),
            duration_minutes=360,
            price=Decimal("470"),
            save=True,
        )
        _, [outcome] = self.fire(flight, DisruptionKind.CANCELLATION)
        itinerary.refresh_from_db()
        flight.refresh_from_db()
        assert outcome.response == DisruptionResponse.REBOOKED
        assert outcome.rebooked_itinerary.legs() == [on_time]
        assert itinerary.status == ItineraryStatus.CANCELLED
        assert flight.seats_left == 0

    def test_cancellation_without_compliant_alternative_needs_traveler(self, booked):
        """The only alternative is $300 more, over the rebooking limit, so the traveler is asked
        and the original itinerary stays as the record."""
        itinerary, flight = booked
        make_flight(
            origin="SFO",
            destination="JFK",
            departs_at=at(1, 10),
            duration_minutes=360,
            price=Decimal("620"),
            save=True,
        )
        _, [outcome] = self.fire(flight, DisruptionKind.CANCELLATION)
        itinerary.refresh_from_db()
        assert outcome.response == DisruptionResponse.NEEDS_TRAVELER
        assert [r.evaluation.option.price for r in outcome.decision.needs_approval] == [
            Decimal("620")
        ]
        assert itinerary.status == ItineraryStatus.ACTIVE
