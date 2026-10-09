"""Tests for recipe 10's helpers. They load the helpers by file path.

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

from jev_cookbook import NoulAnswer, Provenance, load_helpers, replay_key
from jev_cookbook.evaluation import noul_confidence
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def confidence_of(noul):
    return noul_confidence([noul])[0]


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["relevant"]
    proposition = questions["relevant"]
    assert proposition.instructions == helpers.STATEMENT
    assert set(proposition.criteria) == {"true", "false"}
    assert all(isinstance(d, str) and d for d in proposition.criteria.values())


# min_confidence=0.1 is low enough that a far-from-0.5 noul (0.0, 0.1, 0.9, 1.0) clears the
# confidence gate, so these two tests exercise only the business threshold, not the gate.


@pytest.mark.parametrize("noul", [0.55, 0.70, 0.90, 1.0])
def test_a_confident_pair_at_or_above_the_threshold_is_relevant(noul):
    # min_confidence=0.01 is low enough that even a noul right at the business threshold
    # (confidence exactly 0.10) clears the gate, so this test exercises only the threshold.
    result = helpers.check_relevance("AR1", answer(noul), threshold=0.55, min_confidence=0.01)
    assert (result.pair_id, result.outcome, result.is_relevant) == (
        "AR1",
        helpers.RELEVANT,
        True,
    )


@pytest.mark.parametrize("noul", [0.0, 0.10, 0.40, 0.549])
def test_a_confident_pair_below_the_threshold_is_not_relevant(noul):
    result = helpers.check_relevance("AR1", answer(noul), threshold=0.55, min_confidence=0.01)
    assert (result.pair_id, result.outcome, result.is_relevant) == (
        "AR1",
        helpers.NOT_RELEVANT,
        False,
    )


def test_the_business_threshold_is_inclusive():
    confident = helpers.check_relevance("AR1", answer(0.55), threshold=0.55, min_confidence=0.01)
    just_below = helpers.check_relevance(
        "AR1", answer(0.55 - 1e-9), threshold=0.55, min_confidence=0.01
    )
    assert (confident.outcome, confident.is_relevant) == (helpers.RELEVANT, True)
    assert (just_below.outcome, just_below.is_relevant) == (helpers.NOT_RELEVANT, False)


@pytest.mark.parametrize("noul", [0.48, 0.5, 0.52])
def test_low_confidence_goes_to_review_whichever_side_it_leans(noul):
    # Set min_confidence just above this noul's own confidence, computed rather than hardcoded.
    result = helpers.check_relevance(
        "AR1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul) + 0.01
    )
    assert result.outcome == helpers.REVIEW
    # is_relevant still reports what the business threshold alone would have decided.
    assert result.is_relevant == (noul >= 0.55)


def test_the_confidence_gate_is_inclusive():
    noul = 0.9
    exact = helpers.check_relevance(
        "AR1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul)
    )
    just_above = helpers.check_relevance(
        "AR1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul) + 1e-9
    )
    assert exact.outcome == helpers.RELEVANT  # confidence == min_confidence clears the gate
    assert just_above.outcome == helpers.REVIEW


def test_a_high_confidence_wrong_leaning_pair_is_still_decided_not_reviewed():
    # The confidence gate protects against genuine ambiguity (noul near 0.5), not against a
    # confidently wrong answer (noul far from 0.5 on the "wrong" side of the gold label): it has
    # no way to tell the two apart, which is the point this test pins (this recipe's
    # "-hard-wrong" fixtures are exactly this shape).
    noul = 0.95
    result = helpers.check_relevance("AR1", answer(noul), threshold=0.55, min_confidence=0.5)
    assert result.outcome == helpers.RELEVANT
    assert result.is_relevant is True


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        helpers.check_relevance("AR1", answer(0.5), threshold=bad, min_confidence=0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_min_confidence_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
        helpers.check_relevance("AR1", answer(0.5), threshold=0.5, min_confidence=bad)


def test_the_state_hides_the_pair_id():
    fields = {"pair_id": "AR9", "question": "How do I log in?", "response": "Use your email."}
    assert helpers.build_state(fields) == {
        "question": "How do I log in?",
        "response": "Use your email.",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
