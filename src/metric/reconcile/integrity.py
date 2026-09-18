"""Conditional integrity: nothing must exist, but what exists must cohere.

Every check here is conditional on the shape the corpus actually has. A policy with
no tools, no conversational turns or no thresholds is a perfectly good policy, and a
pipeline that demanded them would produce a graph shaped by its own expectations
rather than by the document.

What these checks catch instead is a graph that contradicts itself by omission: an
outcome that occurs and goes nowhere, a state that is neither an ending nor followed
by anything, a decision with one branch. Each becomes a question, never a repair.
Filling in a missing destination is the single most tempting and most damaging thing
this stage could do — it would turn a documentation gap into a confident assertion
that a live agent is then graded against.
"""

from __future__ import annotations

import re

from metric.graph.model import Graph
from metric.ontology.canonical import CARDINALS
from metric.ontology.ids import question_id
from metric.ontology.types import Question, Span

_NUMBER = re.compile(rf"\b(?:\d+|{'|'.join(CARDINALS)})\b", re.IGNORECASE)


def check(graph: Graph) -> list[Question]:
    return [
        *_outcomes_without_destination(graph),
        *_states_going_nowhere(graph),
        *_single_branch_decisions(graph),
        *_unattached_rules(graph),
        *_conditions_on_undeclared_variables(graph),
        *_numeric_rule_beside_threshold(graph),
        *_outcome_name_collisions(graph),
    ]


def _outcomes_without_destination(graph: Graph) -> list[Question]:
    reached = {t.tail for t in graph.by_relation("HAS_OUTCOME")}
    reached |= {t.tail for t in graph.by_relation("RETURNS")}
    has_destination = {t.head for t in graph.by_relation("LEADS_TO")}

    return [
        _question(
            "integrity/outcome-destination",
            outcome,
            heading=f"{graph.label(outcome)} has no destination",
            detail=(
                "the corpus says this outcome can occur but never says what follows it. "
                "Nothing has been inferred; a next state must come from the source or from "
                "a person."
            ),
            evidence=_evidence_for(graph, outcome),
        )
        for outcome in sorted(reached - has_destination)
    ]


def _states_going_nowhere(graph: Graph) -> list[Question]:
    terminal = {
        t.head for t in graph.by_relation("IS_TERMINAL") if t.tail.strip().lower() == "true"
    }
    with_next = {t.head for t in graph.by_relation("HAS_NEXT_STEP")}
    states = set(graph.ids_of_type("State"))

    return [
        _question(
            "integrity/state-dead-end",
            state,
            heading=f"{graph.label(state)} is neither terminal nor followed by anything",
            detail="the corpus does not say whether this state ends the journey or continues",
            evidence=_evidence_for(graph, state),
        )
        for state in sorted(states - terminal - with_next)
    ]


def _single_branch_decisions(graph: Graph) -> list[Question]:
    outcomes: dict[str, set[str]] = {}
    for triple in graph.by_relation("HAS_OUTCOME"):
        outcomes.setdefault(triple.head, set()).add(triple.tail)

    return [
        _question(
            "integrity/decision-branches",
            decision,
            heading=f"{graph.label(decision)} has only one outcome",
            detail="a decision with a single outcome is not a decision; a branch is missing",
            evidence=_evidence_for(graph, decision),
        )
        for decision, tails in sorted(outcomes.items())
        if len(tails) < 2
    ]


def _unattached_rules(graph: Graph) -> list[Question]:
    governed = {t.tail for t in graph.by_relation("GOVERNED_BY")}
    rules = set(graph.ids_of_type("Rule"))

    return [
        _question(
            "integrity/rule-scope",
            rule,
            heading=f"{graph.label(rule)} is not attached to anything",
            detail=(
                "the rule was extracted but nothing is recorded as governed by it, so there "
                "is no point at which it could be checked"
            ),
            evidence=_evidence_for(graph, rule),
        )
        for rule in sorted(rules - governed)
    ]


def _conditions_on_undeclared_variables(graph: Graph) -> list[Question]:
    declared = {t.tail for t in graph.by_relation("HAS_STATE_VARIABLE")}
    return [
        _question(
            "integrity/undeclared-variable",
            triple.tail,
            heading=f"{graph.label(triple.tail)} is tested but never declared",
            detail=(
                "a condition compares this variable, but no capability or use case declares "
                "it, so nothing knows where its value comes from"
            ),
            evidence=triple.spans,
        )
        for triple in graph.by_relation("ON_VARIABLE")
        if triple.tail not in declared
    ]


def _numeric_rule_beside_threshold(graph: Graph) -> list[Question]:
    """A rule that states a number over a subject that also carries a threshold.

    This is where the design deliberately stops short. "must not make a fourth
    attempt" and "a maximum of 3 attempts" are the same limit, but reading the first
    as the second is an inference, so they stay two facts and a person is asked
    whether they agree.
    """
    numeric_rules = {
        t.head: t
        for t in graph.by_relation("RULE_STATES")
        if _NUMBER.search(t.tail)
    }
    if not numeric_rules:
        return []

    thresholded = {t.head for t in graph.by_relation("HAS_THRESHOLD")}
    questions: list[Question] = []

    for triple in graph.by_relation("GOVERNED_BY"):
        if triple.head not in thresholded or triple.tail not in numeric_rules:
            continue
        rule = numeric_rules[triple.tail]
        questions.append(
            _question(
                "integrity/numeric-restatement",
                triple.head,
                triple.tail,
                heading=f"{graph.label(triple.head)} carries both a threshold and a numeric rule",
                detail=(
                    "a rule stating a number governs a subject that also has an extracted "
                    "threshold. They have not been merged — confirm they agree, or record "
                    "which one holds."
                ),
                evidence=rule.spans + _evidence_for(graph, triple.head),
            )
        )
    return questions


def _outcome_name_collisions(graph: Graph) -> list[Question]:
    """One outcome name returned by two different tools.

    `FAILED` from an authentication call and `FAILED` from a transfer call carry the
    same name and mean different things, but entity identity is a hash of the name and
    cannot know that. Splitting them automatically would invent a distinction the
    corpus does not make; leaving them merged would let one tool's failure inherit the
    other's consequences. So the collision is reported and a person qualifies the name.
    """
    sources: dict[str, set[str]] = {}
    for triple in graph.by_relation("RETURNS"):
        sources.setdefault(triple.tail, set()).add(triple.head)

    return [
        _question(
            "integrity/outcome-collision",
            outcome,
            heading=f"{graph.label(outcome)} is returned by more than one tool",
            detail=(
                "tools "
                + ", ".join(sorted(graph.label(tool) for tool in tools))
                + " all return this name. They have been merged into one outcome because "
                "nothing distinguishes them. Confirm they are the same outcome, or qualify "
                "the names in the source."
            ),
            evidence=_evidence_for(graph, outcome),
        )
        for outcome, tools in sorted(sources.items())
        if len(tools) > 1
    ]


def _evidence_for(graph: Graph, entity: str) -> tuple[Span, ...]:
    spans = [
        span
        for triple in graph.live
        if entity in (triple.head, triple.tail)
        for span in triple.spans
    ]
    return tuple(spans[:4])


def _question(
    kind: str, *subject: str, heading: str, detail: str, evidence: tuple[Span, ...]
) -> Question:
    return Question(
        id=question_id(kind, *subject),
        kind=kind,
        heading=heading,
        detail=detail,
        blocks=" ".join(subject),
        evidence=evidence,
    )
