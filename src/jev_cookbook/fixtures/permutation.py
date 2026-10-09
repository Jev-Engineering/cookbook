"""A deterministic permutation for per-item option order (``docs/fixtures.md``, "Per-item
option order"; issue #181).

``random.shuffle`` (and the ``_randbelow``/``getrandbits`` machinery it is built on) is not an
algorithm the ``random`` module documents as stable across CPython versions: the module's docs
promise only that ``random.Random.random()`` "will continue to produce the same sequence when
the compatible seeder is given the same seed", and name no such guarantee for ``shuffle()``.
Recipe 12's per-sentence candidate shuffle and ``ScriptedBackend.rng_for`` (``../backends.py``,
``docs/backends.md``) both derive a per-item seed the same way (hash the key, seed
``random.Random`` from the digest) specifically to keep committed replay keys and fixtures
reproducible; the one gap was ``shuffle()`` itself.

``stable_permutation`` closes that gap: it builds the permutation with a hand-written
Durstenfeld (Fisher-Yates, swapping from the end) shuffle that calls nothing but
``random.Random(seed).random()`` -- the one method the documentation commits to. The seed is
derived exactly as ``ScriptedBackend.rng_for`` derives its own: SHA-256 of ``seed_key``, the
first 16 hex characters (64 bits) read as an int. Two independent, fixed things are then
guaranteed stable forever: the hashing (SHA-256 is a fixed specification) and the one
``random()`` call this module uses, so the resulting permutation is pinned to an exact,
reproducible value on every supported Python (the test suite pins it for both 3.10 and 3.14).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from typing import TypeVar

__all__ = ["stable_permutation", "stable_shuffle"]

T = TypeVar("T")


def _seed(seed_key: str) -> int:
    digest = hashlib.sha256(seed_key.encode()).hexdigest()
    return int(digest[:16], 16)


def stable_permutation(seed_key: str, n: int) -> tuple[int, ...]:
    """A permutation of ``range(n)``, deterministic in ``seed_key`` alone.

    Construction: Durstenfeld's Fisher-Yates shuffle, swapping from the end, driven only by
    ``random.Random(seed).random()`` where ``seed`` is the first 64 bits of the SHA-256 digest
    of ``seed_key`` (the same derivation ``ScriptedBackend.rng_for`` uses). See the module
    docstring for why this -- and not ``random.shuffle`` -- is the documented-stable choice.

    ``n <= 1`` returns the identity (``()`` or ``(0,)``) without touching ``random`` at all, so
    it needs no seed and is trivially stable. Two different ``seed_key`` values give different
    permutations with overwhelming probability (SHA-256 is not designed to collide), never
    guaranteed distinct, but a shared permutation across the catalog's keys has not been seen.
    """
    if not isinstance(seed_key, str):
        raise TypeError("seed_key must be a str")
    if type(n) is not int or n < 0:
        raise ValueError(f"n must be a non-negative int, got {n!r}")
    order = list(range(n))
    if n <= 1:
        return tuple(order)
    rng = random.Random(_seed(seed_key))
    for i in range(n - 1, 0, -1):
        j = int(rng.random() * (i + 1))
        if j > i:  # pragma: no cover -- float rounding guard, not reachable in practice
            j = i
        order[i], order[j] = order[j], order[i]
    return tuple(order)


def stable_shuffle(seed_key: str, items: Sequence[T]) -> tuple[T, ...]:
    """``items``, reordered by ``stable_permutation(seed_key, len(items))``.

    Use this (or ``stable_permutation`` directly, for an index-based order) for per-example
    option order and first-shown sides: ``stable_shuffle(f"{recipe}:{example_id}", options)``.
    Never ``random.shuffle`` or the authored list order -- see ``docs/fixtures.md``, "Per-item
    option order".
    """
    pool = list(items)
    return tuple(pool[i] for i in stable_permutation(seed_key, len(pool)))
