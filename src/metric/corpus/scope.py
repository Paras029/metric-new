"""Which parts of a document are policy.

A source file is rarely all policy. It carries a preamble, a change log, an appendix,
commentary about itself. The pipeline read the card-authentication file's own closing
notes — "why this document is a good phase-1 target", a table of *which ingestion problem
each section exercises* — and produced eight Rules from them. Every one was well-formed,
correctly cited, and governed nothing, so each raised a question for a human. Eight of the
fifteen unattached-rule questions in that build came from prose about the pipeline rather
than from the policy.

No amount of extraction quality fixes that. The model was asked to find rules in a passage
that contains sentences shaped exactly like rules; it did. **What section a passage belongs
to is a fact about the corpus, and the corpus file is where it is stated.**

So a document can name the sections to read, or the sections to leave. Matching is on the
heading path every passage already carries, by prefix, case-insensitively, so `"3"` selects
`## 3. Operating procedure` and everything nested under it.

Left out passages are counted and reported rather than silently dropped: a scope that
excludes most of a document is either right and worth seeing, or a typo.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from metric.ontology.types import Passage

_LEADING = re.compile(r"^[\s#>*_]*(?:(\d+(?:\.\d+)*)[.)]?\s*)?")


@dataclass(frozen=True, slots=True)
class Scope:
    """Which sections of one document to ingest. Empty `include` means all of them."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    @property
    def everything(self) -> bool:
        return not (self.include or self.exclude)

    def admits(self, passage: Passage) -> bool:
        path = tuple(_key(heading) for heading in passage.heading_path)
        if any(_matches(path, _key(name)) for name in self.exclude):
            return False
        if not self.include:
            return True
        return any(_matches(path, _key(name)) for name in self.include)


@dataclass(frozen=True, slots=True)
class Scoped:
    passages: tuple[Passage, ...]
    dropped: tuple[Passage, ...]

    @property
    def sections_dropped(self) -> tuple[str, ...]:
        return tuple(
            sorted({p.heading_path[0] if p.heading_path else "(no heading)" for p in self.dropped})
        )

    @property
    def note(self) -> str:
        if not self.dropped:
            return ""
        return (
            f"{len(self.dropped)} passages were out of scope and not read: "
            f"{', '.join(self.sections_dropped)}"
        )


def apply_scope(passages: Sequence[Passage], scope: Scope) -> Scoped:
    if scope.everything:
        return Scoped(tuple(passages), ())
    kept = tuple(p for p in passages if scope.admits(p))
    return Scoped(kept, tuple(p for p in passages if p not in kept))


def _key(heading: str) -> str:
    """A heading reduced to what a person would type to name it.

    Numbering is kept when the corpus gives it, because `"3"` naming §3 is the common
    case and the shortest thing to write.
    """
    return " ".join(heading.split()).casefold().strip("#*_ .:")


def _matches(path: Sequence[str], wanted: str) -> bool:
    """Whether any heading on the path starts with, or is numbered by, `wanted`."""
    if not wanted:
        return False
    for heading in path:
        if heading.startswith(wanted):
            return True
        number = _LEADING.match(heading)
        if number and number.group(1) and number.group(1) == wanted.strip(". "):
            return True
    return False
