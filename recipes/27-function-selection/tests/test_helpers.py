"""Tests for recipe 27's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

EXPECTED_OPTION_NAMES = (
    "send_email",
    "schedule_meeting",
    "create_ticket",
    "set_reminder",
    "update_record",
    "lookup_contact",
    "no_function",
)


def _answer(choice: str, confidence: float, options=EXPECTED_OPTION_NAMES) -> ChoiceAnswer:
    """A synthetic Choice answer naming ``choice`` at (approximately) ``confidence``, spreading
    the rest evenly over the other options -- the same construction build_fixtures.py uses."""
    n = len(options)
    p_max = confidence * (1 - 1 / n) + 1 / n
    remaining = (1 - p_max) / (n - 1)
    probabilities = {name: (p_max if name == choice else remaining) for name in options}
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


# --------------------------------------------------------------------------------------------
# The catalog itself, against literal expected values (never helpers' own data, which would
# make the assertion self-referential).
# --------------------------------------------------------------------------------------------


def test_the_catalog_has_six_functions_plus_the_fallback():
    assert tuple(helpers.FUNCTIONS) == EXPECTED_OPTION_NAMES[:-1]
    assert helpers.OPTION_NAMES == EXPECTED_OPTION_NAMES
    assert helpers.NO_FUNCTION == "no_function"
    for name, spec in helpers.FUNCTIONS.items():
        assert spec["description"], name
        assert spec["schema"], name
        for arg_name, arg_spec in spec["schema"].items():
            assert arg_spec["type"] in (
                "string",
                "email",
                "email_list",
                "integer",
                "date",
                "record_id",
                "enum",
            ), (name, arg_name)
            assert isinstance(arg_spec["required"], bool), (name, arg_name)
            if arg_spec["type"] == "enum":
                assert len(arg_spec["enum"]) >= 2, (name, arg_name)


def test_build_questions_offers_every_option_with_a_description():
    order = helpers.option_order_for("some-item")
    assert sorted(order) == sorted(EXPECTED_OPTION_NAMES)
    questions = helpers.build_questions(order)
    assert set(questions) == {"function"}
    function = questions["function"]
    assert tuple(function.criteria) == order
    for name in EXPECTED_OPTION_NAMES:
        assert function.criteria[name]


def test_option_order_is_shuffled_and_not_the_authored_order():
    # stable_shuffle, not list position: at least one item's shuffled order must differ from
    # OPTION_NAMES itself, and different items must not all land on the same permutation.
    orders = {item_id: helpers.option_order_for(item_id) for item_id in ("r01", "r02", "r03")}
    assert any(order != helpers.OPTION_NAMES for order in orders.values())
    assert len(set(orders.values())) > 1
    # Deterministic: the same item id always gives the same order.
    assert helpers.option_order_for("r01") == orders["r01"]


# --------------------------------------------------------------------------------------------
# extract_arguments: the tested extractor, never a hand-written dict in ROWS.
# --------------------------------------------------------------------------------------------


def test_extract_arguments_parses_the_trailer():
    text = "Please send this now.\nArguments: to=ana@example.com; subject=Hello; body=Hi there"
    assert helpers.extract_arguments(text) == {
        "to": "ana@example.com",
        "subject": "Hello",
        "body": "Hi there",
    }


def test_extract_arguments_keeps_pipe_separated_lists_as_one_value():
    text = "Schedule it.\nArguments: title=Sync; attendees=a@example.com|b@example.com"
    arguments = helpers.extract_arguments(text)
    assert arguments["attendees"] == "a@example.com|b@example.com"


def test_extract_arguments_returns_empty_when_there_is_no_trailer():
    assert helpers.extract_arguments("Just a plain message with no arguments at all.") == {}


def test_extract_arguments_ignores_malformed_and_blank_pairs():
    text = "Go.\nArguments: to=ana@example.com; ; malformed; subject=Hi"
    assert helpers.extract_arguments(text) == {"to": "ana@example.com", "subject": "Hi"}


# --------------------------------------------------------------------------------------------
# validate_arguments: every violation kind the use case names, and the all-valid case.
# --------------------------------------------------------------------------------------------


def test_validate_arguments_reports_missing_required():
    violations = helpers.validate_arguments("send_email", {"to": "ana@example.com"})
    assert violations == [
        "missing required argument: subject",
        "missing required argument: body",
    ]


def test_validate_arguments_reports_wrong_type_for_every_type():
    assert helpers.validate_arguments(
        "send_email", {"to": "not-an-email", "subject": "s", "body": "b"}
    ) == ["wrong type for argument: to"]
    assert helpers.validate_arguments(
        "schedule_meeting",
        {
            "title": "Sync",
            "attendees": "a@example.com",
            "duration_minutes": "soon",
            "date": "2026-11-02",
        },
    ) == ["wrong type for argument: duration_minutes"]
    assert helpers.validate_arguments(
        "schedule_meeting",
        {
            "title": "Sync",
            "attendees": "a@example.com",
            "duration_minutes": "30",
            "date": "November 2nd",
        },
    ) == ["wrong type for argument: date"]
    assert helpers.validate_arguments(
        "update_record", {"record_id": "ABC-1", "field": "status", "value": "closed"}
    ) == ["wrong type for argument: record_id"]
    assert helpers.validate_arguments(
        "schedule_meeting",
        {
            "title": "Sync",
            "attendees": "a@example.com|not-an-email",
            "duration_minutes": "30",
            "date": "2026-11-02",
        },
    ) == ["wrong type for argument: attendees"]
    assert helpers.validate_arguments(
        "send_email", {"to": "a@example.com", "subject": "", "body": "b"}
    ) == ["wrong type for argument: subject"]


def test_validate_arguments_reports_value_outside_the_enumeration():
    assert helpers.validate_arguments("create_ticket", {"title": "t", "priority": "urgent"}) == [
        "value outside the enumeration for argument: priority"
    ]


def test_validate_arguments_accepts_a_valid_optional_argument_and_omitted_optionals():
    assert (
        helpers.validate_arguments(
            "send_email", {"to": "a@example.com", "subject": "s", "body": "b"}
        )
        == []
    )
    assert (
        helpers.validate_arguments(
            "send_email",
            {"to": "a@example.com", "subject": "s", "body": "b", "priority": "high"},
        )
        == []
    )
    assert helpers.validate_arguments(
        "send_email",
        {"to": "a@example.com", "subject": "s", "body": "b", "priority": "urgent"},
    ) == ["value outside the enumeration for argument: priority"]


def test_validate_arguments_combines_several_violation_kinds():
    violations = helpers.validate_arguments("create_ticket", {"priority": "urgent"})
    assert violations == [
        "missing required argument: title",
        "value outside the enumeration for argument: priority",
    ]


# --------------------------------------------------------------------------------------------
# resolve: the composed rule, every branch.
# --------------------------------------------------------------------------------------------


def test_resolve_sends_a_low_confidence_answer_to_review_whatever_it_names():
    actions, queue = ActionLog(), ReviewQueue()
    answer = _answer("send_email", 0.2)
    resolution = helpers.resolve(
        "r1",
        answer,
        {"to": "a@example.com", "subject": "s", "body": "b"},
        0.5,
        actions=actions,
        queue=queue,
    )
    assert resolution.outcome == helpers.REVIEW
    assert resolution.reason == "confidence below the threshold"
    assert len(actions) == 0
    assert len(queue) == 1

    # no_function is gated the same way: low confidence still goes to review, never treated as
    # an unconditionally-accepted fallback.
    actions2, queue2 = ActionLog(), ReviewQueue()
    low_no_function = _answer("no_function", 0.2)
    resolution2 = helpers.resolve("r2", low_no_function, {}, 0.5, actions=actions2, queue=queue2)
    assert resolution2.outcome == helpers.REVIEW
    assert resolution2.reason == "confidence below the threshold"


def test_resolve_accepts_a_confident_no_function_with_no_action_recorded():
    actions, queue = ActionLog(), ReviewQueue()
    answer = _answer("no_function", 0.9)
    resolution = helpers.resolve("r3", answer, {}, 0.5, actions=actions, queue=queue)
    assert resolution.outcome == helpers.NO_FUNCTION_OUTCOME
    assert resolution.choice == "no_function"
    assert len(actions) == 0
    assert len(queue) == 0


def test_resolve_sends_invalid_arguments_to_review_naming_the_violation():
    actions, queue = ActionLog(), ReviewQueue()
    answer = _answer("send_email", 0.9)
    resolution = helpers.resolve(
        "r4", answer, {"to": "a@example.com"}, 0.5, actions=actions, queue=queue
    )
    assert resolution.outcome == helpers.REVIEW
    assert resolution.reason == "missing required argument: subject"
    assert resolution.violations == (
        "missing required argument: subject",
        "missing required argument: body",
    )
    assert len(actions) == 0
    assert len(queue) == 1
    assert queue.pending()[0].reason == "missing required argument: subject"


def test_resolve_records_a_confident_valid_match_in_the_action_log():
    actions, queue = ActionLog(), ReviewQueue()
    answer = _answer("send_email", 0.9)
    arguments = {"to": "a@example.com", "subject": "s", "body": "b"}
    resolution = helpers.resolve("r5", answer, arguments, 0.5, actions=actions, queue=queue)
    assert resolution.outcome == helpers.EXECUTED
    assert resolution.choice == "send_email"
    assert len(actions) == 1
    assert len(queue) == 0
    entry = actions.to_dicts()[0]
    assert entry["kind"] == "send_email"
    assert entry["executed"] is False


def test_resolve_rejects_an_out_of_range_min_confidence():
    actions, queue = ActionLog(), ReviewQueue()
    answer = _answer("send_email", 0.9)
    with pytest.raises(ValueError):
        helpers.resolve("r6", answer, {}, 1.5, actions=actions, queue=queue)


# --------------------------------------------------------------------------------------------
# gold_outcome, task_correct, accepted_and_correct, and the invalid-argument hard-case helpers.
# --------------------------------------------------------------------------------------------


def test_gold_outcome_for_no_function_and_valid_and_invalid_real_functions():
    assert helpers.gold_outcome("no_function", {}) == ("no_function", "no_function")
    valid_args = {"to": "a@example.com", "subject": "s", "body": "b"}
    assert helpers.gold_outcome("send_email", valid_args) == ("executed", "send_email")
    assert helpers.gold_outcome("send_email", {"to": "a@example.com"}) == ("review", "send_email")


def test_task_correct_matches_the_execution_target_not_only_the_outcome():
    valid_args = {"to": "a@example.com", "subject": "s", "body": "b"}
    executed_right = helpers.Resolution(
        "r1", "send_email", helpers.EXECUTED, helpers.REASON_EXECUTED
    )
    assert helpers.task_correct(executed_right, "send_email", valid_args)

    # Executed, but the WRONG function -- a confidently wrong selection whose own schema
    # happened to accept these arguments. Outcome matches (both "executed"), but the function
    # that actually ran does not, so this is incorrect at task level.
    executed_wrong = helpers.Resolution(
        "r1", "lookup_contact", helpers.EXECUTED, helpers.REASON_EXECUTED
    )
    assert not helpers.task_correct(executed_wrong, "send_email", valid_args)

    reviewed = helpers.Resolution(
        "r1", "send_email", helpers.REVIEW, "confidence below the threshold"
    )
    assert not helpers.task_correct(reviewed, "send_email", valid_args)
    assert helpers.task_correct(reviewed, "send_email", {"to": "a@example.com"})

    no_function_right = helpers.Resolution(
        "r1", "no_function", helpers.NO_FUNCTION_OUTCOME, helpers.REASON_NO_FUNCTION
    )
    assert helpers.task_correct(no_function_right, "no_function", {})
    assert not helpers.task_correct(no_function_right, "send_email", valid_args)


def test_accepted_and_correct_pools_every_resolution():
    valid_args = {"to": "a@example.com", "subject": "s", "body": "b"}
    resolutions = [
        helpers.Resolution("r1", "send_email", helpers.EXECUTED, helpers.REASON_EXECUTED),
        helpers.Resolution("r2", "send_email", helpers.REVIEW, "confidence below the threshold"),
        helpers.Resolution(
            "r3", "no_function", helpers.NO_FUNCTION_OUTCOME, helpers.REASON_NO_FUNCTION
        ),
    ]
    gold = {"r1": "send_email", "r2": "send_email", "r3": "no_function"}
    # r2's arguments ARE valid, so the gold outcome for it is "executed" -- the stored REVIEW
    # resolution (confidence below the threshold) is therefore wrong at task level, not merely
    # "unanswered".
    arguments = {"r1": valid_args, "r2": valid_args, "r3": {}}
    accepted, correct = helpers.accepted_and_correct(resolutions, gold, arguments)
    assert accepted == [True, False, True]
    assert correct == [True, False, True]


def test_invalid_argument_hard_cases_and_rejection_rate():
    valid_args = {"to": "a@example.com", "subject": "s", "body": "b"}
    gold = {"r1": "send_email", "r2": "send_email", "r3": "no_function"}
    arguments = {"r1": {"to": "a@example.com"}, "r2": valid_args, "r3": {}}
    hard_cases = helpers.invalid_argument_hard_cases(gold, arguments)
    assert hard_cases == ["r1"]

    rejected = {
        "r1": helpers.Resolution(
            "r1", "send_email", helpers.REVIEW, "missing required argument: subject"
        )
    }
    assert helpers.invalid_argument_rejection_rate(rejected, hard_cases) == 1.0

    not_rejected = {
        "r1": helpers.Resolution("r1", "lookup_contact", helpers.EXECUTED, helpers.REASON_EXECUTED)
    }
    assert helpers.invalid_argument_rejection_rate(not_rejected, hard_cases) == 0.0

    with pytest.raises(ValueError):
        helpers.invalid_argument_rejection_rate({}, [])


# --------------------------------------------------------------------------------------------
# Fixture-facing guards: replay keys match the current questions, and the strong form of
# "stored answers are not all right".
# --------------------------------------------------------------------------------------------


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. Each example's own
    # shuffled option order (not a single shared `questions` object) is part of what the
    # replay key hashes.
    for example in load_inputs(RECIPE):
        order = helpers.option_order_for(example.id)
        questions = helpers.build_questions(order)
        expected = replay_key(helpers.build_state(example.fields), questions)
        assert example.replay_keys == (expected,)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard; this re-derives the frozen confidence gate from
    # `validation` (selection correctness: does the raw choice equal the gold function) and
    # requires a wrong `test` answer at or above it -- a mistake the gate would still let
    # through, which is what evaluating on `test` exists to catch.
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        order = helpers.option_order_for(example.id)
        questions = helpers.build_questions(order)
        return backend.decide(helpers.build_state(example.fields), questions)["function"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [val_answers[e.id].choice == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id for e in test if decide(e).choice != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
