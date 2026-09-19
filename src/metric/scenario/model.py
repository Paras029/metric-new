"""What a base scenario is.

The book's unit is a **base**: a situation whose ground truth is fixed and recoverable
from the graph, before any enrichment varies how it is presented. A journey through the
states is one kind of base. So is "the fourth attempt, against a limit of three", and
"a tool this state does not declare", and "the wording this turn must contain".

They share a shape — a subject in the graph, an answer read off the graph, and the set
of entities the contract narrows to — so they share a type. The alternative is a
separate pipeline per category, and then the enrichment layer, the planner, the UI and
the report each learn eleven special cases.

`steps` is filled only by traversal categories. `answer` is the ground truth in the
category's own answer type, and `checked` records whether it survived being recovered a
second time (see `bases.verify`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Step:
    state: str
    decision: str
    outcome: str
    next_state: str

    @property
    def entities(self) -> tuple[str, ...]:
        return tuple(x for x in (self.state, self.decision, self.outcome, self.next_state) if x)


@dataclass(frozen=True, slots=True)
class Scenario:
    """One base: a situation, its ground truth, and where in the graph it came from."""

    id: str
    category: str
    family: str
    answer_type: str
    question: str
    answer: tuple[str, ...]
    subject: tuple[str, ...] = ()
    entry: str = ""
    steps: tuple[Step, ...] = ()
    terminal: str = ""
    ends_as: str = ""
    complete: bool = True
    origin: str = "graph"
    checked: bool = True
    check_note: str = ""

    @property
    def entities(self) -> tuple[str, ...]:
        """Everything this base touches, in encounter order, for narrowing the contract."""
        seen: list[str] = [self.entry] if self.entry else []
        for step in self.steps:
            seen.extend(e for e in step.entities if e not in seen)
        seen.extend(e for e in self.subject if e not in seen)
        return tuple(seen)

    @property
    def length(self) -> int:
        return len(self.steps)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "family": self.family,
            "answer_type": self.answer_type,
            "question": self.question,
            "answer": list(self.answer),
            "subject": list(self.subject),
            "entry": self.entry,
            "terminal": self.terminal,
            "ends_as": self.ends_as,
            "complete": self.complete,
            "origin": self.origin,
            "checked": self.checked,
            "check_note": self.check_note,
            "steps": [
                {
                    "state": s.state,
                    "decision": s.decision,
                    "outcome": s.outcome,
                    "next_state": s.next_state,
                }
                for s in self.steps
            ],
        }


@dataclass(frozen=True, slots=True)
class ScenarioSpace:
    """Every base the graph supports, plus what it could not reach and why."""

    scenarios: tuple[Scenario, ...]
    truncated: bool = False
    uncovered: tuple[tuple[str, str, str], ...] = ()
    unreachable: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    rejected: tuple[Scenario, ...] = ()
    coverage: dict[str, int] = field(default_factory=dict)
    inadmissible: tuple[str, ...] = ()

    def of_category(self, category: str) -> tuple[Scenario, ...]:
        return tuple(s for s in self.scenarios if s.category == category)

    @property
    def families(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scenario in self.scenarios:
            counts[scenario.family] = counts.get(scenario.family, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenarios": [s.as_dict() for s in self.scenarios],
            "truncated": self.truncated,
            "uncovered": [list(edge) for edge in self.uncovered],
            "unreachable": list(self.unreachable),
            "notes": list(self.notes),
            "rejected": [s.as_dict() for s in self.rejected],
            "coverage": dict(sorted(self.coverage.items())),
            "inadmissible": list(self.inadmissible),
        }
