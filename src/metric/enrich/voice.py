"""A worked materialiser: turning chosen levels into what the customer actually says.

The default materialiser varies nothing and says so. That is honest, and it means every
column of the design is inert — a cohort run under it can show `clarity=garbled` doing
fine because no run was ever garbled.

This is the other half: one installation's renderer for the voice catalogue, registered
as `voice`. It is deliberately a worked example rather than a general mechanism, because
there is no general mechanism to have. Making a transcript read as though it came through
a noisy line depends on the language, the channel and the ASR in front of it, and every
choice below is a guess that a team with real transcripts would replace.

What it does not do is as important. It never touches what the situation *is* — it takes
the base's question as given and changes only how it arrives. A materialiser that edited
the situation would be changing the ground truth from inside the presentation layer, and
the attribution that came back would be measuring the renderer.

Levels it does not know how to render are returned as `unrendered`, so the report can say
which columns of the design reached the agent and which were metadata.
"""

from __future__ import annotations

from collections.abc import Mapping

from metric.enrich.materialize import register

# Deliberately small and legible. A team with transcripts would replace these with
# substitutions their own ASR actually makes.
_MISHEARD = {
    "authenticate": "auth in a cape",
    "authentication": "a authentication",
    "account": "a count",
    "security": "sick your ity",
    "transfer": "trans for",
    "verify": "very fy",
    "card": "cart",
}

_HESITATIONS = ("um, ", "sorry, ", "I mean, ")


def render(question: str, levels: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    """The opening turn as this customer would say it, and what went unrendered."""
    text = question
    rendered: set[str] = set()

    clarity = levels.get("clarity")
    if clarity in {"clear", "hesitant", "garbled"}:
        text = _clarity(text, clarity)
        rendered.add("clarity")

    asr = levels.get("asr")
    if asr in {"clean", "mild_noise", "heavy_noise", "lossy", "degraded"}:
        text = _asr(text, asr)
        rendered.add("asr")

    persona = levels.get("persona")
    if persona in {"cooperative", "impatient", "confused"}:
        text = _persona(text, persona)
        rendered.add("persona")

    history = levels.get("history")
    if history in {"none", "prior_turns"}:
        text = _history(text, history)
        rendered.add("history")

    paraphrase = levels.get("paraphrase")
    if paraphrase in {"verbatim", "light", "heavy"}:
        text = _paraphrase(text, paraphrase)
        rendered.add("paraphrase")

    return text, tuple(sorted(set(levels) - rendered))


def _clarity(text: str, level: str) -> str:
    if level == "hesitant":
        return _HESITATIONS[0] + text.replace(". ", "... ")
    if level == "garbled":
        words = text.split()
        broken = [w if index % 4 else f"{w[:2]}—{w}" for index, w in enumerate(words)]
        return " ".join(broken)
    return text


def _asr(text: str, level: str) -> str:
    """What the transcript looks like after the line and the recogniser have had it."""
    if level == "clean":
        return text
    aggressive = level in {"heavy_noise", "degraded"}
    words = text.split()
    out: list[str] = []
    for index, word in enumerate(words):
        stripped = word.strip(".,;:").lower()
        if stripped in _MISHEARD and (aggressive or index % 3 == 0):
            out.append(_MISHEARD[stripped])
        elif aggressive and index % 7 == 6:
            out.append("[inaudible]")
        else:
            out.append(word)
    return " ".join(out)


def _persona(text: str, level: str) -> str:
    if level == "impatient":
        return f"{text} — and quickly please, I have been on hold for twenty minutes."
    if level == "confused":
        return f"{text} At least I think that's what I need. Is that right?"
    return text


def _history(text: str, level: str) -> str:
    if level == "prior_turns":
        return (
            "Sorry, I was talking to someone else about my statement a moment ago and got "
            f"cut off. Anyway. {text}"
        )
    return text


def _paraphrase(text: str, level: str) -> str:
    if level == "light":
        return text.replace("must", "needs to").replace("the agent", "you")
    if level == "heavy":
        return f"Look, what I'm getting at is this: {text.lower()}"
    return text


register("voice", render)
