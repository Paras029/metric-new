"""Composing the base space: capability, then taxonomy, then generation, then the check.

The order is the argument.

1. **Read the graph's capabilities.** What kinds of fact does it actually hold?
2. **Admit the categories those capabilities support**, and report the rest with the
   capability each is missing. A policy stating no prohibitions generates no prohibition
   material and says why, rather than reporting a category at zero.
3. **Generate**, one generator per admitted category.
4. **Check every base by recovering its answer a second way**, from the raw triples.
   Bases that fail are quarantined with the disagreement, not dropped.

Three sources of bases, as the book has it, and everything downstream treats them
identically: mined from the graph, taken from a seed file of hand-labelled cases, or
supplied outright as a situation with its own answer. The third is what lets a team
harden a set of real cases before there is any policy corpus at all.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from metric.graph.journey import Journey
from metric.graph.model import Graph
from metric.ontology.ids import assertion_id
from metric.scenario.bases import DEFAULT_PER_CATEGORY, generate, verify
from metric.scenario.capability import Capabilities, capabilities
from metric.scenario.model import Scenario, ScenarioSpace
from metric.scenario.paths import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PATHS, enumerate_scenarios
from metric.scenario.taxonomy import BY_NAME, admissible, unknown_categories


class SeedError(Exception):
    """Raised when a seed file of supplied bases is malformed."""


def build_space(
    graph: Graph,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_paths: int = DEFAULT_MAX_PATHS,
    default_revisits: int = 3,
    reach_for_uncovered: bool = True,
    per_category: int = DEFAULT_PER_CATEGORY,
    categories: tuple[str, ...] = (),
    seeds: Iterable[Scenario] = (),
) -> ScenarioSpace:
    """Every base this graph supports, checked, with what it could not support."""
    journey = Journey(graph, default_revisits=default_revisits)
    caps = capabilities(graph)
    notes: list[str] = []

    unknown = unknown_categories(categories)
    if unknown:
        notes.append(
            f"settings name categories the taxonomy does not define: {', '.join(unknown)}"
        )
    admissibility = admissible(caps, only=categories)
    notes.extend(admissibility.reasons)

    admitted: list[Scenario] = []
    rejected: list[Scenario] = []
    truncated = False
    uncovered: tuple[tuple[str, str, str], ...] = ()
    unreachable: tuple[str, ...] = ()

    for category in admissibility.admitted:
        if category.name == "journey_path":
            paths = enumerate_scenarios(
                graph,
                max_depth=max_depth,
                max_paths=max_paths,
                journey=journey,
                reach_for_uncovered=reach_for_uncovered,
            )
            produced: tuple[Scenario, ...] = paths.scenarios
            truncated, uncovered, unreachable = paths.truncated, paths.uncovered, paths.unreachable
            notes.extend(paths.notes)
        else:
            produced = generate(graph, journey, caps, category.name, limit=per_category)

        for base in produced:
            checked = verify(graph, base)
            (admitted if checked.checked else rejected).append(checked)

    for seed in seeds:
        admitted.append(verify(graph, seed) if seed.category in BY_NAME else seed)

    if rejected:
        notes.append(
            f"{len(rejected)} generated bases did not survive answer recovery and were "
            "quarantined; see `rejected` for the disagreement in each"
        )
    if not caps.closed_world and "tool_absence" in admissibility.names:
        notes.append(
            "some states declare no tools, so `tool_absence` generated nothing — "
            "an undeclared tool cannot be told apart from a gap in the corpus"
        )

    return ScenarioSpace(
        scenarios=tuple(admitted),
        truncated=truncated,
        uncovered=uncovered,
        unreachable=unreachable,
        notes=tuple(notes),
        rejected=tuple(rejected),
        coverage=_coverage(admitted, admissibility.names),
        inadmissible=admissibility.reasons,
    )


def _coverage(scenarios: list[Scenario], admitted: tuple[str, ...]) -> dict[str, int]:
    """Counts per admitted category, including the zeros.

    A category that was admissible and produced nothing is the interesting case — the
    graph had the capability and no instance of it — and it disappears from a report
    that only counts what exists.
    """
    counts = dict.fromkeys(admitted, 0)
    for scenario in scenarios:
        counts[scenario.category] = counts.get(scenario.category, 0) + 1
    return counts


def load_seeds(path: Path) -> tuple[Scenario, ...]:
    """Bases supplied by hand: a situation, its answer, and what it is about.

    The book's second and third sources. A supplied answer *is* the ground truth — it is
    checked against the graph where the category allows, and kept either way with the
    disagreement recorded, because the point of a seed case is often that it is a real
    one the graph has not caught up with.
    """
    with path.open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    if not isinstance(document, dict):
        raise SeedError(f"{path} does not contain a YAML mapping")

    found: list[Scenario] = []
    for index, raw in enumerate(document.get("bases") or ()):
        if not isinstance(raw, dict):
            raise SeedError(f"{path}: every base must be a mapping")
        found.append(_seed(raw, path, index))
    return tuple(found)


def _seed(raw: dict[str, Any], path: Path, index: int) -> Scenario:
    try:
        question = str(raw["question"])
        answer = tuple(str(a) for a in raw["answer"])
    except KeyError as exc:
        raise SeedError(f"{path}: base {index} is missing {exc.args[0]!r}") from exc

    category = str(raw.get("category", "supplied"))
    definition = BY_NAME.get(category)
    subject = tuple(str(s) for s in raw.get("subject") or ())

    return Scenario(
        id=str(raw.get("id") or assertion_id("seed", category, question)),
        category=category,
        family=definition.family if definition else "supplied",
        answer_type=definition.answer_type if definition else str(raw.get("answer_type", "text")),
        question=question,
        answer=answer,
        subject=subject,
        origin="seed",
        checked=False,
        check_note="supplied by hand; the answer was not recovered from the graph",
    )


def describe(graph: Graph) -> dict[str, Any]:
    """What this graph can be asked, before anything is generated from it."""
    caps: Capabilities = capabilities(graph)
    return {"capabilities": caps.as_dict(), "taxonomy": admissible(caps).as_dict()}
