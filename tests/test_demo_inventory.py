from datetime import timedelta

import pytest

from tests.factories import TODAY, active_policy, at
from travel.decisions import DecisionKind, DirectionDecision, decide_direction
from travel.demo import reset
from travel.models import (
    BillableCode,
    BookingIntent,
    Cabin,
    DisruptionEvent,
    DisruptionKind,
    Flight,
    User,
)
from travel.policy import Violation, approval_rules, effective_rules, evaluate_options
from travel.ranking import rank
from travel.schemas import TripConstraints
from travel.search import find_options
from travel.services.booking import book_itinerary
from travel.services.disruptions import DisruptionResponse, process_event


@pytest.fixture
def demo(db):
    reset(TODAY, days=25)


def plan(username, origin, destination, days_out, code=None, **rank_kwargs) -> DirectionDecision:
    traveler = User.objects.get(username=username)
    policy = active_policy()
    billable_code = BillableCode.objects.get(code=code) if code else None
    evaluations = evaluate_options(
        find_options(origin, destination, TODAY + timedelta(days=days_out)),
        traveler.seniority,
        effective_rules(policy, billable_code),
        TODAY,
    )
    return decide_direction(rank(evaluations, traveler, **rank_kwargs), approval_rules(policy))


def flight_numbers(ranked_options) -> list[str]:
    return ["+".join(leg.flight_number for leg in r.evaluation.option.legs) for r in ranked_options]


@pytest.mark.usefixtures("demo")
class TestDemoScenarios:
    """The seeded inventory produces each demo conflict through the real pipeline."""

    def test_acme_trip_inside_contract_window_needs_approval(self):
        """Jordan's Acme trip 10 days out passes the company 7-day window but not Acme's 14."""
        decision = plan("jordan", "SFO", "JFK", 10, code="ACME-001")
        assert decision.kind == DecisionKind.REQUEST_APPROVAL
        assert Violation.INSIDE_BOOKING_WINDOW in decision.chosen.evaluation.violations

    def test_preference_only_met_over_budget_gets_split_offer(self):
        """Priya's UA nonstop is over the $400 cap, so she gets in-policy options plus UA1
        marked as needing approval."""
        decision = plan("priya", "SFO", "JFK", 14)
        assert decision.kind == DecisionKind.PROPOSE
        assert decision.can_book_now
        assert "UA1" in flight_numbers(decision.needs_approval)

    def test_vp_auto_books_business_on_loyalty_airline(self):
        """Victoria asking for business gets BA business (her FF airline) booked outright,
        within 20% of the cheaper VS business fare and under the $3,000 VP cap."""
        decision = plan("victoria", "JFK", "LHR", 21, requested_cabin=Cabin.BUSINESS)
        assert decision.kind == DecisionKind.AUTO_BOOK
        assert flight_numbers([decision.chosen]) == ["BA178"]
        assert decision.chosen.evaluation.option.cabin == Cabin.BUSINESS

    def test_analyst_asking_for_business_sees_it_needs_approval(self):
        """Sam asking for business on the same route is offered economy/premium to book now,
        with business only as needing approval."""
        decision = plan("sam", "JFK", "LHR", 21, requested_cabin=Cabin.BUSINESS)
        assert decision.kind == DecisionKind.PROPOSE
        assert {r.evaluation.option.cabin for r in decision.can_book_now} <= {
            Cabin.ECONOMY,
            Cabin.PREMIUM_ECONOMY,
        }
        assert all(
            Violation.CABIN_NOT_ALLOWED in r.evaluation.violations
            for r in decision.needs_approval
            if r.evaluation.option.cabin == Cabin.BUSINESS
        )

    def test_cancellation_rebooks_onto_flight_that_makes_dinner(self):
        """Priya's 6am B6 is cancelled; the cheapest alternative lands after her 7pm dinner,
        so the agent rebooks the on-time nonstop within the $200 limit."""
        priya = User.objects.get(username="priya")
        day = TODAY + timedelta(days=14)
        constraints = TripConstraints(
            origin="SFO", destination="JFK", depart_date=day, arrive_outbound_by=at(14, 19)
        )
        intent = BookingIntent.objects.create(
            traveler=priya, constraints=constraints.model_dump(mode="json")
        )
        b6 = Flight.objects.get(flight_number="B6615", departs_at__date=day, cabin=Cabin.ECONOMY)
        book_itinerary(intent, [b6], active_policy(), at(0, 12), "test booking")
        event = DisruptionEvent.objects.create(
            flight=b6, kind=DisruptionKind.CANCELLATION, occurred_at=at(0, 12)
        )
        [outcome] = process_event(event, at(0, 12))
        assert outcome.response == DisruptionResponse.REBOOKED
        [new_leg] = outcome.rebooked_itinerary.legs()
        assert new_leg.arrives_at <= at(14, 19)
        assert new_leg.price - b6.price <= 200
