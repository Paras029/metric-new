"""Running a contract against a trace."""

from __future__ import annotations

from metric.contract.model import Contract
from metric.evaluate.graders import Evidence, grade
from metric.evaluate.model import Evaluation
from metric.graph.model import Graph
from metric.ontology.schema import Schema
from metric.resolve import resolve_for_trace
from metric.runtime.context import replay
from metric.trace.binding import BoundTrace, Lexicon, bind
from metric.trace.model import Trace


def evaluate(
    graph: Graph, bound: BoundTrace, contract: Contract, *, checkpoint_variable: str = ""
) -> Evaluation:
    lexicon = Lexicon(graph, checkpoint_variable=checkpoint_variable)
    evidence = Evidence(graph=graph, bound=bound, context=replay(bound, lexicon))
    return Evaluation(
        contract=contract,
        verdicts=tuple(grade(assertion, evidence) for assertion in contract.assertions),
        binding_coverage=bound.coverage,
        unbound=tuple(sorted({b.token for b in bound.unbound if b.token})),
    )


def evaluate_trace(
    graph: Graph,
    schema: Schema,
    trace: Trace,
    *,
    identity: str,
    checkpoint_variable: str = "",
) -> Evaluation:
    """Bind, resolve and grade in one step — the production path.

    Nothing about a trace is assumed: what it binds to decides the contract, and what
    it fails to bind is carried through to the evaluation rather than narrowing it.
    """
    bound = bind(trace, graph, checkpoint_variable=checkpoint_variable)
    contract = resolve_for_trace(graph, schema, bound, identity=identity)
    return evaluate(graph, bound, contract, checkpoint_variable=checkpoint_variable)
