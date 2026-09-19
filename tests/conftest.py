"""Shared fixtures, and the test double that stands in for the model.

`ScriptedGateway` answers with triples a test names, but works out the passage label
itself by finding the quote in the rendered batch. That keeps the scripts readable
and, more usefully, makes them exercise the real batching and labelling rather than
hard-coding what those produced on the day the test was written.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from metric.ontology.schema import Schema, load_schema
from metric.workspace import BuildSpec, Workspace

REPO = Path(__file__).resolve().parents[1]
POLICY = REPO / "grounding" / "07-card-authentication-policy.md"

_LABEL = re.compile(r"^\[(P\d+)\] \(", re.MULTILINE)


class ScriptedGateway:
    """A gateway with no network, no cache, and answers supplied by the test."""

    identity = "scripted/test"

    def __init__(
        self,
        *,
        entities: list[dict[str, str]] | None = None,
        triples: list[dict[str, str]] | None = None,
    ) -> None:
        self.entities = entities or []
        self.triples = triples or []
        self.calls: list[str] = []

    def json(
        self, *, system: str, prompt: str, schema: dict[str, Any], label: str
    ) -> dict[str, Any]:
        self.calls.append(label)
        if label.startswith("glossary"):
            return {"entities": self.entities}

        answered = [
            {**triple, "passage": found}
            for triple in self.triples
            if (found := _label_for(prompt, triple["quote"])) is not None
        ]
        return {"non_normative": not answered, "triples": answered}


def _label_for(prompt: str, quote: str) -> str | None:
    """Which labelled block of the rendered batch contains `quote`."""
    marks = list(_LABEL.finditer(prompt))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(prompt)
        if quote in prompt[mark.start() : end]:
            return mark.group(1)
    return None


@pytest.fixture(scope="session")
def core_schema() -> Schema:
    return load_schema(REPO / "schemas" / "core.ontology.yaml")


@pytest.fixture(scope="session")
def card_auth_schema() -> Schema:
    return load_schema(
        REPO / "schemas" / "core.ontology.yaml",
        REPO / "schemas" / "card_auth.ontology.yaml",
    )


@pytest.fixture(scope="session")
def policy_path() -> Path:
    return POLICY


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> Workspace:
    """The card-auth workspace, built once from the recorded extraction."""
    out = tmp_path_factory.mktemp("build")
    return Workspace(BuildSpec.from_corpus(REPO / "corpus.yaml", out_dir=out))


@pytest.fixture(scope="session")
def aop(tmp_path_factory: pytest.TempPathFactory) -> Workspace:
    """The AOP workspace: real traces, no policy document, an observed graph."""
    out = tmp_path_factory.mktemp("aop")
    return Workspace(BuildSpec.from_corpus(REPO / "corpus-aop.yaml", out_dir=out))


@pytest.fixture()
def reviewable(tmp_path: Path) -> Workspace:
    """A fresh workspace with its own questions file, for tests that answer questions."""
    return Workspace(BuildSpec.from_corpus(REPO / "corpus.yaml", out_dir=tmp_path))
