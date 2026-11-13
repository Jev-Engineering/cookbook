"""Follow-ups to the image request profile and its preflight: hashing, the cap messages, one
profile per audited request, and agreement between the size count and the base64 validator."""

from __future__ import annotations

import base64
import itertools
import re

import pytest

from jev_cookbook import Noul, accounting, vision
from jev_cookbook.vision import (
    ImageRequestProfile,
    ImageRequestTooLarge,
    image_request_profile,
    preflight_image_request,
)

MIB = 1024 * 1024
CAP = 32 * MIB


def sized(n: int) -> dict[str, str]:
    """A raw asset whose ``data_base64`` decodes to exactly ``n`` bytes (content irrelevant)."""
    return {"type": "image", "format": "png", "data_base64": base64.b64encode(b"\0" * n).decode()}


# --- hashing -----------------------------------------------------------------------------------


def test_a_profile_is_hashable_and_equal_profiles_hash_equal_whatever_the_question_order():
    first = ImageRequestProfile(1, 10, 3, 30, 1, {"a": 1, "b": 1})
    second = ImageRequestProfile(1, 10, 3, 30, 1, {"b": 1, "a": 1})
    assert first == second and hash(first) == hash(second)
    assert len({first, second}) == 1
    assert first != ImageRequestProfile(1, 10, 3, 30, 1, {"a": 2, "b": 0})
    assert {first: "x"}[second] == "x"


def test_a_profile_from_a_real_request_is_hashable():
    profile = image_request_profile("<a>", {"q": Noul(instructions="See <a>.")}, {"<a>": sized(5)})
    assert hash(profile) == hash(
        image_request_profile("<a>", {"q": Noul(instructions="See <a>.")}, {"<a>": sized(5)})
    )


# --- the distinct check cannot fire alone ------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "instructions"),
    [
        ("<a>", "Fine?"),
        ("<a> <a> <b>", "Compare <b>."),
        ({"x": ["<a>", "<b> <c>"]}, "Use <c> and <c>."),
        ("<ab> <a>", "<abc>"),
    ],
)
def test_expanded_bytes_are_never_below_distinct_bytes(state, instructions):
    assets = {
        ref: sized(size)
        for ref, size in (("<a>", 7), ("<b>", 11), ("<c>", 3), ("<ab>", 5), ("<abc>", 2))
    }
    profile = image_request_profile(state, {"q": Noul(instructions=instructions)}, assets)
    assert profile.expanded_bytes >= profile.distinct_bytes
    assert profile.copies >= profile.distinct_assets


# --- messages ----------------------------------------------------------------------------------


def test_one_byte_over_the_cap_is_told_apart_from_the_cap_in_both_messages():
    with pytest.raises(ImageRequestTooLarge) as distinct:
        preflight_image_request(ImageRequestProfile(1, CAP + 1, 1, CAP + 1, 1, {"q": 0}))
    text = str(distinct.value)
    assert "33,554,433 bytes" in text and "33,554,432-byte (32 MiB) cap" in text
    with pytest.raises(ImageRequestTooLarge) as expanded:
        preflight_image_request(ImageRequestProfile(1, CAP, 2, CAP + 1, 2, {"q": 0}))
    text = str(expanded.value)
    assert "33,554,433 bytes" in text and "33,554,432-byte (32 MiB) cap" in text
    preflight_image_request(ImageRequestProfile(1, CAP, 1, CAP, 1, {}))  # at the cap: allowed


def test_the_expanded_message_lists_only_questions_that_hold_copies():
    per_question = {"a": 0, "b": 2, "c": 0, "d": 1}
    with pytest.raises(ImageRequestTooLarge) as caught:
        preflight_image_request(ImageRequestProfile(1, MIB, 3, CAP + 1, 0, per_question))
    text = str(caught.value)
    assert "per question {'b': 2, 'd': 1}" in text
    assert "'a'" not in text and "'c'" not in text


def test_the_expanded_message_says_when_no_question_holds_a_copy():
    with pytest.raises(ImageRequestTooLarge) as caught:
        preflight_image_request(ImageRequestProfile(1, MIB, 40, CAP + 1, 40, {"a": 0, "b": 0}))
    assert "40 in the state, none in any question" in str(caught.value)


def test_a_long_question_list_is_cut_to_ten_with_a_count_of_the_rest():
    per_question = {f"q{n:02d}": 1 for n in range(25)}
    with pytest.raises(ImageRequestTooLarge) as caught:
        preflight_image_request(ImageRequestProfile(1, MIB, 25, CAP + 1, 0, per_question))
    text = str(caught.value)
    assert "'q09': 1}" in text and "'q10'" not in text
    assert "and 15 more question(s) with copies" in text


# --- one profile per audited request ----------------------------------------------------------


def test_an_audited_image_request_computes_its_profile_once(monkeypatch):
    calls = []
    real = vision.image_request_profile

    def counting(*args):
        calls.append(args)
        return real(*args)

    monkeypatch.setattr(vision, "image_request_profile", counting)
    state, questions, assets = "<a> <a>", {"q": Noul(instructions="See <a>.")}, {"<a>": sized(4)}
    profile = accounting._profile(state, questions, assets)
    assert profile == {"distinct_images": 1, "images": 3}
    assert len(calls) == 1
    # A second request gets its own profile: nothing is carried over between requests.
    assert accounting._profile("<a>", questions, assets) == {"distinct_images": 1, "images": 2}
    assert len(calls) == 2
    assert accounting._ONE_REQUEST.get() is None


def test_the_shared_profile_is_cleared_when_a_counter_raises(monkeypatch):
    monkeypatch.setitem(accounting.PROFILE_COUNTERS, "zz_broken", lambda *args: -1)
    with pytest.raises(ValueError, match="non-negative int"):
        accounting._profile("<a>", {"q": Noul()}, {"<a>": sized(4)})
    assert accounting._ONE_REQUEST.get() is None


def test_a_counter_called_outside_an_audit_still_counts():
    count = accounting.PROFILE_COUNTERS["images"]
    assert count("<a> <a>", {"q": Noul()}, {"<a>": sized(4)}) == 2
    assert count("text", {"q": Noul()}, None) == 0


# --- base64 sizes agree with the validator -----------------------------------------------------


def _validator_length(encoded: str) -> int | None:
    """Decoded length when ``validate_image_asset``'s base64 step accepts ``encoded``, else None."""
    try:
        return len(vision._decode_base64(encoded))
    except ValueError:
        return None


# Canonical padded base64: whole groups of four, the last one optionally ending "==" or "=".
_CANONICAL_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")


def test_the_validator_accepts_exactly_canonical_base64_on_every_python_version():
    # Before Python 3.13, b64decode(validate=True) also accepted excess padding such as "=" or
    # "AAAA="; the validator must refuse it everywhere, as 3.13 and later do.
    for length in range(0, 9):
        for chars in itertools.product("Aw+=", repeat=length):
            encoded = "".join(chars)
            accepted = _validator_length(encoded) is not None
            assert accepted == bool(_CANONICAL_BASE64.fullmatch(encoded)), encoded
    for excess in ("=", "==", "AAAA=", "AAAA==", "Aw==="):
        with pytest.raises(ValueError, match="standard base64"):
            vision._decode_base64(excess)


def test_the_size_count_agrees_with_the_validator_for_every_short_string_including_excess_padding():
    # Every string of length 0 to 8 over a small alphabet that includes padding, so excess or
    # misplaced "=" is covered; runs on every interpreter in CI, Python 3.10 included.
    alphabet = "Aw+="
    checked = 0
    for length in range(0, 9):
        for chars in itertools.product(alphabet, repeat=length):
            encoded = "".join(chars)
            decoded = _validator_length(encoded)
            if decoded is None:
                continue
            checked += 1
            assert vision._encoded_size({"data_base64": encoded}) == decoded, encoded
    assert checked > 1000
