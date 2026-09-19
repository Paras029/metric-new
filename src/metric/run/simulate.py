"""Driving one run, and a whole plan.

The loop is small on purpose: open, send, record, ask the customer for the next turn,
stop. Everything that decides whether the run was any good happens after it, through
`evaluate_trace` — the same function that grades a conversation lifted out of production.

What the loop is careful about:

**It stops for a reason, and says which.** An agent that never finishes, a customer that
runs out, a turn budget exhausted — three different things, and folding them together
would hide a hung agent inside a normal-looking cohort.

**It records silence.** A turn that produced no tool call is a fact about the run and has
to be assertable against, so it becomes an observation rather than nothing at all.

**It never writes a state the agent did not narrate.** The checkpoint observation is
written only when the reply carries one. Filling it in from the plan would make every
turn `checkpoint`-certain and every inference look like instrumentation, which would turn
the one property that lets a run fail an agent into a lie.

**A run that could not have failed does not reach attribution.** `Cohort.outcomes()` drops
them. A cohort padded with ungradable runs shows every factor level doing well, and the
better the padding the stronger the finding.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from metric.contract.compile import Compiled
from metric.enrich.design import Plan, Variant
from metric.enrich.materialize import Materialiser, identity, materialize
from metric.evaluate.model import Evaluation
from metric.evaluate.run import evaluate_trace
from metric.graph.model import Graph
from metric.ontology.schema import Schema
from metric.run.customer import ScriptedCustomer
from metric.run.model import Agent, Cohort, Customer, Reply, Run
from metric.scenario.model import Scenario
from metric.trace.model import Observation, Trace
from metric.trace.model import Turn as TraceTurn

DEFAULT_MAX_TURNS = 12

CustomerFactory = Callable[[Scenario, dict[str, str]], Customer]

# Only the reference fixture needs this. A real agent is one object for the whole cohort,
# because it is one deployed system, and it never sees the levels a run was planned under
# — it sees what the customer says, which is the whole point of the materialiser.
AgentFactory = Callable[[Scenario, dict[str, str]], Agent]


@dataclass(frozen=True, slots=True)
class Settings:
    """How a run is driven. Nothing here can change what is required of the agent."""

    max_turns: int = DEFAULT_MAX_TURNS
    checkpoint_variable: str = "checkpoint"
    materialiser: Materialiser | str = identity


def simulate(
    base: Scenario,
    variant: Variant,
    agent: Agent,
    *,
    graph: Graph,
    schema: Schema,
    identity_digest: str,
    compiled: Compiled | None = None,
    settings: Settings | None = None,
    customer: Customer | None = None,
) -> Run:
    """Run one variant and grade it the way a production trace is graded."""
    config = settings or Settings()
    levels = variant.factor_levels

    rendered = materialize(
        scenario=base.id,
        variant=variant.id,
        question=base.question,
        levels=levels,
        materialiser=config.materialiser,
    )
    speaker = customer or ScriptedCustomer(base, opening=rendered.text)

    trace, notes = _converse(
        speaker,
        agent,
        run_id=variant.id,
        max_turns=config.max_turns,
        checkpoint_variable=config.checkpoint_variable,
    )

    evaluation = evaluate_trace(
        graph,
        schema,
        trace,
        identity=identity_digest,
        checkpoint_variable=config.checkpoint_variable,
        compiled=compiled,
    )

    return Run(
        variant=variant.id,
        scenario=base.id,
        levels=variant.levels,
        trace=trace,
        evaluation=evaluation,
        agent=agent.identity,
        customer=speaker.identity,
        staged=_staged(base, evaluation),
        unrendered=rendered.unrendered,
        notes=notes,
    )


def _staged(base: Scenario, evaluation: Evaluation) -> bool:
    """Did the run reach anything the base is about?

    The weakest useful check, and the strongest available: a base names the entities its
    situation involves, and a conversation that touched none of them did not stage it.
    Nothing here can confirm the situation arose the way the base meant it to.
    """
    wanted = set(base.entities) | set(base.subject)
    if not wanted:
        return True
    touched = {
        entity
        for truth in evaluation.turns
        for entity in (*truth.binding.states, *truth.observed.tools, *truth.observed.outcomes)
    }
    return bool(wanted & touched)


def _converse(
    customer: Customer,
    agent: Agent,
    *,
    run_id: str,
    max_turns: int,
    checkpoint_variable: str,
) -> tuple[Trace, tuple[str, ...]]:
    session = agent.begin(run_id)
    turns: list[TraceTurn] = []
    said = customer.opening()
    notes: list[str] = []

    for index in range(max_turns):
        reply = session.send(said)
        turns.append(_turn(index, said, reply, checkpoint_variable))

        if reply.finished:
            break

        # The customer running out is not the end of the call, and this is the subtlest
        # thing in the loop. An agent moves at the end of its turn, so the state it moves
        # *into* — very often the one that has to transfer, or say the closing wording —
        # never gets a turn of its own if the conversation stops the moment the script
        # does. A real caller falls silent and stays on the line, so that is what happens.
        #
        # Capping the silence instead was tried and is worse: it cuts off an agent that is
        # still making progress, and a run cut off short of an ending is indistinguishable
        # from one that stalled. Only the turn budget ends a call, and hitting it is
        # reported, so a stall is visible as what it is.
        following = customer.reply(reply)
        said = following if following is not None else ""
    else:
        notes.append(
            f"the conversation hit the {max_turns}-turn budget without the agent finishing; "
            "this is a stalled run, not a completed one"
        )

    return Trace(conversation_id=run_id, source="simulated", turns=tuple(turns)), tuple(notes)


def _turn(index: int, heard: str, reply: Reply, checkpoint_variable: str) -> TraceTurn:
    observations: list[Observation] = []

    def record(kind: str, name: str = "", value: str = "", **extra: object) -> None:
        observations.append(
            Observation(
                turn=index,
                step=len(observations),
                kind=kind,  # type: ignore[arg-type]
                name=name,
                value=value,
                ref=f"{index}.{len(observations)}",
                arguments=extra.get("arguments", ()),  # type: ignore[arg-type]
            )
        )

    record("utterance", value=heard)

    if reply.capability:
        record("capability", name=reply.capability)
    if reply.state and checkpoint_variable:
        record("state_write", name=checkpoint_variable, value=reply.state)

    for call in reply.tools:
        record("tool_call", name=call.name, arguments=call.arguments)
        if call.outcome:
            record("outcome", name=call.outcome)

    if reply.silent:
        record("silence")
    if reply.said:
        record("assistant", value=reply.said)

    return TraceTurn(index=index, name=f"turn {index}", observations=tuple(observations))


def simulate_plan(
    bases: Sequence[Scenario],
    plan: Plan,
    agent: Agent,
    *,
    graph: Graph,
    schema: Schema,
    identity_digest: str,
    compiled: Compiled | None = None,
    settings: Settings | None = None,
    customers: CustomerFactory | None = None,
    agents: AgentFactory | None = None,
    limit: int = 0,
) -> Cohort:
    """Run every variant of a plan, in the order the plan lists them."""
    by_id = {base.id: base for base in bases}
    runs: list[Run] = []
    notes: list[str] = []
    missing: set[str] = set()

    variants = plan.variants[:limit] if limit else plan.variants
    if limit and limit < len(plan.variants):
        notes.append(
            f"ran {limit} of {len(plan.variants)} variants; this is a sample of the plan, "
            "and a factor level may be under-represented in it"
        )

    for variant in variants:
        base = by_id.get(variant.scenario)
        if base is None:
            missing.add(variant.scenario)
            continue
        levels = variant.factor_levels
        runs.append(
            simulate(
                base,
                variant,
                agents(base, levels) if agents else agent,
                graph=graph,
                schema=schema,
                identity_digest=identity_digest,
                compiled=compiled,
                settings=settings,
                customer=customers(base, levels) if customers else None,
            )
        )

    if missing:
        notes.append(f"{len(missing)} variants named a base this build does not have")

    ungradable = len(runs) - sum(1 for r in runs if r.gradable)
    if ungradable:
        notes.append(
            f"{ungradable} of {len(runs)} runs had no turn the agent placed itself, so they "
            "could not have failed and are excluded from attribution"
        )
    unstaged = sum(1 for r in runs if not r.staged)
    if unstaged:
        notes.append(
            f"{unstaged} of {len(runs)} runs never reached anything their base is about, so "
            "the situation under test did not arise and they are excluded from attribution"
        )
    if any(r.unrendered for r in runs):
        notes.append(
            "some factor levels were not rendered into the conversation, so nothing should "
            "be attributed to them — register a materialiser to change that"
        )

    return Cohort(
        runs=tuple(runs),
        agent=agent.identity,
        identity=identity_digest,
        notes=tuple(notes),
    )
