"""Choosing which variants to actually run.

Crossing every scenario with every level of every factor is exponential and nobody
runs it. Pairwise covering is the standard first answer: every *pair* of levels appears
together in at least one run, which catches the large majority of interaction faults at
a small multiple of the base count rather than a product.

Two things make this honest rather than arbitrary.

**Coverage is reported, not asserted.** The plan says how many pairs it covers out of
how many exist. A design that misses pairs says so.

**Test volume is derived, not decreed.** The old generator had a
`VARIATIONS_BY_MATERIALITY` table marked *placeholder — pending sign-off*, and it was
the only thing connecting risk to effort. Here a scenario's materiality comes from its
own contract — whether any assertion on it can block — so the extra adverse run that
high-materiality scenarios get is traceable to the policy rather than to an unapproved
number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metric.enrich.factors import Catalogue, Factor
from metric.ontology.ids import assertion_id

Assignment = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class Variant:
    id: str
    scenario: str
    levels: Assignment
    reason: str

    @property
    def summary(self) -> str:
        return ", ".join(f"{name}={level}" for name, level in self.levels)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scenario": self.scenario,
            "levels": [list(pair) for pair in self.levels],
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class Plan:
    variants: tuple[Variant, ...]
    pairs_covered: int
    pairs_total: int
    excluded: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.pairs_covered == self.pairs_total

    def for_scenario(self, scenario: str) -> tuple[Variant, ...]:
        return tuple(v for v in self.variants if v.scenario == scenario)

    def as_dict(self) -> dict[str, Any]:
        return {
            "variants": [v.as_dict() for v in self.variants],
            "pairs_covered": self.pairs_covered,
            "pairs_total": self.pairs_total,
            "excluded": list(self.excluded),
        }


def covering_array(factors: tuple[Factor, ...]) -> list[Assignment]:
    """A greedy pairwise covering array over `factors`.

    Greedy rather than optimal: each row is seeded with an uncovered pair and then
    filled a factor at a time, always taking the level that covers the most pairs still
    missing. It produces a few more rows than an optimal design and is deterministic,
    which matters more here — a test plan that changes size between runs cannot be
    compared with the last one.
    """
    if len(factors) < 2:
        return [((f.name, level),) for f in factors for level in f.levels]

    uncovered = {
        ((i, a), (j, b))
        for i in range(len(factors))
        for j in range(i + 1, len(factors))
        for a in factors[i].levels
        for b in factors[j].levels
    }

    rows: list[Assignment] = []
    while uncovered:
        (first_index, first_level), (second_index, second_level) = min(uncovered)
        chosen: dict[int, str] = {first_index: first_level, second_index: second_level}

        for index, factor in enumerate(factors):
            if index in chosen:
                continue
            chosen[index] = _best_level(factor, uncovered, chosen, index)

        rows.append(tuple((factors[i].name, chosen[i]) for i in sorted(chosen)))
        uncovered -= _pairs_of(chosen)

    return rows


def plan(scenarios: dict[str, bool], catalogue: Catalogue) -> Plan:
    """Build a plan across scenarios. `scenarios` maps id to "can anything here block?"."""
    factors = catalogue.invariant
    excluded = tuple(
        f"{f.name} changes what is required, so it needs its own base rather than a variant"
        for f in catalogue.situational
    )
    if not factors:
        return Plan((), 0, 0, excluded)

    rows = covering_array(factors)
    variants: list[Variant] = []
    for scenario, blocking in sorted(scenarios.items()):
        for row in rows:
            variants.append(_variant(scenario, row, "pairwise"))
        if blocking:
            adverse = _adverse(factors)
            if adverse and adverse not in rows:
                variants.append(_variant(scenario, adverse, "adverse"))

    return Plan(
        variants=tuple(variants),
        pairs_covered=len({p for row in rows for p in _pairs_of(_as_indexed(row, factors))}),
        pairs_total=_total_pairs(factors),
        excluded=excluded,
    )


def _variant(scenario: str, levels: Assignment, reason: str) -> Variant:
    return Variant(
        id=assertion_id("variant", scenario, *(f"{n}={v}" for n, v in levels)),
        scenario=scenario,
        levels=levels,
        reason=reason,
    )


def _best_level(
    factor: Factor,
    uncovered: set[tuple[tuple[int, str], tuple[int, str]]],
    chosen: dict[int, str],
    index: int,
) -> str:
    """The level covering the most still-missing pairs, ties broken by declared order."""
    scored = [
        (_gain(uncovered, chosen, index, level), -position, level)
        for position, level in enumerate(factor.levels)
    ]
    return max(scored)[2]


def _adverse(factors: tuple[Factor, ...]) -> Assignment | None:
    """Every factor at its hardest declared level, for scenarios that can block.

    One row, not a sweep: the point is that the case which matters most is seen under
    the worst conditions the catalogue knows how to produce.
    """
    if not any(f.adverse for f in factors):
        return None
    return tuple((f.name, f.adverse or f.baseline) for f in factors)


def _as_indexed(row: Assignment, factors: tuple[Factor, ...]) -> dict[int, str]:
    positions = {f.name: i for i, f in enumerate(factors)}
    return {positions[name]: level for name, level in row if name in positions}


def _pairs_of(chosen: dict[int, str]) -> set[tuple[tuple[int, str], tuple[int, str]]]:
    indexes = sorted(chosen)
    return {
        ((i, chosen[i]), (j, chosen[j]))
        for position, i in enumerate(indexes)
        for j in indexes[position + 1 :]
    }


def _gain(
    uncovered: set[tuple[tuple[int, str], tuple[int, str]]],
    chosen: dict[int, str],
    index: int,
    level: str,
) -> int:
    candidate = {**chosen, index: level}
    return len(_pairs_of(candidate) & uncovered)


def _total_pairs(factors: tuple[Factor, ...]) -> int:
    return sum(
        len(factors[i].levels) * len(factors[j].levels)
        for i in range(len(factors))
        for j in range(i + 1, len(factors))
    )
