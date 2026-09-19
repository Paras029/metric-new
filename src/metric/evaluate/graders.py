"""One grader per assertion kind.

Each grader answers from the bound trace and the replayed runtime state, and nothing
else. No grader reaches back into the graph for a fact the contract did not carry —
the contract is the interface, and a grader that goes around it would make a verdict
irreproducible from the contract that produced it.

Where a grader cannot tell, it says so. The most common reason is that the trace
carries no state bindings at all: transitions and terminal states are then simply not
observable, and reporting them `undecided` says what is missing rather than passing an
agent because the instrumentation is thin.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from metric.admit.grounding import normalised
from metric.contract.model import Assertion
from metric.evaluate.model import Verdict, verdict
from metric.graph.model import Graph
from metric.ontology.canonical import as_number
from metric.runtime.context import RuntimeContext
from metric.trace.binding import BoundTrace


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything a grader may look at."""

    graph: Graph
    bound: BoundTrace
    context: RuntimeContext

    def label(self, entity: str) -> str:
        return self.graph.label(entity) if entity else "the run"

    def names(self, entities: tuple[str, ...]) -> str:
        return ", ".join(sorted(self.label(e) for e in entities))

    @property
    def states_observed(self) -> bool:
        return bool(self.bound.entities("State"))

    @property
    def tool_of_span(self) -> dict[str, str | None]:
        """Which Tool each observed span name bound to, resolved once."""
        return {
            b.observation.name: b.entity
            for b in self.bound.of_kind("tool_call")
            if b.observation.name
        }

    def refs(self, *entities: str) -> tuple[str, ...]:
        wanted = set(entities)
        return tuple(
            b.observation.ref for b in self.bound.bindings if b.entity in wanted and b.entity
        )


Grader = Callable[[Assertion, Evidence], Verdict]


def grade(assertion: Assertion, evidence: Evidence) -> Verdict:
    grader = GRADERS.get(assertion.kind)
    if grader is None:
        return verdict(
            assertion, "undecided", f"no grader for {assertion.kind}"
        )
    return grader(assertion, evidence)


def _tool_called(assertion: Assertion, evidence: Evidence) -> Verdict:
    """Every tool the state declares must have been called somewhere in the run.

    Scoped to the whole run rather than to the state, because pinning a call to a
    state needs checkpoint bindings the trace may not carry. When the state *was*
    observed the check is meaningful; when no state was observed at all it still
    catches a tool that was never called.
    """
    missing = [tool for tool in assertion.expected if evidence.context.calls(tool) == 0]
    if not missing:
        return verdict(
            assertion,
            "pass",
            f"{evidence.names(assertion.expected)} called",
            *evidence.refs(*assertion.expected),
        )
    if evidence.states_observed and assertion.subject not in evidence.bound.entities("State"):
        return verdict(
            assertion,
            "not_applicable",
            f"{evidence.label(assertion.subject)} was never reached",
        )
    return verdict(
        assertion,
        "fail",
        f"{evidence.names(tuple(missing))} was never called",
    )


def _outcome_allowed(assertion: Assertion, evidence: Evidence) -> Verdict:
    tool = assertion.subject
    returned_by = evidence.tool_of_span
    observed = [
        b
        for b in evidence.bound.of_kind("outcome")
        if b.observation.name and returned_by.get(b.observation.name) == tool
    ]
    if not observed:
        return verdict(
            assertion, "not_applicable", f"{evidence.label(tool)} returned nothing in this run"
        )

    unexpected = [b for b in observed if b.entity not in assertion.expected]
    if not unexpected:
        return verdict(
            assertion,
            "pass",
            f"{evidence.label(tool)} returned only declared outcomes",
            *(b.observation.ref for b in observed),
        )

    names = ", ".join(sorted({b.token for b in unexpected}))
    return verdict(
        assertion,
        "fail",
        f"{evidence.label(tool)} returned {names}, which the policy does not declare",
        *(b.observation.ref for b in unexpected),
    )


def _transition_expected(assertion: Assertion, evidence: Evidence) -> Verdict:
    outcome = assertion.subject
    if outcome not in evidence.context.sequence:
        return verdict(assertion, "not_applicable", f"{evidence.label(outcome)} did not occur")
    if not evidence.states_observed:
        return verdict(
            assertion,
            "undecided",
            "the trace carries no state checkpoints, so the transition cannot be observed",
        )

    following = _next_state(evidence, outcome)
    if following is None:
        return verdict(
            assertion, "undecided", f"nothing was observed after {evidence.label(outcome)}"
        )
    if following in assertion.expected:
        return verdict(
            assertion, "pass", f"went to {evidence.label(following)}", *evidence.refs(following)
        )
    return verdict(
        assertion,
        "fail",
        f"went to {evidence.label(following)}, policy requires "
        f"{evidence.names(assertion.expected)}",
        *evidence.refs(outcome, following),
    )


def _transition_allowed(assertion: Assertion, evidence: Evidence) -> Verdict:
    state = assertion.subject
    if not evidence.states_observed:
        return verdict(
            assertion, "undecided", "the trace carries no state checkpoints"
        )
    if state not in evidence.context.sequence:
        return verdict(assertion, "not_applicable", f"{evidence.label(state)} was never reached")

    following = _next_state(evidence, state)
    if following is None:
        return verdict(assertion, "not_applicable", f"{evidence.label(state)} ended the run")
    if following in assertion.expected:
        return verdict(assertion, "pass", f"moved to {evidence.label(following)}")
    return verdict(
        assertion,
        "fail",
        f"moved to {evidence.label(following)}, which the policy does not allow from "
        f"{evidence.label(state)}",
        *evidence.refs(state, following),
    )


def _terminal_expected(assertion: Assertion, evidence: Evidence) -> Verdict:
    states = evidence.bound.entities("State")
    if not states:
        return verdict(
            assertion,
            "undecided",
            "no state was observed, so where the run ended cannot be established",
        )
    last = states[-1]
    if last in assertion.expected:
        return verdict(assertion, "pass", f"ended at {evidence.label(last)}", *evidence.refs(last))
    return verdict(
        assertion,
        "fail",
        f"ended at {evidence.label(last)}, which is not a declared ending",
        *evidence.refs(last),
    )


def _order_expected(assertion: Assertion, evidence: Evidence) -> Verdict:
    first, second = assertion.subject, assertion.expected[0]
    order = evidence.context.precedes(first, second)
    if order is None:
        return verdict(
            assertion,
            "not_applicable",
            f"{evidence.label(first)} and {evidence.label(second)} did not both occur",
        )
    if order:
        return verdict(assertion, "pass", f"{evidence.label(first)} came first")
    return verdict(
        assertion,
        "fail",
        f"{evidence.label(second)} came before {evidence.label(first)}",
        *evidence.refs(first, second),
    )


def _count_limit(assertion: Assertion, evidence: Evidence) -> Verdict:
    limit = as_number(assertion.expected[0]) if assertion.expected else None
    if limit is None:
        return verdict(assertion, "undecided", f"{assertion.expected} is not a number")

    subject = assertion.subject
    calls = evidence.context.calls(subject)
    peak = evidence.context.peak(subject)
    observed = max(calls, peak or 0)

    if calls == 0 and peak is None:
        return verdict(
            assertion, "not_applicable", f"{evidence.label(subject)} was never exercised"
        )
    if observed <= limit:
        return verdict(
            assertion, "pass", f"reached {observed}, limit {limit}", *evidence.refs(subject)
        )
    return verdict(
        assertion,
        "fail",
        f"reached {observed}, over the limit of {limit}",
        *evidence.refs(subject),
    )


def _action_required(assertion: Assertion, evidence: Evidence) -> Verdict:
    observable = _observable_targets(assertion, evidence)
    if not observable:
        return verdict(
            assertion,
            "undecided",
            f"{evidence.names(assertion.expected)} calls no tool, so it leaves no trace",
        )
    missing = [t for t in observable if evidence.context.calls(t) == 0]
    if not missing:
        return verdict(
            assertion,
            "pass",
            f"{evidence.names(tuple(observable))} happened",
            *evidence.refs(*observable),
        )
    return verdict(assertion, "fail", f"{evidence.names(tuple(missing))} did not happen")


def _action_forbidden(assertion: Assertion, evidence: Evidence) -> Verdict:
    observable = _observable_targets(assertion, evidence)
    if not observable:
        return verdict(
            assertion,
            "undecided",
            f"{evidence.names(assertion.expected)} calls no tool, "
            "so a violation would be invisible",
        )
    happened = [t for t in observable if evidence.context.calls(t) > 0]
    if not happened:
        return verdict(assertion, "pass", f"{evidence.names(tuple(observable))} did not happen")
    return verdict(
        assertion,
        "fail",
        f"{evidence.names(tuple(happened))} happened and is forbidden",
        *evidence.refs(*happened),
    )


def _text_required(assertion: Assertion, evidence: Evidence) -> Verdict:
    said = [b.observation for b in evidence.bound.bindings if b.observation.kind == "assistant"]
    if not said:
        return verdict(assertion, "undecided", "the trace carries no agent utterances")

    wanted = normalised(assertion.expected[0])
    for observation in said:
        if wanted and wanted in normalised(observation.value):
            return verdict(assertion, "pass", "the required wording was used", observation.ref)
    return verdict(
        assertion,
        "fail",
        "the required wording does not appear in anything the agent said",
        *(o.ref for o in said),
    )


def _next_state(evidence: Evidence, after: str) -> str | None:
    sequence = evidence.context.sequence
    if after not in sequence:
        return None
    states = set(evidence.bound.entities("State"))
    for entity in sequence[sequence.index(after) + 1 :]:
        if entity in states:
            return entity
    return None


def _observable_targets(assertion: Assertion, evidence: Evidence) -> list[str]:
    """Reduce a required or forbidden target to the tools that would evidence it.

    A Tool is its own evidence. An Action is observable through whatever it invokes;
    an Action that invokes nothing cannot be graded from a trace, and saying so is
    more useful than passing it.
    """
    tools = set(evidence.graph.ids_of_type("Tool"))
    targets: list[str] = []
    for target in assertion.expected:
        if target in tools:
            targets.append(target)
            continue
        targets.extend(t.tail for t in evidence.graph.out(target, "INVOKES"))
    return sorted(set(targets))


GRADERS: dict[str, Grader] = {
    "tool_called": _tool_called,
    "outcome_allowed": _outcome_allowed,
    "transition_expected": _transition_expected,
    "transition_allowed": _transition_allowed,
    "terminal_expected": _terminal_expected,
    "order_expected": _order_expected,
    "count_limit": _count_limit,
    "action_required": _action_required,
    "action_forbidden": _action_forbidden,
    "text_required": _text_required,
}
