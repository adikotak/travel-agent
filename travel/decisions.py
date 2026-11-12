from dataclasses import dataclass, field

from django.db import models

from travel.policy import ApprovalRules, is_rejected
from travel.ranking import RankedOption

MAX_COMPLIANT_SHOWN = 3
MAX_APPROVAL_SHOWN = 2


class DecisionKind(models.TextChoices):
    """What the agent does next for a direction or a whole trip; declared most to least cautious."""

    NO_OPTIONS = "no-options", "No options"
    REQUEST_APPROVAL = "request-approval", "Request approval"
    PROPOSE = "propose", "Propose options"
    AUTO_BOOK = "auto-book", "Auto-book"


@dataclass(frozen=True)
class DirectionDecision:
    """The decision for one direction, plus the options worth showing the traveler."""

    kind: DecisionKind
    chosen: RankedOption | None
    reasoning: str
    can_book_now: list[RankedOption] = field(default_factory=list)
    needs_approval: list[RankedOption] = field(default_factory=list)


def decide_direction(ranked: list[RankedOption], rules: ApprovalRules) -> DirectionDecision:
    """Decide one direction from preference-ranked options.

    Auto-book only when the best compliant option fits the traveler's preferences
    as well as the best option overall; if a preference can only be met by an
    option needing approval, propose both. If nothing is compliant, the
    best-fitting approvable option goes to the manager.
    """
    candidates = [r for r in ranked if not is_rejected(r.evaluation, rules)]
    can_book_now = [r for r in candidates if r.evaluation.is_compliant]
    needs_approval = [r for r in candidates if not r.evaluation.is_compliant]
    shown = {
        "can_book_now": can_book_now[:MAX_COMPLIANT_SHOWN],
        "needs_approval": needs_approval[:MAX_APPROVAL_SHOWN],
    }
    if not candidates:
        return DirectionDecision(
            kind=DecisionKind.NO_OPTIONS, chosen=None, reasoning="no bookable flights found"
        )
    best = candidates[0]
    if not can_book_now:
        return DirectionDecision(
            kind=DecisionKind.REQUEST_APPROVAL,
            chosen=best,
            reasoning="no option is within policy; best fit needs approval: "
            + "; ".join(best.evaluation.reasons),
            **shown,
        )
    best_compliant = can_book_now[0]
    if best_compliant.miss_vector == best.miss_vector:
        return DirectionDecision(
            kind=DecisionKind.AUTO_BOOK,
            chosen=best_compliant,
            reasoning="within policy and fits stated preferences as well as any option",
            **shown,
        )
    unmet = [p.label for p in best_compliant.misses if p not in best.misses]
    return DirectionDecision(
        kind=DecisionKind.PROPOSE,
        chosen=best_compliant,
        reasoning="best in-policy option misses "
        + ", ".join(unmet).lower()
        + "; an option that meets it needs approval",
        **shown,
    )


def combine(decisions: list[DirectionDecision]) -> DecisionKind:
    """The trip-level decision is the most cautious of its directions."""
    order = list(DecisionKind)
    return min((d.kind for d in decisions), key=order.index)
