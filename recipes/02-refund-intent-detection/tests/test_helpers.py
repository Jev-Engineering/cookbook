"""Tests for recipe 02's helpers. They load the helpers by file path.

A Noul's confidence (``jev_cookbook.evaluation.noul_confidence``) is ``|2p - 1|``, the same
Choice confidence formula applied to a yes/no Choice (docs/evaluation.md, "Noul three-path
pattern", S03). Tests that need a value near 0.5 still call ``noul_confidence`` themselves and
set ``min_confidence`` relative to what it returns, rather than hardcoding the number, so they
stay correct if the formula's exact value is ever revisited again. Tests that only need a
*far-from-0.5* probability (confidence close to 1) use plain numbers instead, since no
plausible formula revision would move those.
"""

from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold, select_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def confidence_of(noul):
    return noul_confidence([noul])[0]


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["refund_requested"]
    proposition = questions["refund_requested"]
    assert proposition.instructions == helpers.STATEMENT
    assert set(proposition.criteria) == {"true", "false"}
    assert all(isinstance(d, str) and d for d in proposition.criteria.values())


# min_confidence=0.1 is low enough that a far-from-0.5 noul (0.0, 0.1, 0.9, 1.0) clears the
# confidence gate, so these two tests exercise only the business threshold, not the gate.


@pytest.mark.parametrize("noul", [0.80, 0.85, 0.93, 1.0])
def test_a_confident_message_at_or_above_the_threshold_is_flagged(noul):
    result = helpers.route("RF1", answer(noul), threshold=0.80, min_confidence=0.1)
    assert (result.ticket_id, result.outcome, result.would_flag) == (
        "RF1",
        helpers.FLAGGED,
        True,
    )


@pytest.mark.parametrize("noul", [0.0, 0.10, 0.70, 0.79])
def test_a_confident_message_below_the_threshold_is_not_flagged(noul):
    result = helpers.route("RF1", answer(noul), threshold=0.80, min_confidence=0.1)
    assert (result.ticket_id, result.outcome, result.would_flag) == (
        "RF1",
        helpers.NOT_FLAGGED,
        False,
    )


def test_the_business_threshold_is_inclusive():
    confident = helpers.route("RF1", answer(0.80), threshold=0.80, min_confidence=0.1)
    just_below = helpers.route("RF1", answer(0.80 - 1e-9), threshold=0.80, min_confidence=0.1)
    assert (confident.outcome, confident.would_flag) == (helpers.FLAGGED, True)
    assert (just_below.outcome, just_below.would_flag) == (helpers.NOT_FLAGGED, False)


@pytest.mark.parametrize("noul", [0.48, 0.5, 0.52])
def test_low_confidence_goes_to_review_whichever_side_it_leans(noul):
    # Set min_confidence just above this noul's own confidence, computed rather than hardcoded.
    result = helpers.route(
        "RF1", answer(noul), threshold=0.80, min_confidence=confidence_of(noul) + 0.01
    )
    assert result.outcome == helpers.REVIEW
    # would_flag still reports what the business threshold alone would have decided.
    assert result.would_flag == (noul >= 0.80)


def test_the_confidence_gate_is_inclusive():
    noul = 0.9
    exact = helpers.route("RF1", answer(noul), threshold=0.80, min_confidence=confidence_of(noul))
    just_above = helpers.route(
        "RF1", answer(noul), threshold=0.80, min_confidence=confidence_of(noul) + 1e-9
    )
    assert exact.outcome == helpers.FLAGGED  # confidence == min_confidence clears the gate
    assert just_above.outcome == helpers.REVIEW


def test_a_high_confidence_wrong_leaning_message_is_still_flagged_not_reviewed():
    # The confidence gate protects against genuine ambiguity (noul near 0.5), not against a
    # confidently wrong answer (noul far from 0.5 on the "wrong" side of the gold label): it has
    # no way to tell the two apart, which is the point this test pins.
    noul = 0.95
    result = helpers.route("RF1", answer(noul), threshold=0.80, min_confidence=0.5)
    assert result.outcome == helpers.FLAGGED
    assert result.would_flag is True


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        helpers.route("RF1", answer(0.5), threshold=bad, min_confidence=0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_min_confidence_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
        helpers.route("RF1", answer(0.5), threshold=0.5, min_confidence=bad)


def test_the_state_hides_the_ticket_id():
    fields = {"ticket_id": "RF9", "text": "Please refund my order."}
    assert helpers.build_state(fields) == {"text": "Please refund my order."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive both cut-offs the way the notebook does -- the business threshold by F1 on
    validation, then the confidence gate among cut-offs that still cover at least 70% of
    validation -- and require a wrong, confidently-flagged `test` message at or above the gate:
    a mistake it would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["refund_requested"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_noul = [decide(e).noul for e in validation]
    val_gold = [labels[e.id] for e in validation]
    threshold = select_threshold(val_gold, val_noul, objective="f1")
    would_flag = [n >= threshold for n in val_noul]
    raw_correct = [f == g for f, g in zip(would_flag, val_gold, strict=True)]
    val_confidence = noul_confidence(val_noul)
    min_confidence = select_confidence_threshold(raw_correct, val_confidence, min_coverage=0.7)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_noul = [decide(e).noul for e in test]
    test_gold = [labels[e.id] for e in test]
    test_would_flag = [n >= threshold for n in test_noul]
    test_confidence = noul_confidence(test_noul)
    wrong_and_confident = [
        e.id
        for e, flag, gold, conf in zip(
            test, test_would_flag, test_gold, test_confidence, strict=True
        )
        if flag != gold and conf >= min_confidence
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
