"""Evaluating a Condition against observed state.

A condition in this ontology is three triples — `ON_VARIABLE`, `OPERATOR`,
`COMPARE_TO` — rather than a sentence, which is the whole point. The old generator
kept branch conditions as prose that nothing parsed: `outcome_condition` was rendered
into prompts and shown in a UI and never once evaluated. A structured predicate can be
wrong, but it can be *checked*, and prose cannot.

`None` is a first-class answer. A condition over a variable the run never touched is
undecided, not false. Treating it as false would quietly convert missing telemetry
into a passing test.
"""

from __future__ import annotations

from dataclasses import dataclass

from metric.graph.model import Graph
from metric.ontology.canonical import as_number
from metric.runtime.context import RuntimeContext


@dataclass(frozen=True, slots=True)
class Predicate:
    """A condition reduced to the three things needed to evaluate it."""

    condition: str
    variable: str | None
    operator: str
    value: str | None

    @property
    def decidable(self) -> bool:
        if not self.operator or self.variable is None:
            return False
        return self.operator == "exists" or self.value is not None


def read_predicate(graph: Graph, condition: str) -> Predicate:
    variable = _one(graph, condition, "ON_VARIABLE")
    operator = _one(graph, condition, "OPERATOR") or ""
    compared = _one(graph, condition, "COMPARE_TO")
    return Predicate(
        condition=condition,
        variable=variable,
        operator=operator,
        value=_literal_of(graph, compared) if compared else None,
    )


def holds(graph: Graph, condition: str, context: RuntimeContext) -> bool | None:
    predicate = read_predicate(graph, condition)
    if not predicate.decidable or predicate.variable is None:
        return None

    observed = context.value(predicate.variable)
    if predicate.operator == "exists":
        return observed is not None
    if observed is None:
        return None

    return _compare(predicate.operator, observed, predicate.value or "")


def _compare(operator: str, observed: str, expected: str) -> bool | None:
    if operator == "in":
        return observed in {part.strip() for part in expected.split(",")}

    left, right = as_number(observed), as_number(expected)
    if left is not None and right is not None:
        return _numeric(operator, left, right)

    if operator == "eq":
        return observed.casefold() == expected.casefold()
    if operator == "neq":
        return observed.casefold() != expected.casefold()
    return None


def _numeric(operator: str, left: int, right: int) -> bool | None:
    match operator:
        case "lt":
            return left < right
        case "lte":
            return left <= right
        case "eq":
            return left == right
        case "neq":
            return left != right
        case "gte":
            return left >= right
        case "gt":
            return left > right
    return None


def _one(graph: Graph, head: str, relation: str) -> str | None:
    found = graph.out(head, relation)
    return found[0].tail if found else None


def _literal_of(graph: Graph, value_entity: str) -> str | None:
    """A `Value` carries its literal on `VALUE_IS`, recorded verbatim from the source."""
    return _one(graph, value_entity, "VALUE_IS")
