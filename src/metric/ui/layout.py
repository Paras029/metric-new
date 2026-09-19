"""Laying the workflow out as an SVG, computed in Python.

A force-directed picture of a policy graph is unreadable — it is a process, and a
process wants layers. So states are placed by distance from the entry, edges are drawn
as curves labelled with the outcome that causes them, and back edges (the retry loops,
which are where the interesting failures live) are bent out to the side rather than
hidden behind the nodes they connect.

The rules governing a state do not get their own boxes. They are a count on the node
and the text on hover, because a graph that draws every obligation as a node stops
being a picture of the journey.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from metric.graph.journey import Journey
from metric.graph.model import Graph

BOX_W, BOX_H = 232.0, 56.0
GAP_X, GAP_Y = 46.0, 104.0
PAD = 28.0
LANE = 30.0  # horizontal spacing between stacked back-edge routes


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    label: str
    x: float
    y: float
    terminal: bool
    entry: bool
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    label: str
    back: bool
    lane: int = 0


def layout(graph: Graph) -> tuple[list[Node], list[Edge], float, float]:
    journey = Journey(graph)
    states = sorted(set(graph.ids_of_type("State")) & _mentioned(journey), key=graph.label)
    if not states:
        return [], [], 0.0, 0.0

    entries = [s for s in journey.entries() if s in states]
    depth, forward = _depths(journey, entries or states[:1], states)

    rows: dict[int, list[str]] = {}
    for state in sorted(states, key=lambda node: (depth.get(node, 0), graph.label(node))):
        rows.setdefault(depth.get(state, 0), []).append(state)
    _order_rows(rows, forward)

    widest = max(len(row) for row in rows.values())
    width = PAD * 2 + widest * BOX_W + (widest - 1) * GAP_X
    height = PAD * 2 + len(rows) * BOX_H + (len(rows) - 1) * GAP_Y

    nodes: list[Node] = []
    position: dict[str, tuple[float, float]] = {}
    for level in sorted(rows):
        row = rows[level]
        span = len(row) * BOX_W + (len(row) - 1) * GAP_X
        left = (width - span) / 2
        for index, state in enumerate(row):
            x = left + index * (BOX_W + GAP_X)
            y = PAD + level * (BOX_H + GAP_Y)
            position[state] = (x, y)
            nodes.append(
                Node(
                    id=state,
                    label=graph.label(state),
                    x=x,
                    y=y,
                    terminal=state in journey.terminals,
                    entry=state in entries,
                    rules=_rules(graph, state),
                )
            )

    edges: list[Edge] = []
    lane = 0
    for state in states:
        for _, outcome, target in journey.successors(state):
            if target not in position:
                continue
            back = (state, target) not in forward
            edges.append(
                Edge(
                    source=state,
                    target=target,
                    label=graph.label(outcome) if outcome else "",
                    back=back,
                    lane=lane if back else 0,
                )
            )
            lane += 1 if back else 0

    # Back edges share a lane to the right of the whole diagram, so a loop can never be
    # drawn through a node it has nothing to do with.
    width += lane * LANE + (PAD if lane else 0)
    return nodes, edges, width, height


def render(graph: Graph) -> str:
    nodes, edges, width, height = layout(graph)
    if not nodes:
        return "<p class='empty'>No states in this graph, so there is no workflow to draw.</p>"

    at = {node.id: node for node in nodes}
    parts = [
        f"<svg viewBox='0 0 {width:.0f} {height:.0f}' width='100%' "
        f"style='max-width:{width:.0f}px' xmlns='http://www.w3.org/2000/svg' "
        "font-family='ui-sans-serif,system-ui,sans-serif'>",
        "<defs><marker id='a' viewBox='0 0 8 8' refX='7' refY='4' markerWidth='7' "
        "markerHeight='7' orient='auto'><path d='M0,0 L8,4 L0,8 z' fill='currentColor'/>"
        "</marker></defs>",
        "<g stroke='currentColor' fill='none' opacity='.34'>",
    ]

    right_edge = max(node.x + BOX_W for node in nodes)
    for edge in edges:
        parts.append(
            _edge_path(at[edge.source], at[edge.target], edge.back, edge.lane, right_edge)
        )
    parts.append("</g>")

    for edge in edges:
        if edge.label:
            parts.append(
                _edge_label(
                    at[edge.source], at[edge.target], edge.label, edge.back, edge.lane, right_edge
                )
            )

    for node in nodes:
        parts.append(_node(node))

    parts.append("</svg>")
    return "".join(parts)


def _edge_path(source: Node, target: Node, back: bool, lane: int, right_edge: float) -> str:
    x1, y1 = source.x + BOX_W / 2, source.y + BOX_H
    x2, y2 = target.x + BOX_W / 2, target.y

    if back:
        # Routed only through empty space: down into the gap below the source row, out
        # to a lane clear of every node, up, then into the gap above the target row.
        # A straight line between the two boxes would cross whatever sits between them.
        side = right_edge + PAD + lane * LANE
        below = source.y + BOX_H + GAP_Y / 2
        above = target.y - GAP_Y / 2
        return (
            f"<path d='M{x1:.0f},{y1:.0f} L{x1:.0f},{below:.0f} L{side:.0f},{below:.0f} "
            f"L{side:.0f},{above:.0f} L{x2:.0f},{above:.0f} L{x2:.0f},{y2:.0f}' "
            "stroke-dasharray='4 3' marker-end='url(#a)'/>"
        )

    mid = (y1 + y2) / 2
    return (
        f"<path d='M{x1:.0f},{y1:.0f} C{x1:.0f},{mid:.0f} "
        f"{x2:.0f},{mid:.0f} {x2:.0f},{y2:.0f}' marker-end='url(#a)'/>"
    )


def _edge_label(
    source: Node, target: Node, label: str, back: bool, lane: int, right_edge: float
) -> str:
    if back:
        x = right_edge + PAD + lane * LANE + 6
        y = (source.y + target.y) / 2 + BOX_H / 2
        anchor = "start"
    else:
        x = (source.x + target.x) / 2 + BOX_W / 2
        y = (source.y + BOX_H + target.y) / 2 + 4
        anchor = "middle"
    return (
        f"<text x='{x:.0f}' y='{y:.0f}' text-anchor='{anchor}' font-size='11' "
        f"fill='currentColor' opacity='.66'>{escape(_clip(label, 22))}</text>"
    )


def _node(node: Node) -> str:
    # The ending is the thing a reader looks for first, so it is the one place in the
    # diagram that is not monochrome.
    stroke = "var(--seal)" if node.terminal else "currentColor"
    weight = "2" if node.terminal or node.entry else "1"
    dash = " stroke-dasharray='3 3'" if node.entry and not node.terminal else ""
    title = escape("\n".join(node.rules)) if node.rules else ""

    badge = ""
    if node.rules:
        badge = (
            f"<circle cx='{node.x + BOX_W - 15:.0f}' cy='{node.y + 15:.0f}' r='9' "
            "fill='currentColor' opacity='.12'/>"
            f"<text x='{node.x + BOX_W - 15:.0f}' y='{node.y + 19:.0f}' text-anchor='middle' "
            f"font-size='10.5' fill='currentColor' opacity='.72'>{len(node.rules)}</text>"
        )

    return (
        f"<g><title>{title}</title>"
        f"<rect x='{node.x:.0f}' y='{node.y:.0f}' width='{BOX_W:.0f}' height='{BOX_H:.0f}' "
        f"rx='8' fill='none' stroke='{stroke}' stroke-width='{weight}' "
        f"opacity='{'.9' if node.terminal else '.5'}'{dash}/>"
        f"{badge}"
        f"{_label(node)}</g>"
    )


def _order_rows(rows: dict[int, list[str]], forward: set[tuple[str, str]]) -> None:
    """Order each row by where its parents sit, so forward edges cross less.

    One barycentre pass, top to bottom. It is not an optimal ordering and does not need
    to be — it removes the crossings that come from alphabetical placement, which are
    most of them on a policy graph this size.
    """
    for level in sorted(rows)[1:]:
        above = {state: index for index, state in enumerate(rows[level - 1])}
        if not above:
            continue

        def parent_mean(state: str, above: dict[str, int] = above) -> float:
            positions = [above[src] for src, dst in forward if dst == state and src in above]
            return sum(positions) / len(positions) if positions else len(above) / 2

        rows[level].sort(key=lambda state: (parent_mean(state), state))


def _label(node: Node) -> str:
    lines = _wrap(node.label, 27)
    top = node.y + BOX_H / 2 + (4 if len(lines) == 1 else -3)
    spans = "".join(
        f"<tspan x='{node.x + 14:.0f}' dy='{0 if index == 0 else 15}'>{escape(line)}</tspan>"
        for index, line in enumerate(lines)
    )
    return (
        f"<text x='{node.x + 14:.0f}' y='{top:.0f}' font-size='12.5' "
        f"fill='currentColor'>{spans}</text>"
    )


def _wrap(text: str, limit: int) -> list[str]:
    """At most two lines; a name too long for both is clipped on the second."""
    if len(text) <= limit:
        return [text]
    words = text.split()
    first: list[str] = []
    while words and len(" ".join([*first, words[0]])) <= limit:
        first.append(words.pop(0))
    if not first:
        first = [words.pop(0)]
    return [" ".join(first), _clip(" ".join(words), limit)]


def _depths(
    journey: Journey, entries: list[str], states: list[str]
) -> tuple[dict[str, int], set[tuple[str, str]]]:
    """Layer every state, and say which edges run forward.

    Breadth-first discovery decides direction: an edge to a state discovered earlier is
    a loop. Layers then come from the longest forward path, so an edge never joins two
    states on the same row — which would draw as a line straight through whatever sits
    between them.
    """
    order: dict[str, int] = {entry: index for index, entry in enumerate(entries)}
    frontier = list(entries)
    while frontier:
        nxt: list[str] = []
        for state in frontier:
            for _, _, target in journey.successors(state):
                if target in states and target not in order:
                    order[target] = len(order)
                    nxt.append(target)
        frontier = nxt
    for state in states:
        order.setdefault(state, len(order))

    forward = {
        (state, target)
        for state in states
        for _, _, target in journey.successors(state)
        if target in states and order[target] > order[state]
    }

    depth = dict.fromkeys(states, 0)
    for _ in range(len(states)):
        changed = False
        for state, target in forward:
            if depth[target] < depth[state] + 1:
                depth[target] = depth[state] + 1
                changed = True
        if not changed:
            break
    return depth, forward


def _rules(graph: Graph, state: str) -> tuple[str, ...]:
    statements = []
    for governed in graph.out(state, "GOVERNED_BY"):
        stated = graph.out(governed.tail, "RULE_STATES")
        statements.append(stated[0].tail if stated else graph.label(governed.tail))
    return tuple(sorted(set(statements)))


def _mentioned(journey: Journey) -> set[str]:
    found = set(journey.edges)
    for edges in journey.edges.values():
        found.update(target for _, _, target in edges)
    found.update(journey.terminals)
    return found


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
