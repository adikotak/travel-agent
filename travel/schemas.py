from datetime import UTC, date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from travel.models import Cabin


class TripConstraints(BaseModel):
    """The traveler's current requirements for a trip; stored on `BookingIntent.constraints`.

    `arrive_outbound_by` is local wall-clock time at the destination (e.g. a client
    dinner), stored with UTC tzinfo like flight times. `notes` keeps context worth
    repeating back to the traveler, never policy input.
    """

    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    return_date: date | None = None
    arrive_outbound_by: datetime | None = None
    requested_cabin: Cabin | None = None
    airlines: list[str] = Field(default_factory=list)
    excluded_airlines: list[str] = Field(default_factory=list)
    nonstop_only: bool = False
    outbound_depart_after: time | None = None
    outbound_depart_before: time | None = None
    return_depart_after: time | None = None
    return_depart_before: time | None = None
    max_price_usd: int | None = None
    is_client_billable: bool = False
    notes: str = ""

    @field_validator("arrive_outbound_by")
    @classmethod
    def as_local_wall_clock(cls, value: datetime | None) -> datetime | None:
        return value.replace(tzinfo=UTC) if value is not None else None

    @model_validator(mode="after")
    def return_not_before_departure(self) -> "TripConstraints":
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("return_date is before depart_date")
        return self


class OfferedOption(BaseModel):
    """One numbered option as offered in an outbound email; stored in `Email.options`."""

    number: int
    direction: str
    label: str
    flight_ids: list[int]
    price: Decimal
    can_book_now: bool
    reasons: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)
