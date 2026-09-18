"""The EvaluationContract: what policy required, in a form something can check.

An `Assertion` is one checkable expectation carrying four things the old generator's
expectations had none of:

- **provenance** — the triples it came from and their source spans, so "why was the
  agent failed for this?" has an answer that ends in a sentence of the policy;
- **severity** — a blocker and a nice-to-have are not the same finding;
- **a derivation level** — the ground-truth ladder, so a governance reviewer can see
  whether an expectation came from a deterministic reading, from graph resolution or
  from runtime state;
- **a status** — whether the triple underneath it is confirmed or still awaiting
  review. An expectation resting on an unreviewed extraction can advise. It cannot
  block.

The contract is produced by the same compiler whether the binding is a generated
scenario or an observed trace. That symmetry is the point: a synthetic benchmark and
production evaluation that resolve expectations differently will drift apart, and the
drift will be invisible because each looks self-consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from metric.ontology.types import Span

AssertionKind = Literal[
    "tool_called",
    "outcome_allowed",
    "transition_expected",
    "transition_allowed",
    "terminal_expected",
    "order_expected",
    "count_limit",
    "action_required",
    "action_forbidden",
    "text_required",
    "uncompiled",
]

Dimension = Literal[
    "outcome", "policy", "state", "trajectory", "tool", "grounding", "communication"
]

Severity = Literal["blocker", "error", "warning", "info", "advisory"]
Level = Literal["L1", "L2", "L3", "L4", "L5"]

SEVERITY_ORDER: tuple[Severity, ...] = ("blocker", "error", "warning", "info", "advisory")


@dataclass(frozen=True, slots=True)
class Assertion:
    id: str
    kind: AssertionKind
    subject: str
    expected: tuple[str, ...]
    scope: str
    dimension: Dimension
    severity: Severity
    level: Level
    sources: tuple[tuple[str, str, str], ...]
    evidence: tuple[Span, ...]
    provisional: bool = False
    note: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity in {"blocker", "error"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "expected": list(self.expected),
            "scope": self.scope,
            "dimension": self.dimension,
            "severity": self.severity,
            "level": self.level,
            "sources": [list(triple) for triple in self.sources],
            "evidence": [span.as_dict() for span in self.evidence],
            "provisional": self.provisional,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Contract:
    """Identity, binding and assertions.

    `identity` is the build the expectations came from. Without it a verdict cannot be
    reproduced and cannot be re-examined after the policy changes.
    """

    id: str
    binding: str
    identity: str
    assertions: tuple[Assertion, ...]
    notes: tuple[str, ...] = ()

    def of_kind(self, *kinds: AssertionKind) -> tuple[Assertion, ...]:
        return tuple(a for a in self.assertions if a.kind in kinds)

    def about(self, subject: str) -> tuple[Assertion, ...]:
        return tuple(a for a in self.assertions if a.subject == subject)

    @property
    def blocking(self) -> tuple[Assertion, ...]:
        return tuple(a for a in self.assertions if a.blocking)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "binding": self.binding,
            "identity": self.identity,
            "assertions": [a.as_dict() for a in self.assertions],
            "notes": list(self.notes),
        }
