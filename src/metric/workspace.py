"""Everything one build needs, in one object.

The CLI and the UI drive the same pipeline, so they share this rather than each
assembling their own. The important part is `answer()`: recording a decision writes
`questions.yaml` and rebuilds, which is what makes the review queue a loop instead of
a report. Approving an expectation is the moment it stops advising and starts being
able to fail an agent, and that has to be one action, not a file edit followed by a
remembered command.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

from metric.accuracy import Accuracy, load_annotation, measure
from metric.contract.compile import compile_all
from metric.contract.model import Contract
from metric.discover.emit import load_observations
from metric.enrich.design import Item, Plan, plan
from metric.enrich.factors import Catalogue, load_catalogue
from metric.enrich.factors import Profile as FactorProfile
from metric.evaluate.model import Evaluation
from metric.evaluate.run import evaluate_trace
from metric.llm.gateway import Gateway
from metric.llm.select import build_gateway
from metric.ontology.schema import Schema, load_schema
from metric.pipeline import BuildResult, DocumentSpec, ingest
from metric.resolve import resolve_for_scenario
from metric.review import ANSWERS, Decision, evidence_key, read, write
from metric.scenario.model import ScenarioSpace
from metric.scenario.space import build_space, describe, load_seeds
from metric.settings import Settings, load_settings
from metric.telemetry.profile import Profile, load_profile
from metric.trace.galileo import read_galileo_export
from metric.trace.model import Trace

QUESTIONS_FILE = "questions.yaml"


@dataclass(frozen=True, slots=True)
class BuildSpec:
    """Where a build's inputs live. One place, so the CLI and the UI cannot diverge."""

    documents: tuple[DocumentSpec, ...]
    schema_path: Path
    extension_path: Path | None = None
    profile_path: Path | None = None
    observations_path: Path | None = None
    catalogue_path: Path | None = None
    seeds_path: Path | None = None
    annotation_path: Path | None = None
    settings_path: Path | None = None
    fixture_path: Path | None = None
    cache_path: Path | None = None
    traces: tuple[Path, ...] = ()
    out_dir: Path = Path("build")
    replay: bool = False
    use_case: str = ""
    factor_profile: str = ""
    settings_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_corpus(cls, path: Path, **overrides: object) -> BuildSpec:
        """Read a corpus file: documents with their versions, plus optional inputs."""
        with path.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
        root = path.parent

        documents = tuple(
            DocumentSpec(
                path=root / str(entry["path"]),
                policy_version=str(entry.get("policy_version", "")),
                effective_date=str(entry.get("effective_date", "")),
                sections=tuple(str(s) for s in entry.get("sections") or ()),
                skip_sections=tuple(str(s) for s in entry.get("skip_sections") or ()),
            )
            for entry in document.get("documents") or ()
        )
        settings: dict[str, object] = {"documents": documents}
        for key, field_name in (
            ("schema", "schema_path"),
            ("extend", "extension_path"),
            ("profile", "profile_path"),
            ("observed", "observations_path"),
            ("factors", "catalogue_path"),
            ("seeds", "seeds_path"),
            ("annotation", "annotation_path"),
            ("settings", "settings_path"),
            ("fixture", "fixture_path"),
        ):
            if document.get(key):
                settings[field_name] = root / str(document[key])
        if document.get("traces"):
            settings["traces"] = tuple(root / str(t) for t in document["traces"])
        for key, field_name in (("use_case", "use_case"), ("factor_profile", "factor_profile")):
            if document.get(key):
                settings[field_name] = str(document[key])

        settings.update(overrides)
        spec = cls(**settings)  # type: ignore[arg-type]
        if spec.settings_path is None and (root / "metric.yaml").exists():
            spec = replace(spec, settings_path=root / "metric.yaml")
        return spec


def _write_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class Workspace:
    """A built graph, its scenarios, its evaluations, and the review loop over it."""

    def __init__(self, spec: BuildSpec) -> None:
        self.spec = spec
        self.schema: Schema = load_schema(spec.schema_path, spec.extension_path)
        self.profile: Profile | None = (
            load_profile(spec.profile_path) if spec.profile_path else None
        )
        self.observations = (
            load_observations(spec.observations_path) if spec.observations_path else None
        )
        self.catalogue: Catalogue | None = (
            load_catalogue(spec.catalogue_path) if spec.catalogue_path else None
        )
        self.annotation = (
            load_annotation(spec.annotation_path) if spec.annotation_path else None
        )
        self.settings: Settings = replace(
            load_settings(spec.settings_path), **(spec.settings_overrides or {})
        )
        self.seeds = load_seeds(spec.seeds_path) if spec.seeds_path else ()
        self.traces: tuple[Trace, ...] = tuple(read_galileo_export(p) for p in spec.traces)
        self.build()

    @property
    def factor_profile(self) -> FactorProfile | None:
        """The named bundle of factors and levels this corpus asked for."""
        if self.catalogue is None or not self.spec.factor_profile:
            return None
        found = self.catalogue.profiles.get(self.spec.factor_profile)
        if found is None:
            raise ValueError(
                f"{self.spec.catalogue_path} declares no profile "
                f"{self.spec.factor_profile!r}; it has "
                f"{', '.join(sorted(self.catalogue.profiles)) or 'none'}"
            )
        return found

    @property
    def questions_path(self) -> Path:
        return self.spec.out_dir / QUESTIONS_FILE

    @property
    def checkpoint_variable(self) -> str:
        return self.profile.checkpoint_variable if self.profile else ""

    def build(self) -> BuildResult:
        self.decisions: dict[str, Decision] = read(self.questions_path)
        answers = {q: d.answer for q, d in self.decisions.items() if d.answered}

        self.result = ingest(
            self.spec.documents,
            schema=self.schema,
            gateway=self._gateway(),
            decisions=answers,
            profile=self.profile,
            observations=self.observations,
            settings=self.settings,
        )
        self.graph = self.result.graph
        self.compiled = compile_all(self.graph, self.schema)
        scenario_settings = self.settings.scenario
        self.capabilities = describe(self.graph)
        self.space: ScenarioSpace = build_space(
            self.graph,
            max_depth=scenario_settings.max_depth,
            max_paths=scenario_settings.max_paths,
            default_revisits=scenario_settings.default_revisits,
            reach_for_uncovered=scenario_settings.reach_for_uncovered,
            seeds=self.seeds,
        )
        self.plan: Plan | None = self._plan()
        self.accuracy: Accuracy | None = (
            measure(self.graph, self.schema, self.annotation) if self.annotation else None
        )
        self.evaluations: tuple[Evaluation, ...] = tuple(
            evaluate_trace(
                self.graph,
                self.schema,
                trace,
                identity=self.identity,
                checkpoint_variable=self.checkpoint_variable,
                compiled=self.compiled,
            )
            for trace in self.traces
        )
        return self.result

    def _plan(self) -> Plan | None:
        """Which variants of each base to run.

        A base's weight comes from its own contract — whether anything on it can block —
        rather than from a table of variation counts nobody approved. Its family and
        answer type come with it, so relevance filtering happens inside the planner.
        """
        if self.catalogue is None:
            return None
        items = []
        for scenario in self.space.scenarios:
            contract = self.contract_for(scenario.id)
            items.append(
                Item(
                    id=scenario.id,
                    category=scenario.category,
                    family=scenario.family,
                    answer_type=scenario.answer_type,
                    blocking=bool(contract and contract.blocking),
                )
            )
        return plan(
            items,
            self.catalogue,
            arrangement=self.settings.enrich.arrangement,
            profile=self.factor_profile,
            adverse_run=self.settings.enrich.adverse_run,
        )

    @property
    def identity(self) -> str:
        return self.result.manifest.identity.digest

    @property
    def passages(self) -> dict[str, Any]:
        return self.result.passages

    def write(self, out_dir: Path) -> None:
        """Every artefact of this build, including what it would test and what it found.

        The graph alone is half the story. A reviewer picking this up later needs the
        test space it implies and the verdicts it produced, keyed to the same build
        identity, or they cannot tell whether a number came from this policy or the
        last one.
        """
        from metric import reports

        reports.write_build(
            self.result, out_dir, decisions=self.decisions, sections=self._sections()
        )
        _write_json(
            out_dir / reports.SCENARIOS_FILE,
            {**self.space.as_dict(), **self.capabilities, "settings": self.settings.as_dict()},
        )
        if self.plan is not None:
            _write_json(out_dir / reports.PLAN_FILE, self.plan.as_dict())
        if self.accuracy is not None:
            _write_json(out_dir / "accuracy.json", self.accuracy.as_dict())
        if self.evaluations:
            _write_json(
                out_dir / reports.EVALUATIONS_FILE,
                {"evaluations": [e.as_dict() for e in self.evaluations]},
            )

    def _sections(self) -> list[str]:
        """What the graph implies and what it found, appended to the build report."""
        space = self.space
        caps = self.capabilities["capabilities"]
        lines = [*self._accuracy_section(), 
            "## Test space",
            "",
            f"{len(space.scenarios)} bases across {len(space.families)} families, generated "
            f"from the capabilities this graph exposes: "
            f"{', '.join(caps['present']) or 'none'}.",
            "",
            "| category | bases |",
            "|---|---|",
            *(f"| {name} | {count} |" for name, count in space.coverage.items()),
            "",
        ]
        lines += [f"- not admissible: {reason}" for reason in space.inadmissible]
        if space.rejected:
            lines.append(
                f"- **{len(space.rejected)} bases failed answer recovery** and were "
                "quarantined rather than admitted"
            )
        if space.truncated:
            lines.append("**Enumeration was truncated** — this is a prefix of the space.")
        if space.uncovered:
            lines.append(f"{len(space.uncovered)} decision branches remain uncovered.")
        if space.unreachable:
            lines.append(f"{len(space.unreachable)} states are unreachable from any entry.")

        if self.plan is not None:
            design = self.plan
            lines += [
                "",
                f"{len(design.variants)} runs once enrichment is applied ({design.arrangement}), "
                f"covering {design.pairs_covered} of {design.pairs_total} pairs any base "
                "could exercise" + ("." if design.complete else " — **incomplete**."),
            ]
            lines += [f"- {note}" for note in (*design.notes, *design.excluded)]

        if not self.evaluations:
            return ["\n".join(lines)]

        lines += [
            "",
            "## Evaluations",
            "",
            "| trace | pass | fail | undecided | bound |",
            "|---|---|---|---|---|",
        ]
        for evaluation in self.evaluations:
            counts = Counter(v.outcome for v in evaluation.verdicts)
            lines.append(
                f"| {evaluation.contract.binding} | {counts.get('pass', 0)} | "
                f"{counts.get('fail', 0)} | {counts.get('undecided', 0)} | "
                f"{evaluation.binding_coverage:.0%} |"
            )
        return ["\n".join(lines)]

    def _accuracy_section(self) -> list[str]:
        """How right the graph is, first, because everything below assumes it."""
        found = self.accuracy
        if found is None:
            return [
                "## Accuracy",
                "",
                "No annotation is configured, so **nothing checks whether this graph matches "
                "the source**. Every figure below describes a graph that has not been "
                "verified against the document it came from.",
                "",
            ]

        strict, relaxed, high = found.overall, found.relaxed, found.high_materiality
        lines = [
            "## Accuracy",
            "",
            f"Against {found.annotation.annotator}"
            + ("" if found.annotation.independent else " — **not independent**")
            + ".",
            "",
            "| scored | precision | recall | over |",
            "|---|---|---|---|",
            f"| strict | {strict.precision:.0%} {strict.precision_interval} | "
            f"{strict.recall:.0%} {strict.recall_interval} | {strict.actual} facts |",
            f"| relaxed | {relaxed.precision:.0%} | {relaxed.recall:.0%} | — |",
            f"| high materiality | {high.precision:.0%} | {high.recall:.0%} | "
            f"{high.actual} facts |",
            "",
        ]
        lines += [f"- **under gate**: {failure}" for failure in found.failures]
        if found.invented or found.missed:
            lines.append(
                f"- {len(found.invented)} invented, {len(found.missed)} missed, "
                f"{len(found.naming)} named differently — see `accuracy.json`"
            )
        if not found.annotation.independent:
            lines.append(
                "- this measurement cannot clear a build: the annotator saw the prompts"
            )
        return ["\n".join([*lines, ""])]

    def contract_for(self, scenario_id: str) -> Contract | None:
        scenario = next((s for s in self.space.scenarios if s.id == scenario_id), None)
        if scenario is None:
            return None
        return resolve_for_scenario(
            self.graph, self.schema, scenario, identity=self.identity, compiled=self.compiled
        )

    def answer(self, question_id: str, answer: str) -> None:
        """Record one decision and rebuild, so its effect is visible immediately."""
        self.answer_many([(question_id, answer)])

    def answer_many(self, answers: Sequence[tuple[str, str]]) -> None:
        """Record several decisions, then rebuild once."""
        questions = {q.id: q for q in self.result.questions}
        for question_id, answer in answers:
            if answer not in ANSWERS or not answer:
                raise ValueError(f"{answer!r} is not one of: {', '.join(a for a in ANSWERS if a)}")
            question = questions.get(question_id)
            if question is None:
                raise KeyError(f"no open question {question_id}")
            self.decisions[question_id] = Decision(
                question_id=question_id,
                evidence_key=evidence_key(question),
                answer=answer,
            )
        write(self.questions_path, self.result.questions, decisions=self.decisions)
        self.build()

    def _gateway(self) -> Gateway:
        """The model transport, chosen by settings rather than by the call site."""
        return build_gateway(
            self.settings.llm,
            cache_path=self.spec.cache_path,
            fixture_path=self.spec.fixture_path,
            replay=self.spec.replay,
            use_case=self.spec.use_case,
        )
