"""Tests for recipe 19's helpers. They load the helpers by file path."""

import re
from collections import Counter
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
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


def _frozen_threshold():
    """The threshold the notebook freezes, re-derived independently of it: chosen on
    `validation` exactly the way `select_confidence_threshold` is documented to, never copied
    from a run's printed output."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    val = select_split(load_inputs(RECIPE), "validation")
    answers = [backend.decide(helpers.build_state(e.fields), questions)["outcome"] for e in val]
    correct = [a.choice == labels[e.id] for a, e in zip(answers, val, strict=True)]
    confidence = [a.confidence for a in answers]
    return select_confidence_threshold(correct, confidence, target_accuracy=1.0)


def test_the_options_come_from_a_literal_expected_list():
    # Against literal expected values, not helpers' own data, which would make the assertion
    # self-referential: comparing OUTCOMES against OUTCOMES would still pass if the option list
    # and the table built from it drifted together.
    options = list(helpers.build_questions()["outcome"].criteria)
    assert options == list(EXPECTED_OUTCOMES)


def test_the_workflow_table_matches_a_literal_expected_mapping():
    assert helpers.WORKFLOWS == EXPECTED_WORKFLOWS


@pytest.mark.parametrize(
    "outcome", ("test_regression", "dependency_problem", "infrastructure_failure")
)
def test_confident_substantive_outcome_logs_an_automated_remedy(outcome):
    actions, queue = ActionLog(), ReviewQueue()
    confident = answer(_dist(outcome, 0.9))
    diagnosis = helpers.classify("build-1", confident, 0.5, actions=actions, queue=queue)
    assert (diagnosis.outcome, diagnosis.workflow) == (outcome, EXPECTED_WORKFLOWS[outcome])
    assert diagnosis.reason == "confident match"
    assert len(actions) == 1
    assert len(queue) == 0
    assert actions.to_dicts()[0]["kind"] == EXPECTED_WORKFLOWS[outcome]
    assert actions.to_dicts()[0]["executed"] is False


def test_confident_unknown_goes_to_the_review_queue_not_the_action_log():
    # unknown clears the same gate as everything else, but its workflow names no automated
    # remedy, so an accepted unknown answer is logged to the review queue, not the action log:
    # accepted, not rejected for low confidence, but still a person's call to make.
    actions, queue = ActionLog(), ReviewQueue()
    confident = answer(_dist("unknown", 0.9))
    diagnosis = helpers.classify("build-1", confident, 0.5, actions=actions, queue=queue)
    assert diagnosis.outcome == "unknown"
    assert diagnosis.workflow == "manual_triage"
    assert diagnosis.reason == "no option fits"
    assert len(actions) == 0
    assert len(queue) == 1
    item = queue.to_dicts()[0]
    assert item["reason"] == "no option fits"
    assert item["status"] == "pending"


@pytest.mark.parametrize("outcome", EXPECTED_OUTCOMES)
def test_low_confidence_goes_to_review_whatever_the_outcome(outcome):
    # The gate applies to every option alike, unknown included: there is exactly one condition
    # that sends an answer to review, and this is it.
    actions, queue = ActionLog(), ReviewQueue()
    unsure = answer(_dist(outcome, 0.30))  # confidence (0.30 - 0.25) / 0.75 = 0.0667
    diagnosis = helpers.classify("build-1", unsure, 0.5, actions=actions, queue=queue)
    assert diagnosis.outcome == "review"
    assert diagnosis.workflow is None
    assert diagnosis.reason == "confidence below the threshold"
    assert len(actions) == 0
    assert len(queue) == 1
    assert queue.to_dicts()[0]["reason"] == "confidence below the threshold"


def test_the_threshold_is_inclusive():
    confident = answer(_dist("test_regression", 0.85))
    at = helpers.classify(
        "build-1", confident, confident.confidence, actions=ActionLog(), queue=ReviewQueue()
    )
    just_above = helpers.classify(
        "build-1", confident, confident.confidence + 1e-9, actions=ActionLog(), queue=ReviewQueue()
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
    # The failure line's own window (2 lines: itself plus one after) plus the dependency
    # match's window (3 lines) plus one "..." gap marker: 6 lines, not a generous multiple of
    # MAX_EXCERPT_LINES that would let a much longer excerpt pass too.
    assert len(excerpt.splitlines()) == 6


def test_trimming_falls_back_to_the_start_when_nothing_matches():
    full_log = "\n".join(f"line {i}: nothing interesting happened" for i in range(30))
    excerpt = helpers.trim_log(full_log, max_lines=5)
    assert excerpt == "\n".join(f"line {i}: nothing interesting happened" for i in range(5))


def test_trimming_on_every_committed_fixture_keeps_the_matching_decisive_line():
    # "the trimming is checked against the untrimmed log kept in the fixtures" (README, the
    # notebook's "The state" section): this is the check, run over every one of the 40 inputs,
    # not only the two inline examples above and the one fixture shown in the notebook.
    for example in load_inputs(RECIPE):
        full_log = example.fields["full_log"]
        excerpt = helpers.trim_log(full_log)
        assert len(excerpt) <= len(full_log), example.id
        for pattern in (helpers.DEPENDENCY_RE, helpers.INFRASTRUCTURE_RE):
            match = pattern.search(full_log)
            if match:
                assert match.group(0) in excerpt, (example.id, match.group(0))


DEPENDENCY_ALTERNATIVES = (
    r"ModuleNotFoundError",
    r"ImportError: cannot import",
    r"No matching distribution found",
    r"Could not find a version that satisfies",
    r"conflicting dependencies",
    r"version solving failed",
)
INFRASTRUCTURE_ALTERNATIVES = (
    r"runner has received a shutdown signal",
    r"[Ll]ost communication with the (runner|server)",
    r"This step has timed out",
    r"OOMKilled",
    r"exit code 137",
    r"exit code 143",
    r"Connection reset by peer",
    r"self-hosted runner lost",
    r"The operation was canceled",
)


def test_the_regex_alternatives_above_match_the_compiled_patterns():
    # Pins the lists above against the real patterns (not split on "|", which would mangle the
    # one alternative that has its own internal "|": "(runner|server)").
    assert helpers.DEPENDENCY_RE.pattern == "|".join(DEPENDENCY_ALTERNATIVES)
    assert helpers.INFRASTRUCTURE_RE.pattern == "|".join(INFRASTRUCTURE_ALTERNATIVES)


def test_every_dependency_and_infrastructure_pattern_fires_on_a_fixture():
    # A public regex alternative that never matches any fixture would silently widen the
    # notebook's keyword-regex baseline's reach with nothing here to exercise it.
    logs = [e.fields["full_log"] for e in load_inputs(RECIPE)]
    for alternative in DEPENDENCY_ALTERNATIVES + INFRASTRUCTURE_ALTERNATIVES:
        compiled = re.compile(alternative)
        assert any(compiled.search(log) for log in logs), alternative


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


def test_a_wrong_test_answer_survives_the_frozen_gate():
    """A working confidence gate does not catch everything: at least one wrong `test` answer
    has confidence at or above the threshold `select_confidence_threshold` actually freezes
    (re-derived here, not a literal unrelated to it), so `test` risk is non-zero."""
    threshold = _frozen_threshold()
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    confident_and_wrong = [
        e.id
        for e in select_split(load_inputs(RECIPE), "test")
        if (a := backend.decide(helpers.build_state(e.fields), questions)["outcome"]).confidence
        >= threshold
        and a.choice != labels[e.id]
    ]
    assert confident_and_wrong, "test should keep at least one wrong answer the frozen gate accepts"


def test_every_workflow_row_is_exercised_by_an_accepted_answer():
    """Every row of `WORKFLOWS` fires for at least one accepted answer on each split: the
    recipe's headline, picking the next diagnostic workflow from the table, is demonstrated for
    the whole table, not half of it."""
    threshold = _frozen_threshold()
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    for split in ("validation", "test"):
        actions, queue = ActionLog(), ReviewQueue()
        for e in select_split(load_inputs(RECIPE), split):
            a = backend.decide(helpers.build_state(e.fields), questions)["outcome"]
            helpers.classify(e.fields["build_id"], a, threshold, actions=actions, queue=queue)
        fired = set(Counter(entry["kind"] for entry in actions.to_dicts()))
        fired |= {
            entry["item"]["workflow"]
            for entry in queue.to_dicts()
            if entry["reason"] == "no option fits"
        }
        assert fired == set(helpers.WORKFLOWS.values()), (split, fired)
