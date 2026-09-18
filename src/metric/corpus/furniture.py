"""Running headers and footers.

A line repeating across a document is page furniture, not content. Left in, it
pollutes quotes and breaks span verification on otherwise correct extractions —
which shows up as a mysterious rejection rate rather than as a parse bug.

Detection is by repetition alone: short lines that recur often are furniture
whatever they say, so no domain vocabulary is baked in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from metric.corpus.blocks import RawBlock

_MAX_FURNITURE_CHARS = 90
_MIN_REPEATS = 3


def find_furniture(
    blocks: Iterable[RawBlock],
    *,
    min_repeats: int = _MIN_REPEATS,
    max_chars: int = _MAX_FURNITURE_CHARS,
) -> frozenset[str]:
    counts: Counter[str] = Counter()
    for block in blocks:
        if block.kind in {"heading", "image"}:
            continue
        text = block.text.strip()
        if text and len(text) <= max_chars:
            counts[text] += 1
    return frozenset(text for text, count in counts.items() if count >= min_repeats)


def strip_furniture(blocks: Iterable[RawBlock], furniture: frozenset[str]) -> list[RawBlock]:
    if not furniture:
        return list(blocks)
    return [block for block in blocks if block.text.strip() not in furniture]
