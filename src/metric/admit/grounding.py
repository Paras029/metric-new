"""Locating a claimed quote in the passage it cites.

Tolerant of typography, intolerant of rewording. A PDF turns a hyphen into an en
dash and a run of spaces into one; a model that rewords is asserting something the
source does not say, and the difference between those two has to be mechanical.

One decision does most of the work: on a match, the span records **the source's own
characters**, not the string the model returned. Normalisation can therefore be as
forgiving as the format requires without any risk of a paraphrase entering the
evidence, because the model's wording is never what gets stored.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_QUOTE_CHARS = 8

# Every substitution is one character for one character. A mapping that changed length
# would silently desynchronise the offset table this module exists to keep honest.
_SUBSTITUTIONS = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    " ": " ",
}


@dataclass(frozen=True, slots=True)
class Location:
    start: int
    end: int
    text: str
    exact: bool


def locate(
    quote: str, passage_text: str, *, min_quote_chars: int = MIN_QUOTE_CHARS
) -> Location | None:
    """Find `quote` in `passage_text`, returning the source substring that matched."""
    if len(quote.strip()) < min_quote_chars:
        return None

    start = passage_text.find(quote)
    if start >= 0:
        end = start + len(quote)
        return Location(start=start, end=end, text=passage_text[start:end], exact=True)

    haystack, offsets = _normalise(passage_text)
    needle, _ = _normalise(quote)
    if not needle:
        return None

    at = haystack.find(needle)
    if at < 0:
        return None

    start = offsets[at]
    end = offsets[at + len(needle) - 1] + 1
    return Location(start=start, end=end, text=passage_text[start:end], exact=False)


def normalised(text: str) -> str:
    """The folded form, for comparisons that do not need offsets."""
    return _normalise(text)[0]


def _normalise(text: str) -> tuple[str, list[int]]:
    """Fold typography, case and whitespace, keeping each output character's source index.

    Built one character at a time rather than by `str.translate` plus `casefold`,
    because both can change length and the offset table has to stay exact — a span
    that points a few characters off is worse than no span at all.
    """
    out: list[str] = []
    offsets: list[int] = []
    in_space = False

    for index, char in enumerate(text):
        mapped = _SUBSTITUTIONS.get(char, char)
        if mapped.isspace():
            if in_space or not out:
                continue
            in_space = True
            out.append(" ")
            offsets.append(index)
            continue
        in_space = False
        lowered = mapped.lower()
        out.append(lowered if len(lowered) == 1 else mapped)
        offsets.append(index)

    while out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets
