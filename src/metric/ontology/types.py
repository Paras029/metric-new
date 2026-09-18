"""The types the whole pipeline moves.

A `Candidate` is what an extractor proposes; a `Triple` is what survived admission.
Keeping them distinct is what makes "what was thrown away, and why" answerable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PassageKind = Literal["prose", "table", "list", "heading", "image"]
Method = Literal["deterministic", "llm", "vision", "human", "telemetry"]
Materiality = Literal["high", "normal"]
TailKind = Literal["entity", "literal"]
TripleStatus = Literal["admitted", "review", "rejected", "conflicted", "superseded"]

LITERAL_TYPE = "literal"


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    path: str
    sha256: str
    media_type: str
    policy_version: str = ""
    effective_date: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "policy_version": self.policy_version,
            "effective_date": self.effective_date,
        }


@dataclass(frozen=True, slots=True)
class Passage:
    """A unit of source text with a stable, content-derived identity.

    `location` is human-facing ("p3", "sheet:Tools!r4", "§3.D"); `id` is what the
    rest of the pipeline keys on and never changes for unchanged text.
    """

    id: str
    doc_id: str
    location: str
    kind: PassageKind
    heading_path: tuple[str, ...]
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "location": self.location,
            "kind": self.kind,
            "heading_path": list(self.heading_path),
            "text": self.text,
        }


@dataclass(frozen=True, slots=True)
class Span:
    """A located quote. `start`/`end` index into the passage text."""

    passage_id: str
    start: int
    end: int
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "passage_id": self.passage_id,
            "start": self.start,
            "end": self.end,
            "quote": self.quote,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Span:
        return cls(
            passage_id=str(data["passage_id"]),
            start=int(data["start"]),
            end=int(data["end"]),
            quote=str(data["quote"]),
        )


@dataclass(frozen=True, slots=True)
class Candidate:
    """A proposed triple, in surface form, not yet bound to entities.

    `quote` is what the extractor claims supports it. Admission locates that quote
    in the passage; a candidate whose quote cannot be found is discarded, because a
    fabricated citation is worse than no citation.
    """

    head: str
    head_type: str
    relation: str
    tail: str
    tail_type: str
    passage_id: str
    quote: str
    method: Method

    def as_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "head_type": self.head_type,
            "relation": self.relation,
            "tail": self.tail,
            "tail_type": self.tail_type,
            "passage_id": self.passage_id,
            "quote": self.quote,
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class Entity:
    """A canonical node. `surfaces` records every spelling the corpus used for it."""

    id: str
    type: str
    canonical: str
    surfaces: frozenset[str] = field(default_factory=frozenset)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "canonical": self.canonical,
            "surfaces": sorted(self.surfaces),
        }


@dataclass(frozen=True, slots=True)
class Triple:
    """An admitted fact.

    `spans` grows when duplicates merge: one fact stated three ways keeps all three
    citations rather than discarding two of them.
    """

    head: str
    relation: str
    tail: str
    tail_kind: TailKind
    spans: tuple[Span, ...]
    methods: frozenset[Method]
    materiality: Materiality = "normal"
    status: TripleStatus = "admitted"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.head, self.relation, self.tail)

    def as_dict(self) -> dict[str, Any]:
        return {
            "head": self.head,
            "relation": self.relation,
            "tail": self.tail,
            "tail_kind": self.tail_kind,
            "spans": [s.as_dict() for s in self.spans],
            "methods": sorted(self.methods),
            "materiality": self.materiality,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Triple:
        return cls(
            head=str(data["head"]),
            relation=str(data["relation"]),
            tail=str(data["tail"]),
            tail_kind=data["tail_kind"],
            spans=tuple(Span.from_dict(s) for s in data["spans"]),
            methods=frozenset(data["methods"]),
            materiality=data.get("materiality", "normal"),
            status=data.get("status", "admitted"),
        )


@dataclass(frozen=True, slots=True)
class Rejection:
    """A candidate that failed admission, kept with the criterion it failed.

    A first-class record rather than a log line: quarantine is how a broken
    extractor is found.
    """

    candidate: Candidate
    criterion: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.as_dict(),
            "criterion": self.criterion,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Question:
    """Something the pipeline could not settle, addressed to a person."""

    id: str
    kind: str
    heading: str
    detail: str
    blocks: str
    evidence: tuple[Span, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "heading": self.heading,
            "detail": self.detail,
            "blocks": self.blocks,
            "evidence": [s.as_dict() for s in self.evidence],
        }
