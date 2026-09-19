"""What made the agent fail: which factor level, and which component.

The design exists to make this question answerable. Bases fix what is required;
enrichment varies only presentation; so when a cohort of runs comes back, a difference in
pass rate between two levels of one factor is attributable to that level rather than to
the situation having changed underneath it. This module is where that is finally cashed
in, and it is deliberately small — the statistics are only honest because the design
upstream was.

Three things it refuses to do, each because the alternative produces a number that reads
as evidence and is not.

**No bare pass rates.** Every rate carries a Wilson interval. Four of five passing is not
80% ± nothing; at that sample size the interval runs from roughly 38% to 96%, and a
report that prints 80% invites a decision the data cannot support.

**No unadjusted comparisons.** Testing every level of every factor means dozens of
comparisons, and at a nominal 5% one in twenty looks significant by chance alone.
Benjamini–Hochberg controls the false discovery rate across the family, so "these three
levels matter" means it across all the tests that were run, not across the three that
happened to be interesting.

**No effect without a direction and a size.** An odds ratio and the interval around it,
not a p-value on its own. A level that halves the odds of passing and a level that moves
them by a percent can both be significant in a large enough cohort, and only one is worth
acting on.

Weak-link attribution is the other half and needs no statistics: within a single failing
run, the first component in execution order whose output was wrong is the one to fix.
Everything downstream of it was working from bad input and its failure is a consequence,
not a cause.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

Z = 1.959963984540054  # two-sided 95%


@dataclass(frozen=True, slots=True)
class Outcome:
    """One run: which base, under which levels, and whether it passed."""

    variant: str
    scenario: str
    levels: tuple[tuple[str, str], ...]
    passed: bool

    def level(self, factor: str) -> str | None:
        return next((v for name, v in self.levels if name == factor), None)


@dataclass(frozen=True, slots=True)
class Interval:
    low: float
    high: float

    def __str__(self) -> str:
        return f"[{self.low:.1%}, {self.high:.1%}]"

    def as_dict(self) -> dict[str, float]:
        return {"low": self.low, "high": self.high}


@dataclass(frozen=True, slots=True)
class Rate:
    passed: int
    total: int

    @property
    def value(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def interval(self) -> Interval:
        return wilson(self.passed, self.total)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "total": self.total,
            "rate": self.value,
            "interval": self.interval.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class LevelEffect:
    """One level of one factor, against every other level of that factor."""

    factor: str
    level: str
    rate: Rate
    baseline: Rate
    odds_ratio: float
    odds_interval: Interval
    p_value: float
    q_value: float = 1.0

    @property
    def significant(self) -> bool:
        """Survives false-discovery correction and the interval excludes no effect."""
        return self.q_value < 0.05 and not (self.odds_interval.low < 1.0 < self.odds_interval.high)

    @property
    def direction(self) -> str:
        if not self.significant:
            return "none"
        return "harms" if self.odds_ratio < 1.0 else "helps"

    def as_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "level": self.level,
            "rate": self.rate.as_dict(),
            "baseline": self.baseline.as_dict(),
            "odds_ratio": self.odds_ratio,
            "odds_interval": self.odds_interval.as_dict(),
            "p_value": self.p_value,
            "q_value": self.q_value,
            "significant": self.significant,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class Attribution:
    overall: Rate
    effects: tuple[LevelEffect, ...]
    by_scenario: dict[str, Rate]
    notes: tuple[str, ...]

    @property
    def significant(self) -> tuple[LevelEffect, ...]:
        return tuple(e for e in self.effects if e.significant)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.as_dict(),
            "effects": [e.as_dict() for e in self.effects],
            "by_scenario": {k: v.as_dict() for k, v in sorted(self.by_scenario.items())},
            "notes": list(self.notes),
        }


def attribute(outcomes: Sequence[Outcome], *, min_cell: int = 5) -> Attribution:
    """Per-level effects across a cohort, corrected for multiplicity."""
    if not outcomes:
        return Attribution(Rate(0, 0), (), {}, ("no runs to attribute",))

    overall = Rate(sum(1 for o in outcomes if o.passed), len(outcomes))
    notes: list[str] = []

    factors: dict[str, set[str]] = {}
    for outcome in outcomes:
        for name, level in outcome.levels:
            factors.setdefault(name, set()).add(level)

    raw: list[LevelEffect] = []
    for factor in sorted(factors):
        levels = sorted(factors[factor])
        if len(levels) < 2:
            notes.append(f"{factor} was held at one level, so nothing can be attributed to it")
            continue
        for level in levels:
            here = [o for o in outcomes if o.level(factor) == level]
            rest = [o for o in outcomes if o.level(factor) not in (level, None)]
            if len(here) < min_cell or len(rest) < min_cell:
                notes.append(
                    f"{factor}={level} has {len(here)} runs against {len(rest)}; "
                    f"fewer than {min_cell} either side is not enough to compare"
                )
                continue
            raw.append(_effect(factor, level, here, rest))

    return Attribution(
        overall=overall,
        effects=_correct(raw),
        by_scenario=_by_scenario(outcomes),
        notes=tuple(notes),
    )


def _effect(
    factor: str, level: str, here: Sequence[Outcome], rest: Sequence[Outcome]
) -> LevelEffect:
    a = sum(1 for o in here if o.passed)
    b = len(here) - a
    c = sum(1 for o in rest if o.passed)
    d = len(rest) - c

    ratio, interval, p_value = _odds(a, b, c, d)
    return LevelEffect(
        factor=factor,
        level=level,
        rate=Rate(a, len(here)),
        baseline=Rate(c, len(rest)),
        odds_ratio=ratio,
        odds_interval=interval,
        p_value=p_value,
    )


def _odds(a: int, b: int, c: int, d: int) -> tuple[float, Interval, float]:
    """Odds ratio with a Haldane–Anscombe correction and a Wald interval on the log.

    The half-count correction is what keeps a zero cell — every run at one level
    failing, which is exactly the case worth reporting — from producing an infinite
    ratio and no interval at all.
    """
    a_, b_, c_, d_ = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    ratio = (a_ / b_) / (c_ / d_)
    log_ratio = math.log(ratio)
    error = math.sqrt(1 / a_ + 1 / b_ + 1 / c_ + 1 / d_)
    interval = Interval(math.exp(log_ratio - Z * error), math.exp(log_ratio + Z * error))
    p_value = 2 * (1 - _normal_cdf(abs(log_ratio) / error))
    return ratio, interval, p_value


def _correct(effects: Sequence[LevelEffect]) -> tuple[LevelEffect, ...]:
    """Benjamini–Hochberg across every comparison made, not each one alone."""
    if not effects:
        return ()
    total = len(effects)
    order = sorted(range(total), key=lambda i: effects[i].p_value)

    running = 1.0
    q_values = [1.0] * total
    for rank, index in reversed(list(enumerate(order, start=1))):
        running = min(running, effects[index].p_value * total / rank)
        q_values[index] = running

    corrected = [replace(effect, q_value=q_values[i]) for i, effect in enumerate(effects)]
    return tuple(sorted(corrected, key=lambda e: (e.factor, e.level)))


def _by_scenario(outcomes: Sequence[Outcome]) -> dict[str, Rate]:
    counts: dict[str, list[int]] = {}
    for outcome in outcomes:
        cell = counts.setdefault(outcome.scenario, [0, 0])
        cell[0] += int(outcome.passed)
        cell[1] += 1
    return {name: Rate(passed, total) for name, (passed, total) in counts.items()}


def wilson(passed: int, total: int) -> Interval:
    """A score interval, which behaves at the edges where the normal one does not.

    At 5/5 the normal approximation gives [1.0, 1.0] — perfect confidence from five
    observations. Wilson gives roughly [0.57, 1.0], which is what five observations
    actually support.
    """
    if total == 0:
        return Interval(0.0, 0.0)
    rate = passed / total
    denominator = 1 + Z**2 / total
    centre = (rate + Z**2 / (2 * total)) / denominator
    spread = (
        Z * math.sqrt(rate * (1 - rate) / total + Z**2 / (4 * total**2)) / denominator
    )
    return Interval(max(0.0, centre - spread), min(1.0, centre + spread))


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# --------------------------------------------------------------------------------------
# weak link


@dataclass(frozen=True, slots=True)
class WeakLink:
    """The first thing in execution order that went wrong, and what followed it."""

    turn: int
    component: str
    finding: str
    downstream: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "component": self.component,
            "finding": self.finding,
            "downstream": list(self.downstream),
        }


def weak_link(turns: Sequence[Any]) -> WeakLink | None:
    """The earliest turn with a finding, and the tool it was working with.

    Blame lands on the first component whose output was wrong, because everything after
    it was reasoning from bad input. A failure report that lists every turn with a
    finding makes the fourth consequence look as important as the cause.

    `turns` is a sequence of `TurnTruth`. It is typed loosely on purpose: attribution
    sits above evaluation and importing the other way would make the reverse mapping
    depend on the reporting layer.
    """
    for truth in turns:
        if not truth.findings:
            continue
        tools = truth.observed.tools or truth.expected.tools
        return WeakLink(
            turn=truth.turn,
            component=tools[0] if tools else "(no tool call)",
            finding=truth.findings[0],
            downstream=tuple(
                f"turn {t.turn}: {t.findings[0]}"
                for t in turns
                if t.turn > truth.turn and t.findings
            ),
        )
    return None
