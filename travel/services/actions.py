import logging

from travel.models import ActionKind, ActionLog, BookingIntent, DisruptionEvent, Email

logger = logging.getLogger(__name__)


def log_action(
    booking_intent: BookingIntent | None,
    action: ActionKind,
    reasoning: str,
    *,
    email: Email | None = None,
    disruption_event: DisruptionEvent | None = None,
) -> ActionLog:
    """Record an agent decision or side effect with the reasoning shown in the inbox UI."""
    logger.info(
        "agent.action",
        extra={
            "booking_intent_id": booking_intent.pk if booking_intent else None,
            "action": action,
        },
    )
    return ActionLog.objects.create(
        booking_intent=booking_intent,
        action=action,
        reasoning=reasoning,
        email=email,
        disruption_event=disruption_event,
    )
