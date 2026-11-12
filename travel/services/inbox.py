import logging
import re
from datetime import datetime

from django.conf import settings
from django.db import transaction

from travel.models import BookingIntent, Email, EmailDirection, EmailThread, User
from travel.services.trips import handle_email

logger = logging.getLogger(__name__)

TRIP_TAG = re.compile(r"\bTRIP-(\d+)\b", re.IGNORECASE)
UNKNOWN_SENDER_REPLY = (
    "Hi,\n\nI only handle travel for registered employees, and I don't recognize this "
    "address. Please write from your company email.\n\n— Travel Agent"
)


def _tagged_intent(subject: str, body: str, sender: User) -> BookingIntent | None:
    """The sender's own trip referenced by a TRIP-<id> tag, so a new thread can resume it."""
    match = TRIP_TAG.search(f"{subject}\n{body}")
    if match is None:
        return None
    return BookingIntent.objects.filter(pk=int(match.group(1)), traveler=sender).first()


@transaction.atomic
def receive_email(
    from_address: str,
    subject: str,
    body: str,
    now: datetime,
    thread: EmailThread | None = None,
) -> EmailThread:
    """Accept an email sent to the agent and process it; returns the thread it landed on.

    All-or-nothing: if any step fails (e.g. the LLM call), nothing is stored, so
    the sender can simply resend instead of leaving a half-processed thread.
    """
    sender = User.objects.filter(email__iexact=from_address).first()
    if thread is None:
        intent = _tagged_intent(subject, body, sender) if sender else None
        thread = EmailThread.objects.create(subject=subject, booking_intent=intent)
    email = Email.objects.create(
        thread=thread,
        direction=EmailDirection.INBOUND,
        from_address=from_address,
        to_addresses=[settings.AGENT_EMAIL],
        subject=subject,
        body=body,
        sent_at=now,
    )
    logger.info("email.received", extra={"email_id": email.pk, "thread_id": thread.pk})
    if sender is None:
        Email.objects.create(
            thread=thread,
            direction=EmailDirection.OUTBOUND,
            from_address=settings.AGENT_EMAIL,
            to_addresses=[from_address],
            subject=f"Re: {subject}",
            body=UNKNOWN_SENDER_REPLY,
            sent_at=now,
        )
        return thread
    handle_email(email, sender, now)
    return thread
