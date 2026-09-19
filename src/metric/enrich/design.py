"""Choosing which variants to actually run.

Crossing every base with every level of every factor is exponential and nobody runs it.
Pairwise covering is the standard first answer: every *pair* of levels appears together
in at least one run, which catches the large majority of interaction faults at a small
multiple of the base count rather than a product.

**Two arrangements**, and the choice is a real one.

- **Crossed** — the design covers presentation factors only, and every base is paired
  with every row. Exhaustive per base, and the cost grows with the number of bases.
- **Embedded** — the base is promoted to a factor and varied jointly with the rest. The
  suite is a fixed size regardless of how many bases there are, and because the base is
  a factor, a failure can be attributed to the base item itself.

Embedding under a modest budget can leave individual bases under-represented or missing
entirely, which is the one way this arrangement can quietly mislead. The resolution here
is the conservative one: the base is treated as a **balanced blocking factor** — equal
runs per base — with the presentation factors spread within that allocation rather than
sampled jointly across it. A base that gets no runs at all is reported, not hidden.

Three things make this honest rather than arbitrary.

**Relevance is applied before the design, not after.** A factor meaningless for a base
is not crossed with it. Spending budget on cells that cannot fail for the reason the
column claims to measure dilutes every attribution drawn from that column.

**Coverage is reported, not asserted.** The plan says how many pairs it covers out of
how many exist. A design that misses pairs says so, and an embedded design usually does.

**Test volume is derived, not decreed.** The old generator had a
`VARIATIONS_BY_MATERIALITY` table marked *placeholder — pending sign-off*, and it was
the only thing connecting risk to effort. Here a base's materiality comes from its own
contract — whether any assertion on it can block — so the extra adverse run that
high-materiality bases get is traceable to the policy rather than to an unapproved
number.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from metric.enrich.factors import Catalogue, Factor, Profile
from metric.ontology.ids import assertion_id

Assignment = tuple[tuple[str, str], ...]
_Pair = tuple[tuple[int, str], tuple[int, str]]


@dataclass(frozen=True, slots=True)
class Item:
    """A base, as the design layer needs to see it.

    Deliberately not the `Scenario` type. The design layer has no business knowing how a
    base was mined, and keeping it to these five fields is what lets graph-mined, seeded
    and supplied bases go through the same planner.
    """

    id: str
    category: str
    family: str
    answer_type: str
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class Variant:
    id: str
    scenario: str
    levels: Assignment
    reason: str

    @property
    def summary(self) -> str:
        return ", ".join(f"{name}={level}" for name, level in self.levels)

    @property
    def factor_levels(self) -> dict[str, str]:
        """The chosen levels as data, for a materialiser to render."""
        return dict(self.levels)

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
    arrangement: str = "crossed"
    notes: tuple[str, ...] = ()
    dropped: dict[str, tuple[str, ...]] = field(default_factory=dict)

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
            "arrangement": self.arrangement,
            "notes": list(self.notes),
            "dropped": {k: list(v) for k, v in sorted(self.dropped.items())},
        }


def covering_array(factors: Sequence[Factor]) -> list[Assignment]:
    """A greedy pairwise covering array over `factors`.

    Greedy rather than optimal: each row is seeded with an uncovered pair and then
    filled a factor at a time, always taking the level that covers the most pairs still
    missing. It produces a few more rows than an optimal design and is deterministic,
    which matters more here — a test plan that changes size between runs cannot be
    compared with the last one.
    """
    if len(factors) < 2:
        return [((f.name, level),) for f in factors for level in f.levels]

    uncovered: set[_Pair] = {
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


def plan(
    items: Sequence[Item],
    catalogue: Catalogue,
    *,
    arrangement: str = "crossed",
    profile: Profile | None = None,
    budget: int = 0,
    adverse_run: bool = True,
) -> Plan:
    """Build a plan over bases, applying the profile and then relevance."""
    active = catalogue.apply(profile)
    if profile is not None and profile.arrangement:
        arrangement = profile.arrangement
    if profile is not None and profile.categories:
        items = [i for i in items if i.category in set(profile.categories)]

    excluded = tuple(
        f"{f.name} changes what is required, so it needs its own base rather than a variant"
        for f in active.situational
    )
    if not active.invariant or not items:
        return Plan((), 0, 0, excluded, arrangement)

    relevance = {
        item.id: active.relevant(
            family=item.family, answer_type=item.answer_type, category=item.category
        )
        for item in items
    }
    dropped = {
        item.id: tuple(
            f.name for f in active.invariant if f not in relevance[item.id]
        )
        for item in items
        if len(relevance[item.id]) < len(active.invariant)
    }

    if arrangement == "embedded":
        return _embedded(items, active, relevance, excluded, dropped, budget, adverse_run)
    return _crossed(items, active, relevance, excluded, dropped, adverse_run)


def _crossed(
    items: Sequence[Item],
    catalogue: Catalogue,
    relevance: dict[str, tuple[Factor, ...]],
    excluded: tuple[str, ...],
    dropped: dict[str, tuple[str, ...]],
    adverse_run: bool,
) -> Plan:
    """Every base against the full covering array over the factors relevant to it."""
    arrays: dict[tuple[str, ...], list[Assignment]] = {}
    variants: list[Variant] = []
    notes: list[str] = []

    for item in sorted(items, key=lambda i: i.id):
        factors = relevance[item.id]
        if not factors:
            notes.append(f"{item.id} ({item.category}): no factor applies, so it runs once bare")
            variants.append(_variant(item.id, (), "bare"))
            continue

        key = tuple(f.name for f in factors)
        rows = arrays.setdefault(key, covering_array(factors))
        variants.extend(_variant(item.id, row, "pairwise") for row in rows)

        if adverse_run and item.blocking:
            worst = _adverse(factors)
            if worst is not None and worst not in rows:
                variants.append(_variant(item.id, worst, "adverse"))

    return Plan(
        variants=tuple(variants),
        pairs_covered=_covered(catalogue.invariant, [v.levels for v in variants]),
        pairs_total=_reachable(catalogue.invariant, relevance),
        excluded=excluded,
        arrangement="crossed",
        notes=tuple(notes),
        dropped=dropped,
    )


def _embedded(
    items: Sequence[Item],
    catalogue: Catalogue,
    relevance: dict[str, tuple[Factor, ...]],
    excluded: tuple[str, ...],
    dropped: dict[str, tuple[str, ...]],
    budget: int,
    adverse_run: bool,
) -> Plan:
    """The base as a balanced blocking factor: equal runs each, rows spread within.

    Rows are taken from the shared covering array at a rotating offset, so the suite as
    a whole still sweeps it even though no single base sees all of it. That is the trade
    being made, and `pairs_covered` reports what it cost.
    """
    ordered = sorted(items, key=lambda i: i.id)
    rows = covering_array(catalogue.invariant)
    requested = budget or len(rows)
    per_base = max(1, requested // len(ordered))

    variants: list[Variant] = []
    notes = [
        f"embedded: {len(ordered)} bases x {per_base} runs each, drawn from a "
        f"{len(rows)}-row array; no base sees the whole array"
    ]
    if requested < len(ordered):
        notes.append(
            f"a budget of {requested} is smaller than the {len(ordered)} bases, so each "
            "was given one run rather than being dropped"
        )

    offset = 0
    for item in ordered:
        allowed = {f.name for f in relevance[item.id]}
        for step in range(per_base):
            row = rows[(offset + step) % len(rows)]
            variants.append(
                _variant(item.id, tuple(p for p in row if p[0] in allowed), "embedded")
            )
        offset += per_base
        if adverse_run and item.blocking:
            worst = _adverse(relevance[item.id])
            if worst is not None:
                variants.append(_variant(item.id, worst, "adverse"))

    return Plan(
        variants=tuple(variants),
        pairs_covered=_covered(catalogue.invariant, [v.levels for v in variants]),
        pairs_total=_reachable(catalogue.invariant, relevance),
        excluded=excluded,
        arrangement="embedded",
        notes=tuple(notes),
        dropped=dropped,
    )


def _variant(scenario: str, levels: Assignment, reason: str) -> Variant:
    return Variant(
        id=assertion_id("variant", scenario, reason, *(f"{n}={v}" for n, v in levels)),
        scenario=scenario,
        levels=levels,
        reason=reason,
    )


def _best_level(
    factor: Factor, uncovered: set[_Pair], chosen: dict[int, str], index: int
) -> str:
    """The level covering the most still-missing pairs, ties broken by declared order."""
    scored = [
        (_gain(uncovered, chosen, index, level), -position, level)
        for position, level in enumerate(factor.levels)
    ]
    return max(scored)[2]


def _adverse(factors: Sequence[Factor]) -> Assignment | None:
    """Every factor at its hardest declared level, for bases that can block.

    One row, not a sweep: the point is that the case which matters most is seen under
    the worst conditions the catalogue knows how to produce.
    """
    if not any(f.adverse for f in factors):
        return None
    return tuple((f.name, f.adverse or f.baseline) for f in factors)


def _covered(factors: Sequence[Factor], rows: Sequence[Assignment]) -> int:
    positions = {f.name: i for i, f in enumerate(factors)}
    seen: set[_Pair] = set()
    for row in rows:
        seen |= _pairs_of({positions[n]: v for n, v in row if n in positions})
    return len(seen)


def _pairs_of(chosen: dict[int, str]) -> set[_Pair]:
    indexes = sorted(chosen)
    return {
        ((i, chosen[i]), (j, chosen[j]))
        for position, i in enumerate(indexes)
        for j in indexes[position + 1 :]
    }


def _gain(uncovered: set[_Pair], chosen: dict[int, str], index: int, level: str) -> int:
    return len(_pairs_of({**chosen, index: level}) & uncovered)


def _reachable(factors: Sequence[Factor], relevance: dict[str, tuple[Factor, ...]]) -> int:
    """The pairs any base could have exercised, which is the honest denominator.

    Counting against the full catalogue would charge the design for pairs relevance
    ruled out — `number_reading` against `paraphrase` when no base has a numeric answer —
    and a plan can then never be complete however well it is built. What a coverage
    figure should answer is whether the design used the bases it had, not whether the
    catalogue happened to contain a combination the corpus has no use for.
    """
    positions = {f.name: i for i, f in enumerate(factors)}
    reachable: set[_Pair] = set()
    for relevant in relevance.values():
        indexes = sorted(positions[f.name] for f in relevant if f.name in positions)
        for position, i in enumerate(indexes):
            for j in indexes[position + 1 :]:
                reachable |= {
                    ((i, a), (j, b))
                    for a in factors[i].levels
                    for b in factors[j].levels
                }
    return len(reachable)
