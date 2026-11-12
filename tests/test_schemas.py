from datetime import date

import pytest
from pydantic import ValidationError

from travel.schemas import TripConstraints


class TestTripConstraints:
    """Validation of the stored trip-constraints shape."""

    def test_round_trip_through_json(self):
        """Constraints serialized to the JSON column parse back unchanged."""
        constraints = TripConstraints(
            origin="SFO", destination="JFK", depart_date=date(2026, 12, 1), return_date=None
        )
        assert TripConstraints.model_validate(constraints.model_dump(mode="json")) == constraints

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"origin": "SF"}, id="origin-not-iata"),
            pytest.param({"return_date": date(2026, 11, 30)}, id="return-before-departure"),
            pytest.param({"requested_cabin": "luxury"}, id="unknown-cabin"),
        ],
    )
    def test_rejects_invalid_constraints(self, overrides):
        """Malformed codes, inverted dates, and unknown cabins fail validation
        before anything can be stored."""
        fields = {"origin": "SFO", "destination": "JFK", "depart_date": date(2026, 12, 1)}
        with pytest.raises(ValidationError):
            TripConstraints(**{**fields, **overrides})
