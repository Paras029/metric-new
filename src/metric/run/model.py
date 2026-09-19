"""What it takes to actually run a planned variant, and what comes back.

`metric plan` has been producing runs that nothing ran. Everything downstream of it —
the whole attribution layer — took a cohort on faith. This package closes that, and the
shape it takes is mostly a set of refusals.

**The runner does not know the answer.** It drives a conversation and records what
happened. Whether what happened was right is decided afterwards, by the same evaluator
that grades a production trace, against a contract resolved from the graph. A harness
that both stages a situation and judges it is marking its own homework, and the
separation is the only reason a synthetic pass means anything.

**A run produces a `Trace`, not a verdict.** The same type `read_galileo_export` returns.
So a simulated run goes through binding, state placement, ground truth and grading by
exactly the path a real conversation does — which is what stops the synthetic benchmark
drifting away from the production evaluation it is supposed to predict.

**The agent is behind a protocol.** Three methods. An installation reaches its agent over
whatever transport it has, and nothing in this package knows about it — the same seam
`Gateway` gives the model call.

What the customer says *is* allowed to come from the base. A test case is entitled to
know which situation it is staging; that is what a base is. It is the contract, and only
the contract, that must be resolved independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from metric.attribution import Outcome
from metric.evaluate.model import Evaluation
from metric.trace.model import Trace


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool the agent invoked, and the symbolic result it got back."""

    name: str
    arguments: tuple[tuple[str, str], ...] = ()
    outcome: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": [list(pair) for pair in self.arguments],
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class Reply:
    """One turn from the agent's side.

    `state` is the agent narrating where it thinks it is. An agent that fills it can be
    *failed*; an agent that leaves it empty can only be analysed, because the binder has
    to infer the position and inference is not good enough to accuse with. That asymmetry
    is deliberate and it is the strongest argument for instrumenting an agent properly.
    """

    said: str = ""
    tools: tuple[ToolCall, ...] = ()
    state: str = ""
    capability: str = ""
    finished: bool = False

    @property
    def silent(self) -> bool:
        return not self.tools


class Session(Protocol):
    """One conversation with the agent under test."""

    def send(self, utterance: str) -> Reply:
        """Give the agent the customer's next turn and take its reply."""
        ...


class Agent(Protocol):
    """The system under test, behind three methods and nothing else."""

    @property
    def identity(self) -> str:
        """What the manifest records. A different agent is a different result."""
        ...

    def begin(self, run_id: str) -> Session: ...


class Customer(Protocol):
    """The other side of the conversation: what the situation makes someone say."""

    @property
    def identity(self) -> str: ...

    def opening(self) -> str: ...

    def reply(self, to: Reply) -> str | None:
        """The next customer turn, or `None` when the situation is played out."""
        ...


@dataclass(frozen=True, slots=True)
class Run:
    """One variant, run once: what was said, what was graded, and what it cost."""

    variant: str
    scenario: str
    levels: tuple[tuple[str, str], ...]
    trace: Trace
    evaluation: Evaluation
    agent: str
    customer: str
    staged: bool = True
    unrendered: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def findings(self) -> tuple[str, ...]:
        """What the turn walk found, on turns the agent placed itself.

        Only those. On an inferred turn the position is a guess and a finding against it
        would be an accusation built on one.
        """
        return tuple(f for t in self.evaluation.turns if t.gradable for f in t.findings)

    @property
    def passed(self) -> bool:
        """A run passes when nothing gradable failed, by either route.

        Two routes, because the evaluator has two. Compiled assertions catch what the
        contract states; the turn walk catches what the graph required *at a position* —
        a tool the state does not declare, a transition it does not permit, wording it
        fixes. Counting only the first let an agent calling tools it had no business
        calling pass with the finding printed underneath, which is worse than not looking.

        Not "everything passed": `undecided` and `not_applicable` are neither. Folding
        them into a pass is how an evaluator comes to look confident about a blind spot,
        and folding them into a failure would punish an agent for our instrumentation.
        """
        return not self.evaluation.by_outcome("fail") and not self.findings

    @property
    def gradable(self) -> bool:
        """Whether this run could have failed at all.

        A run with no gradable turn tells you nothing about the agent, and counting it as
        a pass in the cohort would let poor instrumentation read as good behaviour.
        """
        return self.evaluation.certain > 0

    @property
    def usable(self) -> bool:
        """Gradable, and the situation the base names actually arose.

        `staged` is the weaker of the two and the easier to get wrong. A conversation can
        run to completion, bind perfectly and fail an assertion without ever reaching the
        thing under test — the customer pressed for a forbidden action and the agent was
        somewhere else entirely. Counting that as a failure blames the agent for the
        harness, and counting it as a pass is worse.

        What is checked is deliberately weak and honest about it: whether the run touched
        any entity the base is about. That catches the situation never arising. It cannot
        confirm the situation arose *as the base intended*, and nothing here can.
        """
        return self.gradable and self.staged

    def outcome(self) -> Outcome:
        return Outcome(
            variant=self.variant,
            scenario=self.scenario,
            levels=self.levels,
            passed=self.passed,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "scenario": self.scenario,
            "levels": [list(pair) for pair in self.levels],
            "agent": self.agent,
            "customer": self.customer,
            "passed": self.passed,
            "gradable": self.gradable,
            "staged": self.staged,
            "usable": self.usable,
            "unrendered": list(self.unrendered),
            "notes": list(self.notes),
            "trace": self.trace.as_dict(),
            "failures": [
                {
                    "kind": v.assertion.kind,
                    "severity": v.assertion.severity,
                    "detail": v.detail,
                }
                for v in self.evaluation.failures
            ],
        }


@dataclass(frozen=True, slots=True)
class Cohort:
    """Every run of a plan, and what can honestly be said about the set of them."""

    runs: tuple[Run, ...]
    agent: str
    identity: str
    notes: tuple[str, ...] = ()

    @property
    def gradable(self) -> tuple[Run, ...]:
        return tuple(r for r in self.runs if r.gradable)

    @property
    def usable(self) -> tuple[Run, ...]:
        return tuple(r for r in self.runs if r.usable)

    @property
    def unstaged(self) -> tuple[Run, ...]:
        return tuple(r for r in self.runs if not r.staged)

    def outcomes(self) -> tuple[Outcome, ...]:
        """Only usable runs reach attribution.

        A cohort padded with runs that could not have failed, or that never reached the
        situation, would show every factor level doing well — and the more padding, the
        stronger the finding.
        """
        return tuple(r.outcome() for r in self.usable)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "identity": self.identity,
            "runs": [r.as_dict() for r in self.runs],
            "gradable": len(self.gradable),
            "usable": len(self.usable),
            "unstaged": len(self.unstaged),
            "notes": list(self.notes),
        }
