"""Tests for recipe 09's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, validate_recipe

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


CLEAR_INVOICE = answer(
    {"invoices": 0.90, "contracts": 0.03, "reports": 0.03, "correspondence": 0.02, "unsorted": 0.02}
)
CLEAR_UNSORTED = answer(
    {"invoices": 0.03, "contracts": 0.03, "reports": 0.03, "correspondence": 0.03, "unsorted": 0.88}
)

# One low-confidence answer per real folder, each barely ahead of the rest (confidence 0.0375),
# so a rule that exempts only one folder from the threshold still fails this file's test for it.
LOW_CONFIDENCE_BY_FOLDER = {
    "invoices": answer(
        {
            "invoices": 0.23,
            "contracts": 0.20,
            "reports": 0.19,
            "correspondence": 0.19,
            "unsorted": 0.19,
        }
    ),
    "contracts": answer(
        {
            "invoices": 0.19,
            "contracts": 0.23,
            "reports": 0.20,
            "correspondence": 0.19,
            "unsorted": 0.19,
        }
    ),
    "reports": answer(
        {
            "invoices": 0.19,
            "contracts": 0.19,
            "reports": 0.23,
            "correspondence": 0.20,
            "unsorted": 0.19,
        }
    ),
    "correspondence": answer(
        {
            "invoices": 0.20,
            "contracts": 0.19,
            "reports": 0.19,
            "correspondence": 0.23,
            "unsorted": 0.19,
        }
    ),
}


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["destination"]
    destination = questions["destination"]
    assert list(destination.criteria) == [
        "invoices",
        "contracts",
        "reports",
        "correspondence",
        "unsorted",
    ]
    assert all(isinstance(d, str) and d for d in destination.criteria.values())
    assert isinstance(destination.instructions, str) and destination.instructions


def test_a_confident_real_folder_is_placed():
    result = helpers.propose_destination("F1", CLEAR_INVOICE, 0.3)
    assert (result.file_id, result.destination, result.outcome) == (
        "F1",
        "invoices",
        helpers.PLACED,
    )


def test_jev_naming_unsorted_is_never_placed_however_confident():
    result = helpers.propose_destination("F1", CLEAR_UNSORTED, 0.3)
    assert result.destination is None
    assert result.outcome == helpers.REVIEW
    assert result.reason == "no folder matches"


@pytest.mark.parametrize("folder", ["invoices", "contracts", "reports", "correspondence"])
def test_a_low_confidence_folder_goes_unsorted_whatever_the_folder(folder):
    a = LOW_CONFIDENCE_BY_FOLDER[folder]
    assert a.choice == folder
    assert a.confidence < 0.5
    result = helpers.propose_destination("F1", a, 0.5)
    assert result.destination is None
    assert result.outcome == helpers.REVIEW
    assert "threshold" in result.reason


def test_the_threshold_is_inclusive():
    t = CLEAR_INVOICE.confidence
    assert helpers.propose_destination("F1", CLEAR_INVOICE, t).outcome == helpers.PLACED
    assert helpers.propose_destination("F1", CLEAR_INVOICE, t + 1e-9).outcome == helpers.REVIEW


def test_selection_signal_excludes_unsorted_so_the_threshold_is_never_affected_by_it():
    # Mutation check: an unsorted answer has no real confidence a selector could use (it is
    # never placed, whatever its confidence), so selection_signal must leave it out of the
    # search entirely rather than standing in some confidence number for it. With it excluded,
    # even the loosest possible target (0.0: accept any accuracy) can only select a real,
    # in-range confidence that propose_destination will accept as a threshold.
    answers = [CLEAR_INVOICE, CLEAR_UNSORTED, *LOW_CONFIDENCE_BY_FOLDER.values()]
    gold = ["invoices", "unsorted", *LOW_CONFIDENCE_BY_FOLDER.keys()]

    correct, confidence = helpers.selection_signal(answers, gold)
    assert len(confidence) == len(answers) - 1  # the unsorted answer is excluded
    assert all(0.0 <= c <= 1.0 for c in confidence)

    threshold = select_confidence_threshold(correct, confidence, target_accuracy=0.0)
    assert 0.0 <= threshold <= 1.0
    helpers.propose_destination("F1", CLEAR_INVOICE, threshold)  # must not raise


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.propose_destination("F1", CLEAR_INVOICE, bad)


def test_the_state_hides_the_file_id():
    fields = {"file_id": "F9", "filename": "notes.txt", "excerpt": "It works fine."}
    assert helpers.build_state(fields) == {"filename": "notes.txt", "excerpt": "It works fine."}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example;
    # adapt this when an example needs a dependent second request (CONTRIBUTING: a question that
    # depends on an earlier answer goes in a later request), where the example lists a key for
    # each request in order.
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    assert validate_recipe(RECIPE).mode == "replay"
    for example in examples:
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    """A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    caught every mistake, which would hide the exact lesson this fixture set exists to teach.
    Re-derive the threshold the way the notebook does (the lowest confidence at which every
    validation answer naming a real folder is correct) and require a wrong `test` answer at or
    above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["destination"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_correct, val_confidence = helpers.selection_signal(
        [decide(e) for e in validation], [labels[e.id] for e in validation]
    )
    threshold = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if decide(e).choice != helpers.UNSORTED
        and decide(e).choice != labels[e.id]
        and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
