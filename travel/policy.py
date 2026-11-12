from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import models
from pydantic import BaseModel

from travel.models import BillableCode, Cabin, Seniority, TravelPolicy
from travel.search import TravelOption


class Violation(models.TextChoices):
    """Ways an option breaks policy; values match `TravelPolicy.approval_rules`."""

    OVER_BUDGET = "over-budget", "Over budget"
    CABIN_NOT_ALLOWED = "cabin-not-allowed", "Cabin not allowed"
    INSIDE_BOOKING_WINDOW = "inside-booking-window", "Inside booking window"
    ABOVE_LOWEST_LOGICAL_FARE = "above-lowest-logical-fare", "Above lowest logical fare"
    NEVER_ALLOWED_CABIN = "never-allowed-cabin", "Never-allowed cabin"
    DISRUPTION_REBOOKING_OVER_LIMIT = (
        "disruption-rebooking-over-limit",
        "Disruption rebooking over limit",
    )


class BudgetRules(BaseModel):
    long_haul_threshold_minutes: int
    short_haul_max_usd: Decimal
    long_haul_max_usd: Decimal


class SeniorLongHaulRules(BaseModel):
    min_seniority: Seniority
    cabins: list[Cabin]
    max_usd: Decimal


class CabinRules(BaseModel):
    short_haul: list[Cabin]
    long_haul: list[Cabin]
    senior_long_haul: SeniorLongHaulRules


class LowestLogicalFareRules(BaseModel):
    max_over_cheapest_pct: Decimal
    exempt_if_saves_minutes: int


class BookingWindowRules(BaseModel):
    min_days_in_advance: int


class NeverAllowedRules(BaseModel):
    cabins: list[Cabin]


class DisruptionRebookingRules(BaseModel):
    max_price_increase_usd: Decimal


class PolicyRules(BaseModel):
    """Typed view of `TravelPolicy.rules` after client contract overrides are merged in."""

    budget_per_direction: BudgetRules
    cabins: CabinRules
    lowest_logical_fare: LowestLogicalFareRules
    booking_window: BookingWindowRules
    never_allowed: NeverAllowedRules
    disruption_rebooking: DisruptionRebookingRules


class ApprovalRules(BaseModel):
    """Typed view of `TravelPolicy.approval_rules`."""

    requires_approval: list[Violation]
    always_rejected: list[Violation]


@dataclass(frozen=True)
class DisruptedBooking:
    """The original leg being replaced; switches evaluation to the disruption-rebooking rules."""

    cabin: Cabin
    price: Decimal


@dataclass
class OptionEvaluation:
    """An option's policy result. Empty `violations` means it can be booked without approval."""

    option: TravelOption
    is_long_haul: bool
    budget_usd: Decimal
    violations: list[Violation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_compliant(self) -> bool:
        return not self.violations


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively replace keys of `base` with those in `overrides`."""
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
            continue
        merged[key] = value
    return merged


def effective_rules(policy: TravelPolicy, billable_code: BillableCode | None) -> PolicyRules:
    """Company rules with the client contract applied for trips billed to `billable_code`."""
    overrides = billable_code.policy_overrides if billable_code is not None else {}
    return PolicyRules.model_validate(deep_merge(policy.rules, overrides))


def approval_rules(policy: TravelPolicy) -> ApprovalRules:
    return ApprovalRules.model_validate(policy.approval_rules)


def is_rejected(evaluation: OptionEvaluation, rules: ApprovalRules) -> bool:
    return any(violation in rules.always_rejected for violation in evaluation.violations)


def _seniority_at_least(seniority: Seniority, minimum: Seniority) -> bool:
    levels = list(Seniority)
    return levels.index(seniority) >= levels.index(minimum)


def _cabin_rank(cabin: Cabin) -> int:
    return list(Cabin).index(cabin)


@dataclass(frozen=True)
class _Tier:
    is_long_haul: bool
    allowed_cabins: list[Cabin]
    budget_usd: Decimal


def _tier(option: TravelOption, seniority: Seniority, rules: PolicyRules) -> _Tier:
    """Budget and allowed cabins for this option's haul length and the traveler's level."""
    budget = rules.budget_per_direction
    senior = rules.cabins.senior_long_haul
    is_long_haul = option.total_minutes >= budget.long_haul_threshold_minutes
    if is_long_haul and _seniority_at_least(seniority, senior.min_seniority):
        return _Tier(True, senior.cabins, senior.max_usd)
    if is_long_haul:
        return _Tier(True, rules.cabins.long_haul, budget.long_haul_max_usd)
    return _Tier(False, rules.cabins.short_haul, budget.short_haul_max_usd)


def _add(evaluation: OptionEvaluation, violation: Violation, reason: str) -> None:
    evaluation.violations.append(violation)
    evaluation.reasons.append(reason)


def evaluate_options(
    options: list[TravelOption],
    seniority: Seniority,
    rules: PolicyRules,
    today: date,
    disrupted: DisruptedBooking | None = None,
) -> list[OptionEvaluation]:
    """Evaluate every option for one direction against the rules.

    Lowest logical fare compares each option with the cheapest otherwise-compliant
    option in the same cabin, so an allowed upgrade isn't judged against economy.
    With `disrupted`, the disruption-rebooking rules replace budget, cabin tier,
    booking window, and lowest logical fare.
    """
    evaluations = []
    for option in options:
        tier = _tier(option, seniority, rules)
        evaluation = OptionEvaluation(
            option=option, is_long_haul=tier.is_long_haul, budget_usd=tier.budget_usd
        )
        if option.cabin in rules.never_allowed.cabins:
            _add(
                evaluation, Violation.NEVER_ALLOWED_CABIN, f"{option.cabin.label} is never allowed"
            )
        elif disrupted is not None:
            _check_disruption_rebooking(evaluation, rules, disrupted)
        else:
            _check_standard_rules(evaluation, tier, rules, today)
        evaluations.append(evaluation)
    if disrupted is None:
        _check_lowest_logical_fare(evaluations, rules)
    return evaluations


def _check_standard_rules(
    evaluation: OptionEvaluation, tier: _Tier, rules: PolicyRules, today: date
) -> None:
    option = evaluation.option
    haul = "long-haul" if tier.is_long_haul else "short-haul"
    if option.cabin not in tier.allowed_cabins:
        _add(
            evaluation,
            Violation.CABIN_NOT_ALLOWED,
            f"{option.cabin.label} isn't allowed on this {haul} trip for your level",
        )
    if option.price > tier.budget_usd:
        _add(
            evaluation,
            Violation.OVER_BUDGET,
            f"${option.price:,.0f} is over the ${tier.budget_usd:,.0f} {haul} budget",
        )
    days_out = (option.first_leg.departs_at.date() - today).days
    min_days = rules.booking_window.min_days_in_advance
    if days_out < min_days:
        _add(
            evaluation,
            Violation.INSIDE_BOOKING_WINDOW,
            f"departs in {days_out} days; trips must be booked {min_days}+ days ahead",
        )


def _check_disruption_rebooking(
    evaluation: OptionEvaluation, rules: PolicyRules, disrupted: DisruptedBooking
) -> None:
    option = evaluation.option
    if _cabin_rank(option.cabin) > _cabin_rank(disrupted.cabin):
        _add(
            evaluation,
            Violation.CABIN_NOT_ALLOWED,
            f"{option.cabin.label} is above the original {disrupted.cabin.label} cabin",
        )
    increase = option.price - disrupted.price
    limit = rules.disruption_rebooking.max_price_increase_usd
    if increase > limit:
        _add(
            evaluation,
            Violation.DISRUPTION_REBOOKING_OVER_LIMIT,
            f"${increase:,.0f} more than the original fare; rebooking limit is ${limit:,.0f}",
        )


def _check_lowest_logical_fare(evaluations: list[OptionEvaluation], rules: PolicyRules) -> None:
    llf = rules.lowest_logical_fare
    cheapest_by_cabin: dict[Cabin, TravelOption] = {}
    for evaluation in evaluations:
        option = evaluation.option
        cheapest = cheapest_by_cabin.get(option.cabin)
        if evaluation.is_compliant and (cheapest is None or option.price < cheapest.price):
            cheapest_by_cabin[option.cabin] = option
    for evaluation in evaluations:
        option = evaluation.option
        cheapest = cheapest_by_cabin.get(option.cabin)
        if cheapest is None:
            continue
        ceiling = cheapest.price * (1 + llf.max_over_cheapest_pct / 100)
        minutes_saved = cheapest.total_minutes - option.total_minutes
        if option.price > ceiling and minutes_saved < llf.exempt_if_saves_minutes:
            _add(
                evaluation,
                Violation.ABOVE_LOWEST_LOGICAL_FARE,
                f"${option.price - cheapest.price:,.0f} more than the cheapest "
                f"{option.cabin.label.lower()} option without saving "
                f"{llf.exempt_if_saves_minutes // 60}+ hours",
            )
