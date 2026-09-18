"""Blocks to passages.

A passage is the unit everything downstream keys on: batching, quoting, evidence and
provenance. Its id is a content hash, so unchanged text keeps its identity across
builds and a human decision made about it survives re-ingestion.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from metric.corpus.blocks import RawBlock
from metric.corpus.furniture import find_furniture, strip_furniture
from metric.corpus.readers import read_document
from metric.ontology.ids import document_id, passage_id, sha256_file
from metric.ontology.types import Document, Passage

_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def describe_document(
    path: Path, *, policy_version: str = "", effective_date: str = ""
) -> Document:
    digest = sha256_file(str(path))
    return Document(
        id=document_id(path.name, digest),
        path=str(path),
        sha256=digest,
        media_type=_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        policy_version=policy_version,
        effective_date=effective_date,
    )


def passages_from_blocks(document: Document, blocks: Iterable[RawBlock]) -> list[Passage]:
    """Assign identity, dropping furniture and headings-with-no-content.

    Headings are kept out of the passage set: they carry no assertion of their own,
    and they already travel with every passage beneath them as `heading_path`.
    """
    material = list(blocks)
    furniture = find_furniture(material)
    kept = strip_furniture(material, furniture)

    passages: list[Passage] = []
    seen: set[str] = set()
    for block in kept:
        if block.kind == "heading":
            continue
        text = block.text.strip()
        if not text:
            continue
        identity = passage_id(document.id, block.location, text)
        if identity in seen:
            continue
        seen.add(identity)
        passages.append(
            Passage(
                id=identity,
                doc_id=document.id,
                location=block.location,
                kind=block.kind,
                heading_path=block.heading_path,
                text=text,
            )
        )
    return passages


def read_passages(
    path: Path, *, policy_version: str = "", effective_date: str = ""
) -> tuple[Document, list[Passage]]:
    document = describe_document(path, policy_version=policy_version, effective_date=effective_date)
    return document, passages_from_blocks(document, read_document(path))
