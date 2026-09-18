"""Content-addressed response cache.

This is the pipeline's actual reproducibility mechanism, and it is worth being
precise about why. Current Claude models reject `temperature`, `top_p` and `top_k`
outright, so there is no sampling knob to pin: two identical requests may return
different text, and no amount of prompt discipline changes that.

What is achievable is that a *build* reproduces. A response is keyed by the exact
request that produced it, so re-running a build over an unchanged corpus replays
recorded responses and yields a byte-identical graph. Model variation is then not
hidden — it is confined to the moment a request is first made, and measured by
running the reproducibility harness with the cache bypassed.

The cache is therefore a build artefact, not an optimisation. Deleting it does not
change what the pipeline means; it changes whether the last build can be reproduced.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CacheMiss(KeyError):
    """Raised by a replay-only gateway when a request was never recorded."""


def request_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ResponseCache:
    root: Path

    def path_for(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            record = json.load(handle)
        response = record.get("response")
        if not isinstance(response, dict):
            raise ValueError(f"{path}: cache entry has no response object")
        return response

    def put(self, key: str, *, request: dict[str, Any], response: dict[str, Any]) -> None:
        """Records the request alongside the response.

        Without the request a cache entry cannot be audited: a wrong answer is
        indistinguishable from a wrong question.
        """
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"key": key, "request": request, "response": response}
        path.write_text(
            json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
