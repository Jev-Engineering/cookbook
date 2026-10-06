"""Plain-JSON validation and canonical serialization (private; see docs/backends.md)."""

from __future__ import annotations

import json
import math
from typing import Any


def plain_json(value: Any, where: str = "value") -> Any:
    """Return a deep copy of ``value`` restricted to plain JSON types.

    Accepted: ``str``, ``bool``, ``int``, finite ``float``, ``None``, ``list``/``tuple``
    (copied to ``list``) and ``dict`` with ``str`` keys. Anything else (numpy scalars,
    sets, dataclasses, NaN, infinity) raises ``TypeError`` or ``ValueError`` naming
    the offending path, so a bad state fails loudly instead of hashing differently.
    """
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return value
    if kind is float:
        if not math.isfinite(value):
            raise ValueError(f"{where}: NaN and infinity are not valid JSON")
        return value
    if kind in (list, tuple):
        return [plain_json(v, f"{where}[{i}]") for i, v in enumerate(value)]
    if kind is dict:
        out: dict[str, Any] = {}
        for k, v in value.items():
            if type(k) is not str:
                raise TypeError(f"{where}: dict keys must be str, got {type(k).__name__}")
            out[k] = plain_json(v, f"{where}[{k!r}]")
        return out
    raise TypeError(
        f"{where}: {kind.__name__} is not plain JSON "
        "(use str, int, float, bool, None, list, dict; convert numpy values with .item())"
    )


def _normalize(value: Any) -> Any:
    """Canonical form: newlines to LF in every string, negative zero to zero."""
    if type(value) is str:
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if type(value) is float:
        return 0.0 if value == 0.0 else value
    if type(value) is list:
        return [_normalize(v) for v in value]
    if type(value) is dict:
        out: dict[str, Any] = {}
        for k, v in value.items():
            nk = _normalize(k)
            if nk in out:
                raise ValueError(f"keys collide after newline normalization: {nk!r}")
            out[nk] = _normalize(v)
        return out
    return value


def canonical_json(value: Any) -> str:
    """Serialize plain JSON deterministically (the string that replay keys hash).

    Object keys sorted, no whitespace, ``ensure_ascii=True`` (so the text is pure ASCII
    and independent of any encoding), ``allow_nan=False``, floats via Python's shortest
    round-trip ``repr`` (identical on every platform and Python 3.10 to 3.14).
    """
    return json.dumps(
        _normalize(plain_json(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
