"""Verdicts, and the four answers a grader is allowed to give.

`pass` and `fail` are the easy two. The other two carry most of the value:

**`not_applicable`** — the situation the assertion is about did not arise. A retry rule
on a run that never failed is not a pass and not a gap; it simply did not apply.
Scoring it as a pass inflates every aggregate.

**`undecided`** — the situation may well have arisen and the trace does not let us
tell. This is the telemetry gap, and it is the single number worth watching: it says
how much of the policy this instrumentation can actually hold an agent to. Folding it
into either pass or fail is how an evaluator comes to look confident about a blind
spot.

There is no overall score here on purpose. Dimensions are reported separately because a
run can reach the right outcome while breaking a rule, or break no rule and end in the
wrong place, and a single number destroys exactly the distinction a reviewer needs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from metric.contract.model import Assertion, Contract, Dimension

Outcome = Literal["pass", "fail", "undecided", "not_applicable"]


@dataclass(frozen=True, slots=True)
class Verdict:
    assertion: Assertion
    outcome: Outcome
    detail: str
    observed: tuple[str, ...] = ()

    @property
    def blocking_failure(self) -> bool:
        return self.outcome == "fail" and self.assertion.blocking

    def as_dict(self) -> dict[str, Any]:
        return {
            "assertion": self.assertion.as_dict(),
            "outcome": self.outcome,
            "detail": self.detail,
            "observed": list(self.observed),
        }


@dataclass(frozen=True, slots=True)
class Evaluation:
    contract: Contract
    verdicts: tuple[Verdict, ...]
    binding_coverage: float
    unbound: tuple[str, ...]

    def by_outcome(self, outcome: Outcome) -> tuple[Verdict, ...]:
        return tuple(v for v in self.verdicts if v.outcome == outcome)

    def by_dimension(self) -> dict[Dimension, Counter[str]]:
        found: dict[Dimension, Counter[str]] = {}
        for verdict in self.verdicts:
            found.setdefault(verdict.assertion.dimension, Counter())[verdict.outcome] += 1
        return found

    @property
    def failures(self) -> tuple[Verdict, ...]:
        """Failures worst first, so the first thing read is the worst thing found."""
        order = {"blocker": 0, "error": 1, "warning": 2, "info": 3, "advisory": 4}
        return tuple(
            sorted(
                self.by_outcome("fail"),
                key=lambda v: (order[v.assertion.severity], v.assertion.kind, v.assertion.id),
            )
        )

    @property
    def blocked(self) -> bool:
        return any(v.blocking_failure for v in self.verdicts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.as_dict(),
            "verdicts": [v.as_dict() for v in self.verdicts],
            "binding_coverage": round(self.binding_coverage, 3),
            "unbound": list(self.unbound),
            "summary": {
                "blocked": self.blocked,
                "counts": dict(Counter(v.outcome for v in self.verdicts)),
                "dimensions": {
                    dimension: dict(counts) for dimension, counts in self.by_dimension().items()
                },
            },
        }


def verdict(assertion: Assertion, outcome: Outcome, detail: str, *refs: str) -> Verdict:
    return Verdict(assertion=assertion, outcome=outcome, detail=detail, observed=tuple(refs))
