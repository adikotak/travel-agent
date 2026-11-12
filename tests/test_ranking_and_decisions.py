from datetime import timedelta
from decimal import Decimal

import pytest

from tests.factories import at, make_user, nonstop
from travel.decisions import DecisionKind, DirectionDecision, combine, decide_direction
from travel.models import Cabin
from travel.policy import ApprovalRules, OptionEvaluation, Violation
from travel.ranking import Preference, rank
from travel.search import TravelOption

APPROVAL_RULES = ApprovalRules(
    requires_approval=[Violation.OVER_BUDGET, Violation.INSIDE_BOOKING_WINDOW],
    always_rejected=[Violation.NEVER_ALLOWED_CABIN],
)


def evaluated(option: TravelOption, *violations: Violation) -> OptionEvaluation:
    return OptionEvaluation(
        option=option,
        is_long_haul=False,
        budget_usd=Decimal("400"),
        violations=list(violations),
        reasons=[v.label for v in violations],
    )


def one_stop(**overrides) -> TravelOption:
    first = nonstop(**overrides).first_leg
    second = nonstop(departs_at=first.arrives_at + timedelta(hours=1)).first_leg
    return TravelOption(legs=(first, second))


class TestRank:
    """Preference fit outranks price; price then travel time break ties."""

    def test_cheapest_first_without_preferences(self):
        """With no stated preferences, options sort by price."""
        cheap, pricey = nonstop(price=Decimal("150")), nonstop(price=Decimal("250"))
        ranked = rank([evaluated(pricey), evaluated(cheap)], make_user())
        assert [r.evaluation.option for r in ranked] == [cheap, pricey]

    @pytest.mark.parametrize(
        "user_kwargs, preferred, other",
        [
            pytest.param(
                {"prefers_nonstop": True},
                lambda: nonstop(price=Decimal("300")),
                lambda: one_stop(price=Decimal("100")),
                id="nonstop",
            ),
            pytest.param(
                {"avoids_red_eyes": True},
                lambda: nonstop(hour=9, price=Decimal("300")),
                lambda: nonstop(hour=23, price=Decimal("100")),
                id="no-red-eye",
            ),
            pytest.param(
                {"preferred_airlines": ["BA"]},
                lambda: nonstop(airline="BA", price=Decimal("300")),
                lambda: nonstop(airline="VS", price=Decimal("100")),
                id="preferred-airline",
            ),
        ],
    )
    def test_preference_beats_price(self, user_kwargs, preferred, other):
        """An option meeting a stated preference ranks above a cheaper one that misses it."""
        preferred_option, other_option = preferred(), other()
        ranked = rank(
            [evaluated(other_option), evaluated(preferred_option)], make_user(**user_kwargs)
        )
        assert ranked[0].evaluation.option is preferred_option

    def test_arrival_deadline_outranks_other_preferences(self):
        """Making a stated deadline matters more than being nonstop."""
        late_nonstop = nonstop(hour=17)
        on_time_connection = one_stop(hour=8)
        ranked = rank(
            [evaluated(late_nonstop), evaluated(on_time_connection)],
            make_user(prefers_nonstop=True),
            arrive_by=at(30, 15),
        )
        assert ranked[0].evaluation.option is on_time_connection
        assert ranked[0].misses == (Preference.NONSTOP,)

    def test_requested_cabin(self):
        """A requested cabin ranks above cheaper options in other cabins."""
        economy = nonstop(price=Decimal("700"))
        business = nonstop(cabin=Cabin.BUSINESS, price=Decimal("2800"))
        ranked = rank(
            [evaluated(economy), evaluated(business)], make_user(), requested_cabin=Cabin.BUSINESS
        )
        assert ranked[0].evaluation.option is business


class TestDecideDirection:
    """Book on our own, propose, or escalate, from ranked options."""

    def decide(self, *evaluations: OptionEvaluation, **user_kwargs):
        return decide_direction(rank(list(evaluations), make_user(**user_kwargs)), APPROVAL_RULES)

    def test_auto_books_when_best_fit_is_compliant(self):
        """The best-fitting option is in policy, so the agent books it without asking."""
        best = nonstop(price=Decimal("200"))
        decision = self.decide(
            evaluated(best), evaluated(nonstop(price=Decimal("500")), Violation.OVER_BUDGET)
        )
        assert decision.kind == DecisionKind.AUTO_BOOK
        assert decision.chosen.evaluation.option is best

    def test_proposes_when_preference_needs_approval(self):
        """Only an over-budget option is nonstop, so both it and the compliant connection are
        offered, split into book-now and needs-approval."""
        connection = one_stop(price=Decimal("320"))
        nonstop_over = nonstop(price=Decimal("520"))
        decision = self.decide(
            evaluated(connection),
            evaluated(nonstop_over, Violation.OVER_BUDGET),
            prefers_nonstop=True,
        )
        assert decision.kind == DecisionKind.PROPOSE
        assert [r.evaluation.option for r in decision.can_book_now] == [connection]
        assert [r.evaluation.option for r in decision.needs_approval] == [nonstop_over]

    def test_requests_approval_when_nothing_compliant(self):
        """Every option is inside the booking window, so the best fit goes to the manager."""
        option = nonstop()
        decision = self.decide(evaluated(option, Violation.INSIDE_BOOKING_WINDOW))
        assert decision.kind == DecisionKind.REQUEST_APPROVAL
        assert decision.chosen.evaluation.option is option

    def test_rejected_options_are_never_offered(self):
        """Never-allowed options are dropped entirely, leaving nothing to offer."""
        decision = self.decide(evaluated(nonstop(cabin=Cabin.FIRST), Violation.NEVER_ALLOWED_CABIN))
        assert decision.kind == DecisionKind.NO_OPTIONS
        assert decision.chosen is None


@pytest.mark.parametrize(
    "kinds, expected",
    [
        pytest.param(
            [DecisionKind.AUTO_BOOK, DecisionKind.AUTO_BOOK], DecisionKind.AUTO_BOOK, id="all-auto"
        ),
        pytest.param(
            [DecisionKind.AUTO_BOOK, DecisionKind.PROPOSE], DecisionKind.PROPOSE, id="propose-wins"
        ),
        pytest.param(
            [DecisionKind.PROPOSE, DecisionKind.REQUEST_APPROVAL],
            DecisionKind.REQUEST_APPROVAL,
            id="approval-wins",
        ),
        pytest.param(
            [DecisionKind.AUTO_BOOK, DecisionKind.NO_OPTIONS],
            DecisionKind.NO_OPTIONS,
            id="no-options-wins",
        ),
    ],
)
def test_trip_decision_is_most_cautious_direction(kinds, expected):
    """A round trip is only auto-booked when both directions would be."""
    decisions = [DirectionDecision(kind=kind, chosen=None, reasoning="") for kind in kinds]
    assert combine(decisions) == expected


def test_only_blocking_preferences_stop_auto_book():
    """With only the arrival deadline blocking, a compliant option that misses just the
    preferred airline is booked rather than proposed against an over-limit one that has it."""
    other_airline = nonstop(airline="AA", price=Decimal("380"))
    preferred_over_limit = nonstop(airline="UA", price=Decimal("520"))
    ranked = rank(
        [
            evaluated(other_airline),
            evaluated(preferred_over_limit, Violation.OVER_BUDGET),
        ],
        make_user(preferred_airlines=["UA"]),
    )
    decision = decide_direction(
        ranked, APPROVAL_RULES, blocking=frozenset({Preference.ARRIVES_ON_TIME})
    )
    assert decision.kind == DecisionKind.AUTO_BOOK
    assert decision.chosen.evaluation.option is other_airline
