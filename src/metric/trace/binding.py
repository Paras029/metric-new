"""Binding what was observed to what the ontology knows.

Two mechanisms, in order, and a third outcome that is not a mechanism.

**Declared** — the `EMITTED_AS_*` relations. A person has said that this Tool appears
in telemetry under that span name, that this Outcome appears as that result token.
These are never extracted from policy: no policy names a span attribute. They are the
transferability seam — a new agent emitting different names needs a new profile, not
new code.

**Lexical** — the observed name folds to the same canonical form as an entity's own
name, within the same type. `authenticate_customer` in a span is the `Tool` called
`authenticate_customer`. This is the deterministic escape hatch the production trace
turns out to allow, and it is the reason a semantic binder is not needed yet.

**Unbound** — and this is the point. An observation that matches nothing stays
unbound and is reported. It is not guessed at, and it is not dropped: "the agent
called a tool we have never heard of" is a finding, and it is invisible the moment
binding is allowed to fail silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from metric.graph.model import Graph
from metric.ontology.ids import canonical_name
from metric.trace.model import Observation, Trace

BindingMethod = Literal["declared", "lexical", "none"]

_CONFIDENCE: dict[BindingMethod, float] = {"declared": 1.0, "lexical": 0.75, "none": 0.0}

# Which entity type each kind of observation can bind to. Type-scoping the lookup is
# what stops a tool and a state that share a name being treated as the same thing.
_TARGET_TYPE: dict[str, str] = {
    "tool_call": "Tool",
    "outcome": "Outcome",
    "capability": "Capability",
    "state_write": "StateVariable",
}
_DECLARING_RELATION: dict[str, str] = {
    "Tool": "EMITTED_AS_TOOL",
    "Outcome": "EMITTED_AS_RESULT",
    "Capability": "EMITTED_AS_WORKFLOW",
    "StateVariable": "EMITTED_AS_FIELD",
    "State": "EMITTED_AS_CHECKPOINT",
}


@dataclass(frozen=True, slots=True)
class Bound:
    observation: Observation
    entity: str | None
    entity_type: str
    method: BindingMethod
    token: str = ""

    @property
    def confidence(self) -> float:
        return _CONFIDENCE[self.method]

    @property
    def attempted(self) -> bool:
        return bool(self.entity_type)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.observation.as_dict(),
            "token": self.token,
            "entity": self.entity,
            "entity_type": self.entity_type,
            "method": self.method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class BoundTrace:
    trace: Trace
    bindings: tuple[Bound, ...]

    def of_kind(self, *kinds: str) -> tuple[Bound, ...]:
        return tuple(b for b in self.bindings if b.observation.kind in kinds)

    def of_type(self, entity_type: str) -> tuple[Bound, ...]:
        return tuple(b for b in self.bindings if b.entity_type == entity_type and b.entity)

    def entities(self, entity_type: str) -> tuple[str, ...]:
        """Bound entity ids of one type, in observed order."""
        return tuple(b.entity for b in self.of_type(entity_type) if b.entity is not None)

    @property
    def unbound(self) -> tuple[Bound, ...]:
        return tuple(b for b in self.bindings if b.attempted and b.entity is None)

    @property
    def coverage(self) -> float:
        attempted = [b for b in self.bindings if b.attempted]
        if not attempted:
            return 1.0
        return sum(1 for b in attempted if b.entity is not None) / len(attempted)


class Lexicon:
    """The lookup a binding goes through: declared names first, then folded names.

    `checkpoint_variable` is the field the agent writes its position to. It is a
    telemetry artefact rather than a policy concept — no policy names the variable an
    agent narrates itself through — so it arrives from the profile and is the one
    variable whose *values* are read as states.
    """

    def __init__(self, graph: Graph, *, checkpoint_variable: str = "") -> None:
        self.checkpoint_variable = canonical_name(checkpoint_variable)
        self._declared: dict[tuple[str, str], str] = {}
        self._lexical: dict[tuple[str, str], str] = {}

        for entity_type, relation in _DECLARING_RELATION.items():
            for triple in graph.by_relation(relation):
                self._declared[(entity_type, canonical_name(triple.tail))] = triple.head

        for entity in graph.entities:
            for surface in entity.surfaces | {entity.canonical}:
                folded = canonical_name(surface)
                if folded:
                    self._lexical.setdefault((entity.type, folded), entity.id)

    def is_checkpoint(self, variable: str) -> bool:
        if not self.checkpoint_variable:
            return False
        return canonical_name(variable) == self.checkpoint_variable

    def look_up(self, entity_type: str, token: str) -> tuple[str | None, BindingMethod]:
        folded = canonical_name(token)
        if not folded:
            return None, "none"
        declared = self._declared.get((entity_type, folded))
        if declared is not None:
            return declared, "declared"
        lexical = self._lexical.get((entity_type, folded))
        if lexical is not None:
            return lexical, "lexical"
        return None, "none"


def bind(trace: Trace, graph: Graph, *, checkpoint_variable: str = "") -> BoundTrace:
    lexicon = Lexicon(graph, checkpoint_variable=checkpoint_variable)
    return BoundTrace(trace=trace, bindings=tuple(_bind_all(trace.observations, lexicon)))


def _bind_all(observations: Sequence[Observation], lexicon: Lexicon) -> list[Bound]:
    bound: list[Bound] = []
    for observation in observations:
        entity_type = _TARGET_TYPE.get(observation.kind)
        if entity_type is None:
            bound.append(Bound(observation, None, "", "none"))
            continue

        token = observation.value if observation.kind == "outcome" else observation.name
        variable = _look_up(observation, entity_type, token, lexicon)
        bound.append(variable)

        # A checkpoint write names a variable *and* asserts a state. Only the declared
        # checkpoint variable has its value read that way: every other write carries a
        # counter or a flag, and chasing those as states would bury the real bindings
        # under a stream of numbers that were never meant to be places.
        if observation.kind == "state_write" and lexicon.is_checkpoint(observation.name):
            bound.append(_look_up(observation, "State", observation.value, lexicon))
    return bound


def _look_up(observation: Observation, entity_type: str, token: str, lexicon: Lexicon) -> Bound:
    entity, method = lexicon.look_up(entity_type, token)
    return Bound(observation, entity, entity_type, method, token=token)
