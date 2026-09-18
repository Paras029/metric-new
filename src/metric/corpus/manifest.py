"""The corpus manifest: what was ingested, and under what conditions.

Build identity is `(corpus, schema, prompts, model, code)`. Same tuple must mean the
same graph, so the manifest is what a reproducibility claim is actually made against
— and what a drift investigation starts from.

Document precedence is declared here rather than inferred. Two versions of a policy
in one corpus are a resolvable conflict only if somebody has said which supersedes
which; guessing from filenames is how the wrong rule wins silently.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metric.ontology.types import Document


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    corpus: str
    schema: str
    prompts: str
    model: str
    code: str

    @property
    def digest(self) -> str:
        payload = "\x1f".join([self.corpus, self.schema, self.prompts, self.model, self.code])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "corpus": self.corpus,
            "schema": self.schema,
            "prompts": self.prompts,
            "model": self.model,
            "code": self.code,
            "digest": self.digest,
        }


@dataclass(slots=True)
class Manifest:
    documents: list[Document] = field(default_factory=list)
    schema_version: str = ""
    prompt_hash: str = ""
    model: str = ""
    code_version: str = ""

    def add(self, document: Document) -> None:
        self.documents.append(document)

    @property
    def corpus_hash(self) -> str:
        """Order-independent: the corpus is a set of documents, not a sequence."""
        parts = sorted(f"{d.sha256}:{Path(d.path).name}" for d in self.documents)
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]

    @property
    def identity(self) -> BuildIdentity:
        return BuildIdentity(
            corpus=self.corpus_hash,
            schema=self.schema_version,
            prompts=self.prompt_hash,
            model=self.model,
            code=self.code_version,
        )

    def supersedes(self, earlier: Document, later: Document) -> bool:
        """Whether `later` takes precedence, by declared effective date only."""
        if not earlier.effective_date or not later.effective_date:
            return False
        return later.effective_date > earlier.effective_date

    def as_dict(self) -> dict[str, Any]:
        return {
            "documents": [d.as_dict() for d in self.documents],
            "identity": self.identity.as_dict(),
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.as_dict(), indent=2, sort_keys=True)
        path.write_text(payload + "\n", encoding="utf-8")
