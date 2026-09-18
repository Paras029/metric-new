"""PDF reader.

A PDF carries no structure — no headings, no tables, no list items, only positioned
glyphs. This reader does not pretend otherwise: it produces paragraph blocks and a
page location, and leaves table recovery to a format that has tables.

That matters because of how tables degrade. A PDF table read as prose puts a header
row and its data rows in the same paragraph, or in adjacent ones, and the header is
then silently detached from the values beneath it. The passage-level fix that works
for markdown, docx and xlsx cannot be applied here, so the honest position is that a
policy whose constraints live in a PDF table needs the source document, not a better
regex. Furniture stripping still runs downstream and removes the running
header/footer that PDFs always carry.

A page that yields no text is refused rather than read as empty: a scanned PDF that
silently contributes nothing is indistinguishable from one that had nothing to say.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from metric.corpus.blocks import RawBlock
from metric.corpus.readers.errors import UnreadableDocument

_MIN_CHARS_PER_PAGE = 20


def read_pdf(path: Path, *, doc_label: str = "") -> list[RawBlock]:
    reader = _open(path)
    label = doc_label or path.stem

    blocks: list[RawBlock] = []
    empty_pages: list[int] = []

    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if len(text.strip()) < _MIN_CHARS_PER_PAGE:
            empty_pages.append(number)
            continue
        blocks.extend(_paragraphs(text, label=label, page=number))

    if empty_pages and len(empty_pages) == len(reader.pages):
        raise UnreadableDocument(
            f"{path.name}: no extractable text on any of {len(reader.pages)} pages. "
            "This is a scanned or image-only PDF; it needs OCR or the source document."
        )
    if empty_pages:
        raise UnreadableDocument(
            f"{path.name}: pages {', '.join(str(p) for p in empty_pages)} have no extractable "
            "text. Ingesting the rest would report coverage over a document that is partly "
            "unread; supply an OCR'd copy or the source document."
        )
    return blocks


def _paragraphs(text: str, *, label: str, page: int) -> list[RawBlock]:
    blocks: list[RawBlock] = []
    for chunk in text.split("\n\n"):
        body = " ".join(chunk.split())
        if body:
            blocks.append(
                RawBlock(
                    location=f"{label}:p{page}",
                    kind="prose",
                    heading_path=(label,),
                    text=body,
                )
            )
    return blocks


def _open(path: Path) -> Any:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise UnreadableDocument(
            f"{path.name}: reading PDF needs pypdf. Install metric[pdf]."
        ) from exc

    try:
        return PdfReader(str(path))
    except Exception as exc:
        raise UnreadableDocument(f"{path.name}: could not be opened as a PDF ({exc}).") from exc
