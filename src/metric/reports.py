"""Build outputs: the graph, what was thrown away, and what is still open.

Three files, not one. A pipeline that emits only a graph is reporting its successes
and hiding its judgement; the quarantine and the question queue are what make the
graph readable as a claim rather than an assertion.

The report is written for someone deciding whether to trust this build, so it leads
with what went wrong: silent batches first, then rejections by criterion, then the
counts.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from metric import review
from metric.ontology.types import Question
from metric.pipeline import BuildResult
from metric.review import Decision

GRAPH_FILE = "graph.json"
QUARANTINE_FILE = "quarantine.json"
QUESTIONS_FILE = "questions.yaml"
MANIFEST_FILE = "manifest.json"
REPORT_FILE = "report.md"


def write_build(
    result: BuildResult,
    out_dir: Path,
    *,
    decisions: Mapping[str, Decision] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions = decisions or {}

    result.graph.write(out_dir / GRAPH_FILE)
    result.manifest.write(out_dir / MANIFEST_FILE)
    review.write(out_dir / QUESTIONS_FILE, result.questions, decisions=decisions)

    (out_dir / QUARANTINE_FILE).write_text(
        json.dumps(
            [rejection.as_dict() for rejection in result.rejections],
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / REPORT_FILE).write_text(render(result, decisions=decisions), encoding="utf-8")


def render(result: BuildResult, *, decisions: Mapping[str, Decision] | None = None) -> str:
    decisions = decisions or {}
    identity = result.manifest.identity
    open_questions = review.outstanding(result.questions, decisions)

    lines = [
        f"# Build {identity.digest}",
        "",
        "| | |",
        "|---|---|",
        f"| corpus | `{identity.corpus}` ({len(result.manifest.documents)} documents) |",
        f"| schema | {identity.schema} |",
        f"| prompts | `{identity.prompts}` |",
        f"| model | {identity.model} |",
        f"| code | {identity.code} |",
        "",
    ]

    lines += _coverage(result)
    lines += _quarantine(result)
    lines += _graph(result)
    lines += _questions(result, open_questions)
    lines += _glossary(result)
    return "\n".join(lines).rstrip() + "\n"


def _coverage(result: BuildResult) -> list[str]:
    coverage = result.coverage
    lines = [
        "## Coverage",
        "",
        f"- {coverage.batches} batches read",
        f"- {coverage.non_normative} reported as non-normative",
        f"- {coverage.rereads} re-read after returning nothing",
    ]
    if coverage.silent:
        lines += [
            f"- **{len(coverage.silent)} still silent after a second read** — these sections",
            "  produced no facts and did not claim to contain none. Read them by hand:",
            *(f"  - `{batch_id}`" for batch_id in coverage.silent),
        ]
    else:
        lines.append("- no silent batches")
    return [*lines, ""]


def _quarantine(result: BuildResult) -> list[str]:
    if not result.rejections:
        return ["## Quarantine", "", "Nothing was rejected.", ""]

    counts = Counter(rejection.criterion for rejection in result.rejections)
    lines = ["## Quarantine", "", "| criterion | rejected |", "|---|---|"]
    lines += [f"| {criterion} | {count} |" for criterion, count in sorted(counts.items())]
    lines += ["", f"Full detail in `{QUARANTINE_FILE}`.", ""]
    return lines


def _graph(result: BuildResult) -> list[str]:
    statuses = Counter(triple.status for triple in result.graph.triples)
    relations = Counter(triple.relation for triple in result.graph.admitted)

    lines = [
        "## Graph",
        "",
        f"{len(result.graph.entities)} entities, {len(result.graph.triples)} triples.",
        "",
        "| status | triples |",
        "|---|---|",
    ]
    lines += [f"| {status} | {count} |" for status, count in sorted(statuses.items())]
    lines += ["", "| relation | admitted |", "|---|---|"]
    lines += [
        f"| {relation} | {count} |"
        for relation, count in sorted(relations.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return [*lines, ""]


def _questions(result: BuildResult, open_questions: list[Question]) -> list[str]:
    if not result.questions:
        return ["## Questions", "", "Nothing was left open.", ""]

    counts = Counter(question.kind for question in result.questions)
    lines = [
        "## Questions",
        "",
        f"{len(open_questions)} of {len(result.questions)} awaiting an answer "
        f"in `{QUESTIONS_FILE}`.",
        "",
        "| kind | raised |",
        "|---|---|",
    ]
    lines += [f"| {kind} | {count} |" for kind, count in sorted(counts.items())]
    return [*lines, ""]


def _glossary(result: BuildResult) -> list[str]:
    contested = result.glossary.contested
    if not contested:
        return []
    lines = [
        "## Contested entity types",
        "",
        "Two sections typed the same surface form differently. Neither was chosen.",
        "",
    ]
    lines += [f"- {entry.render()}" for entry in contested]
    return [*lines, ""]
