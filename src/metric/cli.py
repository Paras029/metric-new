"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import yaml

from metric import reports, review
from metric.evaluate.model import Evaluation
from metric.llm.cache import ResponseCache
from metric.llm.gateway import AnthropicGateway, Gateway, ModelConfig, ReplayGateway
from metric.ontology.schema import SchemaError, load_schema
from metric.pipeline import DocumentSpec, ingest
from metric.telemetry.profile import ProfileError, load_profile
from metric.workspace import BuildSpec, Workspace

DEFAULT_CACHE = Path(".metric/llm-cache")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (SchemaError, ProfileError, FileNotFoundError, ValueError) as exc:
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
    ingest_cmd.add_argument("--model", default=ModelConfig().model)
    ingest_cmd.add_argument("--effort", default=ModelConfig().effort)
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

    plan_cmd = sub.add_parser("plan", help="show the variants each scenario would be run under")
    plan_cmd.add_argument("--corpus", type=Path, default=Path("corpus.yaml"))
    plan_cmd.add_argument("--out", type=Path, default=Path("build"))
    plan_cmd.set_defaults(run=_run_plan)

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

    scenarios = len(space.space.scenarios)
    each = len(design.variants) // max(1, scenarios)
    print(f"{scenarios} scenarios x {each} = {len(design.variants)} runs")
    print(
        f"  pairwise coverage {design.pairs_covered}/{design.pairs_total}"
        + ("" if design.complete else "  INCOMPLETE")
    )
    for note in design.excluded:
        print(f"  excluded: {note}")
    adverse = [v for v in design.variants if v.reason == "adverse"]
    print(f"  {len(adverse)} adverse runs (scenarios whose contract can block)")
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


def _gateway(args: argparse.Namespace) -> Gateway:
    config = ModelConfig(model=args.model, effort=args.effort)
    cache = ResponseCache(root=args.cache)
    if args.replay:
        return ReplayGateway(cache, config=config)
    return AnthropicGateway(config=config, cache=cache)


if __name__ == "__main__":
    raise SystemExit(main())
