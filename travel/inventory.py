"""Mock flight inventory: broad seeded-random schedules plus fixed daily anchor flights.

The random schedules make any reasonable live request bookable. The anchors
guarantee the policy conflicts the demo relies on exist on every day:
SFO<->JFK (nonstop over the short-haul cap, cheaper connection via DEN, and a
spread of arrival times for disruption rebooking) and JFK<->LHR (BA vs VS
business within the lowest-logical-fare margin).
"""

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from travel.models import Cabin, Flight

DOMESTIC_MINUTES = {
    ("SFO", "LAX"): 85,
    ("SFO", "SEA"): 125,
    ("SFO", "DEN"): 150,
    ("SFO", "ORD"): 250,
    ("SFO", "BOS"): 345,
    ("SFO", "ATL"): 290,
    ("LAX", "JFK"): 320,
    ("LAX", "ORD"): 245,
    ("SEA", "JFK"): 315,
    ("JFK", "BOS"): 75,
    ("JFK", "ORD"): 150,
    ("JFK", "MIA"): 185,
    ("JFK", "ATL"): 145,
    ("ORD", "DEN"): 155,
    ("ORD", "BOS"): 140,
    ("ATL", "MIA"): 110,
    ("DEN", "JFK"): 210,
    ("DEN", "BOS"): 230,
    ("DFW", "JFK"): 210,
    ("DFW", "SFO"): 225,
    ("DFW", "ORD"): 150,
}
INTERNATIONAL_MINUTES = {
    ("BOS", "LHR"): 395,
    ("ORD", "LHR"): 470,
    ("SFO", "LHR"): 625,
    ("JFK", "CDG"): 445,
    ("SFO", "NRT"): 675,
    ("ORD", "FRA"): 520,
}
# Fixed UTC offsets (no DST) so stored times are local wall-clock at each airport.
UTC_OFFSET_HOURS = {
    "SFO": -8,
    "LAX": -8,
    "SEA": -8,
    "DEN": -7,
    "ORD": -6,
    "DFW": -6,
    "JFK": -5,
    "BOS": -5,
    "ATL": -5,
    "MIA": -5,
    "LHR": 0,
    "CDG": 1,
    "FRA": 1,
    "NRT": 9,
}
AIRLINES = ["UA", "AA", "DL", "B6", "AS"]
INTERNATIONAL_AIRLINES = ["BA", "VS", "AA", "UA", "AF", "LH", "JL"]
DEPARTURE_SLOTS = [(7, 0), (10, 30), (14, 0), (18, 15)]
RED_EYE_SLOT = (22, 45)

CABIN_MULTIPLIER = {
    Cabin.ECONOMY: Decimal("1"),
    Cabin.PREMIUM_ECONOMY: Decimal("1.9"),
    Cabin.BUSINESS: Decimal("3.8"),
    Cabin.FIRST: Decimal("6"),
}


@dataclass(frozen=True)
class AnchorFlight:
    """A flight that runs every day at the same local time and price."""

    airline: str
    number: int
    origin: str
    destination: str
    departs: tuple[int, int]
    minutes: int
    fares: dict[Cabin, int]


ANCHORS = [
    # SFO -> JFK, short haul by total time: nonstop over the $400 cap, cheaper via DEN.
    AnchorFlight("B6", 615, "SFO", "JFK", (6, 0), 330, {Cabin.ECONOMY: 300}),
    AnchorFlight("UA", 1, "SFO", "JFK", (8, 0), 325, {Cabin.ECONOMY: 520}),
    AnchorFlight("AA", 177, "SFO", "JFK", (10, 0), 330, {Cabin.ECONOMY: 380}),
    AnchorFlight("DL", 431, "SFO", "JFK", (14, 0), 330, {Cabin.ECONOMY: 310}),
    AnchorFlight("UA", 2201, "SFO", "DEN", (7, 0), 150, {Cabin.ECONOMY: 140}),
    AnchorFlight("UA", 2202, "DEN", "JFK", (11, 30), 210, {Cabin.ECONOMY: 170}),
    # JFK -> SFO returns.
    AnchorFlight("UA", 2, "JFK", "SFO", (9, 0), 385, {Cabin.ECONOMY: 495}),
    AnchorFlight("DL", 432, "JFK", "SFO", (13, 0), 390, {Cabin.ECONOMY: 330}),
    AnchorFlight("B6", 616, "JFK", "SFO", (17, 30), 385, {Cabin.ECONOMY: 290}),
    # JFK <-> LHR long haul: BA business within 20% of VS business.
    AnchorFlight(
        "BA",
        178,
        "JFK",
        "LHR",
        (18, 30),
        420,
        {Cabin.ECONOMY: 720, Cabin.PREMIUM_ECONOMY: 1350, Cabin.BUSINESS: 2800, Cabin.FIRST: 6100},
    ),
    AnchorFlight(
        "VS",
        4,
        "JFK",
        "LHR",
        (19, 30),
        415,
        {Cabin.ECONOMY: 680, Cabin.PREMIUM_ECONOMY: 1280, Cabin.BUSINESS: 2400},
    ),
    AnchorFlight(
        "BA",
        117,
        "LHR",
        "JFK",
        (11, 0),
        490,
        {Cabin.ECONOMY: 760, Cabin.PREMIUM_ECONOMY: 1400, Cabin.BUSINESS: 2900},
    ),
    AnchorFlight(
        "VS",
        3,
        "LHR",
        "JFK",
        (13, 0),
        485,
        {Cabin.ECONOMY: 700, Cabin.PREMIUM_ECONOMY: 1300, Cabin.BUSINESS: 2450},
    ),
]


def _local(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _flight(
    airline: str,
    number: int,
    origin: str,
    destination: str,
    departs_at: datetime,
    minutes: int,
    cabin: Cabin,
    price: Decimal,
    seats: int,
    refundable: bool,
) -> Flight:
    return Flight(
        airline=airline,
        flight_number=f"{airline}{number}",
        origin=origin,
        destination=destination,
        departs_at=departs_at,
        arrives_at=departs_at
        + timedelta(
            minutes=minutes,
            hours=UTC_OFFSET_HOURS[destination] - UTC_OFFSET_HOURS[origin],
        ),
        duration_minutes=minutes,
        cabin=cabin,
        price=price.quantize(Decimal("1")),
        is_refundable=refundable,
        seats_left=seats,
    )


def _anchor_flights(day: date) -> list[Flight]:
    return [
        _flight(
            anchor.airline,
            anchor.number,
            anchor.origin,
            anchor.destination,
            _local(day, *anchor.departs),
            anchor.minutes,
            cabin,
            Decimal(price),
            seats=6,
            refundable=cabin == Cabin.BUSINESS,
        )
        for anchor in ANCHORS
        for cabin, price in anchor.fares.items()
    ]


def _random_flights(day: date, days_out: int, rng: random.Random) -> list[Flight]:
    urgency = Decimal("1.4") if days_out < 7 else Decimal("1.15") if days_out < 14 else Decimal("1")
    routes = [(pair, minutes, False) for pair, minutes in DOMESTIC_MINUTES.items()] + [
        (pair, minutes, True) for pair, minutes in INTERNATIONAL_MINUTES.items()
    ]
    flights = []
    for route_index, ((a, b), minutes, international) in enumerate(routes):
        for origin, destination, direction in ((a, b, 0), (b, a, 1)):
            carriers = rng.sample(INTERNATIONAL_AIRLINES if international else AIRLINES, 2)
            slots = DEPARTURE_SLOTS + ([RED_EYE_SLOT] if minutes >= 240 else [])
            for slot_index, slot in enumerate(slots):
                airline = carriers[slot_index % 2]
                number = 3000 + route_index * 40 + direction * 20 + slot_index
                rate = Decimal("1.6") if international else Decimal("1.0")
                base = (Decimal(40) + rate * minutes) * Decimal(str(rng.uniform(0.75, 1.35)))
                if slot == RED_EYE_SLOT:
                    base *= Decimal("0.8")
                cabins = [Cabin.ECONOMY]
                if minutes >= 240:
                    cabins += [Cabin.PREMIUM_ECONOMY, Cabin.BUSINESS]
                if international and slot_index == 3:
                    cabins.append(Cabin.FIRST)
                for cabin in cabins:
                    flights.append(
                        _flight(
                            airline,
                            number,
                            origin,
                            destination,
                            _local(day, *slot),
                            minutes,
                            cabin,
                            base * CABIN_MULTIPLIER[cabin] * urgency,
                            seats=rng.randint(1, 9),
                            refundable=rng.random() < 0.3,
                        )
                    )
    return flights


def generate(today: date, days: int = 45, seed: int = 7) -> list[Flight]:
    """Unsaved flights for `today` through `today + days`; deterministic for a given seed."""
    rng = random.Random(seed)
    flights = []
    for days_out in range(days + 1):
        day = today + timedelta(days=days_out)
        flights += _random_flights(day, days_out, rng)
        flights += _anchor_flights(day)
    return flights
