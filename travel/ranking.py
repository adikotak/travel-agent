from dataclasses import dataclass
from datetime import datetime

from django.db import models

from travel.models import Cabin, User
from travel.policy import OptionEvaluation
from travel.search import TravelOption


class Preference(models.TextChoices):
    """Traveler preferences, declared in ranking priority order (highest first)."""

    ARRIVES_ON_TIME = "arrives-on-time", "Arrives in time"
    REQUESTED_CABIN = "requested-cabin", "Requested cabin"
    NONSTOP = "nonstop", "Nonstop"
    NO_RED_EYE = "no-red-eye", "Not a red-eye"
    PREFERRED_AIRLINE = "preferred-airline", "Preferred airline"


@dataclass(frozen=True)
class RankedOption:
    """An evaluated option with the traveler preferences it meets and misses."""

    evaluation: OptionEvaluation
    matches: tuple[Preference, ...]
    misses: tuple[Preference, ...]

    @property
    def miss_vector(self) -> tuple[bool, ...]:
        return tuple(preference in self.misses for preference in Preference)


def _applicable_preferences(
    option: TravelOption,
    traveler: User,
    arrive_by: datetime | None,
    requested_cabin: Cabin | None,
) -> dict[Preference, bool]:
    """Preferences that apply to this trip, mapped to whether the option meets each."""
    applicable: dict[Preference, bool] = {}
    if arrive_by is not None:
        applicable[Preference.ARRIVES_ON_TIME] = option.last_leg.arrives_at <= arrive_by
    if requested_cabin is not None:
        applicable[Preference.REQUESTED_CABIN] = option.cabin == requested_cabin
    if traveler.prefers_nonstop:
        applicable[Preference.NONSTOP] = option.stops == 0
    if traveler.avoids_red_eyes:
        applicable[Preference.NO_RED_EYE] = not option.is_red_eye
    if traveler.preferred_airlines:
        applicable[Preference.PREFERRED_AIRLINE] = any(
            airline in traveler.preferred_airlines for airline in option.airlines
        )
    return applicable


def rank(
    evaluations: list[OptionEvaluation],
    traveler: User,
    arrive_by: datetime | None = None,
    requested_cabin: Cabin | None = None,
) -> list[RankedOption]:
    """Order options by preference fit, then price, then total travel time.

    Missing a higher-priority preference always ranks below missing only
    lower-priority ones. Policy compliance is not considered here; deciding
    between compliant and approval-needing options is `decisions.decide`'s job.
    """
    ranked = []
    for evaluation in evaluations:
        applicable = _applicable_preferences(
            evaluation.option, traveler, arrive_by, requested_cabin
        )
        ranked.append(
            RankedOption(
                evaluation=evaluation,
                matches=tuple(p for p, met in applicable.items() if met),
                misses=tuple(p for p, met in applicable.items() if not met),
            )
        )
    return sorted(
        ranked,
        key=lambda r: (r.miss_vector, r.evaluation.option.price, r.evaluation.option.total_minutes),
    )
