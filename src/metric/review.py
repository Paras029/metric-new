"""The review loop: a YAML file a person edits, and re-ingestion consumes.

v1's queue is a file, not an interface. What matters is not the surface but the
keying: a decision is recorded against the hash of the *evidence it was made about*,
not against the question's position or the build it came from. An unchanged passage
therefore keeps its answer across every later build, and a passage that was edited
re-queues automatically with the old answer preserved for comparison rather than
silently applied to text it was never about.

That is the difference between a tool that is run once and a tool that survives the
next policy revision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from metric.admit.grounding import normalised
from metric.ontology.types import Question

ANSWERS = ("", "approve", "reject", "defer")


@dataclass(frozen=True, slots=True)
class Decision:
    question_id: str
    evidence_key: str
    answer: str
    note: str = ""

    @property
    def answered(self) -> bool:
        return self.answer not in {"", "defer"}


def evidence_key(question: Question) -> str:
    """Identity of the text a decision was made about."""
    payload = "\x1f".join(sorted(normalised(span.quote) for span in question.evidence))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def write(path: Path, questions: Sequence[Question], *, decisions: Mapping[str, Decision]) -> None:
    """Render the queue, carrying forward every answer that has ever been given.

    Answered questions stop being asked — approving an expectation resolves the thing
    that raised it — so the file has to keep decisions whose question is no longer in
    the queue. Writing only the open ones would make every approval undo itself on the
    next build, silently.
    """
    entries = []
    for question in questions:
        key = evidence_key(question)
        prior = decisions.get(question.id)
        carried = prior is not None and prior.evidence_key == key
        stale = prior is not None and not carried

        entry: dict[str, Any] = {
            "id": question.id,
            "kind": question.kind,
            "heading": question.heading,
            "detail": question.detail,
            "evidence_key": key,
            "answer": prior.answer if carried and prior else "",
            "note": prior.note if carried and prior else "",
            "evidence": [
                {"passage": span.passage_id, "quote": span.quote} for span in question.evidence
            ],
        }
        if stale and prior is not None:
            entry["previous_answer"] = {
                "answer": prior.answer,
                "note": prior.note,
                "evidence_key": prior.evidence_key,
                "why": "the cited text changed since this was answered; answer it again",
            }
        entries.append(entry)

    asked = {question.id for question in questions}
    resolved = [
        {
            "id": decision.question_id,
            "evidence_key": decision.evidence_key,
            "answer": decision.answer,
            "note": decision.note,
        }
        for decision in sorted(decisions.values(), key=lambda d: d.question_id)
        if decision.question_id not in asked and decision.answered
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "answers": list(ANSWERS[1:]),
        "questions": entries,
        "resolved": resolved,
    }
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def read(path: Path) -> dict[str, Decision]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}

    decisions: dict[str, Decision] = {}
    for entry in [*(document.get("questions") or ()), *(document.get("resolved") or ())]:
        answer = str(entry.get("answer") or "").strip().lower()
        if answer not in ANSWERS:
            raise ValueError(
                f"{path}: question {entry.get('id')} has answer {answer!r}; "
                f"expected one of {', '.join(a for a in ANSWERS if a)}"
            )
        decisions[str(entry["id"])] = Decision(
            question_id=str(entry["id"]),
            evidence_key=str(entry.get("evidence_key", "")),
            answer=answer,
            note=str(entry.get("note") or ""),
        )
    return decisions


def outstanding(
    questions: Iterable[Question], decisions: Mapping[str, Decision]
) -> list[Question]:
    """Questions still awaiting a person, including ones whose evidence has changed."""
    return [q for q in questions if _still_open(q, decisions.get(q.id))]


def _still_open(question: Question, decision: Decision | None) -> bool:
    if decision is None or not decision.answered:
        return True
    return decision.evidence_key != evidence_key(question)
