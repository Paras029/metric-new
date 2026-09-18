"""Deterministic harvest.

Two classes of fact are extracted by rule rather than by model, because both are
exactly the kind a model gets subtly wrong and nothing downstream can catch: an
exact number, and the verbatim wording of an obligation.

The division of labour is deliberate. This pass fixes *what the value is* and *what
the sentence says*; binding those to a subject needs context and is the model's job.
So the figure that ends up in the graph is never re-parsed or paraphrased — which is
the one guarantee the geometry in GEODE explicitly cannot provide for a value stated
only once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from metric.ontology.canonical import CARDINALS, as_number
from metric.ontology.types import Candidate, Passage

_CARDINAL_ALT = "|".join(CARDINALS)

# Only quantities introduced by a limit keyword are harvested. A bare number in prose
# is usually an enumeration or a cross-reference, and admitting those costs more in
# noise than the recall is worth -- the model pass sees them anyway.
_LIMIT = re.compile(
    r"\b(maximum of|minimum of|no more than|no fewer than|at most|at least|up to|within)\s+"
    rf"(\d+|{_CARDINAL_ALT})\s+"
    r"((?:[A-Za-z][A-Za-z-]*\s+){0,2}[A-Za-z][A-Za-z-]*)",
    re.IGNORECASE,
)

_MODAL_SEVERITY: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(must not|may not|shall not|cannot|do not|does not|never)\b", re.I), "error"),
    (re.compile(r"\b(must|shall|is required to|are required to)\b", re.I), "error"),
    (re.compile(r"\b(should not|ought not)\b", re.I), "warning"),
    (re.compile(r"\b(should|ought to)\b", re.I), "warning"),
    (re.compile(r"\b(may|can|is permitted to|are permitted to)\b", re.I), "info"),
)

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_TRAILING = " \t .,;:"


def harvest(passages: Iterable[Passage]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for passage in passages:
        if passage.kind == "image":
            continue
        candidates.extend(harvest_values(passage))
        candidates.extend(harvest_rules(passage))
    return candidates


def harvest_values(passage: Passage) -> list[Candidate]:
    """Exact quantities, recorded verbatim.

    The Value entity is named by number *and* unit, so a limit of three attempts and
    a window of three days never collide on the bare figure.
    """
    found: list[Candidate] = []
    for match in _LIMIT.finditer(passage.text):
        number = as_number(match.group(2))
        if number is None:
            continue
        unit = match.group(3).strip(_TRAILING)
        if not unit:
            continue
        name = f"{number} {unit}"
        found.append(
            Candidate(
                head=name,
                head_type="Value",
                relation="VALUE_IS",
                tail=str(number),
                tail_type="literal",
                passage_id=passage.id,
                quote=match.group(0).strip(_TRAILING),
                method="deterministic",
            )
        )
    return found


def harvest_rules(passage: Passage) -> list[Candidate]:
    """Modal sentences, as Rule entities carrying their own wording and severity.

    What the rule requires or forbids is left to the model: the modal tells us a rule
    exists and how hard it bites, not what it governs.
    """
    found: list[Candidate] = []
    for sentence in _sentences(passage.text):
        severity = _severity(sentence)
        if severity is None:
            continue
        found.append(
            Candidate(
                head=sentence,
                head_type="Rule",
                relation="RULE_STATES",
                tail=sentence,
                tail_type="literal",
                passage_id=passage.id,
                quote=sentence,
                method="deterministic",
            )
        )
        found.append(
            Candidate(
                head=sentence,
                head_type="Rule",
                relation="HAS_SEVERITY",
                tail=severity,
                tail_type="literal",
                passage_id=passage.id,
                quote=sentence,
                method="deterministic",
            )
        )
    return found


def _sentences(text: str) -> list[str]:
    return [part.strip(_TRAILING) for part in _SENTENCE.split(text) if part.strip(_TRAILING)]


def _severity(sentence: str) -> str | None:
    for pattern, severity in _MODAL_SEVERITY:
        if pattern.search(sentence):
            return severity
    return None

