"""The pages.

Each one answers a question someone actually has: what did this build produce, what
does the journey look like, what does the graph say and on what evidence, what would
we test, what happened when we graded a real run, and what still needs a person.

Every expectation on every page is one click from the sentence of policy it came from.
That is the whole reason for the provenance machinery underneath, and a UI that shows
verdicts without it would waste it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from html import escape
from urllib.parse import quote as urlquote

from metric.contract.model import Assertion
from metric.evaluate.model import Evaluation
from metric.graph.model import Graph
from metric.ontology.types import Entity, Question, Rejection, Span, Triple
from metric.review import outstanding
from metric.scenario.paths import Scenario
from metric.ui import html, layout
from metric.ui.html import chip, panel, quote, stats, table, tone
from metric.workspace import Workspace


def overview(space: Workspace) -> str:
    result = space.result
    graph = space.graph
    statuses = Counter(t.status for t in graph.triples)
    open_questions = outstanding(result.questions, space.decisions)

    body = [
        "<h1>Build overview</h1>",
        "<p class='lede'>Policy in, an evidence-grounded graph out, then scenarios and "
        "verdicts from the same graph. Every number below is one click from the text it "
        "came from.</p>",
        stats(
            [
                ("entities", len(graph.entities)),
                ("admitted triples", statuses.get("admitted", 0)),
                ("awaiting review", statuses.get("review", 0)),
                ("quarantined", len(result.rejections)),
                ("scenarios", len(space.space.scenarios)),
                ("runs planned", len(space.plan.variants) if space.plan else "—"),
                ("open questions", len(open_questions)),
            ]
        ),
    ]

    identity = result.manifest.identity
    body.append(
        panel(
            "Build identity",
            table(
                ["part", "value"],
                [
                    ["corpus", f"<code>{escape(identity.corpus)}</code>"],
                    ["schema", escape(identity.schema)],
                    ["prompts", f"<code>{escape(identity.prompts)}</code>"],
                    ["model", escape(identity.model)],
                    ["code", escape(identity.code)],
                ],
            )
            + "<p class='lede' style='margin:12px 0 0'>The same tuple must mean the same "
            "graph. A verdict that cannot name the build it came from cannot be reopened "
            "when the policy changes.</p>",
        )
    )

    coverage = result.coverage
    if not result.manifest.documents:
        lines = [
            "<strong>No policy document.</strong> This graph was drafted from telemetry, so "
            "it describes what the agent does rather than what it should do — and nothing in "
            "it can fail that agent. Adding the real operating procedure is what turns it "
            "into ground truth."
        ]
    else:
        lines = [
            f"{coverage.batches} sections read, {coverage.non_normative} reported as carrying "
            f"no facts, {coverage.rereads} read twice after returning nothing."
        ]
    if coverage.silent:
        lines.append(
            f"<strong>{len(coverage.silent)} sections stayed silent</strong> after a second "
            "read — they produced no facts and did not claim to contain none."
        )
    elif result.manifest.documents:
        lines.append("No section was left silently unread.")
    if result.profile_problems:
        lines.append("Telemetry profile: " + "; ".join(escape(p) for p in result.profile_problems))
    body.append(panel("Coverage", "".join(f"<p>{line}</p>" for line in lines)))

    if result.rejections:
        counts = Counter(r.criterion for r in result.rejections)
        body.append(
            panel(
                "Quarantine",
                table(
                    ["criterion", "rejected"],
                    [[escape(k), str(v)] for k, v in sorted(counts.items())],
                ),
            )
        )
    return "".join(body)


def workflow(space: Workspace) -> str:
    return "".join(
        [
            "<h1>Workflow</h1>",
            "<p class='lede'>States and the transitions between them. A dashed outline is an "
            "entry, a heavy one an ending, a dashed curve to the right is a loop back. The "
            "number on a state is how many rules govern it — hover to read them.</p>",
            f"<div class='panel'>{layout.render(space.graph)}</div>",
        ]
    )


def graph_view(space: Workspace, *, relation: str = "", status: str = "") -> str:
    graph = space.graph
    triples = [
        t
        for t in graph.triples
        if (not relation or t.relation == relation) and (not status or t.status == status)
    ]

    relations = sorted({t.relation for t in graph.triples})
    statuses = sorted({t.status for t in graph.triples})
    filters = "".join(
        [
            "<form method='get' class='inline'>",
            _select("relation", relations, relation, "every relation"),
            " ",
            _select("status", statuses, status, "every status"),
            " <button type='submit'>Filter</button> ",
            "<a href='/graph'>reset</a></form>",
        ]
    )

    rows = [
        [
            f"<a href='/entity/{urlquote(t.head)}'>{escape(graph.label(t.head))}</a>",
            f"<code>{escape(t.relation)}</code>",
            escape(graph.label(t.tail))
            if t.tail_kind == "entity"
            else f"<em>{escape(t.tail)}</em>",
            chip(t.status, tone(t.status)),
            " ".join(chip(m) for m in sorted(t.methods)),
            _evidence(space, t.spans),
        ]
        for t in triples[:400]
    ]

    note = ""
    if len(triples) > 400:
        note = f"<p class='lede'>Showing the first 400 of {len(triples)}.</p>"

    return "".join(
        [
            "<h1>Graph</h1>",
            "<p class='lede'>Every fact the build holds, with the words it came from. "
            "<code>review</code> means it rests on a single model reading and can only "
            "advise until somebody confirms it.</p>",
            f"<div class='panel'>{filters}</div>",
            note,
            table(["subject", "relation", "object", "status", "how", "evidence"], rows),
        ]
    )


def _name(entity: Entity) -> str:
    return sorted(entity.surfaces)[0] if entity.surfaces else entity.canonical


def entity_view(space: Workspace, entity_id: str) -> str:
    graph = space.graph
    entity = graph.entity(entity_id)
    if entity is None:
        return "<h1>Not found</h1><p class='lede'>No entity with that id in this build.</p>"

    outgoing = [t for t in graph.triples if t.head == entity_id]
    incoming = [t for t in graph.triples if t.tail == entity_id and t.tail_kind == "entity"]

    def rows(triples: list[Triple], *, other: str) -> list[list[str]]:
        return [
            [
                f"<code>{escape(t.relation)}</code>",
                f"<a href='/entity/{urlquote(getattr(t, other))}'>"
                f"{escape(graph.label(getattr(t, other)))}</a>"
                if t.tail_kind == "entity" or other == "head"
                else f"<em>{escape(t.tail)}</em>",
                chip(t.status, tone(t.status)),
                _evidence(space, t.spans),
            ]
            for t in triples
        ]

    return "".join(
        [
            f"<h1>{escape(_name(entity))}</h1>",
            f"<p class='lede'>{chip(entity.type)} <code>{escape(entity.id)}</code><br>"
            f"Also written: {escape(', '.join(sorted(entity.surfaces)))}</p>",
            panel("Says", table(["relation", "object", "status", "evidence"],
                                rows(outgoing, other="tail"))),
            panel("Referred to by", table(["relation", "subject", "status", "evidence"],
                                          rows(incoming, other="head"))),
        ]
    )


def _path(graph: Graph, scenario: Scenario) -> str:
    labels = [graph.label(scenario.entry)]
    labels += [graph.label(step.next_state) for step in scenario.steps]
    return " → ".join(labels)


def scenarios(space: Workspace) -> str:
    found = space.space
    graph = space.graph

    rows = [
        [
            f"<a href='/scenario/{urlquote(s.id)}'><code>{escape(s.id[:8])}</code></a>",
            chip(s.origin),
            escape(s.category or "—"),
            str(s.length),
            escape(_path(graph, s)),
            chip("ends properly", "pass") if s.complete else chip("no declared ending", "warn"),
        ]
        for s in found.scenarios
    ]

    gaps = []
    if found.truncated:
        gaps.append("<p><strong>Enumeration was truncated.</strong> The scenarios below are "
                    "a prefix of the space, not a cover of it.</p>")
    if found.uncovered:
        gaps.append(f"<p>{len(found.uncovered)} decision branches are still not covered by any "
                    "scenario.</p>")
    if found.unreachable:
        names = ", ".join(escape(graph.label(s)) for s in found.unreachable)
        gaps.append(f"<p>Unreachable from any entry: {names}</p>")
    for note in found.notes:
        gaps.append(f"<p class='lede'>{escape(note)}</p>")
    if not gaps:
        gaps.append("<p>Every declared branch is covered and every state is reachable.</p>")

    return "".join(
        [
            "<h1>Scenarios</h1>",
            "<p class='lede'>Every journey the graph says is possible, plus a focused path "
            "back to any branch the walk missed. Open one to see the contract it would be "
            "tested against.</p>",
            panel("Coverage", "".join(gaps)),
            _variants_panel(space),
            table(["id", "origin", "category", "steps", "path", "ending"], rows),
        ]
    )


def _variants_panel(space: Workspace) -> str:
    design = space.plan
    if design is None:
        return panel(
            "Variants",
            "<p class='lede'>No factor catalogue is configured, so every scenario runs once. "
            "Add <code>factors:</code> to the corpus file to vary how the agent meets each "
            "situation without changing what is required of it.</p>",
        )

    catalogue = space.catalogue
    factors = catalogue.invariant if catalogue else ()
    body = [
        f"<p>{len(design.variants)} runs from {len(space.space.scenarios)} scenarios. "
        f"Pairwise coverage {design.pairs_covered} of {design.pairs_total} level pairs"
        + ("." if design.complete else " — <strong>incomplete</strong>.")
        + "</p>",
        table(
            ["factor", "group", "levels", "hardest"],
            [
                [
                    escape(f.name),
                    chip(f.group),
                    escape(", ".join(f.levels)),
                    escape(f.adverse) or "—",
                ]
                for f in factors
            ],
        ),
    ]
    for note in design.excluded:
        body.append(f"<p class='lede'>{escape(note)}</p>")
    if not any(v.reason == "adverse" for v in design.variants):
        body.append(
            "<p class='lede'>No scenario gets the extra adverse run yet: that is reserved for "
            "scenarios whose contract can actually block, and nothing can until it is "
            "approved in review.</p>"
        )
    return panel("Variants", "".join(body))


def scenario_view(space: Workspace, scenario_id: str) -> str:
    contract = space.contract_for(scenario_id)
    scenario = next((s for s in space.space.scenarios if s.id == scenario_id), None)
    if contract is None or scenario is None:
        return "<h1>Not found</h1><p class='lede'>No scenario with that id in this build.</p>"

    graph = space.graph
    steps = [
        [
            str(index),
            escape(graph.label(step.state)),
            escape(graph.label(step.decision)) if step.decision else "—",
            escape(graph.label(step.outcome)) if step.outcome else "—",
            escape(graph.label(step.next_state)),
        ]
        for index, step in enumerate(scenario.steps, start=1)
    ]

    return "".join(
        [
            f"<h1>Scenario <code>{escape(scenario_id[:8])}</code></h1>",
            f"<p class='lede'>{chip(scenario.origin)} {chip(scenario.category or 'uncategorised')} "
            f"{len(contract.assertions)} assertions resolved from this path.</p>",
            panel("Path", table(["#", "state", "decision", "outcome", "next"], steps)),
            panel("Contract", _assertions(space, contract.assertions)),
            _scenario_variants(space, scenario_id),
        ]
    )


def _scenario_variants(space: Workspace, scenario_id: str) -> str:
    if space.plan is None:
        return ""
    variants = space.plan.for_scenario(scenario_id)
    if not variants:
        return ""
    return panel(
        "Runs",
        "<p class='lede'>Same situation, same contract, different presentation. A failure "
        "under one of these and a pass under another is attributable to the difference.</p>"
        + table(
            ["why", "levels"],
            [[chip(v.reason, "warn" if v.reason == "adverse" else ""), escape(v.summary)]
             for v in variants],
        ),
    )


def evaluations(space: Workspace) -> str:
    if not space.evaluations:
        return (
            "<h1>Evaluations</h1><p class='lede'>No traces are configured. Add them under "
            "<code>traces:</code> in the corpus file.</p>"
        )
    return "".join(
        ["<h1>Evaluations</h1>",
         "<p class='lede'>What policy required of a real run, and what the run actually did. "
         "<em>undecided</em> is the number to watch: it is how much of the policy this "
         "telemetry cannot hold an agent to.</p>"]
        + [_evaluation(space, index, ev) for index, ev in enumerate(space.evaluations)]
    )


def quarantine(space: Workspace) -> str:
    rejections = space.result.rejections
    if not rejections:
        return (
            "<h1>Quarantine</h1><p class='lede'>Nothing was rejected. On a first build that "
            "usually means the extractor is being asked for too little, not that it is "
            "perfect.</p>"
        )

    by_criterion: dict[str, list[Rejection]] = {}
    for rejection in rejections:
        by_criterion.setdefault(rejection.criterion, []).append(rejection)

    blocks = [
        "<h1>Quarantine</h1>",
        "<p class='lede'>Every candidate that did not become a fact, and the criterion it "
        "failed. This is where a broken extractor is found — a criterion suddenly rejecting "
        "far more than it used to is the signal.</p>",
    ]
    for criterion, group in sorted(by_criterion.items()):
        rows = [
            [
                escape(r.candidate.head[:60]),
                f"<code>{escape(r.candidate.relation)}</code>",
                escape(r.candidate.tail[:50]),
                chip(r.candidate.method),
                escape(r.detail),
                quote(r.candidate.quote[:160]),
            ]
            for r in group[:80]
        ]
        blocks.append(
            panel(
                f"{criterion} ({len(group)})",
                table(["subject", "relation", "object", "how", "why", "claimed quote"], rows),
            )
        )
    return "".join(blocks)


def questions(space: Workspace) -> str:
    open_questions = outstanding(space.result.questions, space.decisions)
    by_kind: dict[str, list[Question]] = {}
    for question in open_questions:
        by_kind.setdefault(question.kind, []).append(question)

    if not open_questions:
        return "<h1>Review</h1><p class='lede'>Nothing is waiting on a person.</p>"

    blocks = [
        "<h1>Review</h1>",
        "<p class='lede'>Approving an expectation is the moment it stops advising and "
        "becomes able to fail an agent. Every answer is written to "
        "<code>questions.yaml</code> and the build is redone immediately.</p>",
    ]
    for kind, group in sorted(by_kind.items()):
        rows = [
            [
                escape(q.heading),
                f"<p class='lede' style='margin:0'>{escape(q.detail)}</p>"
                + "".join(quote(span.quote) for span in q.evidence[:2]),
                _answer_form(q.id),
            ]
            for q in group
        ]
        blocks.append(panel(f"{kind} ({len(group)})", table(["what", "why", "answer"], rows)))
    return "".join(blocks)


def _answer_form(question_id: str) -> str:
    return (
        f"<form method='post' action='/answer' class='inline'>"
        f"<input type='hidden' name='id' value='{escape(question_id)}'>"
        "<button class='primary' name='answer' value='approve'>Approve</button> "
        "<button name='answer' value='reject'>Reject</button></form>"
    )


def _evaluation(space: Workspace, index: int, ev: Evaluation) -> str:
    counts = Counter(v.outcome for v in ev.verdicts)
    heading = ev.contract.binding

    rows = [
        [
            chip(v.outcome, tone(v.outcome)),
            chip(v.assertion.severity, tone(v.assertion.severity)),
            f"<code>{escape(v.assertion.kind)}</code>",
            escape(space.graph.label(v.assertion.subject)) if v.assertion.subject else "—",
            escape(v.detail),
            _evidence(space, v.assertion.evidence),
        ]
        for v in sorted(ev.verdicts, key=lambda v: (v.outcome != "fail", v.assertion.kind))
    ]

    unbound = ""
    if ev.unbound:
        unbound = (
            "<p class='lede'>Observed but not in the ontology: "
            + ", ".join(f"<code>{escape(t)}</code>" for t in ev.unbound)
            + ". These are things the agent did that nothing can grade.</p>"
        )

    return panel(
        heading,
        stats(
            [
                ("pass", counts.get("pass", 0)),
                ("fail", counts.get("fail", 0)),
                ("undecided", counts.get("undecided", 0)),
                ("not applicable", counts.get("not_applicable", 0)),
                ("binding coverage", f"{ev.binding_coverage:.0%}"),
            ]
        )
        + f"<p class='lede' style='margin-top:14px'><a href='/trace/{index}'>See what the "
        "run actually did →</a></p>"
        + unbound
        + table(["verdict", "severity", "check", "subject", "what happened", "policy"], rows),
    )


def trace_view(space: Workspace, index: int) -> str:
    if index >= len(space.traces):
        return "<h1>Not found</h1><p class='lede'>No trace at that position.</p>"

    from metric.trace.binding import bind

    trace = space.traces[index]
    bound = bind(trace, space.graph, checkpoint_variable=space.checkpoint_variable)
    by_ref = {(b.observation.ref, b.entity_type): b for b in bound.bindings}

    rows = []
    for observation in trace.observations:
        binding = by_ref.get((observation.ref, _target_of(observation.kind)))
        resolved = "—"
        if binding is not None and binding.entity:
            resolved = (
                f"<a href='/entity/{urlquote(binding.entity)}'>"
                f"{escape(space.graph.label(binding.entity))}</a> {chip(binding.method)}"
            )
        elif binding is not None and binding.attempted:
            resolved = chip("unbound", "warn")
        rows.append(
            [
                str(observation.turn),
                chip(observation.kind),
                escape(observation.name or "—"),
                escape(observation.value[:90]) or "—",
                resolved,
            ]
        )

    return "".join(
        [
            f"<h1>Trace {escape(trace.conversation_id)}</h1>",
            "<p class='lede'>Every observation, and what it bound to. An unbound row is "
            "something the agent did that the ontology has no name for.</p>",
            table(["turn", "kind", "name", "value", "bound to"], rows),
        ]
    )


def passage_view(space: Workspace, passage_id: str, *, start: int = 0, end: int = 0) -> str:
    passage = space.passages.get(passage_id)
    if passage is None:
        return (
            "<h1>Source</h1><p class='lede'>This evidence comes from a telemetry profile "
            "rather than a document, so there is no passage to show.</p>"
        )

    text = passage.text
    if 0 <= start < end <= len(text):
        shown = (
            escape(text[:start])
            + f"<mark>{escape(text[start:end])}</mark>"
            + escape(text[end:])
        )
    else:
        shown = escape(text)

    return "".join(
        [
            "<h1>Source</h1>",
            f"<p class='lede'>{escape(' › '.join(passage.heading_path))} · "
            f"<code>{escape(passage.location)}</code></p>",
            f"<div class='panel' style='line-height:1.7'>{shown}</div>",
        ]
    )


def _assertions(space: Workspace, assertions: tuple[Assertion, ...]) -> str:
    rows = [
        [
            f"<code>{escape(a.kind)}</code>",
            escape(space.graph.label(a.subject)) if a.subject else "—",
            escape(", ".join(space.graph.label(e) for e in a.expected))[:90],
            chip(a.severity, tone(a.severity)),
            chip(a.level),
            _evidence(space, a.evidence),
        ]
        for a in assertions
    ]
    return table(["check", "subject", "expected", "severity", "level", "policy"], rows)


def _evidence(space: Workspace, spans: tuple[Span, ...]) -> str:
    if not spans:
        return "<span class='empty'>—</span>"
    links = []
    for span in spans[:3]:
        href = f"/passage/{urlquote(span.passage_id)}?start={span.start}&end={span.end}"
        links.append(
            f"<a href='{href}' title='{escape(span.quote)}'>{escape(_clip(span.quote))}</a>"
        )
    more = f" +{len(spans) - 3}" if len(spans) > 3 else ""
    return "<br>".join(links) + more


def _select(name: str, options: Sequence[str], selected: str, blank: str) -> str:
    items = [f"<option value=''>{escape(blank)}</option>"]
    items += [
        f"<option value='{escape(o)}'{' selected' if o == selected else ''}>{escape(o)}</option>"
        for o in options
    ]
    return f"<select name='{name}'>{''.join(items)}</select>"


def _target_of(kind: str) -> str:
    return {
        "tool_call": "Tool",
        "outcome": "Outcome",
        "capability": "Capability",
        "state_write": "StateVariable",
    }.get(kind, "")


def _clip(text: str, limit: int = 54) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = [
    "entity_view",
    "evaluations",
    "graph_view",
    "html",
    "overview",
    "passage_view",
    "quarantine",
    "questions",
    "scenario_view",
    "scenarios",
    "trace_view",
    "workflow",
]
