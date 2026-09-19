"""Format dispatch.

Each optional parser is imported inside the reader that needs it, so a package
missing from an internal mirror disables one format rather than the whole pipeline.
A format we cannot read is refused with a reason — never read as empty, because a
document that contributes nothing silently is indistinguishable from one that had
nothing to contribute.
"""

from __future__ import annotations

from pathlib import Path

from metric.corpus.blocks import RawBlock
from metric.corpus.readers.errors import UnreadableDocument
from metric.corpus.readers.markdown import read_markdown

_MARKDOWN = {".md", ".markdown"}
_TEXT = {".txt"}
_IMAGE = {".png", ".jpg", ".jpeg"}


def read_document(path: Path) -> list[RawBlock]:
    suffix = path.suffix.lower()
    label = path.stem

    if suffix in _MARKDOWN:
        return read_markdown(path.read_text(encoding="utf-8"), doc_label=label)
    if suffix in _TEXT:
        return read_markdown(path.read_text(encoding="utf-8"), doc_label=label)
    if suffix == ".pdf":
        from metric.corpus.readers.pdf import read_pdf

        return read_pdf(path, doc_label=label)
    if suffix == ".docx":
        from metric.corpus.readers.docx import read_docx

        return read_docx(path, doc_label=label)
    if suffix in {".xlsx", ".xlsm"}:
        from metric.corpus.readers.xlsx import read_xlsx

        return read_xlsx(path, doc_label=label)
    if suffix in _IMAGE:
        # An image never reaches here: the pipeline sets diagrams aside for the vision
        # passes, which read a workflow into structure rather than into prose. Reaching
        # here means something called the text reader on a picture, and the old stub's
        # answer — a block whose text was the file path — went on to be batched, quoted
        # and cited as if a path were a sentence.
        raise UnreadableDocument(
            f"{path.name} is an image. Diagrams are read by metric.diagram, not as text; "
            "list it under `documents:` and the pipeline routes it there."
        )

    raise UnreadableDocument(
        f"{path.name}: no reader for {suffix!r}. Supported: markdown, text, pdf, docx, xlsx, image."
    )


def supported_suffixes() -> frozenset[str]:
    return frozenset(
        _MARKDOWN | _TEXT | _IMAGE | {".pdf", ".docx", ".xlsx", ".xlsm"}
    )


__all__ = ["RawBlock", "UnreadableDocument", "read_document", "read_markdown", "supported_suffixes"]
