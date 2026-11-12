from dataclasses import dataclass, field

from django.db import models

from travel.policy import ApprovalRules, is_rejected
from travel.ranking import Preference, RankedOption

MAX_COMPLIANT_SHOWN = 3
MAX_APPROVAL_SHOWN = 2
# Things the traveler asked for outright; never silently book something that misses them.
EXPLICIT_REQUESTS = frozenset({Preference.ARRIVES_ON_TIME, Preference.REQUESTED_CABIN})


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


def _misses(ranked: RankedOption, blocking: frozenset[Preference] | None) -> set[Preference]:
    misses = set(ranked.misses)
    return misses if blocking is None else misses & blocking


def decide_direction(
    ranked: list[RankedOption],
    rules: ApprovalRules,
    blocking: frozenset[Preference] | None = None,
) -> DirectionDecision:
    """Decide one direction from preference-ranked options.

    Auto-book only when the best compliant option fits the traveler's preferences
    as well as the best option overall; if a preference can only be met by an
    option needing approval, propose both. If nothing is compliant, the
    best-fitting approvable option goes to the manager.

    Never auto-book an option that misses an explicit request (a cabin, an arrival
    deadline); propose instead, citing why options that would meet it are ruled out.

    `blocking` limits which preferences can stop an auto-book (None means all);
    the rest still order the options.
    """
    rejected = [r for r in ranked if is_rejected(r.evaluation, rules)]
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
    if _misses(best_compliant, blocking) <= _misses(best, blocking):
        unmet_requests = set(best_compliant.misses) & EXPLICIT_REQUESTS
        if unmet_requests:
            return DirectionDecision(
                kind=DecisionKind.PROPOSE,
                chosen=best_compliant,
                reasoning=_unmet_request_reasoning(unmet_requests, rejected),
                **shown,
            )
        return DirectionDecision(
            kind=DecisionKind.AUTO_BOOK,
            chosen=best_compliant,
            reasoning=_auto_book_reasoning(best_compliant),
            **shown,
        )
    unmet = [p.label for p in _misses(best_compliant, blocking) - _misses(best, blocking)]
    return DirectionDecision(
        kind=DecisionKind.PROPOSE,
        chosen=best_compliant,
        reasoning="best in-policy option misses "
        + ", ".join(unmet).lower()
        + "; an option that meets it needs approval",
        **shown,
    )


def _auto_book_reasoning(chosen: RankedOption) -> str:
    option = chosen.evaluation.option
    reasoning = (
        f"within policy (${option.price:,.0f} against a ${chosen.evaluation.budget_usd:,.0f} cap)"
    )
    if chosen.matches:
        reasoning += "; meets " + ", ".join(p.label.lower() for p in chosen.matches)
    return reasoning


def _unmet_request_reasoning(unmet: set[Preference], rejected: list[RankedOption]) -> str:
    labels = ", ".join(p.label.lower() for p in Preference if p in unmet)
    reasoning = f"no bookable option meets the request ({labels})"
    blocked = next((r for r in rejected if not set(r.misses) & unmet), None)
    if blocked is not None:
        reasoning += ": " + "; ".join(blocked.evaluation.reasons)
    return reasoning


def combine(decisions: list[DirectionDecision]) -> DecisionKind:
    """The trip-level decision is the most cautious of its directions."""
    order = list(DecisionKind)
    return min((d.kind for d in decisions), key=order.index)
