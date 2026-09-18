"""Pass B: triples, one call per batch, against the frozen glossary.

The response says either *here are the facts* or *this section states none*. A batch
that says neither — no triples, `non_normative` false — is the only shape that
signals under-extraction, and it is read once more before being reported. Without
that distinction a fact the model simply failed to emit is invisible: nothing
downstream can miss what was never proposed.

The re-read deliberately alters the prompt. An identical request would replay the
identical cached response and prove nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from metric.extract.batching import Batch
from metric.extract.glossary import Glossary
from metric.llm import prompts
from metric.llm.gateway import Gateway
from metric.ontology.schema import Schema
from metric.ontology.types import Candidate, Passage, Rejection

_RETRY_NOTE = (
    "\n\nA previous read of this section returned no facts. Read it again. If it genuinely "
    "states none — a heading, a table of contents, a revision history, a worked example — "
    "say so with non_normative. Otherwise extract what it states."
)


@dataclass(frozen=True, slots=True)
class BatchResult:
    batch_id: str
    non_normative: bool
    candidates: tuple[Candidate, ...]
    rejections: tuple[Rejection, ...]
    reread: bool = False

    @property
    def silent(self) -> bool:
        """Returned nothing and did not claim the section was non-normative."""
        return not self.candidates and not self.non_normative


@dataclass(frozen=True, slots=True)
class Extraction:
    candidates: tuple[Candidate, ...]
    rejections: tuple[Rejection, ...]
    results: tuple[BatchResult, ...]

    @property
    def silent_batches(self) -> tuple[str, ...]:
        return tuple(r.batch_id for r in self.results if r.silent)


def extract(
    batches: Sequence[Batch],
    *,
    gateway: Gateway,
    schema: Schema,
    glossary: Glossary,
) -> Extraction:
    results = [
        extract_batch(batch, gateway=gateway, schema=schema, glossary=glossary)
        for batch in batches
    ]

    candidates = tuple(c for result in results for c in result.candidates)
    rejections = tuple(r for result in results for r in result.rejections)
    return Extraction(candidates=candidates, rejections=rejections, results=tuple(results))


def extract_batch(
    batch: Batch,
    *,
    gateway: Gateway,
    schema: Schema,
    glossary: Glossary,
) -> BatchResult:
    prompt = prompts.triples_prompt(batch, glossary=glossary.render())
    result = _read(batch, prompt, gateway=gateway, schema=schema)
    if not result.silent:
        return result

    retried = _read(batch, prompt + _RETRY_NOTE, gateway=gateway, schema=schema, suffix="/reread")
    return BatchResult(
        batch_id=retried.batch_id,
        non_normative=retried.non_normative,
        candidates=retried.candidates,
        rejections=result.rejections + retried.rejections,
        reread=True,
    )


def _read(
    batch: Batch,
    prompt: str,
    *,
    gateway: Gateway,
    schema: Schema,
    suffix: str = "",
) -> BatchResult:
    response = gateway.json(
        system=prompts.triples_system(schema),
        prompt=prompt,
        schema=prompts.triples_schema(schema),
        label=f"triples[{batch.id}]{suffix}",
    )

    labels = batch.labels
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []

    for item in response.get("triples", ()):
        label = str(item.get("passage", "")).strip().strip("[]")
        passage = labels.get(label)
        candidate = _candidate(item, passage=passage, cited=label)
        if passage is None:
            rejections.append(
                Rejection(
                    candidate=candidate,
                    criterion="citation",
                    detail=f"cited passage {label!r} is not in this batch",
                )
            )
        else:
            candidates.append(candidate)

    return BatchResult(
        batch_id=batch.id,
        non_normative=bool(response.get("non_normative", False)),
        candidates=tuple(candidates),
        rejections=tuple(rejections),
    )


def _candidate(item: dict[str, object], *, passage: Passage | None, cited: str) -> Candidate:
    return Candidate(
        head=str(item.get("head", "")).strip(),
        head_type=str(item.get("head_type", "")),
        relation=str(item.get("relation", "")),
        tail=str(item.get("tail", "")).strip(),
        tail_type=str(item.get("tail_type", "")),
        passage_id=passage.id if passage is not None else f"?{cited}",
        quote=str(item.get("quote", "")),
        method="llm",
    )
