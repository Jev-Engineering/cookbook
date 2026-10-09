"""Tests for recipe 19's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

EXPECTED_OUTCOMES = ("test_regression", "dependency_problem", "infrastructure_failure", "unknown")
EXPECTED_WORKFLOWS = {
    "test_regression": "rerun_suite_with_bisect",
    "dependency_problem": "pin_and_rebuild_dependencies",
    "infrastructure_failure": "requeue_on_fresh_runner",
    "unknown": "manual_triage",
}


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _dist(top, p_max):
    rest = (1.0 - p_max) / 3.0
    return {name: (p_max if name == top else rest) for name in EXPECTED_OUTCOMES}


def test_the_options_come_from_a_literal_expected_list():
    # Against literal expected values, not helpers' own data, which would make the assertion
    # self-referential: comparing OUTCOMES against OUTCOMES would still pass if the option list
    # and the table built from it drifted together.
    options = list(helpers.build_questions()["outcome"].criteria)
    assert options == list(EXPECTED_OUTCOMES)


def test_the_workflow_table_matches_a_literal_expected_mapping():
    assert helpers.WORKFLOWS == EXPECTED_WORKFLOWS


@pytest.mark.parametrize("outcome", EXPECTED_OUTCOMES)
def test_confident_known_outcome_is_accepted_and_logs_its_workflow(outcome):
    actions, queue = ActionLog(), ReviewQueue()
    confident = answer(_dist(outcome, 0.9))
    diagnosis = helpers.classify("build-1", confident, 0.5, actions=actions, queue=queue)
    assert (diagnosis.outcome, diagnosis.workflow) == (outcome, EXPECTED_WORKFLOWS[outcome])
    # unknown's reason is always "no option fits": it bypasses the gate entirely, whatever the
    # confidence, so it is never a "confident match" the way the other three outcomes are.
    assert diagnosis.reason == ("no option fits" if outcome == "unknown" else "confident match")
    assert len(actions) == 1
    assert len(queue) == 0


@pytest.mark.parametrize(
    "outcome", ("test_regression", "dependency_problem", "infrastructure_failure")
)
def test_low_confidence_goes_to_review_for_every_substantive_outcome(outcome):
    actions, queue = ActionLog(), ReviewQueue()
    unsure = answer(_dist(outcome, 0.30))  # confidence (0.30 - 0.25) / 0.75 = 0.0667
    diagnosis = helpers.classify("build-1", unsure, 0.5, actions=actions, queue=queue)
    assert diagnosis.outcome == "review"
    assert diagnosis.workflow is None
    assert diagnosis.reason == "confidence below the threshold"
    assert len(actions) == 0
    assert len(queue) == 1


def test_unknown_is_never_gated_even_at_the_lowest_possible_confidence():
    # unknown bypasses the confidence check entirely: even a bare plurality (confidence just
    # above 0) is delivered as final, never sent to review, whatever the threshold.
    actions, queue = ActionLog(), ReviewQueue()
    barely = answer(_dist("unknown", 0.26))
    diagnosis = helpers.classify("build-1", barely, 1.0, actions=actions, queue=queue)
    assert diagnosis.outcome == "unknown"
    assert diagnosis.workflow == "manual_triage"
    assert diagnosis.reason == "no option fits"
    assert len(actions) == 1
    assert len(queue) == 0


def test_an_outcome_with_no_workflow_entry_goes_to_review():
    # Defensive, like the template's `not in QUEUES` branch: the backend already rejects a
    # choice outside the question's own options, but the rule keeps its own check.
    actions, queue = ActionLog(), ReviewQueue()
    odd = answer(
        {
            "test_regression": 0.1,
            "dependency_problem": 0.1,
            "infrastructure_failure": 0.1,
            "other": 0.7,
        }
    )
    diagnosis = helpers.classify("build-1", odd, 0.0, actions=actions, queue=queue)
    assert diagnosis.outcome == "review"
    assert diagnosis.reason == "not a workflow Python may use"
    assert len(actions) == 0
    assert len(queue) == 1


def test_the_threshold_is_inclusive():
    actions, queue = ActionLog(), ReviewQueue()
    confident = answer(_dist("test_regression", 0.85))
    at = helpers.classify(
        "build-1", confident, confident.confidence, actions=ActionLog(), queue=ReviewQueue()
    )
    just_above = helpers.classify(
        "build-1", confident, confident.confidence + 1e-9, actions=actions, queue=queue
    )
    assert at.outcome == "test_regression"
    assert just_above.outcome == "review"


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify(
            "build-1",
            answer(_dist("test_regression", 0.9)),
            bad,
            actions=ActionLog(),
            queue=ReviewQueue(),
        )


def test_the_state_carries_only_the_trimmed_excerpt():
    fields = {
        "build_id": "CI-9",
        "full_log": "line one\nFAILED tests/x.py::y\nline three\nline four",
    }
    state = helpers.build_state(fields)
    assert list(state) == ["log_excerpt"]
    assert "build_id" not in state["log_excerpt"]


def test_trimming_keeps_a_decisive_line_far_from_the_first_failure():
    filler = "\n".join(f"tests/test_module_{i:02d}.py passed" for i in range(40))
    full_log = (
        "FAILED tests/test_unrelated.py::test_flaky - AssertionError\n"
        f"{filler}\n"
        "ERROR: ModuleNotFoundError: No module named 'acme_sdk.v9'\n"
        "a harmless line right after the decisive one\n"
        "another harmless line further away\n"
        "more trailing noise that stays out of the excerpt"
    )
    excerpt = helpers.trim_log(full_log)
    assert "ModuleNotFoundError" in excerpt
    assert "AssertionError" in excerpt
    assert "more trailing noise" not in excerpt
    assert len(excerpt.splitlines()) <= helpers.MAX_EXCERPT_LINES + 10  # "..." gap markers


def test_trimming_falls_back_to_the_start_when_nothing_matches():
    full_log = "\n".join(f"line {i}: nothing interesting happened" for i in range(30))
    excerpt = helpers.trim_log(full_log, max_lines=5)
    assert excerpt == "\n".join(f"line {i}: nothing interesting happened" for i in range(5))


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    wrong = [
        e.id
        for e in load_inputs(RECIPE)
        if e.id in labels
        and backend.decide(helpers.build_state(e.fields), questions)["outcome"].choice
        != labels[e.id]
    ]
    assert wrong, "the fixtures should contain some wrong answers"


def test_at_least_one_wrong_answer_on_test_is_confident():
    # So that selective risk on `test` is non-zero: a wrong answer the frozen threshold would
    # still accept, not only ones below it.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    confident_and_wrong = [
        e.id
        for e in load_inputs(RECIPE)
        if e.split == "test"
        and e.id in labels
        and (a := backend.decide(helpers.build_state(e.fields), questions)["outcome"]).confidence
        >= 0.6
        and a.choice != labels[e.id]
    ]
    assert confident_and_wrong, "test should keep at least one wrong, confident answer"
