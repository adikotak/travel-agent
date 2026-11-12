from django.contrib.auth.models import AbstractUser
from django.db import models


class TimestampedModel(models.Model):
    """Abstract base adding creation and update timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Seniority(models.TextChoices):
    """Employee seniority levels the travel policy can key off."""

    INDIVIDUAL_CONTRIBUTOR = "individual-contributor", "Individual Contributor"
    MANAGER = "manager", "Manager"
    DIRECTOR = "director", "Director"
    VICE_PRESIDENT = "vice-president", "Vice President"
    EXECUTIVE = "executive", "Executive"


class SeatPreference(models.TextChoices):
    """Traveler seat preference."""

    NO_PREFERENCE = "no-preference", "No Preference"
    WINDOW = "window", "Window"
    AISLE = "aisle", "Aisle"


class Cabin(models.TextChoices):
    """Cabin class of a fare."""

    ECONOMY = "economy", "Economy"
    PREMIUM_ECONOMY = "premium-economy", "Premium Economy"
    BUSINESS = "business", "Business"
    FIRST = "first", "First"


class BookingIntentStatus(models.TextChoices):
    """Lifecycle status of a booking intent."""

    OPEN = "open", "Open"
    PENDING_APPROVAL = "pending-approval", "Pending Approval"
    BOOKED = "booked", "Booked"
    CANCELLED = "cancelled", "Cancelled"


class EmailDirection(models.TextChoices):
    """Whether an email was received by or sent from the agent."""

    INBOUND = "inbound", "Inbound"
    OUTBOUND = "outbound", "Outbound"


class ApprovalStatus(models.TextChoices):
    """Decision state of an approval request."""

    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


class ItineraryStatus(models.TextChoices):
    """Lifecycle status of a booked itinerary."""

    ACTIVE = "active", "Active"
    CANCELLED = "cancelled", "Cancelled"


class DisruptionKind(models.TextChoices):
    """Type of flight disruption."""

    CANCELLATION = "cancellation", "Cancellation"
    DELAY = "delay", "Delay"


class ActionKind(models.TextChoices):
    """Agent actions recorded in the action log."""

    PARSED_REQUEST = "parsed-request", "Parsed Request"
    UPDATED_CONSTRAINTS = "updated-constraints", "Updated Constraints"
    PROPOSED_OPTIONS = "proposed-options", "Proposed Options"
    REQUESTED_APPROVAL = "requested-approval", "Requested Approval"
    BOOKED = "booked", "Booked"
    CANCELLED = "cancelled", "Cancelled"
    HANDLED_DISRUPTION = "handled-disruption", "Handled Disruption"
    SENT_EMAIL = "sent-email", "Sent Email"


class User(AbstractUser):
    """An employee who can request travel or approve it."""

    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )
    seniority = models.CharField(
        max_length=32,
        choices=Seniority.choices,
        default=Seniority.INDIVIDUAL_CONTRIBUTOR,
    )
    seat_preference = models.CharField(
        max_length=32,
        choices=SeatPreference.choices,
        default=SeatPreference.NO_PREFERENCE,
    )
    prefers_nonstop = models.BooleanField(default=False)
    avoids_red_eyes = models.BooleanField(default=False)
    preferred_airlines = models.JSONField(default=list, blank=True)
    frequent_flyer_numbers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Airline code -> loyalty number, e.g. {'UA': 'MP123456'}.",
    )


class TravelPolicy(TimestampedModel):
    """A versioned travel policy, including the rules that decide approval."""

    version = models.PositiveIntegerField(unique=True)
    rules = models.JSONField(default=dict)
    approval_rules = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Travel policy v{self.version}"

    class Meta:
        verbose_name_plural = "travel policies"
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="one_active_travel_policy",
            ),
        ]


class BillableCode(TimestampedModel):
    """A code that travel is charged to; client codes are billed back to the client."""

    code = models.CharField(max_length=32, unique=True)
    client_name = models.CharField(max_length=255, blank=True)
    is_client_billable = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    policy_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Client contract rules, merged over the company policy rules "
            "for trips billed to this code."
        ),
    )

    def __str__(self) -> str:
        return self.code


RED_EYE_START_HOUR = 21
RED_EYE_END_HOUR = 5


class Flight(TimestampedModel):
    """One purchasable fare on a scheduled flight; each cabin on a flight is its own row.

    `departs_at` / `arrives_at` are local wall-clock times at their airports
    (stored with UTC tzinfo, since we keep no airport time zones), so they can be
    compared with a traveler's local deadlines and with other legs at the same
    airport. `duration_minutes` is the authoritative elapsed time.
    """

    airline = models.CharField(max_length=3)
    flight_number = models.CharField(max_length=8)
    origin = models.CharField(max_length=3)
    destination = models.CharField(max_length=3)
    departs_at = models.DateTimeField()
    arrives_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField()
    cabin = models.CharField(max_length=32, choices=Cabin.choices)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_refundable = models.BooleanField(default=False)
    seats_left = models.PositiveIntegerField()

    @property
    def is_red_eye(self) -> bool:
        hour = self.departs_at.hour
        return hour >= RED_EYE_START_HOUR or hour < RED_EYE_END_HOUR

    def __str__(self) -> str:
        route = f"{self.origin}-{self.destination}"
        return f"{self.flight_number} {route} {self.departs_at:%Y-%m-%d %H:%M} ({self.cabin})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["flight_number", "departs_at", "cabin"],
                name="unique_flight_fare",
            ),
        ]
        indexes = [models.Index(fields=["origin", "destination", "departs_at"])]


class BookingIntent(TimestampedModel):
    """A traveler's trip request, tracked across every email thread that references it."""

    traveler = models.ForeignKey(User, on_delete=models.PROTECT, related_name="booking_intents")
    billable_code = models.ForeignKey(
        BillableCode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="booking_intents",
    )
    constraints = models.JSONField(default=dict)
    constraint_revisions = models.JSONField(
        default=list,
        blank=True,
        help_text="Prior constraint snapshots, each with the email that changed them.",
    )
    status = models.CharField(
        max_length=32,
        choices=BookingIntentStatus.choices,
        default=BookingIntentStatus.OPEN,
    )

    def __str__(self) -> str:
        return f"TRIP-{self.pk}"


class EmailThread(TimestampedModel):
    """An email conversation; several threads may reference the same booking intent."""

    booking_intent = models.ForeignKey(
        BookingIntent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="threads",
    )
    subject = models.CharField(max_length=998)

    def __str__(self) -> str:
        return self.subject


class Email(TimestampedModel):
    """A single message in a thread; outbound messages record the options they offered."""

    thread = models.ForeignKey(EmailThread, on_delete=models.CASCADE, related_name="emails")
    direction = models.CharField(max_length=16, choices=EmailDirection.choices)
    from_address = models.EmailField()
    to_addresses = models.JSONField(default=list)
    subject = models.CharField(max_length=998)
    body = models.TextField()
    sent_at = models.DateTimeField()
    options = models.JSONField(
        default=list,
        blank=True,
        help_text="Numbered options shown in an outbound email: flight IDs and quoted price.",
    )
    card = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured content of an agent email (purpose, prose, questions, itinerary) "
        "for rich rendering in the inbox.",
    )

    def __str__(self) -> str:
        return f"{self.direction} {self.from_address}: {self.subject}"

    class Meta:
        ordering = ["sent_at"]


class Approval(TimestampedModel):
    """A request for a manager to approve specific flights at a quoted price."""

    booking_intent = models.ForeignKey(
        BookingIntent, on_delete=models.CASCADE, related_name="approvals"
    )
    approver = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approvals_to_decide")
    flights = models.ManyToManyField(Flight, related_name="approvals")
    quoted_price = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    request_email = models.ForeignKey(
        Email,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_requests",
    )
    decision_email = models.ForeignKey(
        Email,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)


class Itinerary(TimestampedModel):
    """The flights actually booked for a booking intent, under a specific policy version."""

    booking_intent = models.ForeignKey(
        BookingIntent, on_delete=models.PROTECT, related_name="itineraries"
    )
    # Segment order is departure order, so no explicit position is stored.
    flights = models.ManyToManyField(Flight, related_name="itineraries")
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    policy = models.ForeignKey(TravelPolicy, on_delete=models.PROTECT, related_name="itineraries")
    status = models.CharField(
        max_length=16,
        choices=ItineraryStatus.choices,
        default=ItineraryStatus.ACTIVE,
    )
    booked_at = models.DateTimeField()

    def legs(self) -> list[Flight]:
        return list(self.flights.order_by("departs_at"))

    class Meta:
        verbose_name_plural = "itineraries"


class DisruptionEvent(TimestampedModel):
    """A cancellation or delay reported for a flight."""

    flight = models.ForeignKey(Flight, on_delete=models.PROTECT, related_name="disruptions")
    kind = models.CharField(max_length=16, choices=DisruptionKind.choices)
    delay_minutes = models.PositiveIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(kind=DisruptionKind.DELAY, delay_minutes__isnull=False)
                    | models.Q(kind=DisruptionKind.CANCELLATION, delay_minutes__isnull=True)
                ),
                name="delay_minutes_only_for_delays",
            ),
        ]


class ActionLog(TimestampedModel):
    """An agent decision or side effect, with the reasoning behind it."""

    booking_intent = models.ForeignKey(
        BookingIntent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="actions",
    )
    email = models.ForeignKey(
        Email,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
    )
    disruption_event = models.ForeignKey(
        DisruptionEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions",
    )
    action = models.CharField(max_length=32, choices=ActionKind.choices)
    reasoning = models.TextField()

    class Meta:
        ordering = ["created_at"]
