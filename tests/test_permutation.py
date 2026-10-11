"""``stable_permutation`` / ``stable_shuffle``: a deterministic per-item order for option order
and first-shown sides (``docs/fixtures.md``, "Per-item option order"; issue #181).

The permutations below are pinned to exact values. Pinning, not just "it runs and is
deterministic", is the point: if a future CPython version changed how ``random.Random.random()``
behaves for a fixed seed (the one thing the standard library documents as stable), or if this
module's construction changed, these assertions would catch it instead of every recipe fixture
that uses this helper silently reshuffling. The suite runs this file under both the 3.10 and the
3.14 venv (``docs/development.md``, "Continuous integration": the ``Tests (py3.10)`` /
``Tests (py3.14)`` jobs), so the same pinned values are the reproduction check on both
interpreters; nothing in this file is version-conditional.
"""

from __future__ import annotations

import pytest

from jev_cookbook.fixtures import stable_permutation, stable_shuffle

# (seed_key, n) -> the exact permutation, computed once and checked identical on 3.10 and 3.14.
PINNED: dict[tuple[str, int], tuple[int, ...]] = {
    ("r12:v01-happy-high", 0): (),
    ("r12:v01-happy-high", 1): (0,),
    ("r12:v01-happy-high", 2): (1, 0),
    ("r12:v01-happy-high", 3): (2, 0, 1),
    ("r12:v01-happy-high", 5): (0, 3, 4, 1, 2),
    ("r12:v01-happy-high", 8): (1, 5, 2, 0, 6, 4, 7, 3),
    ("r23:cmp-001", 0): (),
    ("r23:cmp-001", 1): (0,),
    ("r23:cmp-001", 2): (1, 0),
    ("r23:cmp-001", 3): (2, 1, 0),
    ("r23:cmp-001", 5): (4, 1, 2, 3, 0),
    ("r23:cmp-001", 8): (2, 1, 4, 7, 3, 5, 6, 0),
    ("abc", 3): (2, 1, 0),
    ("abc", 5): (1, 4, 3, 2, 0),
    ("abc", 8): (2, 6, 5, 1, 7, 4, 3, 0),
    ("xyz", 2): (0, 1),
    ("xyz", 3): (2, 0, 1),
    ("xyz", 5): (4, 1, 3, 0, 2),
    ("xyz", 8): (5, 7, 1, 3, 2, 6, 0, 4),
}


@pytest.mark.parametrize("key_n", list(PINNED))
def test_pinned_permutations(key_n: tuple[str, int]) -> None:
    seed_key, n = key_n
    assert stable_permutation(seed_key, n) == PINNED[key_n]


def test_identity_for_n_0_and_1() -> None:
    for seed_key in ("", "any-key-at-all", "r12:v01-happy-high"):
        assert stable_permutation(seed_key, 0) == ()
        assert stable_permutation(seed_key, 1) == (0,)


def test_result_is_always_a_permutation_of_range_n() -> None:
    for seed_key in ("r12:v01-happy-high", "r23:cmp-001", "abc", "xyz", "", "z" * 200):
        for n in (0, 1, 2, 3, 5, 8, 20, 64):
            perm = stable_permutation(seed_key, n)
            assert sorted(perm) == list(range(n))


def test_deterministic_across_repeated_calls() -> None:
    assert stable_permutation("k", 10) == stable_permutation("k", 10)
    assert stable_permutation("k", 10) == stable_permutation("k", 10)


def test_distinct_across_keys() -> None:
    # 50 independent keys, one 8-item permutation each: no two collide. SHA-256 driven, so a
    # collision here is not expected on any run, let alone reliably reproducible.
    seen = {stable_permutation(f"key-{i}", 8) for i in range(50)}
    assert len(seen) == 50


def test_distinct_from_the_identity_and_from_each_other_for_the_pinned_keys() -> None:
    eight = [PINNED[(k, 8)] for k in ("r12:v01-happy-high", "r23:cmp-001", "abc", "xyz")]
    assert len(set(eight)) == len(eight)
    assert eight[0] != tuple(range(8))


def test_rejects_a_non_string_seed_key() -> None:
    with pytest.raises(TypeError):
        stable_permutation(123, 3)
    with pytest.raises(TypeError):
        stable_permutation(None, 3)


def test_rejects_a_bad_n() -> None:
    with pytest.raises(ValueError):
        stable_permutation("k", -1)
    with pytest.raises(ValueError):
        stable_permutation("k", 2.0)
    with pytest.raises(ValueError):
        stable_permutation("k", True)  # bool is not accepted as int here


def test_stable_shuffle_reorders_items_by_the_same_permutation() -> None:
    items = ["joyful", "cheerful", "pleased"]
    perm = stable_permutation("r12:v01-happy-high", len(items))
    assert stable_shuffle("r12:v01-happy-high", items) == tuple(items[i] for i in perm)
    assert stable_shuffle("r12:v01-happy-high", items) == ("pleased", "joyful", "cheerful")


def test_stable_shuffle_does_not_mutate_or_alias_the_input() -> None:
    items = ["a", "b", "c"]
    original = list(items)
    result = stable_shuffle("k", items)
    assert items == original
    assert isinstance(result, tuple)


def test_stable_shuffle_handles_empty_and_singleton_and_any_sequence_type() -> None:
    assert stable_shuffle("k", []) == ()
    assert stable_shuffle("k", ["only"]) == ("only",)
    assert sorted(stable_shuffle("k", ("a", "b"))) == ["a", "b"]


def test_exported_from_the_fixtures_package() -> None:
    from jev_cookbook import fixtures

    assert "stable_permutation" in fixtures.__all__
    assert "stable_shuffle" in fixtures.__all__
    assert fixtures.stable_permutation is stable_permutation
    assert fixtures.stable_shuffle is stable_shuffle
