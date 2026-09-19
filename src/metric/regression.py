"""Regressing correctness on all factor levels at once.

The marginal comparison in `attribution.py` asks one question at a time: does the pass
rate at this level differ from the pass rate everywhere else? That is the right first
question and it has a known failure, which showed up the first time a real cohort was run
through it.

An agent was built to misbehave under exactly one level, `asr=heavy_noise`. The marginal
attribution found it — and also reported `history=prior_turns`, which the agent had no
reaction to whatsoever. Nothing was wrong with the arithmetic. A pairwise covering array
does not balance every factor within every other's levels, so `history=prior_turns`
happened to sit alongside `heavy_noise` more often than `history=none` did, and inherited
its failures. A marginal comparison cannot tell an effect from the company it keeps.

The fix is the one the book prescribes: regress binary correctness on all factor levels
jointly, so each coefficient is that level's effect **with the others held fixed**. The
confound then has nothing left to borrow.

Three details that are not decoration:

**Ridge, not optional.** A level under which every run failed — the case most worth
reporting — is perfectly separable, and unpenalised logistic regression sends its
coefficient to infinity and never converges. A small ridge penalty keeps the estimate
finite and the intervals meaningful. It biases coefficients towards zero, which makes the
findings conservative rather than generous, and it is reported rather than hidden.

**The intercept is never penalised.** Shrinking it would pull the whole model's baseline
towards a 50% pass rate, which is a claim about nothing.

**The reference level is stated.** Every coefficient is against one level of its factor,
and a reader who does not know which is reading an unlabelled number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from metric.attribution import Interval, Outcome, Z, _normal_cdf

DEFAULT_RIDGE = 1.0
MAX_ITERATIONS = 100
TOLERANCE = 1e-8


@dataclass(frozen=True, slots=True)
class Coefficient:
    """One level's effect, with every other factor held fixed."""

    factor: str
    level: str
    reference: str
    estimate: float
    standard_error: float
    odds_ratio: float
    odds_interval: Interval
    p_value: float
    q_value: float = 1.0

    @property
    def significant(self) -> bool:
        return self.q_value < 0.05 and not (
            self.odds_interval.low < 1.0 < self.odds_interval.high
        )

    @property
    def direction(self) -> str:
        if not self.significant:
            return "none"
        return "harms" if self.odds_ratio < 1.0 else "helps"

    def as_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "level": self.level,
            "reference": self.reference,
            "estimate": self.estimate,
            "standard_error": self.standard_error,
            "odds_ratio": self.odds_ratio,
            "odds_interval": self.odds_interval.as_dict(),
            "p_value": self.p_value,
            "q_value": self.q_value,
            "significant": self.significant,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class Model:
    coefficients: tuple[Coefficient, ...]
    intercept: float
    pseudo_r2: float
    runs: int
    converged: bool
    ridge: float
    notes: tuple[str, ...] = ()

    @property
    def significant(self) -> tuple[Coefficient, ...]:
        return tuple(c for c in self.coefficients if c.significant)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coefficients": [c.as_dict() for c in self.coefficients],
            "intercept": self.intercept,
            "pseudo_r2": self.pseudo_r2,
            "runs": self.runs,
            "converged": self.converged,
            "ridge": self.ridge,
            "notes": list(self.notes),
        }


def adjust(
    outcomes: Sequence[Outcome], *, ridge: float = DEFAULT_RIDGE, min_cell: int = 5
) -> Model:
    """Fit correctness against every factor level at once."""
    if not outcomes:
        return Model((), 0.0, 0.0, 0, False, ridge, ("no runs to model",))

    columns, notes = _columns(outcomes, min_cell)
    if not columns:
        return Model(
            (), 0.0, 0.0, len(outcomes), False, ridge, (*notes, "no factor varies enough to fit")
        )

    design = [[1.0, *(1.0 if run.level(f) == level else 0.0 for f, level, _ in columns)]
              for run in outcomes]
    response = [1.0 if run.passed else 0.0 for run in outcomes]

    beta, converged = _fit(design, response, ridge)
    errors = _standard_errors(design, beta, ridge)

    raw: list[Coefficient] = []
    for index, (factor, level, reference) in enumerate(columns, start=1):
        raw.append(_coefficient(factor, level, reference, beta[index], errors[index]))

    if not converged:
        notes = (*notes, "the fit did not converge; treat these coefficients as indicative")

    return Model(
        coefficients=_correct(raw),
        intercept=beta[0],
        pseudo_r2=_mcfadden(design, response, beta),
        runs=len(outcomes),
        converged=converged,
        ridge=ridge,
        notes=notes,
    )


def _columns(
    outcomes: Sequence[Outcome], min_cell: int
) -> tuple[list[tuple[str, str, str]], tuple[str, ...]]:
    """One column per non-reference level, with the reference it is measured against.

    The reference is the level with the most runs, so the comparison every other level
    makes is against the best-observed one rather than against whichever sorts first.
    """
    counts: dict[str, dict[str, int]] = {}
    for run in outcomes:
        for factor, level in run.levels:
            counts.setdefault(factor, {})[level] = counts.setdefault(factor, {}).get(level, 0) + 1

    columns: list[tuple[str, str, str]] = []
    notes: list[str] = []
    for factor in sorted(counts):
        levels = counts[factor]
        usable = sorted(level for level, n in levels.items() if n >= min_cell)
        if len(usable) < 2:
            notes.append(
                f"{factor} has fewer than two levels with {min_cell} runs, so it was left "
                "out of the model"
            )
            continue
        reference = max(usable, key=lambda level: (levels[level], level))
        columns.extend(
            (factor, level, reference) for level in usable if level != reference
        )
    return columns, tuple(notes)


def _fit(
    design: list[list[float]], response: list[float], ridge: float
) -> tuple[list[float], bool]:
    """Penalised Newton-Raphson. The penalty is what makes a separable level finite."""
    width = len(design[0])
    beta = [0.0] * width

    for _ in range(MAX_ITERATIONS):
        gradient = [0.0] * width
        hessian = [[0.0] * width for _ in range(width)]

        for row, y in zip(design, response, strict=True):
            mu = _sigmoid(sum(b * x for b, x in zip(beta, row, strict=True)))
            weight = max(mu * (1 - mu), 1e-10)
            residual = y - mu
            for i in range(width):
                if row[i] == 0.0:
                    continue
                gradient[i] += row[i] * residual
                for j in range(width):
                    hessian[i][j] += row[i] * weight * row[j]

        for i in range(1, width):  # never penalise the intercept
            gradient[i] -= ridge * beta[i]
            hessian[i][i] += ridge

        step = _solve(hessian, gradient)
        if step is None:
            return beta, False
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < TOLERANCE:
            return beta, True

    return beta, False


def _standard_errors(
    design: list[list[float]], beta: list[float], ridge: float
) -> list[float]:
    """From the inverse penalised Hessian.

    Approximate under a ridge penalty — the usual caveat — and the alternative is no
    interval at all on exactly the coefficients that matter most.
    """
    width = len(beta)
    hessian = [[0.0] * width for _ in range(width)]
    for row in design:
        mu = _sigmoid(sum(b * x for b, x in zip(beta, row, strict=True)))
        weight = max(mu * (1 - mu), 1e-10)
        for i in range(width):
            if row[i] == 0.0:
                continue
            for j in range(width):
                hessian[i][j] += row[i] * weight * row[j]
    for i in range(1, width):
        hessian[i][i] += ridge

    inverse = _invert(hessian)
    if inverse is None:
        return [float("inf")] * width
    return [math.sqrt(max(inverse[i][i], 0.0)) for i in range(width)]


def _coefficient(
    factor: str, level: str, reference: str, estimate: float, error: float
) -> Coefficient:
    if not math.isfinite(error) or error == 0.0:
        return Coefficient(
            factor, level, reference, estimate, error, math.exp(estimate), Interval(0.0, 0.0), 1.0
        )
    return Coefficient(
        factor=factor,
        level=level,
        reference=reference,
        estimate=estimate,
        standard_error=error,
        odds_ratio=math.exp(estimate),
        odds_interval=Interval(
            math.exp(estimate - Z * error), math.exp(estimate + Z * error)
        ),
        p_value=2 * (1 - _normal_cdf(abs(estimate) / error)),
    )


def _correct(coefficients: Sequence[Coefficient]) -> tuple[Coefficient, ...]:
    """Benjamini-Hochberg, across the whole model rather than each coefficient alone."""
    from dataclasses import replace

    if not coefficients:
        return ()
    total = len(coefficients)
    order = sorted(range(total), key=lambda i: coefficients[i].p_value)

    running = 1.0
    q_values = [1.0] * total
    for rank, index in reversed(list(enumerate(order, start=1))):
        running = min(running, coefficients[index].p_value * total / rank)
        q_values[index] = running

    adjusted = [replace(c, q_value=q_values[i]) for i, c in enumerate(coefficients)]
    return tuple(sorted(adjusted, key=lambda c: (c.factor, c.level)))


def _mcfadden(design: list[list[float]], response: list[float], beta: list[float]) -> float:
    """1 - fitted log-likelihood / null log-likelihood.

    Not an R-squared, whatever the name suggests. 0.2 to 0.4 is a strong fit by this
    measure and reading it as "20% of variance explained" is how it gets misreported.
    """
    fitted = sum(
        _log_likelihood(y, _sigmoid(sum(b * x for b, x in zip(beta, row, strict=True))))
        for row, y in zip(design, response, strict=True)
    )
    rate = sum(response) / len(response)
    null = sum(_log_likelihood(y, rate) for y in response)
    if null == 0.0:
        return 0.0
    return max(0.0, min(1.0, 1 - fitted / null))


def _log_likelihood(y: float, mu: float) -> float:
    mu = min(max(mu, 1e-12), 1 - 1e-12)
    return y * math.log(mu) + (1 - y) * math.log(1 - mu)


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1 / (1 + math.exp(-min(x, 700.0)))
    value = math.exp(max(x, -700.0))
    return value / (1 + value)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    inverse = _invert(matrix)
    if inverse is None:
        return None
    return [sum(inverse[i][j] * vector[j] for j in range(len(vector))) for i in range(len(vector))]


def _invert(matrix: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan with partial pivoting. `None` when the matrix is singular."""
    size = len(matrix)
    work = [[*row, *(1.0 if i == j else 0.0 for j in range(size))] for i, row in enumerate(matrix)]

    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(work[r][column]))
        if abs(work[pivot][column]) < 1e-12:
            return None
        work[column], work[pivot] = work[pivot], work[column]

        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            factor = work[row][column]
            if factor == 0.0:
                continue
            work[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(work[row], work[column], strict=True)
            ]

    return [row[size:] for row in work]
