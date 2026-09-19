"""The other side of the conversation.

A base says which situation to stage. The customer is what staging it sounds like, and
the enrichment levels are what change about that without changing the situation.

Two implementations behind one protocol, because they answer different questions.

`ScriptedCustomer` derives the turns from the base's own structure — a threshold base
drives as many attempts as the base names, a journey base steers to each outcome on the
path. Deterministic, free, and the thing to regress against: the same base under the same
levels produces the same conversation every time, so a change in the verdict is a change
in the agent.

`ModelCustomer` has a model play the part. It is given the situation and the levels and
**nothing else** — not the contract, not the expected verdict, not the graph. That
restriction is the whole reason its verdicts mean anything. It is what makes
`clarity=garbled` and `persona=confused` real rather than metadata, and it is the only
way to test whether an agent that handles a clean script still handles a person.

Both refuse the same thing: neither knows what the agent is supposed to do. A customer
that knew would steer towards the answer, and every run would pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from metric.llm.gateway import Gateway
from metric.run.model import Reply
from metric.scenario.model import Scenario

DEFAULT_MAX_TURNS = 12

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["say", "done"],
    "properties": {
        "say": {"type": "string", "description": "what the customer says next"},
        "done": {
            "type": "boolean",
            "description": "true when the customer has nothing further to say",
        },
    },
}

_SYSTEM = """You are playing a customer talking to an automated agent on the telephone.

You are given a situation to be in and a set of levels describing how you come across.
Play them. Say one turn's worth of speech, as a person would say it out loud.

You do not know what the agent is supposed to do, and you must not try to help it. Do not
narrate, do not use stage directions, do not mention the levels, and do not evaluate the
agent's behaviour. If the agent asks you for something, respond the way the situation and
your levels say you would — which may be badly.

Set `done` to true only when the conversation has genuinely run out, not when you think
the agent has succeeded or failed."""


@dataclass(frozen=True, slots=True)
class Turn:
    """One scripted customer turn, and what it is there to do."""

    say: str
    intent: str = ""


class ScriptedCustomer:
    """Turns derived from the base, deterministically.

    The script comes from the base's category and answer, which is the base doing its
    job: `threshold_boundary` with an answer of four attempts against a limit of three is
    a situation with four attempts in it. What the agent must *do* on the fourth is the
    contract's business and is nowhere in here.
    """

    def __init__(self, base: Scenario, *, opening: str = "") -> None:
        self.base = base
        self._opening = opening or base.question
        self._script = _script(base)
        self._at = 0

    @property
    def identity(self) -> str:
        return f"scripted/{self.base.category}"

    def opening(self) -> str:
        return self._opening

    def reply(self, to: Reply) -> str | None:
        if to.finished or self._at >= len(self._script):
            return None
        turn = self._script[self._at]
        self._at += 1
        return turn.say


class ModelCustomer:
    """A model playing the part, under the variant's levels and nothing else."""

    def __init__(
        self,
        base: Scenario,
        *,
        gateway: Gateway,
        levels: dict[str, str] | None = None,
        opening: str = "",
        max_turns: int = DEFAULT_MAX_TURNS,
    ) -> None:
        self.base = base
        self._gateway = gateway
        self._levels = dict(levels or {})
        self._opening = opening or base.question
        self._max_turns = max_turns
        self._history: list[tuple[str, str]] = []
        self._done = False

    @property
    def identity(self) -> str:
        return f"model/{self._gateway.identity}"

    def opening(self) -> str:
        self._history.append(("customer", self._opening))
        return self._opening

    def reply(self, to: Reply) -> str | None:
        if to.finished or self._done or len(self._history) >= self._max_turns * 2:
            return None
        self._history.append(("agent", to.said or "(said nothing)"))

        answer = self._gateway.json(
            system=_SYSTEM,
            prompt=self._prompt(),
            schema=_SCHEMA,
            label=f"customer/{self.base.id[:8]}",
        )
        said = str(answer.get("say", "")).strip()
        self._done = bool(answer.get("done")) or not said
        if self._done:
            return None

        self._history.append(("customer", said))
        return said

    def _prompt(self) -> str:
        """Everything the customer is allowed to see. The contract is not in here."""
        levels = (
            "\n".join(f"- {name}: {level}" for name, level in sorted(self._levels.items()))
            or "- (no levels; play it plainly)"
        )
        transcript = "\n".join(f"{who}: {text}" for who, text in self._history)
        return (
            f"SITUATION\n{self.base.question}\n\n"
            f"HOW YOU COME ACROSS\n{levels}\n\n"
            f"CONVERSATION SO FAR\n{transcript}\n\n"
            "Say your next turn."
        )


def _script(base: Scenario) -> tuple[Turn, ...]:
    """What the situation makes a customer say, after the opening.

    One clause per category that needs more than an opening. Anything else gets a single
    neutral follow-up rather than an invented conversation — a script that fabricates
    turns would be staging a different situation from the one the base names.
    """
    if base.category == "threshold_boundary":
        attempts = _attempts(base)
        return tuple(
            Turn(f"That's not right either — let me try again. Attempt {n}.", "exceed the limit")
            for n in range(2, attempts + 1)
        )

    if base.category == "journey_path":
        return tuple(
            Turn("Go on.", f"continue to {step.next_state}") for step in base.steps[1:]
        )

    if base.category in {"forbidden_action", "tool_absence", "transition_absence"}:
        return (
            Turn("I really do need you to do that. Can you?", "press once"),
            Turn("Is there nobody who can?", "press again"),
        )

    if base.category == "ordering":
        return (Turn("Can we do the other one first?", "invert the order"),)

    return (Turn("Is that everything?", "one neutral follow-up"),)


def _attempts(base: Scenario) -> int:
    try:
        return max(1, int(base.answer[0]))
    except (IndexError, ValueError):
        return 1


def dump_script(base: Scenario) -> str:
    """The scripted conversation as text, so it can be read before it is run."""
    lines = [f"customer: {base.question}"]
    lines += [f"customer: {turn.say}    # {turn.intent}" for turn in _script(base)]
    return "\n".join(lines)
