"""Markdown reader.

Two decisions here carry downstream weight. A table row is emitted with its header
prepended to every cell, because a threshold bound to the wrong subject is the most
expensive silent parse failure available. And a list item is its own block, because
policy prose puts one obligation per bullet and splitting them apart later is
guesswork.
"""

from __future__ import annotations

import re

from metric.corpus.blocks import RawBlock, row_text

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)

# Emphasis is unwrapped as matched pairs rather than by stripping the characters.
# A blanket strip would turn `authenticate_customer` into `authenticatecustomer`, and
# every triple naming that tool would then cite a name the source never used.
_MARKUP: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"`+([^`]*)`+"), r"\1"),
    (re.compile(r"\*\*(\S(?:.*?\S)?)\*\*"), r"\1"),
    (re.compile(r"(?<![\w])__(\S(?:.*?\S)?)__(?![\w])"), r"\1"),
    (re.compile(r"(?<!\*)\*(\S(?:.*?\S)?)\*(?!\*)"), r"\1"),
    (re.compile(r"(?<![\w])_(\S(?:.*?\S)?)_(?![\w])"), r"\1"),
)


def read_markdown(text: str, *, doc_label: str = "") -> list[RawBlock]:
    lines = text.splitlines()
    blocks: list[RawBlock] = []
    heading_path: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if not paragraph:
            return
        body = " ".join(paragraph).strip()
        paragraph.clear()
        if body:
            blocks.append(
                RawBlock(
                    location=_location(doc_label, heading_path),
                    kind="prose",
                    heading_path=tuple(heading_path),
                    text=body,
                )
            )

    while index < len(lines):
        line = lines[index]

        heading = _HEADING.match(line)
        if heading is not None:
            flush_paragraph()
            level = len(heading.group(1))
            title = _plain(heading.group(2))
            del heading_path[level - 1 :]
            heading_path.append(title)
            blocks.append(
                RawBlock(
                    location=_location(doc_label, heading_path),
                    kind="heading",
                    heading_path=tuple(heading_path),
                    text=title,
                )
            )
            index += 1
            continue

        if _TABLE_ROW.match(line) is not None:
            flush_paragraph()
            consumed, table_blocks = _read_table(lines, index, doc_label, tuple(heading_path))
            blocks.extend(table_blocks)
            index += consumed
            continue

        bullet = _BULLET.match(line)
        if bullet is not None:
            flush_paragraph()
            blocks.append(
                RawBlock(
                    location=_location(doc_label, heading_path),
                    kind="list",
                    heading_path=tuple(heading_path),
                    text=_plain(bullet.group(1)),
                )
            )
            index += 1
            continue

        if not line.strip():
            flush_paragraph()
        else:
            paragraph.append(_plain(line.strip()))
        index += 1

    flush_paragraph()
    return blocks


def _read_table(
    lines: list[str], start: int, doc_label: str, heading_path: tuple[str, ...]
) -> tuple[int, list[RawBlock]]:
    """Consume a contiguous table, returning one block per data row.

    The header is repeated into every row so the row carries its own subject. A
    table with no separator rule is treated as data rows with positional headers,
    which is what a reflowed PDF table usually degrades into.
    """
    rows: list[list[str]] = []
    index = start
    while index < len(lines):
        match = _TABLE_ROW.match(lines[index])
        if match is None:
            break
        if _TABLE_RULE.match(lines[index]) is None:
            rows.append([_plain(cell) for cell in match.group(1).split("|")])
        index += 1

    consumed = index - start
    if not rows:
        return consumed, []

    header = rows[0]
    blocks = [
        RawBlock(
            location=f"{_location(doc_label, list(heading_path))}#row{position}",
            kind="table",
            heading_path=heading_path,
            text=row_text(header, row),
        )
        for position, row in enumerate(rows[1:], start=1)
    ]
    return consumed, blocks


def _plain(text: str) -> str:
    stripped = _BREAK.sub(" ", text)
    for pattern, replacement in _MARKUP:
        stripped = pattern.sub(replacement, stripped)
    return " ".join(stripped.split())


def _location(doc_label: str, heading_path: list[str]) -> str:
    trail = " > ".join(heading_path) if heading_path else "(root)"
    return f"{doc_label}:{trail}" if doc_label else trail
