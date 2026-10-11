"""Tests for recipe 12's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

CANDIDATES = ["fast", "swift", "speedy"]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def confident(option, candidates=CANDIDATES):
    """A clearly confident answer naming ``option`` (one of ``candidates`` or
    ``keep_original``)."""
    options = [*candidates, helpers.KEEP_ORIGINAL]
    others = [o for o in options if o != option]
    probabilities = {option: 0.90}
    probabilities.update({o: 0.10 / len(others) for o in others})
    return answer(probabilities)


def low_confidence(option, candidates=CANDIDATES):
    """A barely-ahead answer naming ``option``, confidence well under 0.5."""
    options = [*candidates, helpers.KEEP_ORIGINAL]
    others = [o for o in options if o != option]
    probabilities = {option: 0.35}
    probabilities.update({o: 0.65 / len(others) for o in others})
    return answer(probabilities)


def confident_foreign():
    """A confident answer naming an option that was never offered -- `resolve` must still
    reject it, even though the criteria `build_questions` asks with never offer such an option
    (the check is defensive, not reachable through replay or live)."""
    return answer({"not_a_supplied_option": 0.90, "also_not_one": 0.10})


def test_candidate_options_adds_keep_original_with_a_gloss_for_every_candidate():
    # Against a literal expected value, not helpers.KEEP_ORIGINAL itself: comparing against the
    # module's own constant would still pass if the constant's value and candidate_options'
    # ordering drifted together.
    criteria = helpers.candidate_options("quick", CANDIDATES)
    assert list(criteria) == ["fast", "swift", "speedy", "keep_original"]
    assert all(isinstance(d, str) and d for d in criteria.values())


def test_candidate_options_rejects_a_candidate_with_no_gloss():
    with pytest.raises(KeyError, match="not_a_real_word"):
        helpers.candidate_options("quick", ["fast", "not_a_real_word"])


def test_build_questions_names_the_word_and_keeps_candidate_order():
    questions = helpers.build_questions("quick", CANDIDATES)
    assert list(questions) == ["synonym"]
    synonym = questions["synonym"]
    assert "quick" in synonym.instructions
    assert "keep_original" in synonym.instructions
    # Literal expected value: see test_candidate_options_adds_keep_original_with_a_gloss_for_every_candidate.
    assert list(synonym.criteria) == ["fast", "swift", "speedy", "keep_original"]


def test_build_questions_rejects_an_empty_candidate_list():
    # Defensive, unreachable from this recipe's committed fixtures (every sentence supplies at
    # least one real candidate): with none, the only option would be keep_original alone, a
    # single-option Choice that is never built.
    with pytest.raises(ValueError, match="no_candidate_resolution"):
        helpers.build_questions("quick", [])


def test_no_candidate_resolution_is_a_final_keep_original_with_no_candidates():
    result = helpers.no_candidate_resolution("E1")
    assert (result.item_id, result.choice, result.outcome) == (
        "E1",
        helpers.KEEP_ORIGINAL,
        helpers.ACCEPTED,
    )


def test_the_state_hides_the_item_id_and_the_candidates():
    fields = {
        "item_id": "E1",
        "word": "quick",
        "sentence": "The reply was quick.",
        "candidates": CANDIDATES,
    }
    assert helpers.build_state(fields) == {"word": "quick", "sentence": "The reply was quick."}


@pytest.mark.parametrize("option", [*CANDIDATES, "keep_original"])
def test_a_confident_option_is_accepted_whatever_it_is(option):
    a = confident(option)
    result = helpers.resolve("E1", a, CANDIDATES, 0.5)
    assert (result.choice, result.outcome) == (option, helpers.ACCEPTED)


def test_a_confident_keep_original_is_accepted_like_any_other_option():
    # Unlike a Choice option that always means "the model could not decide" (recipe 07's
    # "unclear"), keep_original is a real, final answer and triggers no side effect, so a confident
    # keep_original is never routed to review just for being chosen.
    a = confident("keep_original")
    result = helpers.resolve("E1", a, CANDIDATES, 0.8)
    assert result.outcome == helpers.ACCEPTED
    assert result.reason == "confident"


@pytest.mark.parametrize("option", [*CANDIDATES, "keep_original"])
def test_a_low_confidence_answer_goes_to_review_whatever_it_is(option):
    a = low_confidence(option)
    assert a.choice == option
    assert a.confidence < 0.5
    result = helpers.resolve("E1", a, CANDIDATES, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


def test_choosing_an_option_never_offered_goes_to_review_even_when_confident():
    a = confident_foreign()
    assert a.choice not in ("fast", "swift", "speedy", "keep_original")
    assert a.confidence >= 0.8
    result = helpers.resolve("E1", a, CANDIDATES, 0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "not a supplied option"


def test_the_threshold_is_inclusive():
    a = confident("fast")
    t = a.confidence
    assert helpers.resolve("E1", a, CANDIDATES, t).outcome == helpers.ACCEPTED
    assert helpers.resolve("E1", a, CANDIDATES, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    a = confident("fast")
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.resolve("E1", a, CANDIDATES, bad)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example,
    # built from that example's own word and candidates (both shape the replay key).
    for example in load_inputs(RECIPE):
        word = example.fields["word"]
        candidates = example.fields["candidates"]
        questions = helpers.build_questions(word, candidates)
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """The threshold this recipe freezes is chosen on `validation` exactly as the notebook does;
    this test recomputes it the same way and asserts that at least one `test` answer is wrong at
    or above it, so the selective-prediction risk the notebook reports on `test` is never zero by
    construction. This is a re-derivation, not just a comment in `build_fixtures.py`, so a future
    fixture edit that accidentally removes the wrong-and-confident case fails CI."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        questions = helpers.build_questions(example.fields["word"], example.fields["candidates"])
        return backend.decide(helpers.build_state(example.fields), questions)["synonym"]

    val_examples = select_split(examples, "validation")
    val_answers = [decide(e) for e in val_examples]
    val_correct = [a.choice in labels[e.id] for e, a in zip(val_examples, val_answers, strict=True)]
    val_confidence = [a.confidence for a in val_answers]
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test_examples = select_split(examples, "test")
    wrong_at_or_above = [
        e.id
        for e in test_examples
        if (a := decide(e)).choice not in labels[e.id] and a.confidence >= threshold
    ]
    assert wrong_at_or_above, "no test answer is wrong at or above the frozen threshold"
