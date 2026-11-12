from datetime import timedelta

import pytest

from tests.factories import TODAY, at, make_flight
from travel.models import Cabin
from travel.search import TravelOption, find_options

SEARCH_DAY = TODAY + timedelta(days=10)


def _sfo_to_ord_leg():
    return make_flight(
        departs_at=at(10, 8), duration_minutes=240, origin="SFO", destination="ORD", save=True
    )


@pytest.mark.django_db
class TestFindOptions:
    """Search composes nonstops and valid one-stop connections for one direction."""

    def test_returns_nonstops_and_valid_connections(self):
        """A nonstop and a connection with a 1h layover in the same cabin are both returned."""
        direct = make_flight(days_out=10, origin="SFO", destination="JFK", save=True)
        first = _sfo_to_ord_leg()
        second = make_flight(
            departs_at=first.arrives_at + timedelta(hours=1),
            origin="ORD",
            destination="JFK",
            save=True,
        )
        legs = {option.legs for option in find_options("SFO", "JFK", SEARCH_DAY)}
        assert legs == {(direct,), (first, second)}

    @pytest.mark.parametrize(
        "layover_minutes, second_leg_overrides",
        [
            pytest.param(30, {}, id="connection-too-short"),
            pytest.param(60, {"cabin": Cabin.BUSINESS}, id="cabin-mismatch"),
            pytest.param(60, {"seats_left": 0}, id="sold-out"),
        ],
    )
    def test_excludes_unbookable_connections(self, layover_minutes, second_leg_overrides):
        """Connections under 45 minutes, across cabins, or without seats are never offered."""
        first = _sfo_to_ord_leg()
        make_flight(
            departs_at=first.arrives_at + timedelta(minutes=layover_minutes),
            origin="ORD",
            destination="JFK",
            save=True,
            **second_leg_overrides,
        )
        assert find_options("SFO", "JFK", SEARCH_DAY) == []

    def test_total_minutes_include_layover(self):
        """Total travel time is air time plus layover, which decides short vs long haul."""
        first = make_flight(departs_at=at(10, 8), duration_minutes=240)
        second = make_flight(departs_at=at(10, 13, 30), duration_minutes=120)
        assert TravelOption(legs=(first, second)).total_minutes == 240 + 90 + 120
