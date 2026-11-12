from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import TODAY, active_policy, make_flight, nonstop
from travel.models import BillableCode, Cabin, Seniority
from travel.policy import (
    DisruptedBooking,
    Violation,
    deep_merge,
    effective_rules,
    evaluate_options,
)
from travel.search import TravelOption

IC = Seniority.INDIVIDUAL_CONTRIBUTOR
VP = Seniority.VICE_PRESIDENT
SHORT = 300
LONG = 420


def violations_for(option: TravelOption, seniority=IC, code: str | None = None, **kwargs):
    billable_code = BillableCode.objects.get(code=code) if code else None
    rules = effective_rules(active_policy(), billable_code)
    [evaluation] = evaluate_options([option], seniority, rules, TODAY, **kwargs)
    return evaluation.violations


def test_deep_merge_replaces_only_overridden_keys():
    """A contract override replaces nested keys and leaves sibling keys intact."""
    base = {"budget": {"short": 400, "long": 1500}, "window": 7}
    assert deep_merge(base, {"budget": {"long": 900}}) == {
        "budget": {"short": 400, "long": 900},
        "window": 7,
    }


@pytest.mark.django_db
class TestCompanyPolicy:
    """Company policy v1 applied with no client contract."""

    @pytest.mark.parametrize(
        "seniority, duration, cabin, price, expected",
        [
            pytest.param(IC, SHORT, Cabin.ECONOMY, 400, [], id="short-at-cap"),
            pytest.param(IC, SHORT, Cabin.ECONOMY, 401, [Violation.OVER_BUDGET], id="short-over"),
            pytest.param(
                IC,
                SHORT,
                Cabin.PREMIUM_ECONOMY,
                300,
                [Violation.CABIN_NOT_ALLOWED],
                id="short-premium",
            ),
            pytest.param(IC, LONG, Cabin.PREMIUM_ECONOMY, 1500, [], id="long-premium-at-cap"),
            pytest.param(
                IC, LONG, Cabin.BUSINESS, 1400, [Violation.CABIN_NOT_ALLOWED], id="ic-business"
            ),
            pytest.param(VP, LONG, Cabin.BUSINESS, 3000, [], id="vp-business-at-cap"),
            pytest.param(
                VP, LONG, Cabin.BUSINESS, 3001, [Violation.OVER_BUDGET], id="vp-business-over"
            ),
            pytest.param(
                VP,
                SHORT,
                Cabin.BUSINESS,
                900,
                [Violation.CABIN_NOT_ALLOWED, Violation.OVER_BUDGET],
                id="vp-short-business",
            ),
            pytest.param(
                VP, LONG, Cabin.FIRST, 2000, [Violation.NEVER_ALLOWED_CABIN], id="first-class"
            ),
        ],
    )
    def test_budget_and_cabin_by_haul_and_seniority(
        self, seniority, duration, cabin, price, expected
    ):
        """Budget and allowed cabins depend on haul length and seniority; first class is
        only ever a never-allowed violation, not also a cabin or budget one."""
        option = nonstop(duration_minutes=duration, cabin=cabin, price=Decimal(price))
        assert violations_for(option, seniority) == expected

    def test_layover_pushes_trip_into_long_haul(self):
        """Haul length uses total travel time, so 5h air + 1.5h layover gets the long-haul cap."""
        first = make_flight(hour=8, duration_minutes=180, price=Decimal("500"))
        second = make_flight(
            departs_at=first.arrives_at + timedelta(minutes=90),
            duration_minutes=120,
            price=Decimal("500"),
        )
        assert violations_for(TravelOption(legs=(first, second))) == []

    @pytest.mark.parametrize(
        "days_out, expected",
        [
            pytest.param(6, [Violation.INSIDE_BOOKING_WINDOW], id="6-days"),
            pytest.param(7, [], id="7-days"),
        ],
    )
    def test_booking_window(self, days_out, expected):
        """Trips departing fewer than 7 days out need approval."""
        assert violations_for(nonstop(days_out=days_out)) == expected


@pytest.mark.django_db
class TestLowestLogicalFare:
    """Pricier options must be within 20% of the cheapest compliant same-cabin option."""

    def evaluate(self, *options: TravelOption):
        rules = effective_rules(active_policy(), None)
        return [e.violations for e in evaluate_options(list(options), IC, rules, TODAY)]

    def test_within_twenty_percent_passes(self):
        """$240 against a $200 cheapest fare is exactly at the 20% ceiling."""
        cheap, pricier = nonstop(price=Decimal("200")), nonstop(price=Decimal("240"))
        assert self.evaluate(cheap, pricier) == [[], []]

    def test_above_twenty_percent_fails(self):
        """$300 against $200 with the same travel time breaks lowest logical fare."""
        cheap, pricier = nonstop(price=Decimal("200")), nonstop(price=Decimal("300"))
        assert self.evaluate(cheap, pricier) == [[], [Violation.ABOVE_LOWEST_LOGICAL_FARE]]

    def test_saving_two_hours_is_exempt(self):
        """A pricier option that saves 2+ hours of travel time is allowed."""
        slow = nonstop(price=Decimal("200"), duration_minutes=350)
        fast = nonstop(price=Decimal("350"), duration_minutes=230)
        assert self.evaluate(slow, fast) == [[], []]

    def test_compares_within_cabin(self):
        """A VP's allowed business fare isn't judged against the cheapest economy fare."""
        rules = effective_rules(active_policy(), None)
        economy = nonstop(duration_minutes=LONG, price=Decimal("700"))
        business = nonstop(duration_minutes=LONG, cabin=Cabin.BUSINESS, price=Decimal("2800"))
        evaluations = evaluate_options([economy, business], VP, rules, TODAY)
        assert [e.violations for e in evaluations] == [[], []]


@pytest.mark.django_db
class TestClientContracts:
    """Client contract overrides replace company rules for trips billed to that client."""

    @pytest.mark.parametrize(
        "code, option_kwargs, expected",
        [
            pytest.param(
                "ACME-001",
                {"duration_minutes": SHORT, "price": Decimal("351")},
                [Violation.OVER_BUDGET],
                id="acme-short-cap-350",
            ),
            pytest.param(
                "ACME-001",
                {"duration_minutes": LONG, "cabin": Cabin.PREMIUM_ECONOMY, "price": Decimal("800")},
                [Violation.CABIN_NOT_ALLOWED],
                id="acme-economy-only-long-haul",
            ),
            pytest.param(
                "ACME-001",
                {"days_out": 10},
                [Violation.INSIDE_BOOKING_WINDOW],
                id="acme-14-day-window",
            ),
            pytest.param(
                "GLOBEX-001",
                {"duration_minutes": 260, "cabin": Cabin.BUSINESS, "price": Decimal("1900")},
                [],
                id="globex-business-over-4h",
            ),
            pytest.param(
                "INITECH-001",
                {"duration_minutes": SHORT, "price": Decimal("401")},
                [Violation.OVER_BUDGET],
                id="initech-company-rules",
            ),
        ],
    )
    def test_contract_overrides(self, code, option_kwargs, expected):
        """Acme is stricter, Globex looser, Initech identical to company policy."""
        assert violations_for(nonstop(**option_kwargs), code=code) == expected

    def test_acme_vp_held_to_economy(self):
        """Acme's contract keeps even a VP in economy on long haul."""
        option = nonstop(duration_minutes=LONG, cabin=Cabin.BUSINESS, price=Decimal("800"))
        assert violations_for(option, VP, code="ACME-001") == [Violation.CABIN_NOT_ALLOWED]


@pytest.mark.django_db
class TestDisruptionRebooking:
    """Rebooking after a disruption uses its own limits instead of budget and booking window."""

    ORIGINAL = DisruptedBooking(cabin=Cabin.ECONOMY, price=Decimal("320"))

    @pytest.mark.parametrize(
        "option_kwargs, expected",
        [
            pytest.param({"price": Decimal("520")}, [], id="plus-200-at-limit"),
            pytest.param(
                {"price": Decimal("521")},
                [Violation.DISRUPTION_REBOOKING_OVER_LIMIT],
                id="over-limit",
            ),
            pytest.param(
                {"cabin": Cabin.PREMIUM_ECONOMY, "price": Decimal("320")},
                [Violation.CABIN_NOT_ALLOWED],
                id="higher-cabin",
            ),
            pytest.param({"days_out": 0, "price": Decimal("450")}, [], id="same-day-over-budget"),
        ],
    )
    def test_rebooking_limits(self, option_kwargs, expected):
        """Same cabin or lower and at most $200 more is in policy, even same-day and over the
        normal budget."""
        option = nonstop(duration_minutes=SHORT, **option_kwargs)
        assert violations_for(option, disrupted=self.ORIGINAL) == expected
