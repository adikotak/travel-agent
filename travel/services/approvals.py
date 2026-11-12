from datetime import datetime
from decimal import Decimal

from django.db import transaction

from travel.models import (
    ActionKind,
    Approval,
    ApprovalStatus,
    BookingIntent,
    BookingIntentStatus,
    Email,
    Flight,
    User,
)
from travel.services.actions import log_action


class ApprovalError(Exception):
    """An approval can't be requested or decided as asked."""


@transaction.atomic
def request_approval(booking_intent: BookingIntent, flights: list[Flight], reason: str) -> Approval:
    """Ask the traveler's manager to approve these exact flights at today's price."""
    approver = booking_intent.traveler.manager
    if approver is None:
        raise ApprovalError(f"{booking_intent.traveler} has no manager to approve travel")
    approval = Approval.objects.create(
        booking_intent=booking_intent,
        approver=approver,
        quoted_price=sum((f.price for f in flights), Decimal("0")),
        reason=reason,
    )
    approval.flights.set(flights)
    booking_intent.status = BookingIntentStatus.PENDING_APPROVAL
    booking_intent.save(update_fields=["status", "updated_at"])
    log_action(booking_intent, ActionKind.REQUESTED_APPROVAL, f"sent to {approver.email}: {reason}")
    return approval


@transaction.atomic
def record_decision(
    approval: Approval,
    decided_by: User,
    approved: bool,
    decision_email: Email,
    decided_at: datetime,
) -> Approval:
    """Record the approver's decision; only the assigned approver may decide, and only once."""
    if decided_by != approval.approver:
        raise ApprovalError(f"{decided_by.email} is not the approver for this request")
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalError(f"approval already {approval.status}")
    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decision_email = decision_email
    approval.decided_at = decided_at
    approval.save(update_fields=["status", "decision_email", "decided_at", "updated_at"])
    if not approved:
        intent = approval.booking_intent
        intent.status = BookingIntentStatus.OPEN
        intent.save(update_fields=["status", "updated_at"])
    return approval
