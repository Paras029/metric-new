"""DOCX reader.

Word keeps what PDF throws away: heading levels are a paragraph style, and a table is
a table. So this reader recovers the heading path properly and applies the same
header-into-every-cell rule the markdown reader uses.

Body and tables are read in document order. python-docx exposes paragraphs and tables
as separate collections, which loses their interleaving, so the reader walks the
underlying XML body instead — otherwise every table in the document lands at the end,
under whatever heading happened to be last.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from metric.corpus.blocks import RawBlock, row_text
from metric.corpus.readers.errors import UnreadableDocument

_HEADING_STYLES = ("heading", "title")


def read_docx(path: Path, *, doc_label: str = "") -> list[RawBlock]:
    docx = _import(path)
    document = _open(docx, path)
    label = doc_label or path.stem

    blocks: list[RawBlock] = []
    heading_path: list[str] = []
    table_index = 0

    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]

        if tag == "p":
            paragraph = docx.text.paragraph.Paragraph(child, document)
            text = " ".join(paragraph.text.split())
            if not text:
                continue
            level = _heading_level(paragraph)
            if level is not None:
                del heading_path[level - 1 :]
                heading_path.append(text)
                blocks.append(_block(label, heading_path, "heading", text))
            else:
                blocks.append(_block(label, heading_path, "prose", text))

        elif tag == "tbl":
            table_index += 1
            blocks.extend(
                _table(docx.table.Table(child, document), label, heading_path, table_index)
            )

    return blocks


def _table(
    table: Any, label: str, heading_path: list[str], table_index: int
) -> list[RawBlock]:
    rows = [[" ".join(cell.text.split()) for cell in row.cells] for row in table.rows]
    if len(rows) < 2:
        return []

    header = rows[0]
    return [
        RawBlock(
            location=f"{_location(label, heading_path)}#table{table_index}r{position}",
            kind="table",
            heading_path=tuple(heading_path),
            text=row_text(header, row),
        )
        for position, row in enumerate(rows[1:], start=1)
        if any(cell.strip() for cell in row)
    ]


def _heading_level(paragraph: Any) -> int | None:
    name = (getattr(paragraph.style, "name", "") or "").strip().lower()
    if not name.startswith(_HEADING_STYLES):
        return None
    if name.startswith("title"):
        return 1
    tail = name.removeprefix("heading").strip()
    return int(tail) if tail.isdigit() else 1


def _block(label: str, heading_path: list[str], kind: str, text: str) -> RawBlock:
    return RawBlock(
        location=_location(label, heading_path),
        kind=kind,  # type: ignore[arg-type]
        heading_path=tuple(heading_path),
        text=text,
    )


def _location(label: str, heading_path: list[str]) -> str:
    trail = " > ".join(heading_path) if heading_path else "(root)"
    return f"{label}:{trail}"


def _import(path: Path) -> Any:
    try:
        # The submodules are imported explicitly: the package does not pull them in, and
        # `docx.table.Table` would fail at use time rather than here.
        import docx
        import docx.table
        import docx.text.paragraph
    except ImportError as exc:
        raise UnreadableDocument(
            f"{path.name}: reading DOCX needs python-docx. Install metric[docx]."
        ) from exc
    return docx


def _open(docx: Any, path: Path) -> Any:
    try:
        return docx.Document(str(path))
    except Exception as exc:
        raise UnreadableDocument(f"{path.name}: could not be opened as DOCX ({exc}).") from exc
