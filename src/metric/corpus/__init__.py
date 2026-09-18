"""Documents in, passages out."""

from metric.corpus.blocks import RawBlock
from metric.corpus.furniture import find_furniture, strip_furniture
from metric.corpus.manifest import BuildIdentity, Manifest
from metric.corpus.passages import describe_document, passages_from_blocks, read_passages
from metric.corpus.readers import UnreadableDocument, read_document, supported_suffixes

__all__ = [
    "BuildIdentity",
    "Manifest",
    "RawBlock",
    "UnreadableDocument",
    "describe_document",
    "find_furniture",
    "passages_from_blocks",
    "read_document",
    "read_passages",
    "strip_furniture",
    "supported_suffixes",
]
