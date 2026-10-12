"""Canonical JSON and fingerprints, exactly as JARVIS-COMMS-R2-DRAFT specifies.

Hash the UTF-8 serialization with object keys sorted recursively, no insignificant
whitespace, Unicode unescaped, array order retained, no Unicode normalization. Parse
with duplicate keys rejected and non-finite numbers rejected. Only str, int, bool,
None, float (finite), list and dict are R2 values.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class CanonError(ValueError):
    """The object is not representable as an R2 value, or the text is not strict JSON."""


def _check(obj: Any, path: str = "$") -> None:
    if obj is None or isinstance(obj, (str, bool)):
        return
    if isinstance(obj, int):
        return
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise CanonError(f"non-finite number at {path}")
        return
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonError(f"non-string key at {path}")
            _check(v, f"{path}.{k}")
        return
    raise CanonError(f"unsupported type {type(obj).__name__} at {path}")


def canonical_bytes(obj: Any) -> bytes:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def _no_dup_pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise CanonError(f"duplicate key {k!r}")
        out[k] = v
    return out


def _no_constant(name):
    raise CanonError(f"non-finite constant {name}")


def parse_strict(text: str) -> Any:
    try:
        obj = json.loads(text, object_pairs_hook=_no_dup_pairs, parse_constant=_no_constant)
    except CanonError:
        raise
    except ValueError as e:
        raise CanonError(f"not JSON: {e}") from None
    _check(obj)
    return obj
