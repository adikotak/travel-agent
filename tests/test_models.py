from datetime import UTC, datetime
from decimal import Decimal

import pytest

from travel.models import Cabin, Flight


@pytest.mark.parametrize(
    "hour, expected",
    [
        pytest.param(20, False, id="8pm-evening"),
        pytest.param(21, True, id="9pm-red-eye"),
        pytest.param(4, True, id="4am-red-eye"),
        pytest.param(5, False, id="5am-morning"),
    ],
)
def test_red_eye_by_local_departure_hour(hour, expected):
    """A flight is a red-eye exactly when it departs between 9pm and 5am local."""
    flight = Flight(
        airline="UA",
        flight_number="UA1",
        origin="SFO",
        destination="JFK",
        departs_at=datetime(2026, 12, 1, hour, tzinfo=UTC),
        arrives_at=datetime(2026, 12, 1, 23, tzinfo=UTC),
        duration_minutes=330,
        cabin=Cabin.ECONOMY,
        price=Decimal("300"),
        seats_left=5,
    )
    assert flight.is_red_eye is expected
