"""What a given graph can actually be asked.

The book's portability mechanism, and the reason its taxonomy survives a change of
domain: a question category names the graph *capability* it needs, and a category is
admissible for a corpus only if the graph built from that corpus exposes that
capability. Nothing is hardcoded per use case — the capabilities are read off the
relations the graph actually contains.

That single rule is what stops the generator inventing test material. A policy that
states no prohibitions yields no prohibition scenarios; an observed graph with no rules
at all yields only traversal ones. The alternative — generate the category anyway and
let it come back empty — reports zero coverage of a category the corpus never supported,
which is indistinguishable from a bug.

The capability report is also the honest answer to "what can you test here?", asked
before a single scenario is generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metric.graph.model import Graph

# A capability is present when the graph holds the relations that make questions of
# that shape answerable. Several capabilities need more than one relation, because a
# question needs both the structure and the thing it points at.
_REQUIREMENTS: dict[str, tuple[tuple[str, ...], ...]] = {
    "path": (("HAS_NEXT_STEP",), ("LEADS_TO",)),
    "branch": (("OFFERS_DECISION", "HAS_OUTCOME"),),
    "threshold": (("HAS_THRESHOLD", "VALUE_IS"),),
    "condition": (("HAS_CONDITION", "ON_VARIABLE", "OPERATOR"),),
    "obligation": (("RULE_REQUIRES",), ("REQUIRES_ACTION",)),
    "prohibition": (("RULE_FORBIDS",),),
    "canonical_text": (("HAS_CANONICAL_TEXT",),),
    "tools": (("USES_TOOL",),),
    "outcomes": (("RETURNS",),),
    "ordered_sequence": (("PRECEDES",),),
    "terminal": (("IS_TERMINAL",),),
    "policy": (("GOVERNED_BY",),),
}

_DESCRIPTIONS: dict[str, str] = {
    "path": "states lead to other states, so a journey can be walked",
    "branch": "decisions have outcomes, so a branch can be forced",
    "threshold": "a limit is stated with a value, so a boundary can be approached",
    "condition": "a condition names a variable and an operator, so it can be evaluated",
    "obligation": "something is required, so an omission is a failure",
    "prohibition": "something is forbidden, so doing it is a failure",
    "canonical_text": "wording is fixed, so a paraphrase is detectable",
    "tools": "states declare their tools, so a tool call can be placed",
    "outcomes": "tools declare their outcomes, so a result can be checked",
    "ordered_sequence": "order is stated, so a sequence can be checked",
    "terminal": "endings are marked, so completion can be checked",
    "policy": "rules attach to the structure they govern",
}


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Which capabilities this graph exposes, and the evidence for each."""

    present: frozenset[str]
    evidence: dict[str, int]
    closed_world: bool

    def __contains__(self, capability: str) -> bool:
        return capability in self.present

    def supports(self, required: tuple[str, ...]) -> bool:
        return all(capability in self.present for capability in required)

    def missing(self, required: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(c for c in required if c not in self.present)

    @property
    def absent(self) -> tuple[str, ...]:
        return tuple(sorted(set(_REQUIREMENTS) - self.present))

    def describe(self, capability: str) -> str:
        return _DESCRIPTIONS.get(capability, capability)

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": sorted(self.present),
            "absent": list(self.absent),
            "evidence": dict(sorted(self.evidence.items())),
            "closed_world": self.closed_world,
        }


def capabilities(graph: Graph) -> Capabilities:
    """Read the graph's capabilities off the relations it holds."""
    counts = {
        relation: len(graph.by_relation(relation))
        for group in _REQUIREMENTS.values()
        for alternative in group
        for relation in alternative
    }

    present: set[str] = set()
    evidence: dict[str, int] = {}
    for capability, alternatives in _REQUIREMENTS.items():
        satisfied = [alt for alt in alternatives if all(counts.get(r, 0) > 0 for r in alt)]
        if satisfied:
            present.add(capability)
            evidence[capability] = max(
                min(counts.get(relation, 0) for relation in alt) for alt in satisfied
            )

    return Capabilities(
        present=frozenset(present),
        evidence=evidence,
        closed_world=_closed_world(graph),
    )


def _closed_world(graph: Graph) -> bool:
    """Whether "the graph does not declare this" means "this is not allowed".

    Two conditions, and both are about the corpus rather than the code.

    Every state that does anything must declare its tools. If half the states are silent,
    an undeclared tool is as likely to be a gap in the corpus as a violation — and
    generating a prohibition from a gap is how a generator comes to fail an agent for
    following a policy correctly.

    And something must have said so other than the agent. A graph discovered from traces
    passes the first condition trivially: its states were *derived from* the tool calls
    made at them, so of course every state declares tools, and of course the tools it
    declares are the ones that agent called. Reading that as a closed world turns "this
    agent has not done that yet" into "this agent may not do that", which is the
    circularity the whole build guards against elsewhere. Closure is a claim a policy can
    make and an observation cannot.
    """
    states = set(graph.ids_of_type("State"))
    if not states:
        return False

    tools = graph.by_relation("USES_TOOL")
    if all(t.methods == {"telemetry"} for t in tools):
        return False

    acting = {t.head for t in tools} & states
    if not acting:
        return False
    terminal = {
        t.head for t in graph.by_relation("IS_TERMINAL") if t.tail.strip().lower() == "true"
    }
    return not (states - acting - terminal)
