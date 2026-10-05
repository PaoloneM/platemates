"""Seasonality expressed as sets of calendar months (1 = January ... 12 = December).

Months are what is stored, because availability of produce does not follow equinoxes and because
months compose by plain set intersection. An empty set always means "all year": that is the safe
default for an ingredient nobody has classified yet.

Users edit seasonality in two modes: by season (the default, four meteorological seasons, each a
fixed group of three months) or, in advanced mode, by individual month. Seasons are only a view
onto months: choosing "summer" stores [6, 7, 8].
"""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

ALL_MONTHS: frozenset[int] = frozenset(range(1, 13))

# Meteorological seasons (northern hemisphere), in calendar order.
SEASON_MONTHS: dict[str, frozenset[int]] = {
    "winter": frozenset({12, 1, 2}),
    "spring": frozenset({3, 4, 5}),
    "summer": frozenset({6, 7, 8}),
    "autumn": frozenset({9, 10, 11}),
}


def month_set_field(help_text: str) -> ArrayField:
    return ArrayField(
        models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)]),
        default=list,
        blank=True,
        help_text=f"{help_text} Calendar months 1-12; empty means all year.",
    )


def as_months(months: Iterable[int] | None) -> frozenset[int]:
    """Normalize a stored month list: empty or missing means all year."""
    values = frozenset(months or ())
    return values or ALL_MONTHS


def intersect_months(*month_lists: Iterable[int] | None) -> frozenset[int]:
    """Months in which every input is in season. May be empty: nothing overlaps."""
    result = ALL_MONTHS
    for months in month_lists:
        result &= as_months(months)
    return result


def seasons_to_months(seasons: Iterable[str]) -> list[int]:
    """Months covered by the given seasons, sorted. Unknown names raise `KeyError`."""
    months: set[int] = set()
    for season in seasons:
        months |= SEASON_MONTHS[season]
    return sorted(months)


def months_to_seasons(months: Iterable[int] | None) -> list[str]:
    """Seasons whose months are all included. Partially covered seasons are left out."""
    values = as_months(months)
    return [name for name, season in SEASON_MONTHS.items() if season <= values]


def is_season_aligned(months: Iterable[int] | None) -> bool:
    """Whether the months are exactly a union of whole seasons, i.e. editable in season mode."""
    values = as_months(months)
    return values == frozenset(seasons_to_months(months_to_seasons(values)))
