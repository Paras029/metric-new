"""Type-aware canonical forms.

Entity identity is a content hash of a canonical surface form, so what counts as
"the same thing" is decided here rather than argued about later. Most types need
nothing beyond case and punctuation folding. `Value` does: a document states the
same limit several ways, and unless those reduce to one key the graph carries the
same constraint two or three times, each with one citation, and nothing downstream
can tell that apart from two genuinely different limits.

Reduction is on number and unit only — "3 authentication attempts", "3 total
authentication attempts" and "3 attempts" agree that the unit is attempts and the
number is three. "3 days" does not collide with any of them.

What is deliberately *not* reduced here: a prohibition that implies a limit.
"must not make a fourth attempt" means the limit is three, but reading it that way
is an inference, and this pipeline does not infer. It stays a separate Rule, and
`integrity` raises a question when a rule and a threshold govern the same subject.
"""

from __future__ import annotations

import re

from metric.ontology.ids import canonical_name

CARDINALS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
NUMBER_WORDS = {value: word for word, value in CARDINALS.items()}

_QUANTITY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+(.*\S)\s*$")
_PLURAL_KEEP = ("ss", "us", "is", "as", "os")


def as_number(token: str) -> int | None:
    """Parse a digit string or a spelled-out cardinal. `None` if it is neither."""
    lowered = token.strip().lower()
    if lowered in CARDINALS:
        return CARDINALS[lowered]
    try:
        return int(lowered)
    except ValueError:
        return None


def canonical_surface(entity_type: str, surface: str) -> str:
    if entity_type == "Value":
        return _canonical_value(surface)
    return canonical_name(surface)


def _canonical_value(surface: str) -> str:
    match = _QUANTITY.match(surface)
    if match is None:
        return canonical_name(surface)

    number, unit_phrase = match.group(1), match.group(2)
    words = canonical_name(unit_phrase).split("_")
    unit = _singular(words[-1]) if words and words[-1] else ""
    return canonical_name(f"{number} {unit}") if unit else canonical_name(number)


def _singular(word: str) -> str:
    if len(word) > 3 and word.endswith("s") and not word.endswith(_PLURAL_KEEP):
        return word[:-1]
    return word
