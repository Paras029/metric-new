"""One resolver, two entry points.

```python
resolve_for_scenario(graph, scenario) -> Contract
resolve_for_trace(graph, bound)       -> Contract
```

This is the structural change against the old generator, which had exactly one way in
— reading a workbook it had written itself — and therefore no way to ask "what did
policy require at the point this real conversation had reached?".

Both functions compile the *same* assertions from the *same* graph and differ only in
what they narrow to. That matters more than it looks: a synthetic benchmark and a
production evaluator that resolve expectations through separate code will drift, and
the drift is invisible because each stays self-consistent. Here a divergence would have
to be a divergence in scope, which is one comparison away from being visible.
"""

from __future__ import annotations

from metric.contract.compile import build_contract
from metric.contract.model import Contract
from metric.graph.model import Graph
from metric.ontology.schema import Schema
from metric.scenario.paths import Scenario
from metric.trace.binding import BoundTrace


def resolve_for_scenario(
    graph: Graph, schema: Schema, scenario: Scenario, *, identity: str
) -> Contract:
    """What policy requires of a generated journey."""
    return build_contract(
        graph,
        schema,
        identity=identity,
        binding=f"scenario:{scenario.id}",
        scope=scenario.entities,
    )


def resolve_for_trace(
    graph: Graph, schema: Schema, bound: BoundTrace, *, identity: str
) -> Contract:
    """What policy required of the journey this trace actually took.

    Scope is what the trace bound to. An unbound observation narrows nothing — it is
    reported by the binder instead, because an expectation dropped for want of a
    binding is an expectation nobody knows is missing.
    """
    observed = {b.entity for b in bound.bindings if b.entity is not None}
    return build_contract(
        graph,
        schema,
        identity=identity,
        binding=f"trace:{bound.trace.conversation_id}",
        scope=tuple(sorted(observed)),
    )
