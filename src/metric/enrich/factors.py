"""The factor catalogue: ways of varying how an agent meets a situation.

The book's central separation. A **base** fixes the policy situation and the contract
that applies to it. **Enrichment** varies the way the agent encounters that situation
without changing what is required — a hesitant customer, a garbled transcript, a longer
history. Vary presentation and the ground truth is untouched, so a failure under one
level and a pass under another is attributable to that level rather than to relabelling.

The catalogue is a YAML file per channel, human-owned like the ontology, because which
factors matter is a property of the use case and not of this code.

`invariant: false` is the important field. A tool timeout does not change how the agent
should *say* something — it changes what is required of it, so it is a different
situation and belongs in its own base. Factors declared non-invariant are reported and
excluded from the design rather than quietly mixed in, because mixing them is exactly
how a variant ends up graded against a contract that never applied to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class CatalogueError(Exception):
    """Raised when a factor catalogue is malformed."""


@dataclass(frozen=True, slots=True)
class Factor:
    name: str
    group: str
    levels: tuple[str, ...]
    invariant: bool = True
    adverse: str = ""
    description: str = ""

    @property
    def baseline(self) -> str:
        """The first level: what the base scenario is assumed to be unless varied."""
        return self.levels[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "levels": list(self.levels),
            "invariant": self.invariant,
            "adverse": self.adverse,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class Catalogue:
    name: str
    factors: tuple[Factor, ...]

    @property
    def invariant(self) -> tuple[Factor, ...]:
        return tuple(f for f in self.factors if f.invariant)

    @property
    def situational(self) -> tuple[Factor, ...]:
        """Factors that change what is required, so each needs its own base."""
        return tuple(f for f in self.factors if not f.invariant)

    def factor(self, name: str) -> Factor | None:
        return next((f for f in self.factors if f.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "factors": [f.as_dict() for f in self.factors]}


def load_catalogue(path: Path) -> Catalogue:
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise CatalogueError(f"{path} does not contain a YAML mapping")

    factors = tuple(_factor(raw, path) for raw in document.get("factors") or ())
    if not factors:
        raise CatalogueError(f"{path} declares no factors")

    names = [f.name for f in factors]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise CatalogueError(f"{path}: duplicate factors {duplicates}")

    return Catalogue(name=str(document.get("name") or path.stem), factors=factors)


def _factor(raw: Any, path: Path) -> Factor:
    if not isinstance(raw, dict):
        raise CatalogueError(f"{path}: every factor must be a mapping")
    try:
        name = str(raw["name"])
        levels = tuple(str(level) for level in raw["levels"])
    except KeyError as exc:
        raise CatalogueError(f"{path}: a factor is missing {exc.args[0]!r}") from exc

    if len(levels) < 2:
        raise CatalogueError(f"{path}: {name} has fewer than two levels, so it varies nothing")
    if len(set(levels)) != len(levels):
        raise CatalogueError(f"{path}: {name} repeats a level")

    adverse = str(raw.get("adverse", ""))
    if adverse and adverse not in levels:
        raise CatalogueError(f"{path}: {name} names an adverse level it does not have: {adverse}")

    return Factor(
        name=name,
        group=str(raw.get("group", "general")),
        levels=levels,
        invariant=bool(raw.get("invariant", True)),
        adverse=adverse,
        description=str(raw.get("description", "")),
    )
