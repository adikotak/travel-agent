from django.conf import settings
from django.db.models import Prefetch
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from travel.demo import reset, title_for
from travel.models import (
    DisruptionEvent,
    DisruptionKind,
    Email,
    EmailThread,
    Flight,
    Itinerary,
    ItineraryStatus,
    User,
)
from travel.services.disruptions import process_event
from travel.services.inbox import receive_email
from travel.services.trips import notify_disruption

DELAY_PRESETS = [45, 180]


def _mailboxes() -> list[dict]:
    return [
        {"user": user, "title": title_for(user)}
        for user in User.objects.filter(is_superuser=False).order_by("pk")
    ]


def _threads_for(user: User) -> list[EmailThread]:
    """Threads where the user sent or received mail, newest activity first."""
    threads = EmailThread.objects.prefetch_related(
        Prefetch("emails", queryset=Email.objects.order_by("sent_at", "pk"))
    ).select_related("booking_intent")
    mine = []
    for thread in threads:
        emails = list(thread.emails.all())
        if any(e.from_address == user.email or user.email in e.to_addresses for e in emails):
            thread.latest_email = emails[-1]
            mine.append(thread)
    return sorted(mine, key=lambda t: t.latest_email.pk, reverse=True)


def _base_context(user: User) -> dict:
    return {
        "mailboxes": _mailboxes(),
        "current": user,
        "llm_configured": bool(settings.OPENAI_API_KEY),
    }


def index(request: HttpRequest) -> HttpResponse:
    first = User.objects.filter(is_superuser=False).order_by("pk").first()
    if first is None:
        return render(request, "travel/empty.html")
    return redirect("mailbox", username=first.username)


def mailbox(request: HttpRequest, username: str, thread_id: int | None = None) -> HttpResponse:
    user = get_object_or_404(User, username=username)
    threads = _threads_for(user)
    selected = next((t for t in threads if t.pk == thread_id), None)
    if selected is None and thread_id is None and threads:
        selected = threads[0]
    intent = selected.booking_intent if selected else None
    context = {
        **_base_context(user),
        "threads": threads,
        "selected": selected,
        "intent": intent,
        "itinerary": intent.itineraries.filter(status=ItineraryStatus.ACTIVE).first()
        if intent
        else None,
        "actions": intent.actions.order_by("created_at", "pk") if intent else [],
        "approvals": intent.approvals.order_by("created_at") if intent else [],
    }
    return render(request, "travel/mailbox.html", context)


def compose(request: HttpRequest, username: str) -> HttpResponse:
    user = get_object_or_404(User, username=username)
    if request.method == "POST":
        thread = receive_email(
            user.email, request.POST["subject"], request.POST["body"], timezone.now()
        )
        return redirect("thread", username=username, thread_id=thread.pk)
    return render(request, "travel/compose.html", _base_context(user))


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
    return render(
        request,
        "travel/ops.html",
        {
            "mailboxes": _mailboxes(),
            "rows": rows,
            "events": events,
            "delays": DELAY_PRESETS,
            "llm_configured": bool(settings.OPENAI_API_KEY),
        },
    )


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
    return redirect("index")
