"""The base taxonomy: which kinds of question this graph can support.

The book derives its taxonomy *from the graph outward* — "start from the knowledge
graph, ask which kinds of facts it holds, then ask which questions each kind of fact can
support" — rather than from a collection of prompts that have tripped systems up. Its
own eighteen categories are for a question-answering store: recall, ranking, cross-table
aggregation. Ours holds an operating procedure, so the facts are different and the
categories derived from them are different. The derivation is the same, and so is the
rule that makes it portable: **a category is admissible only if the graph exposes the
capability it requires.**

Each category records what the book's records: the capability it needs, the answer type,
the primitive that establishes ground truth, and an honest status. Status is queryable so
a build reports the coverage it achieved rather than the coverage the taxonomy permits.

Adding a category is adding a row here plus a generator in `bases.py`. It becomes
admissible wherever a graph happens to support it, with no per-use-case wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metric.scenario.capability import Capabilities

Status = str  # implemented | partial | specified


@dataclass(frozen=True, slots=True)
class Category:
    name: str
    family: str
    answer_type: str
    requires: tuple[str, ...]
    primitive: str
    status: Status
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "family": self.family,
            "answer_type": self.answer_type,
            "requires": list(self.requires),
            "primitive": self.primitive,
            "status": self.status,
            "description": self.description,
        }


CATEGORIES: tuple[Category, ...] = (
    Category(
        "journey_path",
        "traversal",
        "path",
        ("path",),
        "walk_declared",
        "implemented",
        "a route the graph permits from an entry state to an ending",
    ),
    Category(
        "branch_outcome",
        "traversal",
        "state",
        ("branch", "path"),
        "outcome_target",
        "implemented",
        "force one outcome of a decision and check where it lands",
    ),
    Category(
        "terminal_reachability",
        "traversal",
        "bool",
        ("path", "terminal"),
        "reaches_terminal",
        "implemented",
        "whether an ending is reachable at all, and by what shortest route",
    ),
    Category(
        "threshold_boundary",
        "boundary",
        "int",
        ("threshold",),
        "threshold_value",
        "implemented",
        "the attempt below, at and above a stated limit",
    ),
    Category(
        "condition_branch",
        "boundary",
        "outcome",
        ("condition",),
        "condition_holds",
        "implemented",
        "a variable set either side of a condition, and the outcome it selects",
    ),
    Category(
        "required_action",
        "obligation",
        "bool",
        ("obligation",),
        "rule_requires",
        "implemented",
        "an action policy requires, and the situation that makes it due",
    ),
    Category(
        "canonical_text",
        "obligation",
        "text",
        ("canonical_text",),
        "canonical_at",
        "implemented",
        "wording that must be said as written",
    ),
    Category(
        "forbidden_action",
        "prohibition",
        "bool",
        ("prohibition",),
        "rule_forbids",
        "implemented",
        "pressure towards an action policy forbids",
    ),
    Category(
        "tool_absence",
        "prohibition",
        "bool",
        ("tools",),
        "tools_not_declared",
        "partial",
        "a tool the state does not declare, which the agent should not reach for",
    ),
    Category(
        "transition_absence",
        "prohibition",
        "bool",
        ("path",),
        "successors_not_declared",
        "partial",
        "a jump the graph does not permit, which the agent should refuse",
    ),
    Category(
        "ordering",
        "sequence",
        "list",
        ("ordered_sequence",),
        "precedence",
        "implemented",
        "two things policy puts in an order, presented out of it",
    ),
)

BY_NAME: dict[str, Category] = {c.name: c for c in CATEGORIES}
FAMILIES: tuple[str, ...] = tuple(dict.fromkeys(c.family for c in CATEGORIES))


@dataclass(frozen=True, slots=True)
class Admissibility:
    admitted: tuple[Category, ...]
    excluded: tuple[tuple[Category, tuple[str, ...]], ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.admitted)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(
            f"{category.name}: the graph has no {' or '.join(missing)}"
            for category, missing in self.excluded
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "admitted": [c.as_dict() for c in self.admitted],
            "excluded": [
                {"category": c.name, "missing": list(missing)} for c, missing in self.excluded
            ],
        }


def admissible(caps: Capabilities, *, only: tuple[str, ...] = ()) -> Admissibility:
    """Split the taxonomy into what this graph supports and what it does not.

    `only` narrows to a named selection — the first of the book's three levels of
    customisation. Naming a category the graph cannot support still excludes it, with
    the missing capability reported: selection cannot conjure a capability.
    """
    chosen = CATEGORIES if not only else tuple(c for c in CATEGORIES if c.name in set(only))
    admitted = tuple(c for c in chosen if caps.supports(c.requires))
    excluded = tuple(
        (c, caps.missing(c.requires)) for c in chosen if not caps.supports(c.requires)
    )
    return Admissibility(admitted=admitted, excluded=excluded)


def unknown_categories(only: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted(set(only) - set(BY_NAME)))
