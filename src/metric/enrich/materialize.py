"""The boundary between choosing a level and rendering it.

**Selecting a factor is data; rendering its levels is code.** The design writes choices
into a variant — `clarity=garbled`, `persona=impatient` — and that is as far as anything
declarative can go. Making a prompt actually read garbled, actually sound impatient, is
domain work: it depends on the channel, the language, the customer base, and on how the
agent under test is reached at all.

Keeping the two apart is what lets the catalogue stay a shared, diffable artefact while
the rendering stays an installation's own. The alternative — putting rendered text in
the catalogue — makes every team that wants different wording fork the design.

The default is deliberately the identity: the base's own question, with the chosen levels
carried alongside as metadata. It runs, it is reproducible, and it does not pretend to
have varied anything it has not. An installation supplies its own by registering one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Rendered:
    """One runnable case: what to send, under which levels, and what was not rendered."""

    scenario: str
    variant: str
    text: str
    levels: Mapping[str, str]
    unrendered: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "variant": self.variant,
            "text": self.text,
            "levels": dict(sorted(self.levels.items())),
            "unrendered": list(self.unrendered),
            "metadata": dict(sorted(self.metadata.items())),
        }


Materialiser = Callable[[str, Mapping[str, str]], tuple[str, tuple[str, ...]]]


def identity(question: str, levels: Mapping[str, str]) -> tuple[str, tuple[str, ...]]:
    """The default: the question unchanged, every level reported as unrendered.

    Honest rather than useful. A run made under this materialiser varied nothing, and
    the `unrendered` list says exactly which columns of the design were inert — which is
    what stops an attribution being drawn from a factor that never reached the agent.
    """
    return question, tuple(sorted(levels))


_REGISTRY: dict[str, Materialiser] = {"identity": identity}


def register(name: str, materialiser: Materialiser) -> None:
    """Add an installation's own renderer. The one piece of application glue here."""
    _REGISTRY[name] = materialiser


def get(name: str) -> Materialiser:
    if name not in _REGISTRY:
        raise KeyError(
            f"no materialiser named {name!r}; registered: {', '.join(sorted(_REGISTRY))}"
        )
    return _REGISTRY[name]


def materialize(
    *,
    scenario: str,
    variant: str,
    question: str,
    levels: Mapping[str, str],
    materialiser: Materialiser | str = identity,
    metadata: Mapping[str, Any] | None = None,
) -> Rendered:
    render = get(materialiser) if isinstance(materialiser, str) else materialiser
    text, unrendered = render(question, levels)
    return Rendered(
        scenario=scenario,
        variant=variant,
        text=text,
        levels=dict(levels),
        unrendered=unrendered,
        metadata=dict(metadata or {}),
    )
