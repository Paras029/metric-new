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
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_LABEL = re.compile(r"^\[(P\d+)\] \(", re.MULTILINE)


class FixtureMiss(LookupError):
    """The fixture has no recorded answer for this call, and will not invent one."""


class FixtureGateway:
    """Serves recorded entities and triples, keyed by the quote each triple cites."""

    def __init__(
        self,
        *,
        entities: list[dict[str, str]] | None = None,
        triples: list[dict[str, str]] | None = None,
        answers: dict[str, dict[str, Any]] | None = None,
        identity: str = "fixture",
    ) -> None:
        self.entities = entities or []
        self.triples = triples or []
        self.answers = answers or {}
        self._identity = identity
        self.calls: list[str] = []

    @classmethod
    def from_file(cls, path: Path) -> FixtureGateway:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
        return cls(
            entities=document.get("entities") or [],
            triples=document.get("triples") or [],
            answers=document.get("answers") or {},
            identity=f"fixture:{path.name}",
        )

    @property
    def identity(self) -> str:
        return self._identity

    def json(
        self,
        *,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        label: str,
        images: Sequence[Any] = (),
    ) -> dict[str, Any]:
        self.calls.append(label)
        if label.startswith("glossary"):
            return {"entities": self.entities}

        stage = re.split(r"[/\[]", label)[0]
        if stage in self.answers:
            return self.answers[stage]
        if stage != "triples":
            # A recorded extraction has nothing to say about a stage it never saw. Falling
            # through to the triple search would return `{"triples": []}` — a well-formed
            # answer to a question it was not asked — and the caller would read that as the
            # model having found nothing rather than as the fixture having no answer.
            raise FixtureMiss(
                f"{label}: this fixture records an extraction and has no answer for the "
                f"`{stage}` stage. Record one under `answers.{stage}`, or run this stage "
                "against a model"
            )

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
