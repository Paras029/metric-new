"""Getting a picture to a model, in the order a person would look at them.

Two things here that are easy to get wrong and expensive to discover late.

**Order.** A workflow that does not fit on a page is exported as `flow-1.png`,
`flow-2.png`, … `flow-10.png`, and sorting those as strings puts 10 before 2. The join
pass is told to follow an arrow that ran off the edge of one image into the image that
picks it up, so the order it is given them in is the order it assumes. Natural sort, on
the digits in the name.

**Size.** A scanned A3 workflow is routinely 6000px and several megabytes, and the API
refuses it. Refusing late, per call, after a build has already read the text, is the worst
place to find out. So an oversized image is reduced here, once, and the reduction is
reported — a diagram read at half resolution may have lost its smallest arrow labels, and
that is something the person reading the result should know rather than something to hide.

Pillow does the reducing and is optional. Without it an oversized image is refused with the
reason and the dimensions, rather than sent and rejected by the API with something less
useful.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metric.corpus.readers.errors import UnreadableDocument

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# What the API will take. Kept a little under the documented ceilings so a re-encode that
# lands slightly larger than expected does not fail the call.
MAX_EDGE = 7600
MAX_BYTES = 4_700_000

_DIGITS = re.compile(r"(\d+)")


@dataclass(frozen=True, slots=True)
class Image:
    """One picture, ready to attach to a model call."""

    name: str
    media_type: str
    data: bytes
    note: str = ""

    @property
    def digest(self) -> str:
        """Part of the request key, so a changed picture is a different call."""
        return hashlib.sha256(self.data).hexdigest()[:16]

    def as_content(self) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": base64.b64encode(self.data).decode("ascii"),
            },
        }


def natural_key(path: Path) -> tuple[Any, ...]:
    """Sort `flow-2.png` before `flow-10.png`, which a string sort does not."""
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in _DIGITS.split(path.name)
    )


def order(paths: list[Path]) -> list[Path]:
    """The order a person would look at them in."""
    return sorted(paths, key=natural_key)


def load(path: Path) -> Image:
    """Read one image, reducing it if it is too large to send."""
    media_type = MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        raise UnreadableDocument(
            f"{path.name}: {path.suffix or 'this file'} is not an image format this reads. "
            f"Supported: {', '.join(sorted(MEDIA_TYPES))}"
        )

    data = path.read_bytes()
    if not data:
        raise UnreadableDocument(f"{path.name} is empty")

    reduced, note = _fit(data, media_type, path.name)
    return Image(name=path.name, media_type=media_type, data=reduced, note=note)


def _fit(data: bytes, media_type: str, name: str) -> tuple[bytes, str]:
    """Bring an image inside the limits, and say so when that cost resolution."""
    try:
        from PIL import Image as Pillow  # type: ignore[import-not-found]
    except ImportError:
        if len(data) <= MAX_BYTES:
            return data, ""
        raise UnreadableDocument(
            f"{name} is {len(data) // 1_000_000} MB, over the {MAX_BYTES // 1_000_000} MB "
            "limit, and Pillow is not installed to reduce it. Install metric[image], or "
            "export the diagram smaller"
        ) from None

    import io

    try:
        picture = Pillow.open(io.BytesIO(data))
        picture.load()
    except Exception as exc:
        # Any decoder failure, not just the documented ones: Pillow raises a different
        # type per format and a corrupt file reaches here as whatever the plugin threw.
        # Letting that out would take the whole build down over one bad tile, which is
        # the failure `load_all` exists to prevent.
        raise UnreadableDocument(
            f"{name} could not be decoded as an image ({type(exc).__name__}). It may be "
            "truncated, or named with the wrong extension"
        ) from exc

    with picture:
        width, height = picture.size
        if max(width, height) <= MAX_EDGE and len(data) <= MAX_BYTES:
            return data, ""

        scale = min(MAX_EDGE / max(width, height), 1.0)
        # Shrink for the byte ceiling too, in steps, rather than guessing a quality.
        for _ in range(6):
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            buffer = io.BytesIO()
            reduced = picture.convert("RGB") if media_type == "image/jpeg" else picture
            reduced.resize(size, Pillow.LANCZOS).save(
                buffer, format="PNG" if media_type == "image/png" else "JPEG"
            )
            if buffer.tell() <= MAX_BYTES:
                return buffer.getvalue(), (
                    f"{name} was {width}×{height}; reduced to {size[0]}×{size[1]} to send. "
                    "The smallest labels on it may not have survived"
                )
            scale *= 0.75

    raise UnreadableDocument(
        f"{name} could not be reduced under {MAX_BYTES // 1_000_000} MB. Export it as "
        "several smaller images — the reader joins them"
    )


def load_all(paths: list[Path]) -> tuple[list[Image], list[str]]:
    """Every image that could be loaded, in order, and why the rest could not.

    One unreadable image does not stop the others: a pack of eight tiles with one
    corrupt file should still produce seven tiles' worth of workflow and a note naming
    the eighth.
    """
    images: list[Image] = []
    refused: list[str] = []
    for path in order(paths):
        try:
            images.append(load(path))
        except UnreadableDocument as exc:
            refused.append(str(exc))
    return images, refused
