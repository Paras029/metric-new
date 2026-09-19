"""Compiling the graph into assertions.

This module is the transferability seam, so it is worth being explicit about what it
is not. The eval-poc compiled rules through a Python registry keyed by domain rule
codes — `CARD_AUTH_R07` and friends — which works and does not travel: a second use
case needs a second registry, written by someone who knows both the policy and the
codebase.

Here the **relation is the assertion kind**, and the relation declares it — in the
ontology YAML, beside its own domain and range:

```yaml
  - name: RULE_FORBIDS
    domain: [Rule]
    range: [Action, Outcome, State, Tool]
    checks:
      kind: action_forbidden
      dimension: policy
      scope: journey
      grouping: per_head
```

So `RULE_FORBIDS` compiles to a prohibition wherever it appears, in any use case. A use
case that adds a relation of its own declares how it is checked in the same file and
the same edit, and nothing in this module changes. What this module owns is the
*mechanics* — grouping, severity, provenance, derivation level — which are the same
whatever the relation means.

Relations that describe structure rather than obligation say `not_checkable: true`
rather than staying silent, and a relation that says neither is reported as a contract
note. That is the difference between a use case that is covered and one that looks
covered.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from metric.contract.model import Assertion, AssertionKind, Contract, Dimension, Level, Severity
from metric.graph.model import Graph
from metric.ontology.ids import assertion_id
from metric.ontology.schema import CheckSpec, Schema
from metric.ontology.types import Span, Triple

_MAX_EVIDENCE = 4


@dataclass(frozen=True, slots=True)
class Compiled:
    """Every assertion a graph yields, compiled once.

    Compilation reads the whole graph; narrowing to one scenario reads a list. Keeping
    them apart means a hundred scenarios cost one compilation and a hundred filters
    rather than a hundred compilations.
    """

    assertions: tuple[Assertion, ...]
    notes: tuple[str, ...]

    def narrow(self, scope: Sequence[str] | None) -> tuple[Assertion, ...]:
        if scope is None:
            return self.assertions
        wanted = set(scope)
        return tuple(a for a in self.assertions if _in_scope(a, wanted))


def compile_all(graph: Graph, schema: Schema) -> Compiled:
    assertions, notes = compile_assertions(graph, schema)
    return Compiled(assertions=tuple(assertions), notes=tuple(notes))


def compile_assertions(graph: Graph, schema: Schema) -> tuple[list[Assertion], list[str]]:
    assertions: list[Assertion] = []

    for relation in schema.checked_relations:
        check = schema.relations[relation].checks
        if check is None:
            continue
        triples = [t for t in graph.by_relation(relation) if _asserts_something(relation, t)]
        if triples:
            assertions.extend(_compile(graph, relation, check, triples))

    present = frozenset(t.relation for t in graph.live)
    notes = []
    undeclared = schema.undeclared(present)
    if undeclared:
        notes.append(
            ", ".join(undeclared) + " appear in the graph but declare neither `checks:` "
            "nor `not_checkable: true`, so nothing verifies them"
        )
    return sorted(assertions, key=lambda a: (a.kind, a.subject, a.id)), notes


def build_contract(
    graph: Graph,
    schema: Schema,
    *,
    identity: str,
    binding: str,
    scope: Sequence[str] | None = None,
    compiled: Compiled | None = None,
) -> Contract:
    """Compile, then narrow to `scope` if one is given.

    Narrowing keeps journey-scoped assertions whatever the scope: a prohibition that
    holds for the whole journey holds on every path through it, and dropping it
    because the path does not mention it is how a scenario quietly stops testing the
    rule that matters most.

    Pass `compiled` to reuse a compilation across many contracts from one graph.
    """
    prepared = compiled or compile_all(graph, schema)
    return Contract(
        id=assertion_id("contract", binding, identity),
        binding=binding,
        identity=identity,
        assertions=prepared.narrow(scope),
        notes=prepared.notes,
    )


def _in_scope(assertion: Assertion, wanted: set[str]) -> bool:
    if assertion.scope == "journey":
        return True
    return assertion.subject in wanted or bool(wanted & set(assertion.expected))


def _compile(
    graph: Graph, relation: str, rule: CheckSpec, triples: list[Triple]
) -> list[Assertion]:
    if rule.grouping == "all":
        return [_assertion(graph, rule, relation, "", [t.head for t in triples], triples)]

    if rule.grouping == "per_head":
        heads: dict[str, list[Triple]] = {}
        for triple in triples:
            heads.setdefault(triple.head, []).append(triple)
        return [
            _assertion(graph, rule, relation, head, [t.tail for t in group], group)
            for head, group in sorted(heads.items())
        ]

    return [
        _assertion(graph, rule, relation, t.head, [_expected(graph, relation, t)], [t])
        for t in triples
    ]


def _expected(graph: Graph, relation: str, triple: Triple) -> str:
    """A threshold points at a Value; what the assertion needs is the number on it."""
    if relation != "HAS_THRESHOLD":
        return triple.tail
    literal = graph.out(triple.tail, "VALUE_IS")
    return literal[0].tail if literal else triple.tail


def _assertion(
    graph: Graph,
    rule: CheckSpec,
    relation: str,
    subject: str,
    expected: Sequence[str],
    sources: Sequence[Triple],
) -> Assertion:
    observed_only = bool(sources) and all(t.methods == {"telemetry"} for t in sources)
    provisional = observed_only or any(t.status == "review" for t in sources)
    severity = _severity(graph, rule, relation, sources, provisional)
    note = ""
    if observed_only:
        note = (
            "learned from watching this agent, so it cannot fail it — an expectation "
            "derived from behaviour passes by construction"
        )

    if rule.kind == "text_required":
        allowed = graph.out(subject, "GENERATION_ALLOWED")
        if allowed and allowed[0].tail.strip().lower() == "true":
            severity = "info"
            note = "the policy permits paraphrase here, so exact wording is advisory"
        elif not allowed:
            severity = "info" if severity == "warning" else severity
            note = "the policy does not say whether paraphrase is permitted"

    if provisional and not observed_only:
        note = (note + " " if note else "") + (
            "rests on an extraction awaiting review, so it advises rather than blocks"
        )

    values = tuple(sorted(set(expected)))
    return Assertion(
        id=assertion_id(rule.kind, subject, *values),
        kind=cast(AssertionKind, rule.kind),
        subject=subject,
        expected=values,
        scope=rule.scope,
        dimension=cast(Dimension, rule.dimension),
        severity=severity,
        level=_level(graph, subject, sources),
        sources=tuple(sorted({t.key for t in sources})),
        evidence=_evidence(sources),
        provisional=provisional,
        note=note,
    )


def _severity(
    graph: Graph,
    rule: CheckSpec,
    relation: str,
    sources: Sequence[Triple],
    provisional: bool,
) -> Severity:
    if provisional:
        return "advisory"

    # A Rule that states its own consequence outranks the relation's materiality: the
    # policy said how hard this bites, and the ontology only said it matters.
    for triple in sources:
        declared = graph.out(triple.head, "HAS_SEVERITY")
        if declared:
            return _as_severity(declared[0].tail)

    return "error" if any(t.materiality == "high" for t in sources) else "warning"


def _level(graph: Graph, subject: str, sources: Sequence[Triple]) -> Level:
    if subject and graph.out(subject, "HAS_CONDITION"):
        return "L3"
    if all("deterministic" in t.methods for t in sources):
        return "L1"
    return "L2"


def _evidence(sources: Sequence[Triple]) -> tuple[Span, ...]:
    spans = [span for triple in sources for span in triple.spans]
    return tuple(spans[:_MAX_EVIDENCE])


# Relations whose tail is a boolean: `IS_TERMINAL false` says a state is not an ending,
# which is not an expectation to check.
_BOOLEAN_TAILED = frozenset({"IS_TERMINAL"})


def _asserts_something(relation: str, triple: Triple) -> bool:
    if relation not in _BOOLEAN_TAILED:
        return True
    return triple.tail.strip().lower() == "true"


def _as_severity(value: str) -> Severity:
    lowered = value.strip().lower()
    if lowered in {"blocker", "error", "warning", "info"}:
        return lowered  # type: ignore[return-value]
    return "warning"
