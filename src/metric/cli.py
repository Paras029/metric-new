"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from metric import reports, review
from metric.llm.cache import ResponseCache
from metric.llm.gateway import AnthropicGateway, Gateway, ModelConfig, ReplayGateway
from metric.ontology.schema import SchemaError, load_schema
from metric.pipeline import DocumentSpec, ingest

DEFAULT_CACHE = Path(".metric/llm-cache")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (SchemaError, FileNotFoundError, ValueError) as exc:
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
    ingest_cmd.set_defaults(run=_run_ingest)

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

    result = ingest(specs, schema=schema, gateway=gateway)
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
