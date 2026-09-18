"""Reading the Galileo turn-structured OTEL export.

This reader is written against a real production export, not a specification, and
three things in it decide the design.

**There is no state in the span attributes.** No `step_id`, no turn state, no attempt
counter, no terminal flag. Runtime state is real but it is inside tool payloads, in
three carriers: `set_metadata` calls that are literally `(variable, value)` writes,
tool *arguments* that carry the counters, and tool *outputs* that carry the branch
outcome. Everything this reader does is aimed at getting those out intact.

**Payloads are not uniformly JSON.** Tool spans carry JSON; the `llm` span's input and
output are Python reprs (`[{'role': 'user', ...}]`). Both are parsed, and anything
that parses as neither is kept as the raw string rather than dropped — a payload we
cannot read is still evidence that a call happened.

**Turns end badly and must stay gradable.** The last two turns of the sample have an
LLM span, no tool spans, and empty assistant content. That is a `silence` observation,
not a parse failure.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from metric.trace.model import Observation, Trace, Turn

# An outcome is a symbolic token, which is what makes picking it out of a payload
# deterministic: `{"status": "PROFILE_NO_MATCH"}` is a branch, `{"status": 200}` is
# an HTTP code, and no judgement is needed to tell them apart.
_SYMBOLIC = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")
_OUTCOME_KEYS = ("match", "status", "action", "result", "outcome")
_STATE_WRITE_TOOL = "set_metadata"
_STATE_WRITE_KEY = "policy_input"


def read_galileo_export(path: Path) -> Trace:
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)

    turns = tuple(
        _turn(raw, index) for index, raw in enumerate(document.get("turns") or ())
    )
    return Trace(
        conversation_id=_conversation_id(document, turns),
        source=str(path),
        turns=turns,
    )


def _conversation_id(document: dict[str, Any], turns: tuple[Turn, ...]) -> str:
    external = document.get("session_external_id")
    if external:
        return str(external)
    return turns[0].name.split(":")[0] if turns else ""


def _turn(raw: dict[str, Any], fallback_index: int) -> Turn:
    attributes = raw.get("trace_attributes") or {}
    index = _int(attributes.get("galileo_turn_id"), fallback_index)

    observations: list[Observation] = []
    saw_tool = False

    for position, span in enumerate(raw.get("spans") or (), start=1):
        step = _int(span.get("step"), position)
        kind = str(span.get("type", ""))
        name = str(span.get("name", ""))
        ref = f"turn{index}.step{step}"

        if kind == "llm":
            observations.extend(_conversation(span, turn=index, step=step, ref=ref))
        elif kind == "workflow":
            observations.append(
                Observation(
                    turn=index,
                    step=step,
                    kind="capability",
                    name=name,
                    value=_text(span.get("input")),
                    ref=ref,
                )
            )
        elif kind == "tool":
            saw_tool = True
            observations.extend(_tool(span, name=name, turn=index, step=step, ref=ref))

    if not saw_tool:
        observations.append(
            Observation(
                turn=index,
                step=0,
                kind="silence",
                name="",
                value="no tool call in this turn",
                ref=f"turn{index}",
            )
        )

    return Turn(index=index, name=str(raw.get("trace_name", "")), observations=tuple(observations))


def _conversation(span: dict[str, Any], *, turn: int, step: int, ref: str) -> list[Observation]:
    found: list[Observation] = []

    for message in _messages(span.get("input")):
        if message.get("role") == "user":
            found.append(
                Observation(
                    turn=turn,
                    step=step,
                    kind="utterance",
                    name="user",
                    value=str(message.get("content", "")),
                    ref=ref,
                )
            )

    for message in _messages(span.get("output")):
        if message.get("role") == "assistant":
            found.append(
                Observation(
                    turn=turn,
                    step=step,
                    kind="assistant",
                    name="assistant",
                    value=str(message.get("content", "")),
                    ref=ref,
                )
            )
    return found


def _tool(
    span: dict[str, Any], *, name: str, turn: int, step: int, ref: str
) -> list[Observation]:
    payload = _parse(span.get("input"))
    arguments = _arguments(payload)

    if name == _STATE_WRITE_TOOL:
        writes = _state_writes(payload, turn=turn, step=step, ref=ref)
        if writes:
            return writes

    found = [
        Observation(
            turn=turn,
            step=step,
            kind="tool_call",
            name=name,
            value=str(span.get("status_code", "")),
            ref=ref,
            arguments=arguments,
        )
    ]

    outcome = _outcome(_parse(span.get("output")))
    if outcome is not None:
        found.append(
            Observation(
                turn=turn,
                step=step,
                kind="outcome",
                name=name,
                value=outcome,
                ref=ref,
            )
        )
    return found


def _state_writes(
    payload: Any, *, turn: int, step: int, ref: str
) -> list[Observation]:
    """`{"policy_input": ["checkpoint", "check14Key"]}` is a state assignment.

    This is the one place the agent narrates its own transitions, which makes it the
    single most valuable thing in the export.
    """
    if not isinstance(payload, dict):
        return []
    pair = payload.get(_STATE_WRITE_KEY)
    if not isinstance(pair, list) or len(pair) != 2:
        return []
    return [
        Observation(
            turn=turn,
            step=step,
            kind="state_write",
            name=str(pair[0]),
            value=str(pair[1]),
            ref=ref,
        )
    ]


def _arguments(payload: Any) -> tuple[tuple[str, str], ...]:
    """Tool arguments, sorted, with nulls kept.

    A counter passed as `null` is a real observation — it says the counter was unset
    at that call — so it is recorded rather than filtered out.
    """
    if not isinstance(payload, dict):
        return ()
    return tuple(sorted((str(key), _scalar(value)) for key, value in payload.items()))


def _outcome(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in _OUTCOME_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and _SYMBOLIC.match(value):
            return value
    for value in payload.values():
        if isinstance(value, dict):
            nested = _outcome(value)
            if nested is not None:
                return nested
    return None


def _messages(raw: Any) -> list[dict[str, Any]]:
    parsed = _parse(raw)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _parse(raw: Any) -> Any:
    """JSON first, Python repr second, the raw string otherwise."""
    if raw is None or raw == "None":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        pass
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _text(raw: Any) -> str:
    return "" if raw in (None, "None") else str(raw)


def _int(raw: Any, fallback: int) -> int:
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return fallback
