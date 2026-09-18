"""Prompts and the response schemas that constrain them.

Both passes are built from the active ontology rather than written against it, so a
relation added to the YAML reaches the model and its enum in the same edit. The
enum is what makes "the model cannot invent a relation" structural instead of
aspirational: an invented name is not merely rejected downstream, it is unsayable.

`prompt_hash` covers the templates *and* the rendered ontology, because a prompt
that reads differently is a different prompt whether a human or a schema edit
changed it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from metric.extract.batching import Batch
from metric.ontology.schema import RelationSpec, Schema
from metric.ontology.types import LITERAL_TYPE

GLOSSARY_SYSTEM = """\
You are reading one section of a policy document to build a glossary of the things it \
names. You are not extracting facts or relationships in this pass.

Report every entity the section refers to, using the exact surface form the section \
uses. Report a surface form once, even if it appears many times.

An entity is something the policy treats as a thing: a step in a journey, a tool, a \
named outcome, a rule, a runtime variable, a limit, a role. Ordinary nouns that carry \
no policy meaning are not entities.

Where the section names the same thing two ways, report both surface forms — later \
passes need to know they occur, and deciding they are the same thing is not your job.

Assign each surface form the type that best fits from the permitted list. If none \
fits, omit the entity rather than forcing it into a type.
"""

TRIPLES_SYSTEM = """\
You are extracting facts from one section of a policy document into subject–relation–object \
triples. Downstream systems test a live agent against these triples, so a fact you \
invent becomes a test the agent is failed for.

Rules, in order of importance:

1. Extract only what the section states. Never infer a fact from a pattern, complete a \
sequence, or supply a value the section leaves open. If the section says an outcome \
occurs but not what follows it, extract the outcome and stop — do not supply a \
plausible next step.
2. Every triple carries a quote that is a verbatim, contiguous substring of one passage \
in this section, and the label of that passage. Copy the quote character for character. \
Do not paraphrase, join fragments, tidy punctuation or fix typography.
3. The quote must contain the fact. For a triple carrying a number, a name or an exact \
wording, that value must appear in the quote itself.
4. Use only the relations listed below, and respect each one's subject and object types.
5. Prefer a surface form from the glossary when the section refers to the same thing. \
Where the section introduces something the glossary does not have, use the section's \
wording.
6. Extract the same fact once per place it is stated. A fact stated twice in two \
passages is two triples with two quotes; a fact stated once is one triple. Do not \
restate one fact in several relations to be safe.
7. A negative statement is a fact. "must not transfer" is a prohibition, not the \
absence of a permission — extract it with the relation that carries that meaning.
8. Name a Rule by its own sentence, verbatim. A rule has no other name, and using its \
sentence is what lets the same rule found in two places be recognised as one rule.

Set `non_normative` to true when the section states no extractable facts at all — a \
heading block, a table of contents, a revision history, a worked example. That is \
different from finding nothing in a section that plainly contains rules; in that case \
extract what is there.
"""


def glossary_prompt(batch: Batch) -> str:
    return f"Document: {batch.title}\n\nSection:\n\n{batch.render()}"


def triples_prompt(batch: Batch, *, glossary: str) -> str:
    parts = [f"Document: {batch.title}"]
    if glossary:
        parts.append(f"Glossary of entities named across this document:\n{glossary}")
    parts.append(f"Section:\n\n{batch.render()}")
    return "\n\n".join(parts)


def relation_catalogue(schema: Schema) -> str:
    return "\n".join(_relation_line(schema.relations[name]) for name in schema.relation_names)


def entity_type_catalogue(schema: Schema) -> str:
    return "\n".join(f"- {name}" for name in sorted(schema.entity_types))


def triples_system(schema: Schema) -> str:
    return (
        f"{TRIPLES_SYSTEM}\n"
        f"Entity types:\n{entity_type_catalogue(schema)}\n\n"
        f"Relations (subject -> object):\n{relation_catalogue(schema)}\n"
    )


def glossary_system(schema: Schema) -> str:
    return f"{GLOSSARY_SYSTEM}\nPermitted types:\n{entity_type_catalogue(schema)}\n"


def glossary_schema(schema: Schema) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "surface": {"type": "string"},
                        "type": {"type": "string", "enum": sorted(schema.entity_types)},
                    },
                    "required": ["surface", "type"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["entities"],
        "additionalProperties": False,
    }


def triples_schema(schema: Schema) -> dict[str, Any]:
    entity_types = sorted(schema.entity_types)
    return {
        "type": "object",
        "properties": {
            "non_normative": {"type": "boolean"},
            "triples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "head": {"type": "string"},
                        "head_type": {"type": "string", "enum": entity_types},
                        "relation": {"type": "string", "enum": list(schema.relation_names)},
                        "tail": {"type": "string"},
                        "tail_type": {
                            "type": "string",
                            "enum": [*entity_types, LITERAL_TYPE],
                        },
                        "passage": {"type": "string"},
                        "quote": {"type": "string"},
                    },
                    "required": [
                        "head",
                        "head_type",
                        "relation",
                        "tail",
                        "tail_type",
                        "passage",
                        "quote",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["non_normative", "triples"],
        "additionalProperties": False,
    }


def prompt_hash(schema: Schema) -> str:
    payload = "\x1f".join([glossary_system(schema), triples_system(schema)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _relation_line(spec: RelationSpec) -> str:
    domain = " | ".join(sorted(spec.domain))
    target = _range(spec)
    flags = []
    if spec.cardinality == "one":
        flags.append("at most one")
    if spec.polarity != "neutral":
        flags.append(spec.polarity)
    suffix = f" [{', '.join(flags)}]" if flags else ""
    line = f"- {spec.name}: {domain} -> {target}{suffix}"
    return f"{line}\n    {spec.description}" if spec.description else line


def _range(spec: RelationSpec) -> str:
    if not spec.takes_literal:
        return " | ".join(sorted(spec.range))
    if spec.literal_type == "enum":
        return f"one of: {' | '.join(sorted(spec.enum))}"
    return f"a {spec.literal_type} value, quoted verbatim from the source"
