"""A diagram reading, as candidate triples with somewhere to cite.

Everything in this graph carries provenance: a triple names the passage and the characters
its claim came from, and the UI is built so a reviewer can click any fact and read the
sentence behind it. A picture has no sentences.

So the reading becomes one. Each image gets a **passage whose text is what was read off
it** — the boxes, the arrows and their labels, enumerated one per line — and every triple
cites the line that carries it. A reviewer clicking a diagram-derived fact sees
`arrow: FAILED — Authentication attempts → Failed authentication and retry`, and beside it
the image it was read from. That is honest: it says what was seen, not what the picture
"means", and it goes through the same admission gate as everything else rather than around
it.

**Why this matters beyond tidiness.** The witness bar holds any high-materiality fact that
rests on a single model reading. A workflow stated in prose *and* drawn as a diagram gives
two independent readings of the same structure, so a fact both of them found has two
witnesses and clears the bar without a person. The card-authentication policy says so
itself: "the workflow backbone should be recoverable from the diagram as well as from §3,
and the two readings agreeing is itself a useful check." This is what makes that check
real rather than aspirational.
"""

from __future__ import annotations

from collections.abc import Sequence

from metric.diagram.structure import Decision, State, Structure
from metric.ontology.ids import passage_id
from metric.ontology.types import Candidate, Method, Passage

# `vision` is the method the ontology already has for this; a diagram-read fact is
# marked with it so the witness bar and the contract compiler can tell it from a
# sentence someone wrote.
METHOD: Method = "vision"


def as_passage(name: str, structure: Structure, *, doc_id: str) -> Passage:
    """What was read off one picture, as text a quote can be located in."""
    text = "\n".join(_lines(structure))
    return Passage(
        id=passage_id(doc_id, f"{name}:reading", text),
        doc_id=doc_id,
        location=f"{name} (as read)",
        kind="image",
        heading_path=(name,),
        text=text,
    )


def as_candidates(
    structure: Structure, *, passage: Passage, use_case: str = ""
) -> list[Candidate]:
    """Every edge the drawing shows, as a candidate citing the line it was read from.

    Only the structural relations. A diagram shows where the journey goes and what
    branches it; it does not show what a rule requires or what wording is fixed, and
    inventing those from a picture would be the one thing this whole pipeline exists to
    refuse.
    """
    lines = {line: line for line in passage.text.splitlines()}
    found: list[Candidate] = []
    states = {s.id: s for s in structure.states}

    def cite(text: str) -> str:
        return lines.get(text, text)

    for state in structure.states:
        if state.reached_via.strip().lower() == "start" and use_case:
            found.append(
                _candidate(
                    "UseCase", use_case, "STARTS_AT", "State", state.name,
                    cite(_state_line(state)), passage,
                )
            )
        if state.terminal:
            found.append(
                _candidate(
                    "State", state.name, "IS_TERMINAL", "literal", "true",
                    cite(_state_line(state)), passage,
                )
            )
        for tool in state.tools:
            found.append(
                _candidate(
                    "State", state.name, "USES_TOOL", "Tool", tool,
                    cite(_state_line(state)), passage,
                )
            )
        for target in state.next_states:
            other = states.get(target)
            if other is not None:
                found.append(
                    _candidate(
                        "State", state.name, "HAS_NEXT_STEP", "State", other.name,
                        cite(_edge_line(state.id, target, structure)), passage,
                    )
                )

    for decision in structure.decisions:
        at = states.get(decision.at_state)
        if at is not None:
            found.append(
                _candidate(
                    "State", at.name, "OFFERS_DECISION", "Decision", decision.name,
                    cite(_decision_line(decision)), passage,
                )
            )
        for outcome in decision.outcomes:
            found.append(
                _candidate(
                    "Decision", decision.name, "HAS_OUTCOME", "Outcome", outcome,
                    cite(_decision_line(decision)), passage,
                )
            )
            landing = _lands(structure, decision.id, outcome)
            if landing is not None:
                found.append(
                    _candidate(
                        "Outcome", outcome, "LEADS_TO", "State", landing.name,
                        cite(_arrow_line(decision, outcome, landing)), passage,
                    )
                )

    return [c for c in found if c.head and c.tail]


def _candidate(
    head_type: str,
    head: str,
    relation: str,
    tail_type: str,
    tail: str,
    quote: str,
    passage: Passage,
) -> Candidate:
    return Candidate(
        head=head,
        head_type=head_type,
        relation=relation,
        tail=tail,
        tail_type=tail_type,
        quote=quote,
        passage_id=passage.id,
        method=METHOD,
    )


def _lines(structure: Structure) -> list[str]:
    """The reading, one fact per line, so a quote can point at exactly one of them."""
    out = [_state_line(s) for s in structure.states]
    for decision in structure.decisions:
        out.append(_decision_line(decision))
        for outcome in decision.outcomes:
            landing = _lands(structure, decision.id, outcome)
            if landing is not None:
                out.append(_arrow_line(decision, outcome, landing))
    states = {s.id: s for s in structure.states}
    for state in structure.states:
        out.extend(
            _edge_line(state.id, target, structure)
            for target in state.next_states
            if target in states
        )
    return out


def _state_line(state: State) -> str:
    bits = [f"box: {state.name}"]
    if state.reached_via:
        bits.append(f"reached via {state.reached_via}")
    if state.terminal:
        bits.append("ends the journey")
    if state.tools:
        bits.append(f"calls {', '.join(state.tools)}")
    return " \u2014 ".join(bits)


def _decision_line(decision: Decision) -> str:
    return f"diamond: {decision.name} — {', '.join(decision.outcomes)}"


def _arrow_line(decision: Decision, outcome: str, landing: State) -> str:
    return f"arrow: {outcome} — {decision.name} → {landing.name}"


def _edge_line(source: str, target: str, structure: Structure) -> str:
    here, there = structure.state(source), structure.state(target)
    return f"arrow: {here.name if here else source} → {there.name if there else target}"


def _lands(structure: Structure, decision_id: str, outcome: str) -> State | None:
    wanted = f"{decision_id}={outcome}".lower().replace(" ", "")
    for state in structure.states:
        if state.reached_via.lower().replace(" ", "") == wanted:
            return state
    return None


def read_into_corpus(
    structures: Sequence[tuple[str, Structure]], *, doc_id: str, use_case: str = ""
) -> tuple[list[Passage], list[Candidate]]:
    """Passages and candidates for a whole set of pictures."""
    passages: list[Passage] = []
    candidates: list[Candidate] = []
    for name, structure in structures:
        if structure.empty:
            continue
        passage = as_passage(name, structure, doc_id=doc_id)
        passages.append(passage)
        candidates.extend(as_candidates(structure, passage=passage, use_case=use_case))
    return passages, candidates
