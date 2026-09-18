"""The declared vocabulary.

The schema is closed for any one build and editable between builds. Extraction is
constrained to whatever it declares, so a model cannot invent a relation; the file
itself is human-owned, versioned and diffable, so the vocabulary is not frozen
forever. That split is the whole difference between this design and one that
normalises an emergent vocabulary after the fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from metric.ontology.types import LITERAL_TYPE, Candidate, Materiality

Cardinality = Literal["one", "many"]
Grouping = Literal["per_triple", "per_head", "all"]

# The assertion kinds a relation may declare. Closed, because each one names a grader
# that has to exist in code -- a schema may say what a relation checks, not invent a
# way of checking it.
CHECK_KINDS = frozenset(
    {
        "tool_called", "outcome_allowed", "transition_expected", "transition_allowed",
        "terminal_expected", "order_expected", "count_limit", "action_required",
        "action_forbidden", "text_required",
    }
)
CHECK_DIMENSIONS = frozenset(
    {"outcome", "policy", "state", "trajectory", "tool", "grounding", "communication"}
)
Polarity = Literal["positive", "negative", "neutral"]
LiteralType = Literal["str", "bool", "int", "enum"]

_BOOL_LITERALS = frozenset({"true", "false"})


class SchemaError(Exception):
    """Raised when a schema file is internally inconsistent or extends core illegally."""


@dataclass(frozen=True, slots=True)
class CheckSpec:
    """What this relation asserts about a live agent.

    Declared beside the relation rather than in a registry keyed by domain rule codes.
    A use case that adds a relation declares how it is checked in the same file and the
    same edit; nothing in the evaluator has to learn about it.
    """

    kind: str
    dimension: str
    scope: str
    grouping: Grouping = "per_triple"


@dataclass(frozen=True, slots=True)
class RelationSpec:
    name: str
    domain: frozenset[str]
    range: frozenset[str]
    cardinality: Cardinality = "many"
    polarity: Polarity = "neutral"
    materiality: Materiality = "normal"
    literal_type: LiteralType | None = None
    enum: frozenset[str] = field(default_factory=frozenset)
    description: str = ""
    checks: CheckSpec | None = None
    not_checkable: bool = False

    @property
    def takes_literal(self) -> bool:
        return LITERAL_TYPE in self.range


@dataclass(frozen=True, slots=True)
class Schema:
    version: int
    name: str
    structural_types: frozenset[str]
    domain_types: frozenset[str]
    relations: dict[str, RelationSpec]

    @property
    def entity_types(self) -> frozenset[str]:
        return self.structural_types | self.domain_types

    @property
    def relation_names(self) -> tuple[str, ...]:
        return tuple(sorted(self.relations))

    def relation(self, name: str) -> RelationSpec | None:
        return self.relations.get(name)

    @property
    def checked_relations(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, s in self.relations.items() if s.checks is not None))

    def undeclared(self, relations: frozenset[str]) -> tuple[str, ...]:
        """Relations that say neither how they are checked nor that they are not.

        Reported rather than assumed: a relation that quietly checks nothing is the
        difference between a use case that is covered and one that looks covered.
        """
        return tuple(
            sorted(
                name
                for name in relations
                if (spec := self.relations.get(name)) is not None
                and spec.checks is None
                and not spec.not_checkable
            )
        )

    def materiality_of(self, relation: str) -> Materiality:
        spec = self.relations.get(relation)
        return spec.materiality if spec else "normal"

    def check(self, candidate: Candidate) -> str | None:
        """Return why a candidate is not schema-valid, or None if it is.

        Checked before anything else in admission: a triple whose shape the schema
        rejects is not worth locating a quote for.
        """
        spec = self.relations.get(candidate.relation)
        if spec is None:
            return f"unknown relation {candidate.relation!r}"

        if candidate.head_type not in self.entity_types:
            return f"unknown head type {candidate.head_type!r}"
        if candidate.head_type not in spec.domain:
            return (
                f"{candidate.relation} does not accept a {candidate.head_type} head "
                f"(domain: {', '.join(sorted(spec.domain))})"
            )

        if spec.takes_literal:
            if candidate.tail_type != LITERAL_TYPE:
                return f"{candidate.relation} takes a literal tail, got {candidate.tail_type!r}"
            return self._check_literal(spec, candidate.tail)

        if candidate.tail_type == LITERAL_TYPE:
            return f"{candidate.relation} takes an entity tail, got a literal"
        if candidate.tail_type not in self.entity_types:
            return f"unknown tail type {candidate.tail_type!r}"
        if candidate.tail_type not in spec.range:
            return (
                f"{candidate.relation} does not accept a {candidate.tail_type} tail "
                f"(range: {', '.join(sorted(spec.range))})"
            )
        return None

    @staticmethod
    def _check_literal(spec: RelationSpec, value: str) -> str | None:
        if spec.literal_type == "enum":
            if value not in spec.enum:
                return (
                    f"{value!r} is not a permitted value for {spec.name} "
                    f"(one of: {', '.join(sorted(spec.enum))})"
                )
        elif spec.literal_type == "bool":
            if value.strip().lower() not in _BOOL_LITERALS:
                return f"{spec.name} takes a boolean literal, got {value!r}"
        elif spec.literal_type == "int":
            try:
                int(value.strip())
            except ValueError:
                return f"{spec.name} takes an integer literal, got {value!r}"
        return None


def load_schema(core_path: Path, extension_path: Path | None = None) -> Schema:
    """Load core, optionally apply one use-case extension, and validate the result.

    An extension may add domain types and relations, and may narrow an existing
    relation's domain or range. It may not widen one: a use case that contradicts
    core is a schema bug, so this raises rather than picking a winner.
    """
    core = _read(core_path)
    schema = _build(core)
    if extension_path is None:
        return schema

    extension = _read(extension_path)
    return _extend(schema, extension, extension_path)


def _read(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SchemaError(f"{path} does not contain a YAML mapping")
    return data


def _build(data: dict[str, Any]) -> Schema:
    types = data.get("entity_types") or {}
    structural = frozenset(types.get("structural") or ())
    domain = frozenset(types.get("domain") or ())
    if not structural:
        raise SchemaError("schema declares no structural entity types")

    relations: dict[str, RelationSpec] = {}
    for raw in data.get("relations") or ():
        spec = _relation(raw, structural | domain)
        if spec.name in relations:
            raise SchemaError(f"duplicate relation {spec.name!r}")
        relations[spec.name] = spec
    if not relations:
        raise SchemaError("schema declares no relations")

    return Schema(
        version=int(data.get("version", 1)),
        name=str(data.get("name", "unnamed")),
        structural_types=structural,
        domain_types=domain,
        relations=relations,
    )


def _relation(raw: dict[str, Any], known_types: frozenset[str]) -> RelationSpec:
    try:
        name = str(raw["name"])
        domain = frozenset(raw["domain"])
        range_ = frozenset(raw["range"])
    except KeyError as exc:
        raise SchemaError(f"relation is missing {exc.args[0]!r}: {raw}") from exc

    unknown_domain = domain - known_types
    if unknown_domain:
        raise SchemaError(f"{name}: domain names unknown types {sorted(unknown_domain)}")
    unknown_range = range_ - known_types - {LITERAL_TYPE}
    if unknown_range:
        raise SchemaError(f"{name}: range names unknown types {sorted(unknown_range)}")

    literal_type = raw.get("literal_type")
    enum = frozenset(raw.get("enum") or ())
    if LITERAL_TYPE in range_:
        if len(range_) > 1:
            raise SchemaError(f"{name}: a literal range cannot be mixed with entity types")
        if literal_type is None:
            raise SchemaError(f"{name}: a literal range must declare literal_type")
        if literal_type == "enum" and not enum:
            raise SchemaError(f"{name}: literal_type enum requires an enum list")
    elif literal_type is not None:
        raise SchemaError(f"{name}: literal_type is only meaningful for a literal range")

    return RelationSpec(
        name=name,
        checks=_checks(name, raw.get("checks")),
        not_checkable=bool(raw.get("not_checkable", False)),
        domain=domain,
        range=range_,
        cardinality=raw.get("cardinality", "many"),
        polarity=raw.get("polarity", "neutral"),
        materiality=raw.get("materiality", "normal"),
        literal_type=literal_type,
        enum=enum,
        description=str(raw.get("description", "")),
    )


def _checks(name: str, raw: Any) -> CheckSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SchemaError(f"{name}: checks must be a mapping")
    try:
        kind, dimension, scope = str(raw["kind"]), str(raw["dimension"]), str(raw["scope"])
    except KeyError as exc:
        raise SchemaError(f"{name}: checks is missing {exc.args[0]!r}") from exc

    if kind not in CHECK_KINDS:
        raise SchemaError(
            f"{name}: {kind!r} is not a known assertion kind "
            f"(one of: {', '.join(sorted(CHECK_KINDS))})"
        )
    if dimension not in CHECK_DIMENSIONS:
        raise SchemaError(f"{name}: {dimension!r} is not a known evaluation dimension")

    grouping = str(raw.get("grouping", "per_triple"))
    if grouping not in {"per_triple", "per_head", "all"}:
        raise SchemaError(f"{name}: {grouping!r} is not a known grouping")

    return CheckSpec(kind=kind, dimension=dimension, scope=scope, grouping=grouping)  # type: ignore[arg-type]


def _extend(core: Schema, data: dict[str, Any], path: Path) -> Schema:
    types = data.get("entity_types") or {}
    if types.get("structural"):
        raise SchemaError(f"{path}: an extension may not add structural types")
    domain_types = core.domain_types | frozenset(types.get("domain") or ())
    known = core.structural_types | domain_types

    relations = dict(core.relations)
    for raw in data.get("relations") or ():
        spec = _relation(raw, known)
        existing = core.relations.get(spec.name)
        if existing is not None:
            _check_narrowing(existing, spec, path)
        relations[spec.name] = spec

    return Schema(
        version=int(data.get("version", core.version)),
        name=str(data.get("name", core.name)),
        structural_types=core.structural_types,
        domain_types=domain_types,
        relations=relations,
    )


def _check_narrowing(core_spec: RelationSpec, override: RelationSpec, path: Path) -> None:
    widened_domain = override.domain - core_spec.domain
    if widened_domain:
        raise SchemaError(
            f"{path}: {override.name} widens the core domain with {sorted(widened_domain)}"
        )
    widened_range = override.range - core_spec.range
    if widened_range:
        raise SchemaError(
            f"{path}: {override.name} widens the core range with {sorted(widened_range)}"
        )
