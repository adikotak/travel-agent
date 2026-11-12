from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from tests.factories import make_flight, make_user
from travel.models import (
    BookingIntent,
    BookingIntentStatus,
    DisruptionEvent,
    EmailDirection,
    ItineraryStatus,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixed_prose")]


@pytest.fixture
def traveler():
    manager = make_user(save=True, email="mgr@co.example", first_name="Morgan")
    return make_user(save=True, email="priya@co.example", first_name="Priya", manager=manager)


def booked_trip(client, parses, traveler):
    day = timezone.now().date() + timedelta(days=20)
    flight = make_flight(
        origin="SFO",
        destination="JFK",
        departs_at=timezone.now().replace(hour=9, minute=0) + timedelta(days=20),
        save=True,
    )
    parses.append(
        {
            "kind": "trip-details",
            "origin": "SFO",
            "destination": "JFK",
            "depart_date": day.isoformat(),
        }
    )
    client.post(
        reverse("compose", args=[traveler.username]),
        {"subject": "NYC trip", "body": "SFO to JFK please"},
    )
    thread = BookingIntent.objects.get().threads.get()
    parses.append({"kind": "option-selection", "option_numbers": [1]})
    client.post(reverse("reply", args=[traveler.username, thread.pk]), {"body": "Option 1"})
    return flight


def test_index_redirects_to_first_mailbox(client, traveler):
    """The landing page opens the first demo user's mailbox."""
    response = client.get(reverse("index"))
    assert response.status_code == 302
    assert response.url == reverse("mailbox", args=[traveler.manager.username])


def test_compose_runs_agent_and_shows_thread(client, parses, traveler):
    """Sending a new email processes it and lands on the thread with the agent's reply."""
    booked_trip(client, parses, traveler)
    intent = BookingIntent.objects.get()
    thread = intent.threads.get()
    page = client.get(reverse("thread", args=[traveler.username, thread.pk]))
    assert page.status_code == 200
    assert b"SFO to JFK please" in page.content
    assert b"Itinerary</p>" in page.content
    assert intent.itineraries.get().legs()[0].flight_number.encode() in page.content
    assert f"TRIP-{intent.pk}".encode() in page.content


def test_mailbox_only_lists_own_threads(client, parses, traveler):
    """Another user's mailbox doesn't show the traveler's private thread."""
    booked_trip(client, parses, traveler)
    other = make_user(save=True, email="sam@co.example")
    page = client.get(reverse("mailbox", args=[other.username]))
    assert b"NYC trip" not in page.content


def test_cancelling_flight_from_control_panel_emails_traveler(client, parses, traveler):
    """Cancelling a booked flight records the event, reacts, and emails the traveler."""
    flight = booked_trip(client, parses, traveler)
    thread = BookingIntent.objects.get().threads.get()
    outbound = thread.emails.filter(direction=EmailDirection.OUTBOUND)
    assert outbound.count() == 2
    response = client.post(reverse("disrupt", args=[flight.pk]))
    assert response.status_code == 302
    assert DisruptionEvent.objects.get().processed_at is not None
    assert outbound.count() == 3
    assert outbound.order_by("-pk").first().to_addresses == [traveler.email]


def test_control_panel_lists_active_itineraries(client, parses, traveler):
    """Booked trips appear in disruption control with their flights."""
    flight = booked_trip(client, parses, traveler)
    assert BookingIntent.objects.get().itineraries.get().status == ItineraryStatus.ACTIVE
    page = client.get(reverse("ops"))
    assert flight.flight_number.encode() in page.content


def request_split_offer(client, parses, traveler):
    """A nonstop-preferring traveler gets an in-policy connection and an over-budget nonstop."""
    traveler.prefers_nonstop = True
    traveler.save()
    departs = timezone.now().replace(hour=7, minute=0) + timedelta(days=20)
    first = make_flight(
        origin="SFO",
        destination="DEN",
        departs_at=departs,
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
        departs_at=departs + timedelta(hours=1),
        duration_minutes=330,
        price=Decimal("520"),
        save=True,
    )
    parses.append(
        {
            "kind": "trip-details",
            "origin": "SFO",
            "destination": "JFK",
            "depart_date": departs.date().isoformat(),
        }
    )
    client.post(
        reverse("compose", args=[traveler.username]),
        {"subject": "NYC", "body": "SFO to JFK"},
    )
    return BookingIntent.objects.get()


def test_options_email_reads_like_email_with_cabin(client, parses, traveler):
    """Offered options render as email tables with a cabin column, split into book-now and
    needs-approval, with no in-page selection controls: the traveler replies by email."""
    intent = request_split_offer(client, parses, traveler)
    page = client.get(reverse("thread", args=[traveler.username, intent.threads.get().pk]))
    assert b"Can book now (within policy)" in page.content
    assert b"Needs manager approval" in page.content
    assert b'<th class="px-3 py-2 font-medium">Cabin</th>' in page.content
    assert b'type="radio"' not in page.content
    assert b'value="approve"' not in page.content


def test_typed_reply_picks_option(client, parses, traveler):
    """Replying by email with an option number books it through the agent."""
    intent = request_split_offer(client, parses, traveler)
    thread = intent.threads.get()
    parses.append({"kind": "option-selection", "option_numbers": [1]})
    client.post(reverse("reply", args=[traveler.username, thread.pk]), {"body": "Option 1 please"})
    intent.refresh_from_db()
    assert intent.status == BookingIntentStatus.BOOKED
