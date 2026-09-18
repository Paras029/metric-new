"""What a reader produces: located text with its structural kind and heading path.

Readers know about file formats and nothing else. Identity, furniture stripping and
passage assembly happen downstream, so every format arrives in the same shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from metric.ontology.types import PassageKind


@dataclass(frozen=True, slots=True)
class RawBlock:
    location: str
    kind: PassageKind
    heading_path: tuple[str, ...]
    text: str


def row_text(header: list[str], row: list[str]) -> str:
    """Render a table row with its column header carried into every cell.

    Shared by every reader that sees a table, because the rule has to be identical
    across formats: a row detached from its header is where a threshold silently
    binds to whatever prose happened to be adjacent.
    """
    pairs = []
    for position, cell in enumerate(row):
        value = cell.strip()
        if not value:
            continue
        label = header[position].strip() if position < len(header) else f"column {position + 1}"
        pairs.append(f"{label}: {value}" if label else value)
    return " | ".join(pairs)
