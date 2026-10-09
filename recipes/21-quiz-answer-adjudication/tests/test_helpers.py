"""Tests for recipe 21's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


MATCH_ANSWER = answer(
    {"match": 0.80, "partial_match": 0.10, "no_match": 0.06, "needs_review": 0.04}
)
PARTIAL_ANSWER = answer(
    {"match": 0.15, "partial_match": 0.70, "no_match": 0.10, "needs_review": 0.05}
)
NO_MATCH_ANSWER = answer(
    {"match": 0.05, "partial_match": 0.10, "no_match": 0.80, "needs_review": 0.05}
)
REVIEW_ANSWER = answer(
    {"match": 0.25, "partial_match": 0.10, "no_match": 0.15, "needs_review": 0.50}
)
VAGUE_MATCH_ANSWER = answer(
    {"match": 0.30, "partial_match": 0.25, "no_match": 0.25, "needs_review": 0.20}
)

TEXT_FIELDS = {"quiz_id": "tower", "response": "a response the normaliser cannot settle"}
NUMBER_FIELDS = {"quiz_id": "moons", "response": "3"}


def test_the_options_are_fixed_by_python():
    # Against literal expected values, not helpers.OUTCOMES itself: comparing against the
    # module's own data would still pass if OUTCOMES and the criteria it feeds drifted
    # together, which is exactly the drift this test exists to catch.
    options = list(helpers.build_questions()["adjudication"].criteria)
    assert options == ["match", "partial_match", "no_match", "needs_review"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Mirrowgate.", "mirrowgate"),
        ("  mirrowgate  ", "mirrowgate"),
        ("MIRROWGATE", "mirrowgate"),
        ("an Observatory Tower", "observatory tower"),
        ("A Lantern Guild", "lantern guild"),
        ("Hale's Guild", "hale s guild"),
    ],
)
def test_normalize_text_folds_case_whitespace_punctuation_and_a_leading_article(raw, expected):
    assert helpers.normalize_text(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", 3.0),
        ("  3 moons  ", 3.0),
        ("three", 3.0),
        ("three moons", 3.0),
        ("THREE", 3.0),
        ("no idea", None),
        ("several", None),
    ],
)
def test_parse_number_reads_digits_and_number_words(raw, expected):
    assert helpers.parse_number(raw) == expected


def test_candidate_set_is_built_by_python_from_the_question_bank():
    assert helpers.candidate_set("tower") == ["Petra Lindqvist", "Lindqvist"]
    assert helpers.candidate_set("moons") == ["3"]


def test_build_state_hides_the_quiz_id_and_carries_the_candidate_set():
    state = helpers.build_state({"quiz_id": "capital", "response": "Mirrowgate"})
    assert state == {
        "question": "What is the capital of the kingdom of Threnvale?",
        "accepted_answers": ["Mirrowgate"],
        "response": "Mirrowgate",
    }


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("Petra Lindqvist", "match"),
        ("Petra Lindqvist.", "match"),
        ("  lindqvist  ", "match"),
        ("LINDQVIST", "match"),
        ("Petra Lindqvest", None),  # a misspelling: not an exact normalized match
        ("Doran Hale", None),  # a wrong entity: still not settled by the normaliser alone
    ],
)
def test_settle_resolves_text_questions_only_on_an_exact_normalized_match(response, expected):
    assert helpers.settle({"quiz_id": "tower", "response": response}) == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("3", "match"),
        ("three", "match"),
        ("3 moons", "match"),
        ("4", "no_match"),
        ("no idea", "no_match"),
        ("several", "no_match"),
    ],
)
def test_settle_always_resolves_number_questions_without_ever_asking_jev(response, expected):
    assert helpers.settle({"quiz_id": "moons", "response": response}) == expected


def test_a_settled_response_never_reads_the_answer_argument():
    # None stands in for "no Jev answer was ever requested"; adjudicate must not touch it
    # when the normaliser alone can decide, text or number.
    result = helpers.adjudicate("q1", {"quiz_id": "tower", "response": "Lindqvist"}, None, 0.5)
    assert (result.outcome, result.settled_without_a_call) == ("match", True)
    result = helpers.adjudicate("q2", {"quiz_id": "moons", "response": "4"}, None, 0.5)
    assert (result.outcome, result.settled_without_a_call) == ("no_match", True)


def test_the_normaliser_wins_even_over_a_contradicting_supplied_answer_text():
    # The normaliser must win unconditionally, not merely "when answer is None": a mutation
    # that reads a supplied answer whenever one exists (`settled = settle(fields) if answer is
    # None else None`) passes every other test in this file, because they only ever pass
    # `None` for a settleable response. This one does not: "Lindqvist" settles to `match`
    # outright, and a confident, contradicting `no_match` answer at a gate low enough to
    # accept it must still lose, on outcome, reason and settled_without_a_call alike.
    contradicting = answer(
        {"match": 0.05, "partial_match": 0.05, "no_match": 0.85, "needs_review": 0.05}
    )
    result = helpers.adjudicate(
        "q1", {"quiz_id": "tower", "response": "Lindqvist"}, contradicting, 0.0
    )
    assert result.outcome == "match"
    assert result.reason == "settled by the normaliser, no model call"
    assert result.settled_without_a_call is True


def test_the_normaliser_wins_even_over_a_contradicting_supplied_answer_number():
    contradicting = answer(
        {"match": 0.85, "partial_match": 0.05, "no_match": 0.05, "needs_review": 0.05}
    )
    result = helpers.adjudicate("q2", {"quiz_id": "moons", "response": "4"}, contradicting, 0.0)
    assert result.outcome == "no_match"
    assert result.reason == "settled by the normaliser, no model call"
    assert result.settled_without_a_call is True


def test_adjudication_example_id_is_whatever_the_caller_passed_not_the_quiz_id():
    # The first argument is this recipe's fixture id (e.g. "d02-review"), never the quiz id
    # inside fields (e.g. "tower"): the two happen to differ on every real fixture.
    settled = helpers.adjudicate(
        "d01-settled", {"quiz_id": "capital", "response": "Mirrowgate"}, None, 0.5
    )
    assert settled.example_id == "d01-settled"
    called = helpers.adjudicate("d02-review", TEXT_FIELDS, MATCH_ANSWER, 0.1)
    assert called.example_id == "d02-review"


def test_queue_item_carries_the_quiz_id_question_and_response():
    assert helpers.queue_item({"quiz_id": "tower", "response": "Lindqvist?"}) == {
        "quiz_id": "tower",
        "question": "Who first lit the Observatory Tower in the city of Veyla?",
        "response": "Lindqvist?",
    }


def test_the_settled_reason_is_pinned():
    result = helpers.adjudicate("q1", {"quiz_id": "moons", "response": "3"}, None, 0.5)
    assert result.reason == "settled by the normaliser, no model call"


def test_the_confident_accept_reason_is_pinned():
    result = helpers.adjudicate("q1", TEXT_FIELDS, MATCH_ANSWER, 0.1)
    assert result.reason == "confidence met the threshold"


def test_an_unsettled_response_without_an_answer_is_an_error():
    with pytest.raises(ValueError, match="needs a Jev answer"):
        helpers.adjudicate("q1", TEXT_FIELDS, None, 0.5)


@pytest.mark.parametrize("answer_obj", [MATCH_ANSWER, PARTIAL_ANSWER, NO_MATCH_ANSWER])
def test_a_confident_answer_is_accepted_as_is_whatever_the_choice(answer_obj):
    result = helpers.adjudicate("q1", TEXT_FIELDS, answer_obj, 0.5)
    assert result.outcome == answer_obj.choice
    assert result.settled_without_a_call is False


def test_the_model_choosing_needs_review_is_never_second_guessed_even_at_zero_confidence():
    result = helpers.adjudicate("q1", TEXT_FIELDS, REVIEW_ANSWER, 0.0)
    assert result.outcome == "needs_review"
    assert result.reason == "the model chose needs_review"


@pytest.mark.parametrize("answer_obj", [MATCH_ANSWER, PARTIAL_ANSWER, NO_MATCH_ANSWER])
def test_low_confidence_goes_to_needs_review_whatever_the_choice(answer_obj):
    result = helpers.adjudicate("q1", TEXT_FIELDS, answer_obj, answer_obj.confidence + 1e-9)
    assert result.outcome == "needs_review"
    assert result.reason == "confidence below the threshold"


def test_the_threshold_is_inclusive():
    assert (
        helpers.adjudicate("q1", TEXT_FIELDS, MATCH_ANSWER, MATCH_ANSWER.confidence).outcome
        == "match"
    )
    boundary = MATCH_ANSWER.confidence + 1e-9
    assert helpers.adjudicate("q1", TEXT_FIELDS, MATCH_ANSWER, boundary).outcome == "needs_review"


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.adjudicate("q1", TEXT_FIELDS, MATCH_ANSWER, bad)


def test_an_answer_with_even_odds_still_reaches_the_gate():
    # Not a hard case by itself, but confirms the gate reads .confidence, not .choice, for a
    # genuinely close call.
    result = helpers.adjudicate("q1", TEXT_FIELDS, VAGUE_MATCH_ANSWER, 0.5)
    assert result.outcome == "needs_review"
    assert result.reason == "confidence below the threshold"


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        settled = helpers.settle(example.fields)
        if settled is not None:
            assert example.replay_keys == ()
        else:
            assert example.replay_keys == (
                replay_key(helpers.build_state(example.fields), questions),
            )


def test_the_gold_label_is_not_concentrated_in_one_option_position():
    # Across the fixtures actually sent to Jev (a settled response never reaches this
    # question, so its gold label says nothing about option order), the correct option sits
    # in every one of the four positions `build_questions` lists them in at least once. S07
    # documents that a Choice answer can lean toward whichever option comes first; a fixture
    # set where the gold label always happened to sit in the same position could not catch a
    # rule that quietly exploited that instead of reading the response.
    gold = load_labels(RECIPE)
    positions = {
        list(helpers.OUTCOMES).index(gold[example.id])
        for example in load_inputs(RECIPE)
        if example.replay_keys and example.id in gold
    }
    assert positions == {0, 1, 2, 3}


def test_stored_answers_are_not_all_right():
    """At least one stored `test` answer sent to Jev is wrong (its raw `choice` does not match
    the gold label) while confident enough to clear the frozen confidence gate -- the fixture
    that keeps `test`'s selective risk non-zero rather than a gate that happens to look perfect
    (docs/fixtures.md, "Avoid synthetic responses so tidy that every model-free baseline scores
    perfectly on test"). The gate is chosen on `validation`'s called responses exactly as the
    notebook chooses it, not assumed."""
    examples = load_inputs(RECIPE)
    gold = load_labels(RECIPE)
    questions = helpers.build_questions()
    backend = get_backend(fixtures=responses_path(RECIPE))

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["adjudication"]

    val_called = [
        e for e in select_split(examples, "validation") if helpers.settle(e.fields) is None
    ]
    val_answers = [decide(e) for e in val_called]
    val_correct = [a.choice == gold[e.id] for e, a in zip(val_called, val_answers, strict=True)]
    val_confidence = [a.confidence for a in val_answers]
    gate = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)
    assert not math.isnan(gate)

    test_called = [e for e in select_split(examples, "test") if helpers.settle(e.fields) is None]
    test_answers = [decide(e) for e in test_called]
    wrong_and_confident = [
        a
        for e, a in zip(test_called, test_answers, strict=True)
        if a.choice != gold[e.id] and a.confidence >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer sent to Jev"
