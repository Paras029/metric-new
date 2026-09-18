"""Deterministic identity.

Every id is a content hash, never a counter. A counter makes the graph depend on
the order things were processed in, which is the difference between a build that
reproduces and one that only usually does.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_ENTITY_ID_LEN = 10
_PASSAGE_ID_LEN = 12


def canonical_name(surface: str) -> str:
    """Fold a surface form to the key an entity id is derived from.

    Case, punctuation and spacing are formatting rather than meaning, so they are
    folded away. Anything that survives folding is a genuine difference and gets a
    different entity.
    """
    folded = unicodedata.normalize("NFKD", surface)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = _NON_ALNUM.sub("_", folded.lower()).strip("_")
    return folded


def _digest(*parts: str, length: int) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def entity_id(entity_type: str, surface: str) -> str:
    """Stable id for an entity of a given type.

    Type participates in the hash, so a `Tool` and a `State` that share a name are
    never the same node — which is the precondition that makes an over-merge across
    types impossible rather than merely discouraged.
    """
    name = canonical_name(surface)
    if not name:
        raise ValueError(f"surface form {surface!r} folds to an empty canonical name")
    return f"{entity_type}:{_digest(entity_type, name, length=_ENTITY_ID_LEN)}"


def literal_id(value: str) -> str:
    """Literal tails are their own value, recorded verbatim and never folded."""
    return value


def question_id(kind: str, *parts: str) -> str:
    """Keyed by what the question is about, so an unanswered question keeps its id."""
    return _digest(kind, *parts, length=_PASSAGE_ID_LEN)


def passage_id(doc_id: str, location: str, text: str) -> str:
    return _digest(doc_id, location, _normalise_for_hash(text), length=_PASSAGE_ID_LEN)


def document_id(path: str, sha256: str) -> str:
    return _digest(path, sha256, length=_PASSAGE_ID_LEN)


def _normalise_for_hash(text: str) -> str:
    """Collapse whitespace so trivial reflow does not change a passage's identity."""
    return " ".join(text.split())


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
