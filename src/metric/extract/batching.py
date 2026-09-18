"""Batching by content size, with structure-aware boundaries.

Batches are cut on passage boundaries and sized by characters, not split by relation
type. A relation-typed split forces one pass per family over the whole corpus and
still cannot see a fact whose head and tail are stated in different families; sizing
by content asks each batch for everything it contains, once.

Each batch carries one passage of context on either side, so a fact stated across a
boundary is visible from both. That deliberately lets the same fact be extracted
twice: two identical spans collapse in dedup, whereas a fact lost at a boundary is
gone for good.

Passages are labelled `[P1]`, `[P2]` … within a batch and the model cites the label.
Asking a model to copy a twelve-character hash back verbatim is a needless source of
unciteable candidates.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from metric.ontology.ids import passage_id
from metric.ontology.types import Passage

DEFAULT_BUDGET_CHARS = 6000
MIN_BATCH_CHARS = 1500


@dataclass(frozen=True, slots=True)
class Batch:
    """A window over the corpus: `core` is what this batch owns, `before`/`after` surround it.

    Context is readable and citable like the core. Ownership only decides which batch
    is accountable for coverage — a batch that returns nothing for its own core is
    what the coverage audit looks at.
    """

    id: str
    core: tuple[Passage, ...]
    before: tuple[Passage, ...] = ()
    after: tuple[Passage, ...] = ()
    title: str = ""

    @property
    def passages(self) -> tuple[Passage, ...]:
        return self.before + self.core + self.after

    @property
    def labels(self) -> dict[str, Passage]:
        return {f"P{i}": p for i, p in enumerate(self.passages, start=1)}

    @property
    def core_ids(self) -> frozenset[str]:
        return frozenset(p.id for p in self.core)

    @property
    def heading_paths(self) -> tuple[tuple[str, ...], ...]:
        seen: list[tuple[str, ...]] = []
        for passage in self.core:
            if passage.heading_path and passage.heading_path not in seen:
                seen.append(passage.heading_path)
        return tuple(seen)

    def render(self) -> str:
        lines: list[str] = []
        for label, passage in self.labels.items():
            heading = " > ".join(passage.heading_path)
            location = f"{passage.location} — {heading}" if heading else passage.location
            lines.append(f"[{label}] ({location})\n{passage.text}")
        return "\n\n".join(lines)


def batch_passages(
    passages: Sequence[Passage],
    *,
    title: str = "",
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    min_chars: int = MIN_BATCH_CHARS,
) -> list[Batch]:
    """Cut `passages` into batches, preferring section boundaries once past `min_chars`.

    A passage longer than the budget is never split: an over-long table row or
    paragraph becomes a batch of its own rather than being cut mid-sentence, where
    the quote it supports would no longer be locatable.
    """
    if not passages:
        return []

    groups: list[list[Passage]] = []
    current: list[Passage] = []
    size = 0

    for index, passage in enumerate(passages):
        length = len(passage.text)
        starts_section = index > 0 and passage.heading_path != passages[index - 1].heading_path
        over_budget = bool(current) and size + length > budget_chars
        at_section = bool(current) and starts_section and size >= min_chars

        if over_budget or at_section:
            groups.append(current)
            current, size = [], 0

        current.append(passage)
        size += length

    if current:
        groups.append(current)

    return [
        Batch(
            id=_batch_id(group),
            core=tuple(group),
            before=(groups[position - 1][-1],) if position > 0 else (),
            after=(groups[position + 1][0],) if position + 1 < len(groups) else (),
            title=title,
        )
        for position, group in enumerate(groups)
    ]


def _batch_id(group: Iterable[Passage]) -> str:
    """Derived from member passages, so an unchanged section keeps its batch identity.

    A positional id would change every batch downstream of an edit and invalidate the
    whole response cache for a one-line change.
    """
    return passage_id("batch", "", "\x1f".join(p.id for p in group))
