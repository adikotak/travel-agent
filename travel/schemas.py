from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from travel.models import Cabin


class TripConstraints(BaseModel):
    """The traveler's current requirements for a trip; stored on `BookingIntent.constraints`.

    `arrive_outbound_by` is local time at the destination (e.g. a client dinner);
    `notes` keeps context worth repeating back to the traveler, never policy input.
    """

    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    depart_date: date
    return_date: date | None = None
    arrive_outbound_by: datetime | None = None
    requested_cabin: Cabin | None = None
    notes: str = ""

    @model_validator(mode="after")
    def return_not_before_departure(self) -> "TripConstraints":
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("return_date is before depart_date")
        return self
