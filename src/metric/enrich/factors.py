"""The factor catalogue: ways of varying how an agent meets a situation.

The book's central separation. A **base** fixes the policy situation and the contract
that applies to it. **Enrichment** varies the way the agent encounters that situation
without changing what is required — a hesitant customer, a garbled transcript, a longer
history. Vary presentation and the ground truth is untouched, so a failure under one
level and a pass under another is attributable to that level rather than to relabelling.

Two relations govern how a factor enters an experiment.

**Invariance** — `invariant: false` says varying this factor changes what is *required*,
not merely how the situation arrives. A tool timeout does not change how the agent should
say something; it changes what it must do. That is a different situation and belongs in
its own base. Non-invariant factors are reported and excluded rather than quietly mixed
in, because mixing them is exactly how a variant ends up graded against a contract that
never applied to it.

**Relevance** — `applies_to` names the base families and answer types a factor is
meaningful for, and is applied automatically when the design is built. Numeric framing
means nothing to a base whose answer is a route through the graph. Crossing it in anyway
does not merely waste runs: it spends the design's budget on cells that cannot fail for
the reason the column claims to measure, and the attribution that comes back is diluted
by them.

Three levels of customisation, in increasing order, and the boundary between them is the
point — **selecting a factor is data; rendering its levels is code.**

1. **Select** factors, or a named profile, and let relevance filter the rest.
2. **Override** a factor's level vocabulary through `level_overrides`, so a domain reads
   in its own terms without forking the shared catalogue.
3. **Add** a factor — a plain YAML entry with the same schema. The one rule is
   invariance: if varying its levels could change the correct answer, it is a base.

Turning a chosen level into actual text — making `garbled` read garbled — happens at the
run boundary, not here. The catalogue records the choice; a materialiser renders it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml


class CatalogueError(Exception):
    """Raised when a factor catalogue or profile is malformed."""


@dataclass(frozen=True, slots=True)
class Applicability:
    """Which bases a factor is meaningful for. Empty means all of them."""

    families: tuple[str, ...] = ()
    answer_types: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()

    @property
    def universal(self) -> bool:
        """Whether nothing *positively* selects. `excludes` alone still means everywhere.

        A factor that names only what it does not apply to applies to the rest. Reading
        an exclusion as though it were a selection would silently drop the factor from
        every base, which is the same failure as forgetting to declare it.
        """
        return not (self.families or self.answer_types or self.categories)

    def covers(self, *, family: str, answer_type: str, category: str) -> bool:
        if category in self.excludes:
            return False
        if self.universal:
            return True
        return (
            (bool(self.families) and family in self.families)
            or (bool(self.answer_types) and answer_type in self.answer_types)
            or (bool(self.categories) and category in self.categories)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "families": list(self.families),
            "answer_types": list(self.answer_types),
            "categories": list(self.categories),
            "excludes": list(self.excludes),
        }


@dataclass(frozen=True, slots=True)
class Factor:
    name: str
    group: str
    levels: tuple[str, ...]
    invariant: bool = True
    adverse: str = ""
    description: str = ""
    applies_to: Applicability = Applicability()

    @property
    def baseline(self) -> str:
        """The first level: what the base scenario is assumed to be unless varied."""
        return self.levels[0]

    def with_levels(self, levels: tuple[str, ...]) -> Factor:
        """An override of the level vocabulary, keeping the adverse level if it survives."""
        return replace(self, levels=levels, adverse=self.adverse if self.adverse in levels else "")

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "group": self.group,
            "levels": list(self.levels),
            "invariant": self.invariant,
            "adverse": self.adverse,
            "description": self.description,
            "applies_to": self.applies_to.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class Catalogue:
    name: str
    factors: tuple[Factor, ...]
    profiles: dict[str, Profile] = field(default_factory=dict)

    @property
    def invariant(self) -> tuple[Factor, ...]:
        return tuple(f for f in self.factors if f.invariant)

    @property
    def situational(self) -> tuple[Factor, ...]:
        """Factors that change what is required, so each needs its own base."""
        return tuple(f for f in self.factors if not f.invariant)

    def factor(self, name: str) -> Factor | None:
        return next((f for f in self.factors if f.name == name), None)

    def relevant(self, *, family: str, answer_type: str, category: str) -> tuple[Factor, ...]:
        """The invariant factors meaningful for one base."""
        return tuple(
            f
            for f in self.invariant
            if f.applies_to.covers(family=family, answer_type=answer_type, category=category)
        )

    def apply(self, profile: Profile | None) -> Catalogue:
        """This catalogue as a named profile sees it: selected, then overridden."""
        if profile is None:
            return self
        chosen = (
            self.factors
            if not profile.factors
            else tuple(f for f in self.factors if f.name in set(profile.factors))
        )
        overridden = tuple(
            f.with_levels(profile.level_overrides[f.name])
            if f.name in profile.level_overrides
            else f
            for f in chosen
        )
        return replace(self, factors=overridden)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "factors": [f.as_dict() for f in self.factors],
            "profiles": {name: p.as_dict() for name, p in sorted(self.profiles.items())},
        }


@dataclass(frozen=True, slots=True)
class Profile:
    """A named bundle: which factors, with which levels, in which arrangement."""

    name: str
    factors: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    level_overrides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    arrangement: str = ""
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "factors": list(self.factors),
            "categories": list(self.categories),
            "level_overrides": {k: list(v) for k, v in sorted(self.level_overrides.items())},
            "arrangement": self.arrangement,
            "description": self.description,
        }


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

    profiles = {
        name: _profile(name, raw, path, {f.name: f for f in factors})
        for name, raw in (document.get("profiles") or {}).items()
    }
    return Catalogue(
        name=str(document.get("name") or path.stem), factors=factors, profiles=profiles
    )


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
        applies_to=_applicability(raw.get("applies_to"), name, path),
    )


def _applicability(raw: Any, factor: str, path: Path) -> Applicability:
    if raw is None:
        return Applicability()
    if not isinstance(raw, dict):
        raise CatalogueError(f"{path}: {factor}'s applies_to must be a mapping")
    known = {"families", "answer_types", "categories", "excludes"}
    unknown = set(raw) - known
    if unknown:
        raise CatalogueError(
            f"{path}: {factor}'s applies_to has unknown keys {sorted(unknown)}; "
            f"expected {sorted(known)}"
        )
    return Applicability(
        families=tuple(str(x) for x in raw.get("families") or ()),
        answer_types=tuple(str(x) for x in raw.get("answer_types") or ()),
        categories=tuple(str(x) for x in raw.get("categories") or ()),
        excludes=tuple(str(x) for x in raw.get("excludes") or ()),
    )


def _profile(name: str, raw: Any, path: Path, factors: dict[str, Factor]) -> Profile:
    if not isinstance(raw, dict):
        raise CatalogueError(f"{path}: profile {name} must be a mapping")

    chosen = tuple(str(f) for f in raw.get("factors") or ())
    missing = sorted(set(chosen) - set(factors))
    if missing:
        raise CatalogueError(f"{path}: profile {name} selects factors that do not exist: {missing}")

    overrides: dict[str, tuple[str, ...]] = {}
    for factor, levels in (raw.get("level_overrides") or {}).items():
        if factor not in factors:
            raise CatalogueError(
                f"{path}: profile {name} overrides levels of {factor}, which does not exist"
            )
        values = tuple(str(level) for level in levels)
        if len(values) < 2:
            raise CatalogueError(
                f"{path}: profile {name} overrides {factor} with fewer than two levels"
            )
        if len(set(values)) != len(values):
            raise CatalogueError(f"{path}: profile {name} repeats a level of {factor}")
        overrides[factor] = values

    arrangement = str(raw.get("arrangement", ""))
    if arrangement and arrangement not in {"crossed", "embedded"}:
        raise CatalogueError(
            f"{path}: profile {name} names arrangement {arrangement!r}, "
            "which is neither crossed nor embedded"
        )

    return Profile(
        name=name,
        factors=chosen,
        categories=tuple(str(c) for c in raw.get("categories") or ()),
        level_overrides=overrides,
        arrangement=arrangement,
        description=str(raw.get("description", "")),
    )
