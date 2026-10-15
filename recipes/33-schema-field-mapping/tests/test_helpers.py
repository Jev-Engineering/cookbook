"""Tests for recipe 33's helpers. They load the helpers by file path."""

import importlib.util
import json
import re
from collections import namedtuple
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def _load_build_fixtures():
    """Import build_fixtures.py by file path, the same way tests/test_build_fixtures.py does,
    so ROWS and its helper functions are plain Python objects rather than re-parsed output."""
    spec = importlib.util.spec_from_file_location(
        "recipe33_build_fixtures_for_helpers_test", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Literal expected option set, typed independently of helpers.TARGET_SCHEMA so the assertion
# below is not self-referential (comparing the module's own data to itself).
EXPECTED_TARGET_FIELDS = [
    "customer_email",
    "customer_id",
    "order_total",
    "order_date",
    "loyalty_tier",
    "shipping_country",
    "product_sku",
    "is_gift_order",
]


def confident(choice, peak=0.85):
    """A full-option probability vector peaked on ``choice``, remainder spread evenly."""
    options = list(helpers.build_questions()["target"].criteria)
    rest = [o for o in options if o != choice]
    each = (1.0 - peak) / len(rest)
    probs = {o: each for o in rest}
    probs[choice] = peak
    return ChoiceAnswer.from_probabilities(probs, Provenance.synthetic())


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["target"]
    criteria = questions["target"].criteria
    assert set(criteria) == set(EXPECTED_TARGET_FIELDS) | {helpers.AMBIGUOUS, helpers.UNMAPPED}
    assert all(isinstance(text, str) and text for text in criteria.values())
    assert isinstance(questions["target"].instructions, str) and questions["target"].instructions


def test_target_schema_has_every_type_category_normalize_type_understands():
    # Every category SOURCE_TYPE_TO_CATEGORY can produce is actually used by some target field,
    # and vice versa, so neither side of the type check has a category the other never reaches.
    schema_categories = {target.type for target in helpers.TARGET_SCHEMA.values()}
    normalized_categories = set(helpers.SOURCE_TYPE_TO_CATEGORY.values())
    assert schema_categories == normalized_categories


def test_normalize_type_rejects_an_unknown_declared_type():
    with pytest.raises(KeyError):
        helpers.normalize_type("nvarchar")


def test_the_state_hides_the_task_id():
    fields = {
        "task_id": "batch_z99",
        "field_name": "weird_col",
        "declared_type": "varchar",
        "description": "A free-text note.",
    }
    assert helpers.build_state(fields) == {
        "field_name": "weird_col",
        "declared_type": "varchar",
        "description": "A free-text note.",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per field.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_every_stored_answers_top_choice_matches_its_row_spec():
    """A fixture-spec shorthand must never default the label-bearing argument, and every
    committed stored answer's own top choice must be the one its row's spec names -- not merely
    close to it, and not some other value a later edit silently substituted.
    ``build_fixtures.answers_for`` reads ``spec["choice"]`` with ``[...]``, never
    ``.get(..., default)``, so a row missing it would already be a ``KeyError`` at build time;
    this test additionally proves every row that *did* specify a choice is honoured by the
    committed ``responses.json``. With ``ambiguous`` and ``unmapped`` both live options here, a
    default that quietly filled in a real target field for every row would turn every
    unmapped/ambiguous row into a mapped one without ever raising."""
    module = _load_build_fixtures()
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    assert len(module.ROWS) > 1
    for row in module.ROWS:
        _ident, _split, task_id, field_name, declared_type, description, _label, spec = row
        fields = module._fields(task_id, field_name, declared_type, description)
        key = module.replay_key(module.helpers.build_state(fields), module.QUESTIONS)
        assert responses[key]["answers"]["target"]["choice"] == spec["choice"]


# ---------------------------------------------------------------------------------------------
# gate_field: confidence and declared-type checks, with no knowledge of any other field yet.
# ---------------------------------------------------------------------------------------------


def test_ambiguous_is_sent_to_review_regardless_of_confidence():
    # Even a high-confidence `ambiguous` answer is a deferral, never a final answer.
    result = helpers.gate_field(
        "f1", "t1", "some_col", "varchar", confident(helpers.AMBIGUOUS), 0.99
    )
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_AMBIGUOUS
    assert result.final_target is None


class _FakeAnswer:
    """A stand-in for a typed answer naming an option outside the question's own set.
    ``ChoiceAnswer`` itself refuses to construct one (its ``choice`` must be a key of its own
    ``probabilities``), and ``jev_cookbook``'s backends already reject such an option at the
    boundary (docs/backends.md), so this exercises `gate_field`'s defensive membership check in
    isolation, the same guard several other recipes' rules keep even though nothing in this
    recipe's own fixtures ever trips it."""

    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence


def test_a_foreign_option_is_rejected_defensively():
    bogus = _FakeAnswer("made_up_option", 0.9)
    result = helpers.gate_field("f1", "t1", "some_col", "varchar", bogus, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_INVALID_OPTION


def test_confidence_below_the_threshold_is_sent_to_review():
    weak = confident("customer_email", peak=0.30)
    result = helpers.gate_field("f1", "t1", "some_col", "varchar", weak, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


def test_the_gate_is_inclusive():
    a = confident("customer_email", peak=0.70)
    at = helpers.gate_field("f1", "t1", "some_col", "varchar", a, a.confidence)
    above = helpers.gate_field("f1", "t1", "some_col", "varchar", a, a.confidence + 1e-9)
    assert at.outcome == helpers.ACCEPTED
    assert above.outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_gate_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.gate_field("f1", "t1", "some_col", "varchar", confident("customer_email"), bad)


def test_unmapped_is_accepted_at_any_remaining_confidence_with_no_type_check():
    result = helpers.gate_field("f1", "t1", "some_col", "varchar", confident(helpers.UNMAPPED), 0.5)
    assert result.outcome == helpers.ACCEPTED
    assert result.final_target == helpers.UNMAPPED
    assert result.reason == helpers.REASON_UNMAPPED_ACCEPTED


def test_a_type_compatible_confident_choice_is_accepted():
    result = helpers.gate_field("f1", "t1", "mail_col", "varchar", confident("customer_email"), 0.5)
    assert result.outcome == helpers.ACCEPTED
    assert result.final_target == "customer_email"
    assert result.reason == helpers.REASON_MAPPED_ACCEPTED


def test_a_declared_type_that_does_not_match_the_chosen_target_is_sent_to_review():
    # customer_email is a "string" target; "int" is a different category.
    result = helpers.gate_field("f1", "t1", "mail_col", "int", confident("customer_email"), 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_TYPE_MISMATCH


@pytest.mark.parametrize("target_name", EXPECTED_TARGET_FIELDS)
def test_every_target_field_is_reachable_and_type_checked(target_name):
    # Every one of the eight real targets, named with its own compatible declared type, is
    # accepted; named with an incompatible one, instead, it is sent to review. Guards against a
    # category accidentally shared (or not shared) between two targets going unnoticed.
    wanted_category = helpers.TARGET_SCHEMA[target_name].type
    compatible_type = next(
        declared
        for declared, category in helpers.SOURCE_TYPE_TO_CATEGORY.items()
        if category == wanted_category
    )
    incompatible_type = next(
        declared
        for declared, category in helpers.SOURCE_TYPE_TO_CATEGORY.items()
        if category != wanted_category
    )
    good = helpers.gate_field("f1", "t1", "col", compatible_type, confident(target_name), 0.5)
    assert good.outcome == helpers.ACCEPTED
    assert good.final_target == target_name
    bad = helpers.gate_field("f1", "t1", "col", incompatible_type, confident(target_name), 0.5)
    assert bad.outcome == helpers.REVIEW
    assert bad.reason == helpers.REASON_TYPE_MISMATCH


# ---------------------------------------------------------------------------------------------
# apply_one_to_one / compose_task: the cross-field composition.
# ---------------------------------------------------------------------------------------------


def _accepted(field_id, task_id, field_name, target):
    return helpers.FieldOutcome(
        field_id,
        task_id,
        field_name,
        target,
        helpers.ACCEPTED,
        target,
        helpers.REASON_MAPPED_ACCEPTED,
    )


def test_two_fields_proposing_different_targets_pass_through_unchanged():
    outcomes = [
        _accepted("f1", "t1", "a", "customer_email"),
        _accepted("f2", "t1", "b", "customer_id"),
    ]
    result = helpers.apply_one_to_one(outcomes)
    assert result == outcomes


def test_two_fields_proposing_the_same_real_target_are_both_sent_to_review():
    outcomes = [
        _accepted("f1", "t1", "a", "shipping_country"),
        _accepted("f2", "t1", "b", "shipping_country"),
    ]
    result = helpers.apply_one_to_one(outcomes)
    assert [o.outcome for o in result] == [helpers.REVIEW, helpers.REVIEW]
    assert all(o.reason == helpers.REASON_CONFLICT for o in result)
    assert all(o.final_target is None for o in result)


def test_several_fields_may_share_unmapped_with_no_conflict():
    outcomes = [
        helpers.FieldOutcome(
            "f1",
            "t1",
            "a",
            helpers.UNMAPPED,
            helpers.ACCEPTED,
            helpers.UNMAPPED,
            helpers.REASON_UNMAPPED_ACCEPTED,
        ),
        helpers.FieldOutcome(
            "f2",
            "t1",
            "b",
            helpers.UNMAPPED,
            helpers.ACCEPTED,
            helpers.UNMAPPED,
            helpers.REASON_UNMAPPED_ACCEPTED,
        ),
    ]
    result = helpers.apply_one_to_one(outcomes)
    assert all(o.outcome == helpers.ACCEPTED for o in result)


def test_a_field_already_under_review_never_triggers_a_conflict():
    reviewed = helpers.FieldOutcome(
        "f1", "t1", "a", "shipping_country", helpers.REVIEW, None, helpers.REASON_LOW_CONFIDENCE
    )
    accepted = _accepted("f2", "t1", "b", "shipping_country")
    result = helpers.apply_one_to_one([reviewed, accepted])
    by_id = {o.field_id: o for o in result}
    assert by_id["f1"].reason == helpers.REASON_LOW_CONFIDENCE  # unchanged
    assert by_id["f2"].outcome == helpers.ACCEPTED  # no competing *accepted* proposal


def test_compose_task_runs_the_gate_before_the_one_to_one_check():
    rows = [
        ("f1", "a", "varchar", confident("shipping_country", peak=0.85)),
        ("f2", "b", "varchar", confident("shipping_country", peak=0.85)),
    ]
    result = helpers.compose_task("t1", rows, 0.5)
    assert all(o.outcome == helpers.REVIEW and o.reason == helpers.REASON_CONFLICT for o in result)


def test_flipping_one_fields_choice_changes_its_siblings_composed_outcome():
    """Both the model's Choice and Python's validation must be shown to matter. Start
    from the two real, committed `validation` fields that collide on `shipping_country`
    (ship_to_cc, alt_country_note) and show that changing only ONE field's stored Choice (what
    the model answered) changes the OTHER field's composed outcome (what Python decided) --
    proof that the one-to-one check is not a fixed per-field verdict, and that the model's
    answer is not inert once Python gets hold of it.
    """
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    ship_to_cc = examples["v11-conflict"]
    alt_country_note = examples["v12-conflict"]
    ship_answer = backend.decide(helpers.build_state(ship_to_cc.fields), questions)["target"]
    alt_answer = backend.decide(helpers.build_state(alt_country_note.fields), questions)["target"]
    assert ship_answer.choice == alt_answer.choice == "shipping_country"

    rows = [
        (
            "v11-conflict",
            ship_to_cc.fields["field_name"],
            ship_to_cc.fields["declared_type"],
            ship_answer,
        ),
        (
            "v12-conflict",
            alt_country_note.fields["field_name"],
            alt_country_note.fields["declared_type"],
            alt_answer,
        ),
    ]
    before = {o.field_id: o for o in helpers.compose_task("batch_v06", rows, 0.5)}
    assert before["v11-conflict"].outcome == helpers.REVIEW
    assert before["v12-conflict"].outcome == helpers.REVIEW

    # Change only alt_country_note's stored Choice to something that does not collide.
    changed_alt_answer = confident(helpers.UNMAPPED)
    rows_changed = [rows[0], (rows[1][0], rows[1][1], rows[1][2], changed_alt_answer)]
    after = {o.field_id: o for o in helpers.compose_task("batch_v06", rows_changed, 0.5)}
    assert after["v11-conflict"].outcome == helpers.ACCEPTED
    assert after["v11-conflict"].final_target == "shipping_country"
    assert after["v12-conflict"].outcome == helpers.ACCEPTED
    assert after["v12-conflict"].final_target == helpers.UNMAPPED


def test_flipping_a_declared_type_on_a_real_fixture_changes_the_composed_outcome():
    """The type-compatibility half of the same property: `order_total_code` (validation) is stored as
    `varchar` and the model's own answer, `order_total`, is semantically right but type-
    mismatched, so Python's validation holds it for review. Changing only its declared type to
    one that matches `order_total`'s own category flips the composed outcome to accepted, with
    no change to the model's answer at all -- proof the type check is doing real work, not
    merely rubber-stamping whatever the model said."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    example = next(e for e in load_inputs(RECIPE) if e.id == "v07-type")
    stored_answer = backend.decide(helpers.build_state(example.fields), questions)["target"]
    assert stored_answer.choice == "order_total"

    rows = [("v07-type", "order_total_code", "varchar", stored_answer)]
    before = helpers.compose_task("batch_v04", rows, 0.5)[0]
    assert before.outcome == helpers.REVIEW
    assert before.reason == helpers.REASON_TYPE_MISMATCH

    rows_changed = [("v07-type", "order_total_code", "numeric", stored_answer)]
    after = helpers.compose_task("batch_v04", rows_changed, 0.5)[0]
    assert after.outcome == helpers.ACCEPTED
    assert after.final_target == "order_total"


def test_conflict_count_counts_only_conflicts():
    outcomes = [
        _accepted("f1", "t1", "a", "customer_email"),
        helpers.FieldOutcome("f2", "t1", "b", "x", helpers.REVIEW, None, helpers.REASON_AMBIGUOUS),
        helpers.FieldOutcome("f3", "t1", "c", "x", helpers.REVIEW, None, helpers.REASON_CONFLICT),
        helpers.FieldOutcome("f4", "t1", "d", "x", helpers.REVIEW, None, helpers.REASON_CONFLICT),
    ]
    assert helpers.conflict_count(outcomes) == 2


# ---------------------------------------------------------------------------------------------
# field_accepted_and_correct / task_accepted_and_correct
# ---------------------------------------------------------------------------------------------


def test_field_accepted_and_correct():
    outcomes = [
        _accepted("f1", "t1", "a", "customer_email"),
        helpers.FieldOutcome("f2", "t1", "b", "x", helpers.REVIEW, None, helpers.REASON_AMBIGUOUS),
        _accepted("f3", "t2", "c", "shipping_country"),
    ]
    gold = {"f1": "customer_email", "f2": "customer_id", "f3": "product_sku"}
    accepted, correct = helpers.field_accepted_and_correct(outcomes, gold)
    assert accepted == [True, False, True]
    # f2 is under review (final_target is None), so it reads as incorrect against any gold,
    # deterministically, not merely "unspecified" (evaluate_outcomes never reads it either way).
    assert correct == [True, False, False]


def test_task_accepted_and_correct_requires_every_field_of_a_task():
    outcomes = [
        _accepted("f1", "t1", "a", "customer_email"),
        _accepted("f2", "t1", "b", "customer_id"),
        _accepted("f3", "t2", "c", "shipping_country"),
        helpers.FieldOutcome("f4", "t2", "d", "x", helpers.REVIEW, None, helpers.REASON_AMBIGUOUS),
    ]
    gold = {
        "f1": "customer_email",
        "f2": "customer_id",
        "f3": "shipping_country",
        "f4": "loyalty_tier",
    }
    task_ids, accepted, correct = helpers.task_accepted_and_correct(outcomes, gold)
    assert task_ids == ["t1", "t2"]
    assert accepted == [True, False]  # t2 has one field under review
    # t2 is unaccepted because f4's final_target is None, which also makes it read as
    # incorrect against gold["f4"] deterministically (evaluate_outcomes never reads it either
    # way, since accepted[1] is False).
    assert correct == [True, False]


def test_task_accepted_and_correct_catches_a_task_where_one_field_is_wrong():
    outcomes = [
        _accepted("f1", "t1", "a", "customer_email"),
        _accepted("f2", "t1", "b", "customer_id"),  # wrong, but still accepted
    ]
    gold = {"f1": "customer_email", "f2": "loyalty_tier"}
    task_ids, accepted, correct = helpers.task_accepted_and_correct(outcomes, gold)
    assert task_ids == ["t1"]
    assert accepted == [True]
    assert correct == [False]


# ---------------------------------------------------------------------------------------------
# submit_reviews
# ---------------------------------------------------------------------------------------------


def test_submit_reviews_queues_only_review_outcomes_in_order():
    accepted_outcome = _accepted("f1", "t1", "a", "customer_email")
    reviewed_outcome = helpers.FieldOutcome(
        "f2", "t1", "b", "x", helpers.REVIEW, None, helpers.REASON_AMBIGUOUS
    )
    answers = {"f1": confident("customer_email"), "f2": confident(helpers.AMBIGUOUS)}
    queue = ReviewQueue()
    helpers.submit_reviews(queue, [accepted_outcome, reviewed_outcome], answers)
    assert len(queue) == 1
    item = queue.to_dicts()[0]
    assert item["item"]["field_id"] == "f2"
    assert item["reason"] == helpers.REASON_AMBIGUOUS
    assert item["answer"]["choice"] == helpers.AMBIGUOUS


# ---------------------------------------------------------------------------------------------
# rows_for_task / compose_split: the split-level grouping, called by the notebook too.
# ---------------------------------------------------------------------------------------------

_FakeExample = namedtuple("_FakeExample", ["id", "fields"])


def _fake_example(field_id, task_id, field_name="col", declared_type="varchar"):
    return _FakeExample(
        field_id, {"task_id": task_id, "field_name": field_name, "declared_type": declared_type}
    )


def test_rows_for_task_groups_by_task_id_preserving_order():
    """Pins the grouping itself, independent of composition: two fields of the same task stay
    together, in the order they were given, and a third field of a different task lands in its
    own group. A grouping bug that keyed every example to one constant task (or dropped
    `task_id` and grouped globally) would fail this directly, before it ever reached
    `compose_split` or the one-to-one check."""
    e1 = _fake_example("f1", "ta")
    e2 = _fake_example("f2", "ta")
    e3 = _fake_example("f3", "tb")
    decisions = {
        "f1": confident("customer_email"),
        "f2": confident("customer_id"),
        "f3": confident("order_date"),
    }
    grouped = helpers.rows_for_task([e1, e2, e3], decisions)
    assert set(grouped) == {"ta", "tb"}
    assert [row[0] for row in grouped["ta"]] == ["f1", "f2"]
    assert [row[0] for row in grouped["tb"]] == ["f3"]


def test_compose_split_checks_the_one_to_one_constraint_within_each_task_only():
    """Two fields in DIFFERENT tasks that both pick the same real target must not conflict: the
    one-to-one constraint is checked within one task's own fields, never across a whole split.
    This is exactly the property a grouping bug -- merging every field of a split into one task,
    say -- would break (a mutation on `helpers.rows_for_task` that always grouped under one
    constant key makes this fail, turning this field's own, correct `ACCEPTED` outcome into a
    manufactured conflict). The notebook and this file both call `helpers.compose_split`, never
    a private copy of the grouping, so a bug here cannot pass one copy and fail silently in the
    other."""
    e1 = _fake_example("f1", "ta")
    e2 = _fake_example("f2", "tb")
    decisions = {"f1": confident("shipping_country"), "f2": confident("shipping_country")}
    outcomes = helpers.compose_split([e1, e2], decisions, 0.5)
    assert all(o.outcome == helpers.ACCEPTED for o in outcomes)
    assert {o.final_target for o in outcomes} == {"shipping_country"}


# ---------------------------------------------------------------------------------------------
# End-to-end over the real fixtures: the threshold, the non-zero `test` risk, and the queue.
# ---------------------------------------------------------------------------------------------


def _decisions(backend, questions, examples):
    return {
        e.id: backend.decide(helpers.build_state(e.fields), questions)["target"] for e in examples
    }


# A coverage floor (the share of validation fields a plain confidence gate alone must answer)
# is chosen deliberately here instead of asking select_confidence_threshold for perfect
# validation accuracy (target_accuracy=1.0): the floor is a property of how much of validation
# the gate may ignore, not a demand that it be perfect. See notebook cell `python-md`.
MIN_COVERAGE = 0.85
THRESHOLD = None  # computed lazily in the fixture below; module-level for the helpers above


@pytest.fixture(autouse=True, scope="module")
def _freeze_threshold():
    global THRESHOLD
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    val_decisions = _decisions(backend, questions, validation)
    val_correct = [val_decisions[e.id].choice == labels[e.id] for e in validation]
    val_confidence = [val_decisions[e.id].confidence for e in validation]
    THRESHOLD = select_confidence_threshold(val_correct, val_confidence, min_coverage=MIN_COVERAGE)
    yield


def test_the_frozen_threshold_objective_is_pinned():
    """Pin the objective and its parameter: the notebook's selection cell and this file must
    agree on both, so a later edit that changes `min_coverage` or swaps in `target_accuracy` in
    only one of the two is caught here, before the consequentiality proofs above describe a
    selection procedure the notebook no longer runs."""
    assert THRESHOLD == pytest.approx(0.7777777777777778)


def test_both_threshold_objectives_select_the_same_gate_on_validation():
    """`python-md` says that on THIS fixture set the alternative objective
    (``target_accuracy=1.0``) selects the same gate as ``min_coverage=MIN_COVERAGE``, which is
    why the preference between them is an argument about which floor to ask for rather than
    about which cut it yields. That is a property of the committed answers, not of either
    function, so a fixture edit could falsify the sentence silently; both cuts are recomputed
    here from the committed responses and compared to each other, never to a literal."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = select_split(examples, "validation")
    val_decisions = _decisions(backend, questions, validation)
    val_correct = [val_decisions[e.id].choice == labels[e.id] for e in validation]
    val_confidence = [val_decisions[e.id].confidence for e in validation]
    by_coverage = select_confidence_threshold(
        val_correct, val_confidence, min_coverage=MIN_COVERAGE
    )
    by_accuracy = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)
    assert by_accuracy == by_coverage


def test_stored_answers_are_not_all_right():
    """Re-derives the frozen threshold directly (the strong form: a wrong `test` answer must
    clear a gate re-computed here, not merely exist somewhere). A wrong-and-confident raw answer
    is a necessary condition, not by itself this recipe's lesson: the stronger assertion below
    is on the full composed pipeline (`gate_field`, then `apply_one_to_one`) -- at least one
    `test` field is *accepted* with the *wrong* final target, a mistake nothing in this
    recipe's own validation catches."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)

    validation = select_split(examples, "validation")
    val_decisions = _decisions(backend, questions, validation)
    val_correct = [val_decisions[e.id].choice == labels[e.id] for e in validation]
    val_confidence = [val_decisions[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(val_correct, val_confidence, min_coverage=MIN_COVERAGE)

    test = select_split(examples, "test")
    test_decisions = _decisions(backend, questions, test)
    wrong_and_confident = [
        e.id
        for e in test
        if test_decisions[e.id].choice != labels[e.id]
        and test_decisions[e.id].confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong raw test answer"

    outcomes = helpers.compose_split(test, test_decisions, threshold)
    accepted_and_wrong = [
        o.field_id
        for o in outcomes
        if o.outcome == helpers.ACCEPTED and o.final_target != labels[o.field_id]
    ]
    assert accepted_and_wrong == ["t16-wrong"]


def test_evaluate_outcomes_reports_a_nonzero_risk_at_both_levels_on_test():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    test = select_split(examples, "test")
    test_decisions = _decisions(backend, questions, test)
    outcomes = helpers.compose_split(test, test_decisions, THRESHOLD)

    field_accepted, field_correct = helpers.field_accepted_and_correct(outcomes, labels)
    field_result = evaluate_outcomes(field_accepted, field_correct)
    assert 0.0 < field_result.risk < 1.0

    task_ids, task_accepted, task_correct = helpers.task_accepted_and_correct(outcomes, labels)
    task_result = evaluate_outcomes(task_accepted, task_correct)
    assert 0.0 < task_result.risk < 1.0
    assert "batch_t08" in task_ids


def test_the_conflict_is_caught_on_both_splits():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    for split in ("validation", "test"):
        split_examples = select_split(examples, split)
        decisions = _decisions(backend, questions, split_examples)
        outcomes = helpers.compose_split(split_examples, decisions, THRESHOLD)
        assert helpers.conflict_count(outcomes) == 2


def test_the_review_queue_holds_every_review_outcome_from_both_splits_and_nothing_else():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)

    # Written independently of the submission below: the exact ids this fixture set's
    # `validation` and `test` splits send to review at the frozen threshold, in the order the
    # notebook submits them (validation, then test, each in task order, fields in input order
    # within a task).
    EXPECTED_REVIEWED_IDS = [
        "v05-ambiguous",
        "v06-wrong",
        "v07-type",
        "v11-conflict",
        "v12-conflict",
        "t05-ambiguous",
        "t06-type",
        "t10-conflict",
        "t11-conflict",
    ]

    queue = ReviewQueue()
    all_ids = set()
    for split in ("validation", "test"):
        split_examples = select_split(examples, split)
        decisions = _decisions(backend, questions, split_examples)
        outcomes = helpers.compose_split(split_examples, decisions, THRESHOLD)
        helpers.submit_reviews(queue, outcomes, decisions)
        all_ids |= {e.id for e in split_examples}

    submitted_ids = [item["item"]["field_id"] for item in queue.to_dicts()]
    assert submitted_ids == EXPECTED_REVIEWED_IDS
    assert len(queue) == len(EXPECTED_REVIEWED_IDS)
    demo_ids = {e.id for e in select_split(examples, "demo")}
    assert demo_ids.isdisjoint(submitted_ids)


def test_the_notebooks_min_coverage_matches_this_files_pinned_value():
    """The frozen gate's objective parameter is defined twice, deliberately: once in the
    notebook's own `python-threshold` cell, once as this file's `MIN_COVERAGE`. Nothing ties
    the two together structurally (a notebook cell's source is not an importable value), so an
    edit that changed only the notebook's own `MIN_COVERAGE` would otherwise leave every test in
    this file green while the notebook ran a different selection than the one these tests
    describe. Parse the committed notebook's cell directly and pin the agreement."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-threshold")
    source = "".join(cell["source"])
    match = re.search(r"MIN_COVERAGE\s*=\s*([0-9.]+)", source)
    assert match, "notebook cell 'python-threshold' no longer defines MIN_COVERAGE"
    assert float(match.group(1)) == MIN_COVERAGE
