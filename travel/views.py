from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from travel.demo import reset, title_for
from travel.models import (
    DisruptionEvent,
    DisruptionKind,
    EmailThread,
    Flight,
    Itinerary,
    ItineraryStatus,
    User,
)
from travel.presenters import email_cards, initials, thread_rows
from travel.services.disruptions import process_event
from travel.services.inbox import receive_email
from travel.services.trips import notify_disruption

DELAY_PRESETS = [45, 180]


def _mailboxes() -> list[dict]:
    return [
        {"user": user, "title": title_for(user), "initials": initials(user.get_full_name())}
        for user in User.objects.filter(is_superuser=False).order_by("pk")
    ]


def _shell(request: HttpRequest, current: User | None, active: str) -> dict:
    return {
        "mailboxes": _mailboxes(),
        "current": current,
        "current_title": title_for(current) if current else "",
        "current_initials": initials(current.get_full_name()) if current else "",
        "active": active,
        "llm_configured": bool(settings.OPENAI_API_KEY),
        "agent_email": settings.AGENT_EMAIL,
    }


def index(request: HttpRequest) -> HttpResponse:
    first = User.objects.filter(is_superuser=False).order_by("pk").first()
    if first is None:
        return render(request, "travel/empty.html", _shell(request, None, "inbox"))
    username = request.session.get("mailbox", first.username)
    return redirect("mailbox", username=username)


def mailbox(request: HttpRequest, username: str, thread_id: int | None = None) -> HttpResponse:
    user = get_object_or_404(User, username=username)
    request.session["mailbox"] = username
    rows = thread_rows(user)
    selected = next((row.thread for row in rows if row.thread.pk == thread_id), None)
    if selected is None and thread_id is None and rows:
        selected = rows[0].thread
    context = {
        **_shell(request, user, "inbox"),
        "rows": rows,
        "selected": selected,
        "cards": email_cards(selected) if selected else [],
    }
    return render(request, "travel/mailbox.html", context)


def _examples(today) -> list[dict[str, str]]:
    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).strftime("%B %-d")

    return [
        {
            "label": "Domestic trip with a dinner",
            "subject": "NYC trip",
            "body": f"Hi! I need to fly from SFO to New York on {day(14)} and come back "
            f"{day(17)}. I have a client dinner at 7pm the night I land.",
        },
        {
            "label": "Client trip (no code yet)",
            "subject": "Acme kickoff",
            "body": f"Need to be in New York for the Acme kickoff on {day(10)}, flying "
            f"out of SFO, back on {day(12)}. This is billable to Acme.",
        },
        {
            "label": "Long haul, business",
            "subject": "London customer visit",
            "body": f"Please book me business class from JFK to London on {day(21)}, "
            f"returning {day(25)}.",
        },
    ]


def compose(request: HttpRequest, username: str) -> HttpResponse:
    user = get_object_or_404(User, username=username)
    if request.method == "POST":
        thread = receive_email(
            user.email, request.POST["subject"], request.POST["body"], timezone.now()
        )
        return redirect("thread", username=username, thread_id=thread.pk)
    context = {
        **_shell(request, user, "inbox"),
        "rows": thread_rows(user),
        "examples": _examples(timezone.now().date()),
    }
    return render(request, "travel/compose.html", context)


@require_POST
def reply(request: HttpRequest, username: str, thread_id: int) -> HttpResponse:
    user = get_object_or_404(User, username=username)
    thread = get_object_or_404(EmailThread, pk=thread_id)
    subject = thread.subject if thread.subject.startswith("Re:") else f"Re: {thread.subject}"
    receive_email(user.email, subject, request.POST["body"], timezone.now(), thread=thread)
    return redirect("thread", username=username, thread_id=thread_id)


def ops(request: HttpRequest) -> HttpResponse:
    itineraries = (
        Itinerary.objects.filter(status=ItineraryStatus.ACTIVE)
        .select_related("booking_intent__traveler")
        .order_by("pk")
    )
    rows = [{"itinerary": itinerary, "legs": itinerary.legs()} for itinerary in itineraries]
    events = DisruptionEvent.objects.select_related("flight").order_by("-pk")[:10]
    current = User.objects.filter(username=request.session.get("mailbox")).first()
    context = {
        **_shell(request, current, "ops"),
        "rows": rows,
        "events": events,
        "delays": DELAY_PRESETS,
    }
    return render(request, "travel/ops.html", context)


@require_POST
def disrupt(request: HttpRequest, flight_id: int) -> HttpResponse:
    flight = get_object_or_404(Flight, pk=flight_id)
    now = timezone.now()
    delay = request.POST.get("delay_minutes")
    event = DisruptionEvent.objects.create(
        flight=flight,
        kind=DisruptionKind.DELAY if delay else DisruptionKind.CANCELLATION,
        delay_minutes=int(delay) if delay else None,
        occurred_at=now,
    )
    for outcome in process_event(event, now):
        notify_disruption(outcome, now)
    return redirect("ops")


@require_POST
def reset_demo(request: HttpRequest) -> HttpResponse:
    reset(timezone.now().date())
    request.session.pop("mailbox", None)
    return redirect("index")
