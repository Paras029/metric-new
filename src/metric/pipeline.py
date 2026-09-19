"""The build: documents in, graph and questions out.

Seven stages, in order. Only one of them — pass B — lets a model decide anything,
and everything it produces has to survive the gate. That is the whole shape of the
thing; the rest of this module is wiring.

Batching is per document. Batching across documents would put one policy's context
header on another policy's text, and a quote located in the wrong document is the
kind of error that survives every later check. The glossary is global, because the
same entity named in two documents is one entity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metric import __version__
from metric.admit.gate import admit
from metric.corpus.manifest import Manifest
from metric.corpus.passages import read_passages
from metric.corpus.scope import Scope, apply_scope
from metric.discover.emit import apply_observations
from metric.extract.batching import Batch, batch_passages
from metric.extract.glossary import Glossary, build_glossary
from metric.extract.harvest import harvest
from metric.extract.triples import extract
from metric.graph.model import Graph
from metric.llm.gateway import Gateway
from metric.llm.prompts import prompt_hash
from metric.ontology.ids import question_id
from metric.ontology.schema import Schema
from metric.ontology.types import Document, Passage, Question, Rejection, Triple
from metric.refine.inert import Pruned
from metric.refine.inert import prune as prune_inert
from metric.refine.names import Refinement
from metric.refine.names import refine as refine_names
from metric.settings import Settings
from metric.telemetry.profile import Profile, apply_profile


@dataclass(frozen=True, slots=True)
class DocumentSpec:
    path: Path
    policy_version: str = ""
    effective_date: str = ""
    sections: tuple[str, ...] = ()
    skip_sections: tuple[str, ...] = ()

    @property
    def scope(self) -> Scope:
        return Scope(include=self.sections, exclude=self.skip_sections)

    @property
    def title(self) -> str:
        return self.path.stem.replace("-", " ").replace("_", " ")


@dataclass(frozen=True, slots=True)
class Coverage:
    """What the corpus was asked and what it answered.

    `silent` is the number that matters: batches that produced nothing and did not
    claim to be non-normative, after a second read. Under-extraction is otherwise
    invisible — a fact never proposed cannot be rejected, counted or missed.
    """

    batches: int
    non_normative: int
    silent: tuple[str, ...]
    rereads: int


@dataclass(frozen=True, slots=True)
class BuildResult:
    graph: Graph
    questions: tuple[Question, ...]
    rejections: tuple[Rejection, ...]
    manifest: Manifest
    coverage: Coverage
    glossary: Glossary
    passages: dict[str, Passage] = field(default_factory=dict)
    profile_problems: tuple[str, ...] = ()
    scope_notes: tuple[str, ...] = ()
    refinement: Refinement | None = None
    pruned: Pruned | None = None


def ingest(
    specs: Sequence[DocumentSpec],
    *,
    schema: Schema,
    gateway: Gateway,
    decisions: Mapping[str, str] | None = None,
    profile: Profile | None = None,
    observations: Mapping[str, Any] | None = None,
    settings: Settings | None = None,
) -> BuildResult:
    from metric.reconcile.run import reconcile

    active = settings or Settings()
    manifest = Manifest(
        schema_version=f"{schema.name}/{schema.version}",
        prompt_hash=prompt_hash(schema),
        model=gateway.identity,
        code_version=__version__,
        settings_digest=active.digest,
    )

    passages: dict[str, Passage] = {}
    effective_dates: dict[str, str] = {}
    batches: list[Batch] = []
    scope_notes: list[str] = []

    for spec in specs:
        document, found = read_passages(
            spec.path,
            policy_version=spec.policy_version,
            effective_date=spec.effective_date,
        )
        manifest.add(document)
        scoped = apply_scope(found, spec.scope)
        found = list(scoped.passages)
        if scoped.note:
            scope_notes.append(f"{spec.path.name}: {scoped.note}")
        _register(found, document, passages=passages, effective_dates=effective_dates)
        batches.extend(
            batch_passages(
                found,
                title=spec.title,
                budget_chars=active.corpus.batch_chars,
                min_chars=active.corpus.min_batch_chars,
            )
        )

    ordered = sorted(passages.values(), key=lambda p: (p.doc_id, p.location, p.id))
    candidates = list(harvest(ordered))

    glossary = build_glossary(batches, gateway=gateway, schema=schema)
    extraction = extract(batches, gateway=gateway, schema=schema, glossary=glossary)
    candidates.extend(extraction.candidates)

    admission = admit(
        candidates, schema=schema, passages=passages, settings=active.admission
    )
    rejections = [*extraction.rejections, *admission.rejections]
    results = extraction.results

    # Names before identity: renaming an entity changes its content hash, so this has to
    # happen before reconciliation folds triples together by id.
    refined = refine_names(
        admission.entities,
        admission.triples,
        gateway=gateway,
        quotes=_quotes(admission.triples),
    )
    pruned = prune_inert(refined.entities, refined.triples, schema)

    reconciled = reconcile(
        pruned.entities,
        pruned.triples,
        schema=schema,
        effective_dates=effective_dates,
        decisions=decisions,
        witness=active.witness,
    )

    graph = reconciled.graph
    if observations is not None:
        graph = apply_observations(graph, observations)

    profile_problems: tuple[str, ...] = ()
    if profile is not None:
        graph, problems = apply_profile(graph, profile)
        profile_problems = tuple(problems)

    questions = tuple(reconciled.questions)
    if pruned.removed:
        questions = (*questions, _inert_question(pruned))

    return BuildResult(
        graph=graph,
        questions=questions,
        rejections=tuple(rejections),
        manifest=manifest,
        coverage=Coverage(
            batches=len(results),
            non_normative=sum(1 for r in results if r.non_normative),
            silent=tuple(r.batch_id for r in results if r.silent),
            rereads=sum(1 for r in results if r.reread),
        ),
        glossary=glossary,
        passages=passages,
        profile_problems=profile_problems,
        scope_notes=tuple(scope_notes),
        refinement=refined,
        pruned=pruned,
    )


def _inert_question(pruned: Pruned) -> Question:
    """One question for all of them, because it is one decision.

    Nine separate "this rule is attached to nothing" questions is not nine decisions — it
    is one question about whether the extractor is missing a clause, asked nine times.
    """
    listed = "\n".join(f"- {i.name}" for i in pruned.removed)
    return Question(
        id=question_id("refine/inert", *(i.entity for i in pruned.removed)),
        kind="refine/inert",
        heading=f"{len(pruned.removed)} rules state nothing checkable and were left out",
        detail=(
            "Each was extracted as a rule but requires, forbids and bounds nothing, and "
            "nothing is governed by it, so it could never have been checked against a "
            "trace. Most are restatements of a rule already in the graph — a summary "
            "section or an evaluation checklist. Any that are not are rules whose clause "
            f"the extractor missed, and belong in the corpus:\n{listed}"
        ),
        blocks="",
        evidence=(),
    )


def _quotes(triples: Sequence[Triple]) -> dict[str, tuple[str, ...]]:
    """The source sentences each entity was found in, for naming it."""
    found: dict[str, list[str]] = {}
    for triple in triples:
        for span in triple.spans:
            for side in (triple.head, triple.tail if triple.tail_kind == "entity" else ""):
                if side and span.quote not in found.setdefault(side, []):
                    found[side].append(span.quote)
    return {entity: tuple(quotes) for entity, quotes in found.items()}


def _register(
    found: Sequence[Passage],
    document: Document,
    *,
    passages: dict[str, Passage],
    effective_dates: dict[str, str],
) -> None:
    for passage in found:
        passages[passage.id] = passage
        effective_dates[passage.id] = document.effective_date
