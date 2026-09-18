"""The one failure a reader is allowed to have."""

from __future__ import annotations


class UnreadableDocument(Exception):
    """A document that cannot be read, named with what would make it readable.

    Always raised, never swallowed. A format we cannot parse must stop the build: a
    document that contributes nothing silently is indistinguishable from one that had
    nothing to contribute, and the coverage report would call the corpus fully read.
    """
