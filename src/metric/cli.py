"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import yaml

from metric import reports, review
from metric.evaluate.model import Evaluation
from metric.llm.gateway import Gateway
from metric.llm.select import build_gateway
from metric.ontology.schema import SchemaError, load_schema
from metric.pipeline import DocumentSpec, ingest
from metric.run.agents import FLAWS
from metric.settings import Settings, SettingsError, load_settings
from metric.telemetry.profile import ProfileError, load_profile
from metric.workspace import BuildSpec, Workspace

DEFAULT_CACHE = Path(".metric/llm-cache")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (SchemaError, ProfileError, SettingsError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="metric", description=__doc__)
    sub = parser.add_subparsers(required=True)

    schema_cmd = sub.add_parser("schema", help="validate the ontology and print a summary")
    _add_schema_args(schema_cmd)
    schema_cmd.set_defaults(run=_run_schema)

    ingest_cmd = sub.add_parser("ingest", help="build a graph from documents")
    _add_schema_args(ingest_cmd)
    ingest_cmd.add_argument("documents", nargs="*", type=Path, help="document paths")
    ingest_cmd.add_argument(
        "--corpus",
        type=Path,
        help="YAML listing documents with policy_version and effective_date",
    )
    ingest_cmd.add_argument("--out", type=Path, default=Path("build"), help="output directory")
    ingest_cmd.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="response cache")
    ingest_cmd.add_argument(
        "--replay",
        action="store_true",
        help="serve every model call from the cache; a miss is an error",
    )
    ingest_cmd.add_argument("--settings", type=Path, help="settings file (default metric.yaml)")
    ingest_cmd.add_argument("--model", help="override llm.model for this run")
    ingest_cmd.add_argument("--effort", help="override llm.effort for this run")
    ingest_cmd.add_argument("--provider", help="override llm.provider for this run")
    ingest_cmd.add_argument("--profile", type=Path, help="telemetry profile for this use case")
    ingest_cmd.add_argument(
        "--fixture", type=Path, help="recorded extraction to build from instead of calling a model"
    )
    ingest_cmd.set_defaults(run=_run_ingest)

    ui_cmd = sub.add_parser("ui", help="browse the build, review it and grade traces")
    ui_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    ui_cmd.add_argument("--out", type=Path, default=Path("build"))
    ui_cmd.add_argument("--host", default="127.0.0.1")
    ui_cmd.add_argument("--port", type=int, default=8765)
    ui_cmd.set_defaults(run=_run_ui)

    eval_cmd = sub.add_parser("evaluate", help="grade traces against the policy graph")
    eval_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    eval_cmd.add_argument("--out", type=Path, default=Path("build"))
    eval_cmd.add_argument(
        "--turns", action="store_true", help="show what the graph required at each turn"
    )
    eval_cmd.set_defaults(run=_run_evaluate)

    plan_cmd = sub.add_parser("plan", help="show the variants each base would be run under")
    plan_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    plan_cmd.add_argument("--out", type=Path, default=Path("build"))
    plan_cmd.set_defaults(run=_run_plan)

    bases_cmd = sub.add_parser(
        "bases", help="what this graph can be asked, and what was generated from it"
    )
    bases_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    bases_cmd.add_argument("--out", type=Path, default=Path("build"))
    bases_cmd.add_argument("--category", help="show the bases of one category in full")
    bases_cmd.set_defaults(run=_run_bases)

    run_cmd = sub.add_parser(
        "run", help="run the plan against an agent and grade every run"
    )
    run_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    run_cmd.add_argument("--out", type=Path, default=Path("build"))
    run_cmd.add_argument(
        "--agent",
        default="reference",
        help="`reference` walks the graph itself; anything else needs an adapter",
    )
    run_cmd.add_argument(
        "--flaw",
        action="append",
        default=[],
        help=f"inject a defect into the reference agent: {', '.join(FLAWS)}",
    )
    run_cmd.add_argument(
        "--flaw-when",
        action="append",
        default=[],
        metavar="LEVEL=FLAW",
        help=(
            "inject a defect only under one factor level, e.g. heavy_noise=skip_wording. "
            "This is how to check the attribution layer end to end: the cohort should "
            "recover that level and no other"
        ),
    )
    run_cmd.add_argument(
        "--materialise", default="voice", help="how a chosen level becomes text"
    )
    run_cmd.add_argument("--limit", type=int, default=0, help="run only the first N variants")
    run_cmd.add_argument(
        "--results", type=Path, help="where to write the cohort, ready for `metric attribute`"
    )
    run_cmd.set_defaults(run=_run_run)

    attribute_cmd = sub.add_parser(
        "attribute", help="which factor level made the agent fail, across a cohort of runs"
    )
    attribute_cmd.add_argument("results", type=Path, help="JSON list of run outcomes")
    attribute_cmd.add_argument(
        "--min-cell", type=int, default=5, help="runs needed either side of a comparison"
    )
    attribute_cmd.add_argument(
        "--marginal-only",
        action="store_true",
        help="skip the adjusted model; marginal comparisons cannot separate confounded factors",
    )
    attribute_cmd.set_defaults(run=_run_attribute)

    settings_cmd = sub.add_parser("settings", help="print the settings a build would use")
    settings_cmd.add_argument("--settings", type=Path, help="settings file (default metric.yaml)")
    settings_cmd.set_defaults(run=_run_settings)

    discover_cmd = sub.add_parser(
        "discover", help="draft a telemetry profile and an observed structure from traces"
    )
    discover_cmd.add_argument("traces", nargs="+", type=Path)
    discover_cmd.add_argument("--name", required=True, help="short name for the files written")
    discover_cmd.add_argument("--use-case", required=True, help="what this agent is called")
    discover_cmd.add_argument("--profile-out", type=Path, help="where to write the profile")
    discover_cmd.add_argument("--observed-out", type=Path, help="where to write the structure")
    discover_cmd.set_defaults(run=_run_discover)

    return parser


def _add_schema_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--schema", type=Path, default=Path("schemas/core.ontology.yaml"), help="core ontology"
    )
    parser.add_argument("--extend", type=Path, help="use-case ontology extending core")


def _run_schema(args: argparse.Namespace) -> int:
    schema = load_schema(args.schema, args.extend)
    print(f"{schema.name} v{schema.version}")
    print(f"  {len(schema.structural_types)} structural types, {len(schema.domain_types)} domain")
    print(f"  {len(schema.relations)} relations")
    high = sorted(n for n, s in schema.relations.items() if s.materiality == "high")
    print(f"  {len(high)} high-materiality: {', '.join(high)}")
    return 0


def _run_ingest(args: argparse.Namespace) -> int:
    schema = load_schema(args.schema, args.extend)
    specs = _specs(args)
    if not specs:
        raise ValueError("no documents given; pass paths or --corpus")

    gateway = _gateway(args)
    decisions = review.read(args.out / reports.QUESTIONS_FILE)
    profile = load_profile(args.profile) if args.profile else None

    answers = {q: d.answer for q, d in decisions.items() if d.answered}
    result = ingest(
        specs, schema=schema, gateway=gateway, decisions=answers, profile=profile
    )
    reports.write_build(result, args.out, decisions=decisions)

    open_questions = review.outstanding(result.questions, decisions)
    print(f"build {result.manifest.identity.digest} -> {args.out}")
    print(
        f"  {len(result.graph.admitted)} admitted, "
        f"{len(result.rejections)} quarantined, "
        f"{len(open_questions)} questions open"
    )
    if result.coverage.silent:
        print(f"  {len(result.coverage.silent)} batches silent — see {reports.REPORT_FILE}")
    return 0


def _run_plan(args: argparse.Namespace) -> int:
    space = _workspace(args)
    design = space.plan
    if design is None:
        raise ValueError(f"{args.corpus} names no factor catalogue, so there is nothing to plan")

    bases = len(space.space.scenarios)
    print(f"{bases} bases -> {len(design.variants)} runs, {design.arrangement}")
    print(
        f"  pairwise coverage {design.pairs_covered}/{design.pairs_total} of the pairs "
        "any base could exercise" + ("" if design.complete else "  INCOMPLETE")
    )
    for note in (*design.notes, *design.excluded):
        print(f"  {note}")
    adverse = [v for v in design.variants if v.reason == "adverse"]
    print(f"  {len(adverse)} adverse runs (bases whose contract can block)")

    if design.dropped:
        by_factor: Counter[str] = Counter()
        for factors in design.dropped.values():
            by_factor.update(factors)
        print("  not relevant, so not crossed in:")
        for factor, count in sorted(by_factor.items()):
            print(f"    {factor}: dropped from {count} of {bases} bases")
    return 0


def _run_bases(args: argparse.Namespace) -> int:
    """What the graph can be asked, before and after generating from it."""
    space = _workspace(args)
    found = space.space
    caps = space.capabilities["capabilities"]

    print(f"capabilities: {', '.join(caps['present']) or 'none'}")
    if caps["absent"]:
        print(f"  absent: {', '.join(caps['absent'])}")
    print(f"  closed world: {caps['closed_world']}")

    print(f"\n{len(found.scenarios)} bases across {len(found.families)} families")
    for category, count in found.coverage.items():
        print(f"  {count:4}  {category}")
    for reason in found.inadmissible:
        print(f"     -  {reason}")

    if found.rejected:
        print(f"\n{len(found.rejected)} failed answer recovery and were quarantined:")
        for base in found.rejected[:10]:
            print(f"  {base.category}: {base.check_note}")

    if args.category:
        print(f"\n{args.category}:")
        for base in found.of_category(args.category):
            print(f"  {base.question}")
    return 0


def _run_run(args: argparse.Namespace) -> int:
    """Run the plan and grade it. The one command that closes plan -> attribute."""
    from metric import enrich  # noqa: F401  - registers the shipped materialisers
    from metric.run.agents import GraphAgent
    from metric.run.simulate import Settings as RunSettings
    from metric.run.simulate import simulate_plan

    space = _workspace(args)
    if space.plan is None:
        raise ValueError(f"{args.corpus} names no factor catalogue, so there is nothing to run")

    unknown = sorted(set(args.flaw) - set(FLAWS))
    if unknown:
        raise ValueError(f"unknown flaws {unknown}; the reference agent has {list(FLAWS)}")
    if args.agent != "reference":
        raise ValueError(
            f"no adapter for agent {args.agent!r}. Implement the `Agent` protocol in "
            "metric.run.model and pass it to simulate_plan; `reference` is a fixture that "
            "walks the graph and cannot tell you anything about a real agent"
        )

    conditional = dict(_pair(entry) for entry in args.flaw_when)
    unknown_conditional = sorted(set(conditional.values()) - set(FLAWS))
    if unknown_conditional:
        raise ValueError(
            f"unknown flaws {unknown_conditional}; the reference agent has {list(FLAWS)}"
        )

    agent = GraphAgent(space.graph, flaws=tuple(args.flaw))
    factory = (
        (lambda base, levels: GraphAgent(space.graph, flaws=conditional, levels=levels))
        if conditional
        else None
    )

    cohort = simulate_plan(
        space.space.scenarios,
        space.plan,
        agent,
        agents=factory,
        graph=space.graph,
        schema=space.schema,
        identity_digest=space.identity,
        compiled=space.compiled,
        settings=RunSettings(
            checkpoint_variable=space.checkpoint_variable or "checkpoint",
            materialiser=args.materialise,
        ),
        limit=args.limit,
    )

    passed = sum(1 for r in cohort.gradable if r.passed)
    print(f"{agent.identity}")
    print(
        f"  {len(cohort.runs)} runs, {len(cohort.gradable)} gradable, "
        f"{passed} passed, {len(cohort.gradable) - passed} failed"
    )
    for note in cohort.notes:
        print(f"  note: {note}")

    # An assertion kind where there is one, otherwise the first turn finding: the run
    # failed for a reason either way, and the two routes read the same in a tally.
    worst: Counter[str] = Counter()
    for run in cohort.gradable:
        if run.passed:
            continue
        reasons = [str(v.assertion.kind) for v in run.evaluation.failures]
        worst.update(reasons or list(run.findings[:1]))
    for kind, count in worst.most_common(5):
        print(f"  {count:4}  {kind[:70]}")

    results = args.results or args.out / "runs.json"
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        json.dumps(
            [
                {
                    "variant": o.variant,
                    "scenario": o.scenario,
                    "levels": dict(o.levels),
                    "passed": o.passed,
                }
                for o in cohort.outcomes()
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {results} — pass it to `metric attribute`")
    return 0


def _pair(entry: str) -> tuple[str, str]:
    level, _, flaw = entry.partition("=")
    if not level or not flaw:
        raise ValueError(f"--flaw-when takes LEVEL=FLAW, not {entry!r}")
    return level, flaw


def _run_attribute(args: argparse.Namespace) -> int:
    """Which level made the agent fail, across a cohort someone actually ran."""
    from metric.attribution import Outcome, attribute
    from metric.regression import adjust

    with args.results.open(encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError(f"{args.results} must hold a JSON list of run outcomes")

    outcomes = [
        Outcome(
            variant=str(r.get("variant", "")),
            scenario=str(r.get("scenario", "")),
            levels=tuple((str(k), str(v)) for k, v in sorted((r.get("levels") or {}).items())),
            passed=bool(r["passed"]),
        )
        for r in records
    ]

    found = attribute(outcomes, min_cell=args.min_cell)
    print(
        f"{found.overall.passed}/{found.overall.total} passed "
        f"({found.overall.value:.0%}, 95% {found.overall.interval})"
    )

    print("\nmarginal — each level against every other level of its factor")
    if not found.significant:
        print("  nothing survives correction for multiplicity")
    for effect in found.significant:
        print(
            f"  {effect.factor}={effect.level} {effect.direction}: "
            f"{effect.rate.value:.0%} vs {effect.baseline.value:.0%}, "
            f"odds ratio {effect.odds_ratio:.2f} {effect.odds_interval}, q={effect.q_value:.3f}"
        )
    for note in found.notes:
        print(f"  note: {note}")

    if args.marginal_only:
        return 0

    model = adjust(outcomes, min_cell=args.min_cell)
    print("\nadjusted — each level with the other factors held fixed")
    print(f"  pseudo-R2 {model.pseudo_r2:.3f} over {model.runs} runs, ridge {model.ridge}")
    if not model.significant:
        print("  nothing survives once the other factors are accounted for")
    for coefficient in model.significant:
        print(
            f"  {coefficient.factor}={coefficient.level} {coefficient.direction} "
            f"(vs {coefficient.reference}): odds ratio {coefficient.odds_ratio:.3f} "
            f"{coefficient.odds_interval}, q={coefficient.q_value:.4f}"
        )
    for note in model.notes:
        print(f"  note: {note}")

    lost = {(e.factor, e.level) for e in found.significant} - {
        (c.factor, c.level) for c in model.significant
    }
    if lost:
        print(
            "\n  "
            + ", ".join(f"{f}={level}" for f, level in sorted(lost))
            + " looked significant marginally and does not survive adjustment — a pairwise "
            "design does not balance every factor within every other's levels, so a level "
            "can inherit the failures of the one it was paired with"
        )
    return 0


def _run_settings(args: argparse.Namespace) -> int:
    settings = _settings(args)
    print(f"settings digest {settings.digest}")
    print(yaml.safe_dump(settings.as_dict(), sort_keys=True, default_flow_style=False).rstrip())
    return 0


def _run_discover(args: argparse.Namespace) -> int:
    from metric.discover.emit import observation_yaml, profile_yaml
    from metric.discover.observe import observe
    from metric.trace.galileo import read_galileo_export

    found = observe([read_galileo_export(path) for path in args.traces])
    profile_out = args.profile_out or Path(f"profiles/{args.name}.telemetry.yaml")
    observed_out = args.observed_out or Path(f"observed/{args.name}.observed.yaml")

    for path, text in (
        (profile_out, profile_yaml(found, name=args.name, use_case=args.use_case)),
        (observed_out, observation_yaml(found, name=args.name, use_case=args.use_case)),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")

    checkpoint = found.checkpoint_variable()
    print(
        f"  {len(found.tools)} tools, {len(found.outcomes)} outcomes, "
        f"{len(found.capabilities)} capabilities, "
        f"{len(found.states(checkpoint))} states from `{checkpoint or 'no checkpoint variable'}`"
    )
    others = [c for c in found.checkpoint_candidates if c != checkpoint]
    if others:
        print(f"  other checkpoint candidates: {', '.join(others)}")
    print("  these describe the agent, not policy — nothing here can fail it")
    return 0


def _run_ui(args: argparse.Namespace) -> int:
    from metric.ui.server import serve

    serve(_workspace(args), host=args.host, port=args.port)
    return 0


def _run_evaluate(args: argparse.Namespace) -> int:
    space = _workspace(args)
    if not space.evaluations:
        raise ValueError(f"{args.corpus} lists no traces to evaluate")

    space.write(args.out)
    for evaluation in space.evaluations:
        counts = Counter(v.outcome for v in evaluation.verdicts)
        print(f"{evaluation.contract.binding}")
        print(
            f"  {counts.get('pass', 0)} pass, {counts.get('fail', 0)} fail, "
            f"{counts.get('undecided', 0)} undecided, "
            f"{counts.get('not_applicable', 0)} not applicable "
            f"({evaluation.binding_coverage:.0%} of observations bound)"
        )
        for verdict in evaluation.failures:
            print(
                f"  FAIL [{verdict.assertion.severity}] "
                f"{verdict.assertion.kind}: {verdict.detail}"
            )
        print(
            f"  {evaluation.certain} of {len(evaluation.turns)} turns placed by the agent "
            f"itself, {evaluation.placed} placed at all"
        )
        if evaluation.unbound:
            print(f"  unbound: {', '.join(evaluation.unbound)}")
        if getattr(args, "turns", False):
            _print_turns(space, evaluation)
    return 0


def _print_turns(space: Workspace, evaluation: Evaluation) -> None:
    label = space.graph.label
    for truth in evaluation.turns:
        binding = truth.binding
        where = " -> ".join(label(s) for s in binding.states) or "(unplaced)"
        print(f"    turn {truth.turn} [{binding.method} {binding.confidence:.2f}] {where}")
        if truth.expected.tools or truth.observed.tools:
            print(
                f"      expects {', '.join(label(t) for t in truth.expected.tools) or '-'}"
                f"  |  did {', '.join(label(t) for t in truth.observed.tools) or '-'}"
            )
        for finding in truth.findings:
            print(f"      ! {finding}")


def _workspace(args: argparse.Namespace) -> Workspace:
    if not args.corpus.exists():
        raise FileNotFoundError(f"{args.corpus} does not exist")
    return Workspace(BuildSpec.from_corpus(args.corpus, out_dir=args.out))


def _specs(args: argparse.Namespace) -> list[DocumentSpec]:
    specs = [DocumentSpec(path=path) for path in args.documents]
    if args.corpus is None:
        return specs

    with args.corpus.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    root = args.corpus.parent
    for entry in document.get("documents") or ():
        specs.append(
            DocumentSpec(
                path=root / str(entry["path"]),
                policy_version=str(entry.get("policy_version", "")),
                effective_date=str(entry.get("effective_date", "")),
            )
        )
    return specs


def _settings(args: argparse.Namespace) -> Settings:
    """Settings from the named file, then whatever the flags overrode."""
    from dataclasses import replace

    path = getattr(args, "settings", None) or (
        Path("metric.yaml") if Path("metric.yaml").exists() else None
    )
    settings = load_settings(path)
    overrides = {
        key: getattr(args, key)
        for key in ("model", "effort", "provider")
        if getattr(args, key, None)
    }
    if not overrides:
        return settings
    return replace(settings, llm=replace(settings.llm, **overrides))


def _gateway(args: argparse.Namespace) -> Gateway:
    return build_gateway(
        _settings(args).llm, cache_path=args.cache, fixture_path=None, replay=args.replay
    )


if __name__ == "__main__":
    raise SystemExit(main())
