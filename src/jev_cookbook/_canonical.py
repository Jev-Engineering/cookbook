"""Plain-JSON validation and canonical serialization (private; see docs/backends.md)."""

from __future__ import annotations

import json
import math
from typing import Any

MAX_DEPTH = 64  # the fixture nesting limit (docs/fixtures.md): containers nested at most this deep


def check_depth(value: Any, where: str = "value", limit: int = MAX_DEPTH) -> None:
    """Raise ``ValueError`` if lists/tuples/dicts in ``value`` nest deeper than ``limit``.

    The outermost container is level 1 (the same count as the fixture validator, which counts
    the line as level 1); a scalar adds no level. Iterative on purpose: it never recurses, so
    a very deep value is a readable ``ValueError`` and not a ``RecursionError``, the answer is
    the same on every interpreter, and a self-referencing container is caught too.
    """
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        kind = type(item)
        if kind in (list, tuple):
            children: Any = item
        elif kind is dict:
            children = item.values()
        else:
            continue
        if depth + 1 > limit:
            raise ValueError(f"{where}: nested deeper than {limit} levels (see docs/fixtures.md)")
        stack.extend((child, depth + 1) for child in children)


def plain_json(value: Any, where: str = "value", max_depth: int | None = None) -> Any:
    """Return a deep copy of ``value`` restricted to plain JSON types.

    Accepted: ``str``, ``bool``, ``int``, finite ``float``, ``None``, ``list``/``tuple``
    (copied to ``list``) and ``dict`` with ``str`` keys. Anything else (numpy scalars,
    sets, dataclasses, NaN, infinity) raises ``TypeError`` or ``ValueError`` naming
    the offending path, so a bad state fails loudly instead of hashing differently. Nesting
    deeper than ``max_depth`` raises ``ValueError``; the default ``None`` applies no limit, so
    shared callers (simulation, questions) behave as they always did. ``replay_key`` passes 64.
    """
    if max_depth is not None:
        check_depth(value, where, max_depth)
    return _plain(value, where)


def _plain(value: Any, where: str) -> Any:
    kind = type(value)
    if value is None or kind in (str, bool, int):
        return value
    if kind is float:
        if not math.isfinite(value):
            raise ValueError(f"{where}: NaN and infinity are not valid JSON")
        return value
    if kind in (list, tuple):
        return [_plain(v, f"{where}[{i}]") for i, v in enumerate(value)]
    if kind is dict:
        out: dict[str, Any] = {}
        for k, v in value.items():
            if type(k) is not str:
                raise TypeError(f"{where}: dict keys must be str, got {type(k).__name__}")
            out[k] = _plain(v, f"{where}[{k!r}]")
        return out
    raise TypeError(
        f"{where}: {kind.__name__} is not plain JSON "
        "(use str, int, float, bool, None, list, dict; convert numpy values with .item())"
    )


def canonical_json(value: Any, max_depth: int | None = None) -> str:
    """Serialize plain JSON deterministically (the string that replay keys hash).

    Object keys keep the order they were written in (that is the order the SDK sends);
    callers sort where order is provably irrelevant. No whitespace, ``ensure_ascii=True``
    (pure ASCII text), ``allow_nan=False``, floats via Python's shortest round-trip
    ``repr`` (identical on every platform and Python 3.10 to 3.14). Strings are hashed
    exactly as written: no newline or Unicode normalization. Nesting past ``max_depth``
    raises ``ValueError`` (see :func:`plain_json`).
    """
    return json.dumps(
        plain_json(value, max_depth=max_depth),
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
