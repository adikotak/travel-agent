from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from tests.factories import make_flight, make_user
from travel.models import BookingIntent, DisruptionEvent, EmailDirection, ItineraryStatus

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
    assert b"Itinerary:" in page.content
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
    assert outbound.count() == 1
    response = client.post(reverse("disrupt", args=[flight.pk]))
    assert response.status_code == 302
    assert DisruptionEvent.objects.get().processed_at is not None
    assert outbound.count() == 2
    assert outbound.order_by("-pk").first().to_addresses == [traveler.email]


def test_control_panel_lists_active_itineraries(client, parses, traveler):
    """Booked trips appear in disruption control with their flights."""
    flight = booked_trip(client, parses, traveler)
    assert BookingIntent.objects.get().itineraries.get().status == ItineraryStatus.ACTIVE
    page = client.get(reverse("ops"))
    assert flight.flight_number.encode() in page.content
