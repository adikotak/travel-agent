from dataclasses import dataclass
from datetime import date, time, timedelta
from decimal import Decimal

from travel.models import Cabin, Flight

MIN_CONNECTION = timedelta(minutes=45)
MAX_CONNECTION = timedelta(hours=6)


@dataclass(frozen=True)
class TravelOption:
    """One way to fly one direction of a trip: a nonstop or two connecting legs in one cabin."""

    legs: tuple[Flight, ...]

    @property
    def first_leg(self) -> Flight:
        return self.legs[0]

    @property
    def last_leg(self) -> Flight:
        return self.legs[-1]

    @property
    def cabin(self) -> Cabin:
        return Cabin(self.first_leg.cabin)

    @property
    def price(self) -> Decimal:
        return sum((leg.price for leg in self.legs), Decimal("0"))

    @property
    def stops(self) -> int:
        return len(self.legs) - 1

    @property
    def total_minutes(self) -> int:
        """Air time plus layovers; layovers are exact because both times are local to the hub."""
        layovers = sum(
            (later.departs_at - earlier.arrives_at for earlier, later in self.pairs()),
            timedelta(),
        )
        air_minutes = sum(leg.duration_minutes for leg in self.legs)
        return air_minutes + int(layovers.total_seconds() // 60)

    @property
    def airlines(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(leg.airline for leg in self.legs))

    @property
    def is_red_eye(self) -> bool:
        return self.first_leg.is_red_eye

    @property
    def flight_ids(self) -> list[int]:
        return [leg.pk for leg in self.legs]

    def pairs(self) -> list[tuple[Flight, Flight]]:
        return list(zip(self.legs, self.legs[1:], strict=False))


def find_options(origin: str, destination: str, on_date: date) -> list[TravelOption]:
    """All nonstop and one-stop options departing `origin` on `on_date` with seats available."""
    departures = list(
        Flight.objects.filter(origin=origin, departs_at__date=on_date, seats_left__gt=0)
    )
    options = [
        TravelOption(legs=(flight,)) for flight in departures if flight.destination == destination
    ]
    for first_leg in departures:
        if first_leg.destination == destination:
            continue
        connections = Flight.objects.filter(
            origin=first_leg.destination,
            destination=destination,
            cabin=first_leg.cabin,
            seats_left__gt=0,
            departs_at__gte=first_leg.arrives_at + MIN_CONNECTION,
            departs_at__lte=first_leg.arrives_at + MAX_CONNECTION,
        )
        options.extend(TravelOption(legs=(first_leg, second_leg)) for second_leg in connections)
    return options


@dataclass(frozen=True)
class SearchFilters:
    """Hard requirements the traveler stated for one direction; options failing any are hidden."""

    nonstop_only: bool = False
    depart_after: time | None = None
    depart_before: time | None = None
    max_price: Decimal | None = None
    airlines: tuple[str, ...] = ()
    excluded_airlines: tuple[str, ...] = ()

    def matches(self, option: TravelOption) -> bool:
        departs = option.first_leg.departs_at.time()
        return not (
            (self.nonstop_only and option.stops > 0)
            or (self.depart_after is not None and departs < self.depart_after)
            or (self.depart_before is not None and departs > self.depart_before)
            or (self.max_price is not None and option.price > self.max_price)
            or (self.airlines and not set(option.airlines) <= set(self.airlines))
            or set(option.airlines) & set(self.excluded_airlines)
        )

    def describe(self) -> list[str]:
        """The active requirements in words, for explaining an empty result."""
        parts = []
        if self.nonstop_only:
            parts.append("nonstop only")
        if self.depart_after is not None:
            parts.append(f"departing after {self.depart_after:%H:%M}")
        if self.depart_before is not None:
            parts.append(f"departing before {self.depart_before:%H:%M}")
        if self.max_price is not None:
            parts.append(f"under ${self.max_price:,.0f}")
        if self.airlines:
            parts.append("only " + ", ".join(self.airlines))
        if self.excluded_airlines:
            parts.append("not " + ", ".join(self.excluded_airlines))
        return parts
