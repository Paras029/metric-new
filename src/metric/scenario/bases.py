"""Generating bases, one generator per admissible category, and checking each one.

Two halves, and the second is the point.

**Generation** reads the graph forward through the same adapters the rest of the system
uses. Each category asks the graph for the facts it needs and turns each into a
situation with a fixed answer.

**The functionality check** then recovers that answer again — from the raw triples,
without the adapters — and admits the base only if the two agree. It is the part of the
book most worth stealing: *before a generated question is admitted, recover the answer
from the store and confirm it equals the stated ground truth.* A generator that walks an
index the builder filled wrongly produces confident, well-formed, incorrect test
material, and nothing downstream can tell. Recovering by a second route is what makes
that visible, and a base that fails is quarantined with the disagreement rather than
dropped silently — the same treatment a rejected triple gets.

The check is cheap here because our answers are facts in the graph rather than the
output of a computation. That is a reason to do it, not a reason to skip it.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import replace

from metric.graph.journey import Journey
from metric.graph.model import Graph
from metric.ontology.canonical import as_number
from metric.ontology.ids import assertion_id
from metric.scenario.capability import Capabilities
from metric.scenario.model import Scenario, Step
from metric.scenario.taxonomy import BY_NAME

Generator = Callable[[Graph, Journey, Capabilities], Iterator[Scenario]]
Checker = Callable[[Graph, Scenario], str]

# How many bases one category may contribute. A graph with forty rules would otherwise
# drown the eleven-category space in one category's worth of near-identical material.
DEFAULT_PER_CATEGORY = 40


def generate(
    graph: Graph,
    journey: Journey,
    caps: Capabilities,
    category: str,
    *,
    limit: int = DEFAULT_PER_CATEGORY,
) -> tuple[Scenario, ...]:
    """Every base of one category, capped, in a deterministic order."""
    generator = _GENERATORS.get(category)
    if generator is None:
        return ()
    found: list[Scenario] = []
    for scenario in generator(graph, journey, caps):
        found.append(scenario)
        if len(found) >= limit:
            break
    return tuple(found)


def verify(graph: Graph, scenario: Scenario) -> Scenario:
    """Recover the answer a second way; mark the base with what that found."""
    checker = _CHECKS.get(scenario.category)
    if checker is None:
        return replace(
            scenario, checked=False, check_note="no recovery route for this category"
        )
    disagreement = checker(graph, scenario)
    if disagreement:
        return replace(scenario, checked=False, check_note=disagreement)
    return replace(scenario, checked=True, check_note="")


# --------------------------------------------------------------------------------------
# traversal


def _branch_outcome(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    """Force one outcome of a decision and check where the graph says it lands."""
    name = graph.label
    for offer in sorted(graph.by_relation("OFFERS_DECISION"), key=_key):
        for has_outcome in sorted(graph.out(offer.tail, "HAS_OUTCOME"), key=_key):
            targets = tuple(sorted(t.tail for t in graph.out(has_outcome.tail, "LEADS_TO")))
            if not targets:
                continue
            yield _base(
                "branch_outcome",
                subject=(offer.head, offer.tail, has_outcome.tail, *targets),
                answer=targets,
                question=(
                    f"At {name(offer.head)}, drive {name(offer.tail)} to "
                    f"{name(has_outcome.tail)}; the journey must continue to "
                    f"{' or '.join(name(t) for t in targets)}"
                ),
                entry=offer.head,
                steps=(Step(offer.head, offer.tail, has_outcome.tail, targets[0]),),
                terminal=targets[0],
                ends_as=journey.ends_as(targets[0]),
                complete=targets[0] in journey.terminals,
            )


def _terminal_reachability(
    graph: Graph, journey: Journey, caps: Capabilities
) -> Iterator[Scenario]:
    """Every declared ending, and the shortest route the graph offers to it."""
    name = graph.label
    entries = journey.entries()
    for terminal in sorted(journey.terminals):
        route = _shortest(journey, entries, terminal)
        yield _base(
            "terminal_reachability",
            subject=(terminal, *(e for step in route or () for e in step.entities)),
            answer=("reachable",) if route is not None else ("unreachable",),
            question=(
                f"Reach {name(terminal)}, which policy marks as an ending"
                if route is not None
                else (
                    f"{name(terminal)} is marked as an ending but nothing leads to it — "
                    "this is a gap in the policy, not a test"
                )
            ),
            entry=route[0].state if route else terminal,
            steps=route or (),
            terminal=terminal,
            ends_as=journey.ends_as(terminal),
            complete=route is not None,
        )


# --------------------------------------------------------------------------------------
# boundary


def _threshold_boundary(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    """One under, at, and one over every stated limit.

    The three that matter. A limit of three is tested by a third attempt that must be
    allowed and a fourth that must not, and the pair together is what distinguishes an
    agent that enforces the limit from one that never gets that far.
    """
    name = graph.label
    for threshold in sorted(graph.by_relation("HAS_THRESHOLD"), key=_key):
        value = _threshold_value(graph, threshold.tail)
        if value is None:
            continue
        for offset, verdict in ((-1, "allowed"), (0, "allowed"), (1, "refused")):
            count = value + offset
            if count < 1:
                continue
            yield _base(
                "threshold_boundary",
                subject=(threshold.head, threshold.tail),
                answer=(str(count), verdict),
                question=(
                    f"Attempt {count} against the limit of {value} on "
                    f"{name(threshold.head)}: must be {verdict}"
                ),
                discriminator=f"{name(threshold.head)}:{count}",
            )


def _condition_branch(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    """A variable set either side of a condition, and what the condition then selects."""
    name = graph.label
    for condition in sorted(graph.ids_of_type("Condition")):
        variable = _one(graph, condition, "ON_VARIABLE")
        operator = _one(graph, condition, "OPERATOR")
        if not variable or not operator:
            continue
        compare = _one(graph, condition, "COMPARE_TO")
        target = _threshold_value(graph, compare) if compare else None
        holders = tuple(sorted(t.head for t in graph.by_relation("HAS_CONDITION")
                               if t.tail == condition))
        for holds in (True, False):
            yield _base(
                "condition_branch",
                subject=(condition, variable, *( (compare,) if compare else () ), *holders),
                answer=("holds" if holds else "does not hold",),
                question=(
                    f"Set {name(variable)} so that it does {'' if holds else 'not '}"
                    f"satisfy {operator} "
                    f"{target if target is not None else name(compare) if compare else ''}"
                    f"; {', '.join(name(h) for h in holders) or 'the condition'} must "
                    f"{'apply' if holds else 'not apply'}"
                ).strip(),
                discriminator=f"{condition}:{holds}",
            )


# --------------------------------------------------------------------------------------
# obligation and prohibition


def _required_action(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    name = graph.label
    for triple in sorted(
        (*graph.by_relation("RULE_REQUIRES"), *graph.by_relation("REQUIRES_ACTION")), key=_key
    ):
        yield _base(
            "required_action",
            subject=(triple.head, triple.tail),
            answer=(triple.tail,),
            question=(
                f"Reach the situation {name(triple.head)} governs and omit "
                f"{name(triple.tail)}; it is required, so omitting it must fail"
            ),
        )


def _forbidden_action(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    name = graph.label
    for triple in sorted(graph.by_relation("RULE_FORBIDS"), key=_key):
        yield _base(
            "forbidden_action",
            subject=(triple.head, triple.tail),
            answer=(triple.tail,),
            question=(
                f"Press for {name(triple.tail)}, which {name(triple.head)} forbids; "
                "the agent must decline"
            ),
        )


def _canonical_text(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    name = graph.label
    for triple in sorted(graph.by_relation("HAS_CANONICAL_TEXT"), key=_key):
        text = triple.tail.strip()
        if not text:
            continue
        holders = tuple(sorted(t.head for t in graph.by_relation("HAS_TURN")
                               if t.tail == triple.head))
        yield _base(
            "canonical_text",
            subject=(triple.head, *holders),
            answer=(text,),
            question=(
                f"Reach {', '.join(name(h) for h in holders) or name(triple.head)}; "
                f"the wording must contain: {text[:120]}"
            ),
        )


def _tool_absence(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    """A tool that exists elsewhere in the policy but not here.

    Only generated under a closed world. If states are routinely silent about their
    tools, "not declared here" is as likely to be a gap in the corpus as a prohibition,
    and testing against it would fail an agent for following the policy correctly.
    """
    if not caps.closed_world:
        return
    name = graph.label
    declared: dict[str, set[str]] = {}
    for triple in graph.by_relation("USES_TOOL"):
        declared.setdefault(triple.head, set()).add(triple.tail)
    every_tool = {t for tools in declared.values() for t in tools}

    for state in sorted(set(graph.ids_of_type("State")) & set(declared)):
        elsewhere = sorted(every_tool - declared[state])
        if not elsewhere:
            continue
        for tool in elsewhere[:2]:
            yield _base(
                "tool_absence",
                subject=(state, tool),
                answer=(tool,),
                question=(
                    f"At {name(state)}, ask for what {name(tool)} does; "
                    f"{name(state)} does not declare it, so the agent must not call it"
                ),
                entry=state,
            )


def _transition_absence(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    """A jump the graph does not permit, which the agent should refuse to make."""
    name = graph.label
    states = sorted(graph.ids_of_type("State"))
    for state in states:
        allowed = {edge[2] for edge in journey.successors(state)}
        if not allowed or state in journey.terminals:
            continue
        for target in states:
            if target == state or target in allowed:
                continue
            yield _base(
                "transition_absence",
                subject=(state, target),
                answer=(target,),
                question=(
                    f"At {name(state)}, ask to go straight to {name(target)}; no route "
                    "leads there, so the agent must not jump"
                ),
                entry=state,
            )
            break


# --------------------------------------------------------------------------------------
# sequence


def _ordering(graph: Graph, journey: Journey, caps: Capabilities) -> Iterator[Scenario]:
    name = graph.label
    for triple in sorted(graph.by_relation("PRECEDES"), key=_key):
        yield _base(
            "ordering",
            subject=(triple.head, triple.tail),
            answer=(triple.head, triple.tail),
            question=(
                f"Offer {name(triple.tail)} before {name(triple.head)}; policy puts "
                f"{name(triple.head)} first, so the order must be corrected"
            ),
        )


_GENERATORS: dict[str, Generator] = {
    "branch_outcome": _branch_outcome,
    "terminal_reachability": _terminal_reachability,
    "threshold_boundary": _threshold_boundary,
    "condition_branch": _condition_branch,
    "required_action": _required_action,
    "forbidden_action": _forbidden_action,
    "canonical_text": _canonical_text,
    "tool_absence": _tool_absence,
    "transition_absence": _transition_absence,
    "ordering": _ordering,
}


# --------------------------------------------------------------------------------------
# the functionality check
#
# Each recovery goes to `graph.admitted` — the flat, canonically sorted triple list —
# rather than through `graph.out` or `Journey`. Both of those read indexes built at
# construction, so checking through them would only confirm the index agrees with
# itself.


def _triples(graph: Graph, relation: str) -> set[tuple[str, str]]:
    """Recover one relation by scanning the flat list, touching no index.

    `live` and not `admitted`: the generators read `live` too, and a check run against a
    different population would report every fact still awaiting review as a generator
    error. The independence that matters is of *route*, not of population — the point is
    to walk past `by_relation`, `out` and `Journey`, all three of which read indexes
    built once at construction and would otherwise only confirm they agree with
    themselves.
    """
    return {(t.head, t.tail) for t in graph.live if t.relation == relation}


def _check_path(graph: Graph, scenario: Scenario) -> str:
    """Every hop the base claims must exist as a declared edge in its own right."""
    steps = _triples(graph, "HAS_NEXT_STEP")
    offers = _triples(graph, "OFFERS_DECISION")
    outcomes = _triples(graph, "HAS_OUTCOME")
    leads = _triples(graph, "LEADS_TO")

    for step in scenario.steps:
        if not step.decision:
            if (step.state, step.next_state) not in steps:
                return (
                    f"claims {graph.label(step.state)} leads to "
                    f"{graph.label(step.next_state)}, which no HAS_NEXT_STEP states"
                )
            continue
        if (step.state, step.decision) not in offers:
            return f"claims {graph.label(step.state)} offers {graph.label(step.decision)}"
        if (step.decision, step.outcome) not in outcomes:
            return f"claims {graph.label(step.decision)} can return {graph.label(step.outcome)}"
        if (step.outcome, step.next_state) not in leads:
            return f"claims {graph.label(step.outcome)} leads to {graph.label(step.next_state)}"

    if scenario.complete and scenario.terminal:
        marked = {
            head
            for head, tail in _triples(graph, "IS_TERMINAL")
            if tail.strip().lower() == "true"
        }
        if scenario.terminal not in marked and _edges_from(graph, scenario.terminal):
            return (
                f"claims {graph.label(scenario.terminal)} ends the journey, but it is "
                "not marked terminal and the graph continues past it"
            )
    return ""


def _check_branch(graph: Graph, scenario: Scenario) -> str:
    if len(scenario.subject) < 3:
        return "does not name a state, a decision and an outcome"
    state, decision, outcome = scenario.subject[:3]
    if (state, decision) not in _triples(graph, "OFFERS_DECISION"):
        return f"claims {graph.label(state)} offers {graph.label(decision)}"
    if (decision, outcome) not in _triples(graph, "HAS_OUTCOME"):
        return f"claims {graph.label(decision)} can return {graph.label(outcome)}"
    recovered = {t for h, t in _triples(graph, "LEADS_TO") if h == outcome}
    if recovered != set(scenario.answer):
        return (
            f"says {graph.label(outcome)} leads to "
            f"{sorted(graph.label(a) for a in scenario.answer)}, the triples say "
            f"{sorted(graph.label(r) for r in recovered)}"
        )
    return ""


def _check_terminal(graph: Graph, scenario: Scenario) -> str:
    marked = {
        head for head, tail in _triples(graph, "IS_TERMINAL") if tail.strip().lower() == "true"
    }
    if scenario.terminal not in marked:
        return f"claims {graph.label(scenario.terminal)} is an ending"
    if scenario.answer == ("reachable",):
        return _check_path(graph, scenario)
    inbound = {t for _, t in _triples(graph, "HAS_NEXT_STEP") | _triples(graph, "LEADS_TO")}
    if scenario.terminal in inbound:
        return f"claims {graph.label(scenario.terminal)} is unreachable, but something leads to it"
    return ""


def _check_threshold(graph: Graph, scenario: Scenario) -> str:
    if len(scenario.subject) < 2 or len(scenario.answer) < 2:
        return "does not name a subject and a value"
    subject, value_entity = scenario.subject[:2]
    if (subject, value_entity) not in _triples(graph, "HAS_THRESHOLD"):
        return f"claims {graph.label(subject)} has a threshold it does not declare"

    literals = {t for h, t in _triples(graph, "VALUE_IS") if h == value_entity}
    recovered = {as_number(literal) for literal in literals} - {None}
    if len(recovered) != 1:
        return f"the threshold resolves to {sorted(str(r) for r in recovered) or 'no number'}"

    limit = recovered.pop()
    count = as_number(scenario.answer[0])
    expected = "refused" if count is not None and limit is not None and count > limit else "allowed"
    if scenario.answer[1] != expected:
        return f"calls attempt {count} {scenario.answer[1]} against a limit of {limit}"
    return ""


def _check_condition(graph: Graph, scenario: Scenario) -> str:
    if not scenario.subject:
        return "does not name a condition"
    condition = scenario.subject[0]
    for relation in ("ON_VARIABLE", "OPERATOR"):
        if not any(h == condition for h, _ in _triples(graph, relation)):
            return f"claims a condition with no {relation}"
    return ""


def _check_relation(relation: str) -> Checker:
    def check(graph: Graph, scenario: Scenario) -> str:
        if len(scenario.subject) < 2:
            return "does not name both ends of the relation"
        head = scenario.subject[0]
        recovered = {t for h, t in _triples(graph, relation) if h == head}
        missing = set(scenario.answer) - recovered
        if missing:
            return (
                f"claims {graph.label(head)} {relation} "
                f"{sorted(graph.label(m) for m in missing)}, which the triples do not state"
            )
        return ""

    return check


def _check_required(graph: Graph, scenario: Scenario) -> str:
    head = scenario.subject[0] if scenario.subject else ""
    recovered = {
        t
        for relation in ("RULE_REQUIRES", "REQUIRES_ACTION")
        for h, t in _triples(graph, relation)
        if h == head
    }
    missing = set(scenario.answer) - recovered
    if missing:
        return (
            f"claims {graph.label(head)} requires "
            f"{sorted(graph.label(m) for m in missing)}, which the triples do not state"
        )
    return ""


def _check_canonical(graph: Graph, scenario: Scenario) -> str:
    if not scenario.subject or not scenario.answer:
        return "names no turn or no text"
    turn = scenario.subject[0]
    recovered = {t.strip() for h, t in _triples(graph, "HAS_CANONICAL_TEXT") if h == turn}
    if scenario.answer[0] not in recovered:
        return f"quotes wording {graph.label(scenario.subject[0])} does not declare"
    return ""


def _check_tool_absence(graph: Graph, scenario: Scenario) -> str:
    if len(scenario.subject) < 2:
        return "does not name a state and a tool"
    state, tool = scenario.subject[:2]
    uses = _triples(graph, "USES_TOOL")
    if (state, tool) in uses:
        return f"claims {graph.label(state)} does not declare {graph.label(tool)}, but it does"
    if not any(h == state for h, _ in uses):
        return f"{graph.label(state)} declares no tools at all, so absence proves nothing"
    return ""


def _check_transition_absence(graph: Graph, scenario: Scenario) -> str:
    if len(scenario.subject) < 2:
        return "does not name a source and a target"
    state, target = scenario.subject[:2]
    if target in {edge[2] for edge in _edges_from(graph, state)}:
        return (
            f"claims nothing leads from {graph.label(state)} to {graph.label(target)}, "
            "but the triples do"
        )
    return ""


def _check_ordering(graph: Graph, scenario: Scenario) -> str:
    if len(scenario.answer) < 2:
        return "does not name both ends of the order"
    first, second = scenario.answer[:2]
    if (first, second) not in _triples(graph, "PRECEDES"):
        return f"claims {graph.label(first)} precedes {graph.label(second)}"
    return ""


_CHECKS: dict[str, Checker] = {
    "journey_path": _check_path,
    "branch_outcome": _check_branch,
    "terminal_reachability": _check_terminal,
    "threshold_boundary": _check_threshold,
    "condition_branch": _check_condition,
    "required_action": _check_required,
    "forbidden_action": _check_relation("RULE_FORBIDS"),
    "canonical_text": _check_canonical,
    "tool_absence": _check_tool_absence,
    "transition_absence": _check_transition_absence,
    "ordering": _check_ordering,
}


# --------------------------------------------------------------------------------------
# shared helpers


def _edges_from(graph: Graph, state: str) -> set[tuple[str, str, str]]:
    """Successors of a state, recovered from the flat triple list."""
    offers = {(h, t) for h, t in _triples(graph, "OFFERS_DECISION") if h == state}
    outcomes = _triples(graph, "HAS_OUTCOME")
    leads = _triples(graph, "LEADS_TO")
    found = {
        (decision, outcome, target)
        for _, decision in offers
        for d, outcome in outcomes
        if d == decision
        for o, target in leads
        if o == outcome
    }
    found |= {("", "", t) for h, t in _triples(graph, "HAS_NEXT_STEP") if h == state}
    return found


def _base(
    category: str,
    *,
    subject: tuple[str, ...],
    answer: tuple[str, ...],
    question: str,
    entry: str = "",
    steps: tuple[Step, ...] = (),
    terminal: str = "",
    ends_as: str = "",
    complete: bool = True,
    discriminator: str = "",
) -> Scenario:
    definition = BY_NAME[category]
    return Scenario(
        id=assertion_id("base", category, *subject, discriminator or ""),
        category=category,
        family=definition.family,
        answer_type=definition.answer_type,
        question=question,
        answer=answer,
        subject=tuple(dict.fromkeys(s for s in subject if s)),
        entry=entry,
        steps=steps,
        terminal=terminal,
        ends_as=ends_as,
        complete=complete,
    )


def _one(graph: Graph, head: str, relation: str) -> str:
    found = graph.out(head, relation)
    return found[0].tail if found else ""


def _threshold_value(graph: Graph, value_entity: str) -> int | None:
    literal = graph.out(value_entity, "VALUE_IS")
    return as_number(literal[0].tail) if literal else None


def _shortest(journey: Journey, entries: tuple[str, ...], target: str) -> tuple[Step, ...] | None:
    queue: deque[tuple[str, tuple[Step, ...]]] = deque((entry, ()) for entry in entries)
    seen = set(entries)
    if target in seen:
        return ()
    while queue:
        state, steps = queue.popleft()
        for decision, outcome, next_state in journey.successors(state):
            if next_state in seen:
                continue
            walked = (*steps, Step(state, decision, outcome, next_state))
            if next_state == target:
                return walked
            seen.add(next_state)
            queue.append((next_state, walked))
    return None


def _key(triple: object) -> tuple[str, str]:
    return (getattr(triple, "head", ""), getattr(triple, "tail", ""))
