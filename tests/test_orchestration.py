from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic_ai.models.function import FunctionModel

from tests.factories import at, make_flight, make_user
from travel.agent.parse import parse_agent
from travel.models import (
    ApprovalStatus,
    BookingIntent,
    BookingIntentStatus,
    DisruptionEvent,
    DisruptionKind,
    EmailDirection,
    EmailThread,
    ItineraryStatus,
)
from travel.schemas import OfferedOption
from travel.services.disruptions import process_event
from travel.services.inbox import receive_email
from travel.services.trips import notify_disruption

NOW = at(0, 12)


pytestmark = pytest.mark.usefixtures("fixed_prose")


@pytest.fixture
def manager():
    return make_user(save=True, email="mgr@co.example", first_name="Morgan")


@pytest.fixture
def traveler(manager):
    return make_user(save=True, email="priya@co.example", first_name="Priya", manager=manager)


def send(sender, body, thread=None, subject="Trip"):
    return receive_email(sender.email, subject, body, NOW, thread=thread)


def last_outbound(thread: EmailThread):
    return thread.emails.filter(direction=EmailDirection.OUTBOUND).order_by("-pk").first()


def trip(days_out: int, **details):
    day = (NOW + timedelta(days=days_out)).date().isoformat()
    return {
        "kind": "trip-details",
        "origin": "SFO",
        "destination": "JFK",
        "depart_date": day,
        **details,
    }


@pytest.mark.django_db
class TestRequests:
    """New requests are clarified, booked, proposed, or escalated by the shared pipeline."""

    def test_unknown_sender_gets_canned_reply_and_no_trip(self, parses):
        """Mail from an unregistered address is answered without parsing or creating a trip."""
        thread = receive_email("stranger@else.example", "Trip", "Book me to Paris", NOW)
        assert "don't recognize this address" in last_outbound(thread).body
        assert not BookingIntent.objects.exists()

    def test_client_trip_asks_for_code_then_escalates_inside_contract_window(
        self, parses, traveler, manager
    ):
        """A client trip without a code gets a question; once ACME-001 is supplied, Acme's
        14-day window makes a 10-day-out trip need the manager's approval."""
        make_flight(origin="SFO", destination="JFK", days_out=10, price=Decimal("300"), save=True)
        parses.append(trip(10, is_client_billable=True))
        thread = send(traveler, "Need NYC on the 22nd for the Acme kickoff")
        assert "billable code" in last_outbound(thread).body

        parses.append({"kind": "trip-details", "billable_code": "acme-001"})
        send(traveler, "It's ACME-001", thread=thread)
        intent = BookingIntent.objects.get()
        approval = intent.approvals.get()
        assert intent.billable_code.code == "ACME-001"
        assert intent.status == BookingIntentStatus.PENDING_APPROVAL
        assert "14+ days ahead" in approval.reason
        assert approval.request_email.to_addresses == [manager.email]

        parses.append({"kind": "approval-decision", "approved": True})
        send(manager, "Approved", thread=approval.request_email.thread)
        intent.refresh_from_db()
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.APPROVED
        assert intent.status == BookingIntentStatus.BOOKED
        assert "Itinerary:" in last_outbound(thread).body
        assert last_outbound(thread).to_addresses == [traveler.email]

    def test_traveler_cannot_approve_own_trip(self, parses, traveler):
        """An approval reply from the traveler is refused; the approval stays pending."""
        make_flight(origin="SFO", destination="JFK", days_out=3, save=True)
        parses.append(trip(3))
        thread = send(traveler, "Need SFO to JFK in 3 days")
        approval = BookingIntent.objects.get().approvals.get()
        parses.append({"kind": "approval-decision", "approved": True})
        send(traveler, "I approve", thread=thread)
        approval.refresh_from_db()
        assert approval.status == ApprovalStatus.PENDING

    def test_split_offer_then_constraint_change_then_pick(self, parses, traveler):
        """A nonstop-preferring traveler gets a split offer (in-policy connection, over-budget
        nonstop); changing the date records a revision and re-offers; picking the in-policy
        option books it without approval."""
        traveler.prefers_nonstop = True
        traveler.save()
        for days_out in (14, 15):
            first = make_flight(
                origin="SFO",
                destination="DEN",
                days_out=days_out,
                hour=7,
                duration_minutes=150,
                price=Decimal("160"),
                save=True,
            )
            make_flight(
                origin="DEN",
                destination="JFK",
                departs_at=first.arrives_at + timedelta(hours=1),
                duration_minutes=200,
                price=Decimal("160"),
                save=True,
            )
            make_flight(
                origin="SFO",
                destination="JFK",
                days_out=days_out,
                hour=8,
                duration_minutes=330,
                price=Decimal("520"),
                save=True,
            )
        parses.append(trip(14))
        thread = send(traveler, "SFO to JFK on the 26th")
        offered = [OfferedOption.model_validate(o) for o in last_outbound(thread).options]
        assert [(o.price, o.can_book_now) for o in offered] == [
            (Decimal("320"), True),
            (Decimal("520"), False),
        ]

        parses.append(
            {"kind": "trip-details", "depart_date": (NOW + timedelta(days=15)).date().isoformat()}
        )
        send(traveler, "Actually the 27th", thread=thread)
        intent = BookingIntent.objects.get()
        assert intent.constraint_revisions[0]["constraints"]["depart_date"].endswith("26")
        offered = [OfferedOption.model_validate(o) for o in last_outbound(thread).options]
        assert len(offered) == 2

        parses.append({"kind": "option-selection", "option_numbers": [1]})
        send(traveler, "Option 1", thread=thread)
        intent.refresh_from_db()
        itinerary = intent.itineraries.get(status=ItineraryStatus.ACTIVE)
        assert intent.status == BookingIntentStatus.BOOKED
        assert itinerary.total_price == Decimal("320")
        assert all(
            leg.departs_at.date() == (NOW + timedelta(days=15)).date() for leg in itinerary.legs()
        )

    def test_trip_tag_in_new_thread_resumes_trip(self, parses, traveler):
        """A fresh email mentioning TRIP-<id> attaches to the existing trip instead of a new one."""
        make_flight(origin="SFO", destination="JFK", days_out=20, save=True)
        parses.append(trip(20))
        send(traveler, "SFO to JFK")
        intent = BookingIntent.objects.get()
        parses.append({"kind": "other", "summary": "asked about the trip"})
        new_thread = send(traveler, "Any update?", subject=f"Question about TRIP-{intent.pk}")
        assert new_thread.booking_intent == intent
        assert BookingIntent.objects.count() == 1


@pytest.mark.django_db
def test_disruption_rebooks_and_emails_traveler_unprompted(parses, traveler):
    """A cancellation on a booked trip rebooks within limits and emails the traveler on the
    original thread without them asking."""
    booked = make_flight(origin="SFO", destination="JFK", days_out=20, hour=9, save=True)
    replacement = make_flight(origin="SFO", destination="JFK", days_out=20, hour=13, save=True)
    parses.append(trip(20))
    thread = send(traveler, "SFO to JFK")
    intent = BookingIntent.objects.get()
    assert intent.itineraries.get().legs() == [booked]

    event = DisruptionEvent.objects.create(
        flight=booked, kind=DisruptionKind.CANCELLATION, occurred_at=NOW
    )
    [outcome] = process_event(event, NOW)
    email = notify_disruption(outcome, NOW)
    assert email.thread == thread
    assert email.to_addresses == [traveler.email]
    assert intent.itineraries.get(status=ItineraryStatus.ACTIVE).legs() == [replacement]


@pytest.mark.django_db
def test_failed_processing_stores_nothing(traveler):
    """If the parser fails mid-email, the inbound email, thread, and trip are all rolled back."""

    def fail(messages, info):
        raise RuntimeError("model unavailable")

    with parse_agent.override(model=FunctionModel(fail)), pytest.raises(RuntimeError):
        send(traveler, "SFO to JFK")
    assert not EmailThread.objects.exists()
    assert not BookingIntent.objects.exists()


@pytest.mark.django_db
def test_airline_restriction_filters_offered_options(parses, traveler):
    """'Only United' becomes a trip constraint: re-offered options contain no other airline,
    and the restriction is recorded as a revision like any other change."""
    for airline, price in (("UA", "380"), ("DL", "300"), ("AA", "310")):
        make_flight(
            origin="SFO",
            destination="JFK",
            days_out=20,
            airline=airline,
            flight_number=f"{airline}9",
            price=Decimal(price),
            save=True,
        )
    traveler.preferred_airlines = ["UA"]
    traveler.save()
    parses.append(trip(20))
    thread = send(traveler, "SFO to JFK")
    parses.append({"kind": "trip-details", "airlines": ["UA"]})
    send(traveler, "can you show me only united options", thread=thread)
    intent = BookingIntent.objects.get()
    assert intent.constraints["airlines"] == ["UA"]
    booked = intent.itineraries.filter(status=ItineraryStatus.ACTIVE).first()
    offered = [OfferedOption.model_validate(o) for o in last_outbound(thread).options]
    flights = booked.legs() if booked else []
    assert all(f.airline == "UA" for f in flights)
    assert all(label.split()[0] == "UA" for label in (o.label for o in offered))
