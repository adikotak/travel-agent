from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

from travel.models import Cabin, Flight, Seniority, TravelPolicy, User
from travel.search import TravelOption

TODAY = date(2026, 11, 12)
_flight_numbers = count(100)


def at(days_out: int, hour: int, minute: int = 0) -> datetime:
    """A local wall-clock time `days_out` days after TODAY."""
    day = TODAY + timedelta(days=days_out)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def make_flight(
    *,
    days_out: int = 30,
    hour: int = 9,
    duration_minutes: int = 120,
    save: bool = False,
    **overrides: Any,
) -> Flight:
    departs_at = overrides.pop("departs_at", at(days_out, hour))
    defaults: dict[str, Any] = {
        "airline": "UA",
        "flight_number": f"UA{next(_flight_numbers)}",
        "origin": "SFO",
        "destination": "LAX",
        "departs_at": departs_at,
        "arrives_at": departs_at + timedelta(minutes=duration_minutes),
        "duration_minutes": duration_minutes,
        "cabin": Cabin.ECONOMY,
        "price": Decimal("200"),
        "seats_left": 9,
    }
    defaults.update(overrides)
    flight = Flight(**defaults)
    if save:
        flight.save()
    return flight


def nonstop(**overrides: Any) -> TravelOption:
    return TravelOption(legs=(make_flight(**overrides),))


def make_user(save: bool = False, **overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "username": f"user{next(_flight_numbers)}",
        "seniority": Seniority.INDIVIDUAL_CONTRIBUTOR,
    }
    defaults.update(overrides)
    user = User(**defaults)
    if save:
        user.save()
    return user


def active_policy() -> TravelPolicy:
    return TravelPolicy.objects.get(is_active=True)
