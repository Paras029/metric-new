"""A reference agent, for exercising the loop and for showing what it catches.

**This is a test fixture, not a system under test.** `GraphAgent` walks the same graph it
will be graded against, so a clean one passes by construction and its passing means
nothing about any real agent. Saying so plainly matters: an evaluation harness that ships
with a agent scoring 100% invites exactly the wrong reading.

What it is actually for is two things a real agent cannot give you.

**A known-good baseline.** If a run fails with no flaw injected, the harness is wrong, not
the agent. That is the only way to tell a defect in the evaluator from a defect in the
thing evaluated, and without it every early failure is ambiguous.

**A controlled defect.** Each flaw below is a specific, named thing an agent does wrong,
and turning one on must produce exactly the finding that describes it — no more, and not a
different one. That is the evaluator's own test, and it is the reason the flaws are
enumerated rather than random.

`flaws` also takes a mapping from factor level to flaw, which is what makes an end-to-end
attribution test possible: make an agent that degrades under `asr=heavy_noise` and the
cohort should recover that level and no other.

One rule this has to keep even though it reads the graph: **it speaks the wire language,
not the graph's.** It emits the names a tool and an outcome are *called*, never their
entity ids, so every run goes through the telemetry binding a production trace goes
through. Emitting ids made the binder resolve nothing while the trace still looked
plausible, and a clean agent failed for not calling a tool it had just called.
"""

from __future__ import annotations

from collections.abc import Mapping

from metric.graph.journey import Journey
from metric.graph.model import Graph
from metric.run.model import Reply, ToolCall

FLAWS = (
    "no_checkpoint",  # never narrates where it is: analysable, never gradable
    "ignore_limit",  # keeps going past a declared threshold
    "extra_tool",  # calls something the state does not declare
    "skip_wording",  # omits wording the policy fixes
    "jump",  # moves somewhere that does not follow
    "stall",  # stops calling tools without reaching an ending
)


class GraphAgent:
    """Walks the graph, with whichever defects were asked for."""

    def __init__(
        self,
        graph: Graph,
        *,
        flaws: Mapping[str, str] | tuple[str, ...] = (),
        levels: Mapping[str, str] | None = None,
        name: str = "reference",
    ) -> None:
        self.graph = graph
        self.journey = Journey(graph)
        self._name = name
        self._flaws = _resolve(flaws, levels or {})

    @property
    def identity(self) -> str:
        active = ",".join(sorted(self._flaws)) or "clean"
        return f"graph-agent/{self._name}?flaws={active}"

    @property
    def flaws(self) -> frozenset[str]:
        return self._flaws

    def begin(self, run_id: str) -> _Walk:
        return _Walk(self.graph, self.journey, self._flaws)


def _resolve(
    flaws: Mapping[str, str] | tuple[str, ...], levels: Mapping[str, str]
) -> frozenset[str]:
    """Either a flat set of flaws, or flaws conditional on the levels this run was given."""
    if not isinstance(flaws, Mapping):
        return frozenset(flaws)
    return frozenset(
        flaw
        for level, flaw in flaws.items()
        if level in {f"{n}={v}" for n, v in levels.items()} or level in set(levels.values())
    )


class _Walk:
    """One conversation: a position in the graph and the defects applied to leaving it."""

    def __init__(self, graph: Graph, journey: Journey, flaws: frozenset[str]) -> None:
        self.graph = graph
        self.journey = journey
        self.flaws = flaws
        entries = journey.entries()
        self.state = entries[0] if entries else ""
        self.visits: dict[str, int] = {self.state: 1} if self.state else {}
        self.turn = 0

    def send(self, utterance: str) -> Reply:
        """One turn is one state's worth of work, and then the move out of it.

        The order matters and getting it wrong is subtle: everything reported — the
        tools, the wording, the narrated position — belongs to the state the agent is
        *in*, and only then does it move. Computing the checkpoint after the move made
        every turn report the tools of one state under the name of the next, which
        surfaced as a clean agent failing `action_required` at a state it had in fact
        reached.
        """
        self.turn += 1
        here = self.state
        if not here:
            return Reply(said="I cannot help with that.", finished=True)

        if "stall" in self.flaws and self.turn > 1:
            return Reply(said="...", state=self._narrate(here))

        reply = Reply(
            said=self._say(here),
            tools=self._tools(here),
            state=self._narrate(here),
            capability=self._capability(here),
            finished=self._advance(here) is None,
        )
        return reply

    def _tools(self, here: str) -> tuple[ToolCall, ...]:
        """The tools this state declares, plus the ones its obligations reach through.

        A policy states obligations two ways. `USES_TOOL` says which tools belong at a
        state; `REQUIRES_ACTION` says an action is due there, and the action `INVOKES` a
        tool. An agent that reads only the first does everything the state permits and
        nothing it owes — which is what this one did until the clean baseline failed with
        `transfer_to_ccp did not happen`, correctly.
        """
        declared = [t.tail for t in self.graph.out(here, "USES_TOOL")]
        for source in (here, *(r.tail for r in self.graph.out(here, "GOVERNED_BY"))):
            for required in (
                *self.graph.out(source, "REQUIRES_ACTION"),
                *self.graph.out(source, "RULE_REQUIRES"),
            ):
                declared.extend(
                    i.tail for i in self.graph.out(required.tail, "INVOKES")
                    if i.tail not in declared
                )

        if "extra_tool" in self.flaws:
            elsewhere = [
                t.tail for t in self.graph.by_relation("USES_TOOL") if t.tail not in declared
            ]
            if elsewhere:
                declared.append(sorted(elsewhere)[0])
        return tuple(
            ToolCall(name=self.graph.label(tool), outcome=self._outcome(tool))
            for tool in declared
        )

    def _outcome(self, tool: str) -> str:
        returned = sorted(t.tail for t in self.graph.out(tool, "RETURNS"))
        return self.graph.label(returned[0]) if returned else ""

    def _say(self, here: str) -> str:
        if "skip_wording" in self.flaws:
            return "Alright."
        fixed = [
            text.tail
            for turn in self.graph.out(here, "HAS_TURN")
            for text in self.graph.out(turn.tail, "HAS_CANONICAL_TEXT")
        ]
        return " ".join(fixed) if fixed else "Alright."

    def _narrate(self, here: str) -> str:
        if "no_checkpoint" in self.flaws:
            return ""
        return self.graph.label(here)

    def _capability(self, here: str) -> str:
        holders = [t.head for t in self.graph.by_relation("HAS_STATE") if t.tail == here]
        return self.graph.label(holders[0]) if holders else ""

    def _advance(self, here: str) -> str | None:
        """Move, and return where to — or `None` when the journey is over."""
        if here in self.journey.terminals:
            return None

        successors = self.journey.successors(here)
        if not successors:
            return None

        if "jump" in self.flaws:
            allowed = {edge[2] for edge in successors}
            elsewhere = sorted(set(self.graph.ids_of_type("State")) - allowed - {here})
            if elsewhere:
                self.state = elsewhere[0]
                return self.state

        target = self._next(successors)
        if target is None:
            return None
        self.state = target
        self.visits[target] = self.visits.get(target, 0) + 1
        return target

    def _next(self, successors: tuple[tuple[str, str, str], ...]) -> str | None:
        """Prefer a state with visits left, so a retry loop is walked rather than skipped.

        Without the limit, this is what an agent that never enforces a threshold does:
        it keeps taking the retry edge because the customer keeps giving it one.
        """
        for _, _, target in successors:
            seen = self.visits.get(target, 0)
            if "ignore_limit" in self.flaws or seen < self.journey.limit(target):
                return target
        return successors[-1][2] if successors else None
