"""Reading a workflow off a set of pictures, in three passes.

**One image at a time.** Each picture is read alone, into an explicit list of boxes and
arrows — the way a person would, and enumerated rather than described, so that a box which
was missed shows up as an arrow pointing at nothing instead of vanishing. A model given
eight tiles at once summarises; given one, it counts.

**Then the join.** One pass sees every image's reading together and follows an arrow that
ran off the edge of one picture into the picture that picks it up. This is what makes a
workflow too long for one page readable at all: the tiles are given in the order a person
would look at them, each box keeps the id its own image gave it, and the join is a
question about which ids are the same box.

**Then the repair.** `structure.audit` says what the joined graph cannot account for — an
outcome that leads nowhere, a state nothing reaches, a branch with one arrow — and those
findings go back with the pictures still attached. Not "read it again, better", which gets
a differently-wrong answer, but a list of specific holes.

A repair never removes. A second look that came back quieter is a worse reading, not a
correction, and letting it delete the first reading's boxes is how a repair pass shrinks a
graph every time it runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from metric.diagram.images import Image
from metric.diagram.structure import Structure, audit, clean, merge
from metric.llm.gateway import Gateway

MAX_REPAIRS = 2

_NODE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["states", "decisions"],
    "properties": {
        "states": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "name"],
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "an id you assign, like S1, S2 — unique on this image",
                    },
                    "name": {"type": "string", "description": "the text written in the box"},
                    "reached_via": {
                        "type": "string",
                        "description": (
                            'either "Start", or "<decision id>=<outcome label>" naming the '
                            "arrow that lands here"
                        ),
                    },
                    "next_decisions": {"type": "array", "items": {"type": "string"}},
                    "next_states": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "boxes reached by an unlabelled arrow",
                    },
                    "terminal": {"type": "boolean", "description": "the journey ends here"},
                    "tools": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "systems or calls named inside the box",
                    },
                    "continues": {
                        "type": "string",
                        "description": (
                            "if an arrow leaves this box and runs off the edge of the "
                            "image, the connector label or page reference it carries"
                        ),
                    },
                },
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "name", "outcomes"],
                "properties": {
                    "id": {"type": "string", "description": "an id you assign, like D1, D2"},
                    "name": {"type": "string", "description": "the text in the diamond"},
                    "outcomes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "the label on each arrow leaving it",
                    },
                    "at_state": {"type": "string", "description": "the box this branches from"},
                },
            },
        },
    },
}

_READ_SYSTEM = """You are reading one page of a workflow diagram.

Enumerate what is drawn. Do not summarise it and do not describe it in prose — list every
box and every arrow, because a box you mention in passing is a box the next step cannot
use.

A box is a state. A diamond, or any box with more than one labelled arrow leaving it, is a
decision, and the text on each arrow leaving it is an outcome. An arrow with no label
leading straight from one box to another is `next_states`.

Give every box and diamond an id of your own — S1, S2, D1 — unique within this image.
Say how each box is reached: "Start" for the one the journey opens in, otherwise
"<decision id>=<outcome label>".

This page may be part of a longer diagram. If an arrow leaves a box and runs off the edge
of the page, or ends at an off-page connector, put whatever that connector says into
`continues` rather than guessing where it goes. Another page will have the other end.

Read only what is drawn. A box you cannot read the text of is still a box: give it an id
and leave the name empty."""

_JOIN_SYSTEM = """You are joining several readings of one workflow into a single graph.

Each reading below is one page of the same diagram, in page order, with ids that are only
unique within its own page. Your job is to work out which boxes are the same box and
produce one graph.

Two things to get right:

Arrows that ran off the edge. A box with `continues` set has an arrow leaving the page.
Find where it lands on another page — usually a box whose connector label matches, or the
first box on the next page — and record the join as `next_states` or `reached_via` on the
real ids.

Repeated boxes. The same box often appears on two pages, once as the real thing and once
as a stub showing where a previous page's arrow arrives. Keep one, and keep every arrow
either copy had.

Renumber freely: give the joined graph its own ids. Keep the box text exactly as it was
read. Do not invent a box or an arrow that no page showed."""

_REPAIR_SYSTEM = """You are looking again at a workflow diagram to settle specific gaps.

Below is the graph read from these pages, and a list of things it cannot account for.
Each one is a place the reading is demonstrably incomplete — an arrow whose destination
went unrecorded, a box nothing leads to.

Look at the pictures again and answer only those points. Return the entries you are
correcting or adding, with their existing ids where they have one.

If a gap is genuinely how the diagram is drawn — an arrow really does leave the page with
no other page picking it up — leave that entry alone rather than inventing a destination.
Returning nothing is a valid answer."""


@dataclass(frozen=True, slots=True)
class Reading:
    """What a set of pictures turned out to say, and how confident that is."""

    structure: Structure
    per_image: tuple[tuple[str, Structure], ...]
    remaining: tuple[str, ...]
    repairs: int
    notes: tuple[str, ...]

    @property
    def sound(self) -> bool:
        """Whether the graph is walkable — no dangling arrows, no unreachable boxes."""
        return not self.remaining and not self.structure.empty

    def as_dict(self) -> dict[str, Any]:
        return {
            "structure": self.structure.as_dict(),
            "per_image": {name: found.as_dict() for name, found in self.per_image},
            "remaining": list(self.remaining),
            "repairs": self.repairs,
            "notes": list(self.notes),
            "sound": self.sound,
        }


def read_diagrams(
    images: Sequence[Image], *, gateway: Gateway, max_repairs: int = MAX_REPAIRS
) -> Reading:
    """Three passes over a set of pictures of one workflow."""
    if not images:
        return Reading(Structure(), (), (), 0, ("no images were given",))

    notes: list[str] = [image.note for image in images if image.note]

    per_image: list[tuple[str, Structure]] = []
    for position, image in enumerate(images, start=1):
        answer = _ask(
            gateway,
            system=_READ_SYSTEM,
            prompt=f"This is page {position} of {len(images)}: {image.name}.",
            images=[image],
            label=f"diagram/read[{image.name}]",
        )
        if answer is None:
            notes.append(f"{image.name} could not be read and was left out")
            continue
        per_image.append((image.name, clean(answer, seen_in=image.name)))

    readable = [(name, found) for name, found in per_image if not found.empty]
    if not readable:
        return Reading(Structure(), tuple(per_image), (), 0, (*notes, "no page read as a workflow"))

    if len(readable) == 1:
        joined = readable[0][1]
    else:
        answer = _ask(
            gateway,
            system=_JOIN_SYSTEM,
            prompt=_join_prompt(readable),
            images=list(images),
            label="diagram/join",
        )
        if answer is None:
            notes.append(
                f"the {len(readable)} pages were read but could not be joined into one "
                "workflow; the first page's reading is used alone"
            )
            joined = readable[0][1]
        else:
            joined = clean(answer)

    structure, remaining, repairs = _repair(
        joined, images=list(images), gateway=gateway, limit=max_repairs
    )
    if remaining:
        notes.append(
            f"{len(remaining)} things about the drawing could not be settled after "
            f"{repairs} further looks; they are listed rather than guessed at"
        )
    return Reading(
        structure=structure,
        per_image=tuple(per_image),
        remaining=remaining,
        repairs=repairs,
        notes=tuple(notes),
    )


def _repair(
    structure: Structure, *, images: list[Image], gateway: Gateway, limit: int
) -> tuple[Structure, tuple[str, ...], int]:
    """Put the audit's findings back with the pictures, until they stop improving."""
    problems = audit(structure)
    for attempt in range(limit):
        if not problems:
            return structure, (), attempt
        answer = _ask(
            gateway,
            system=_REPAIR_SYSTEM,
            prompt=_repair_prompt(structure, problems),
            images=images,
            label=f"diagram/repair[{attempt}]",
        )
        if answer is None:
            break
        improved = merge(structure, clean(answer))
        found = audit(improved)
        # A repair that fixed nothing will not fix anything on a third try either, and
        # the graph is kept either way because merge never removes.
        if len(found) >= len(problems):
            return improved, found, attempt + 1
        structure, problems = improved, found
    return structure, problems, limit


def _join_prompt(readings: list[tuple[str, Structure]]) -> str:
    parts = []
    for position, (name, found) in enumerate(readings, start=1):
        lines = [f"PAGE {position} — {name}"]
        for state in found.states:
            bits = [f"  {state.id} state “{state.name}”"]
            if state.reached_via:
                bits.append(f"reached via {state.reached_via}")
            if state.next_states:
                bits.append(f"then {', '.join(state.next_states)}")
            if state.next_decisions:
                bits.append(f"branches at {', '.join(state.next_decisions)}")
            if state.terminal:
                bits.append("ends the journey")
            if state.continues:
                bits.append(f"arrow leaves the page at “{state.continues}”")
            lines.append("; ".join(bits))
        for decision in found.decisions:
            lines.append(
                f"  {decision.id} decision “{decision.name}” -> "
                f"{', '.join(decision.outcomes) or 'no outcomes read'}"
                + (f" at {decision.at_state}" if decision.at_state else "")
            )
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _repair_prompt(structure: Structure, problems: Sequence[str]) -> str:
    return (
        "THE GRAPH SO FAR\n"
        + _join_prompt([("joined", structure)])
        + "\n\nWHAT IT CANNOT ACCOUNT FOR\n"
        + "\n".join(f"- {problem}" for problem in problems)
    )


def _ask(
    gateway: Gateway,
    *,
    system: str,
    prompt: str,
    images: list[Image],
    label: str,
) -> dict[str, Any] | None:
    """One call. A failure loses one page, not the build.

    A pack of eight tiles with one unreadable page should produce seven pages' worth of
    workflow and a note, rather than nothing at all — which is what raising here would
    give, on the one input format most likely to be scanned badly.
    """
    try:
        return gateway.json(
            system=system, prompt=prompt, schema=_NODE_SCHEMA, label=label, images=images
        )
    except Exception:
        return None
