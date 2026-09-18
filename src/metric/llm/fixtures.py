"""A gateway that answers from a recorded file instead of a model.

This exists for two jobs that turn out to be the same job. Tests need a model that
does not vary and does not need a network; a demo, an air-gapped install and anyone
reviewing the pipeline need a build they can reproduce from the repository alone.

A fixture records *what the model said*, not what the graph should contain. Every
answer still goes through the admission gate, so a fixture claiming an unlocatable
quote is rejected exactly as a live response would be — which is what stops a fixture
quietly becoming a way to hand-author a graph.

The passage label is worked out here rather than recorded. Labels depend on how a
batch happened to be cut, so recording them would pin the fixture to one batching
configuration; finding the quote in the rendered batch keeps the fixture about content
and exercises the real batching and labelling on every run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_LABEL = re.compile(r"^\[(P\d+)\] \(", re.MULTILINE)


class FixtureGateway:
    """Serves recorded entities and triples, keyed by the quote each triple cites."""

    def __init__(
        self,
        *,
        entities: list[dict[str, str]] | None = None,
        triples: list[dict[str, str]] | None = None,
        identity: str = "fixture",
    ) -> None:
        self.entities = entities or []
        self.triples = triples or []
        self._identity = identity
        self.calls: list[str] = []

    @classmethod
    def from_file(cls, path: Path) -> FixtureGateway:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
        return cls(
            entities=document.get("entities") or [],
            triples=document.get("triples") or [],
            identity=f"fixture:{path.name}",
        )

    @property
    def identity(self) -> str:
        return self._identity

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        self.calls.append(label)
        if label.startswith("glossary"):
            return {"entities": self.entities}

        answered = [
            {**triple, "passage": found}
            for triple in self.triples
            if (found := locate_label(prompt, triple["quote"])) is not None
        ]
        return {"non_normative": not answered, "triples": answered}


def locate_label(prompt: str, quote: str) -> str | None:
    """Which labelled block of a rendered batch contains `quote`."""
    marks = list(_LABEL.finditer(prompt))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(prompt)
        if quote in prompt[mark.start() : end]:
            return mark.group(1)
    return None
