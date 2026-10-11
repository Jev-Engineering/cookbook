"""Tests for recipe 31's helpers. They load the helpers by file path."""

import inspect
import json
from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    pool_label_decisions,
    select_confidence_threshold,
    select_threshold,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


# --------------------------------------------------------------------------------------------
# the questions
# --------------------------------------------------------------------------------------------


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {
        "authentication_concern",
        "input_validation_concern",
        "data_loss_concern",
    }
    authentication = questions[helpers.AUTHENTICATION_CONCERN]
    input_validation = questions[helpers.INPUT_VALIDATION_CONCERN]
    data_loss = questions[helpers.DATA_LOSS_CONCERN]
    assert authentication.instructions == (
        "The patch weakens, removes, or bypasses an authentication or authorization check "
        "that was previously enforced."
    )
    assert input_validation.instructions == (
        "The patch leaves external input unvalidated or unsanitized before that input reaches "
        "a sensitive operation such as a query, a file path, a command, or a template."
    )
    assert data_loss.instructions == (
        "The patch risks permanent, unrecoverable loss of data that is already stored."
    )
    for question in (authentication, input_validation, data_loss):
        assert set(question.criteria) == {"true", "false"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # (all three concerns together): every example lists exactly one key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --------------------------------------------------------------------------------------------
# build_state: Jev sees the diff unchanged
# --------------------------------------------------------------------------------------------


def test_build_state_carries_only_the_diff():
    fields = {"diff": "--- a/x.py\n+++ b/x.py\n@@\n-old\n+new\n"}
    state = helpers.build_state(fields)
    assert set(state) == {"diff"}
    assert state["diff"] == fields["diff"]


# --------------------------------------------------------------------------------------------
# decide_concerns: the business tag and the confidence gate, per concern
# --------------------------------------------------------------------------------------------


class _FakeNoul:
    def __init__(self, noul):
        self.noul = noul


def _answers(auth_noul, input_noul, dataloss_noul):
    return {
        helpers.AUTHENTICATION_CONCERN: _FakeNoul(auth_noul),
        helpers.INPUT_VALIDATION_CONCERN: _FakeNoul(input_noul),
        helpers.DATA_LOSS_CONCERN: _FakeNoul(dataloss_noul),
    }


_THRESHOLDS = {
    helpers.AUTHENTICATION_CONCERN: 0.58,
    helpers.INPUT_VALIDATION_CONCERN: 0.50,
    helpers.DATA_LOSS_CONCERN: 0.61,
}


def test_decide_concerns_tags_each_proposition_against_its_own_threshold():
    decisions = helpers.decide_concerns(
        _answers(0.90, 0.10, 0.90), _THRESHOLDS, confidence_gate=0.3
    )
    assert decisions[helpers.AUTHENTICATION_CONCERN].tag is True
    assert decisions[helpers.INPUT_VALIDATION_CONCERN].tag is False
    assert decisions[helpers.DATA_LOSS_CONCERN].tag is True
    assert decisions[helpers.AUTHENTICATION_CONCERN].gated is False
    assert decisions[helpers.INPUT_VALIDATION_CONCERN].gated is False


def test_decide_concerns_gates_on_confidence_whatever_the_tag_says():
    # noul 0.55 is below the authentication threshold (tag False) but its confidence,
    # |2*0.55-1|=0.1, is below a 0.3 gate, so it must be marked gated regardless of the tag.
    decisions = helpers.decide_concerns(
        _answers(0.55, 0.90, 0.90), _THRESHOLDS, confidence_gate=0.3
    )
    assert decisions[helpers.AUTHENTICATION_CONCERN].tag is False
    assert decisions[helpers.AUTHENTICATION_CONCERN].gated is True


@pytest.mark.parametrize("bad_gate", [-0.1, 1.1])
def test_decide_concerns_rejects_an_out_of_range_confidence_gate(bad_gate):
    with pytest.raises(ValueError):
        helpers.decide_concerns(_answers(0.5, 0.5, 0.5), _THRESHOLDS, confidence_gate=bad_gate)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_decide_concerns_rejects_an_out_of_range_threshold(bad_threshold):
    thresholds = {**_THRESHOLDS, helpers.AUTHENTICATION_CONCERN: bad_threshold}
    with pytest.raises(ValueError):
        helpers.decide_concerns(_answers(0.5, 0.5, 0.5), thresholds, confidence_gate=0.3)


def test_decide_concerns_rejects_thresholds_that_do_not_name_exactly_labels():
    with pytest.raises(ValueError):
        helpers.decide_concerns(
            _answers(0.5, 0.5, 0.5),
            {helpers.AUTHENTICATION_CONCERN: 0.9, helpers.INPUT_VALIDATION_CONCERN: 0.9},
            confidence_gate=0.3,
        )
    with pytest.raises(ValueError):
        helpers.decide_concerns(
            _answers(0.5, 0.5, 0.5),
            {**_THRESHOLDS, "extra": 0.5},
            confidence_gate=0.3,
        )


def test_decide_concerns_tag_is_inclusive_at_the_threshold():
    decisions = helpers.decide_concerns(
        _answers(0.58, 0.50, 0.61), _THRESHOLDS, confidence_gate=0.0
    )
    assert decisions[helpers.AUTHENTICATION_CONCERN].tag is True
    assert decisions[helpers.INPUT_VALIDATION_CONCERN].tag is True
    assert decisions[helpers.DATA_LOSS_CONCERN].tag is True


# --------------------------------------------------------------------------------------------
# priority_from_concerns and review_priority: the deterministic composition, every
# label/outcome combination
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flagged,expected_priority,expected_reason",
    [
        (frozenset(), helpers.ROUTINE, helpers.REASON_ROUTINE),
        (
            frozenset({helpers.AUTHENTICATION_CONCERN}),
            helpers.ELEVATED,
            "flagged concerns: authentication_concern",
        ),
        (
            frozenset({helpers.INPUT_VALIDATION_CONCERN}),
            helpers.ELEVATED,
            "flagged concerns: input_validation_concern",
        ),
        (
            frozenset({helpers.DATA_LOSS_CONCERN}),
            helpers.URGENT,
            "flagged concerns: data_loss_concern",
        ),
        (
            frozenset({helpers.AUTHENTICATION_CONCERN, helpers.INPUT_VALIDATION_CONCERN}),
            helpers.URGENT,
            "flagged concerns: authentication_concern, input_validation_concern",
        ),
        (
            frozenset({helpers.AUTHENTICATION_CONCERN, helpers.DATA_LOSS_CONCERN}),
            helpers.URGENT,
            "flagged concerns: authentication_concern, data_loss_concern",
        ),
        (
            frozenset({helpers.INPUT_VALIDATION_CONCERN, helpers.DATA_LOSS_CONCERN}),
            helpers.URGENT,
            "flagged concerns: data_loss_concern, input_validation_concern",
        ),
        (
            frozenset(
                {
                    helpers.AUTHENTICATION_CONCERN,
                    helpers.INPUT_VALIDATION_CONCERN,
                    helpers.DATA_LOSS_CONCERN,
                }
            ),
            helpers.URGENT,
            "flagged concerns: authentication_concern, data_loss_concern, input_validation_concern",
        ),
    ],
)
def test_priority_from_concerns_covers_every_one_of_the_eight_combinations(
    flagged, expected_priority, expected_reason
):
    # expected_reason is a literal string, not helpers.reason_concerns(flagged): asserting
    # against the function under test's own output here would be circular and could not fail
    # if reason_concerns stopped sorting its concern names.
    priority, reason = helpers.priority_from_concerns(flagged)
    assert priority == expected_priority
    assert reason == expected_reason


def test_reason_concerns_is_sorted_so_set_order_never_changes_the_wording():
    # A frozenset's own iteration order is hash-randomized per process (PYTHONHASHSEED), so a
    # frozenset literal input would pass this assertion on some seeds even with sorted()
    # removed from reason_concerns, purely by the luck of which order the two elements happen
    # to iterate in. A list input sidesteps that: list iteration order is exactly insertion
    # order, never hash-dependent, so giving reason_concerns its two elements in the
    # deliberately wrong (reverse-alphabetical) order makes the unsorted join produce the wrong
    # string on every seed, while the correct, sorting implementation still produces the right
    # one regardless of the order it is handed.
    assert helpers.reason_concerns(["input_validation_concern", "authentication_concern"]) == (
        "flagged concerns: authentication_concern, input_validation_concern"
    )


def _decision(label, noul, tag, confidence, gated):
    return helpers.LabelDecision(label, noul, tag, confidence, gated)


def _decisions(tags, gated=(False, False, False)):
    """``{label: LabelDecision}`` for the three concerns, in ``helpers.LABELS`` order, from
    plain ``tags``/``gated`` booleans; ``noul``/``confidence`` are filler values that do not
    matter once ``gated`` is given explicitly."""
    out = {}
    for label, tag, is_gated in zip(helpers.LABELS, tags, gated, strict=True):
        noul = 0.95 if tag else 0.05
        confidence = 0.1 if is_gated else 0.9
        out[label] = _decision(label, noul, tag, confidence, is_gated)
    return out


@pytest.mark.parametrize(
    "gated",
    [
        (True, False, False),
        (False, True, False),
        (False, False, True),
        (True, True, False),
        (True, False, True),
        (False, True, True),
        (True, True, True),
    ],
)
def test_review_priority_reviews_whenever_any_label_is_gated(gated):
    decisions = _decisions((True, True, True), gated=gated)
    result = helpers.review_priority(decisions)
    assert result.priority == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW
    assert result.concerns == frozenset()


@pytest.mark.parametrize(
    "tags,expected_priority",
    [
        ((False, False, False), helpers.ROUTINE),
        ((True, False, False), helpers.ELEVATED),
        ((False, True, False), helpers.ELEVATED),
        ((False, False, True), helpers.URGENT),
        ((True, True, False), helpers.URGENT),
        ((True, False, True), helpers.URGENT),
        ((False, True, True), helpers.URGENT),
        ((True, True, True), helpers.URGENT),
    ],
)
def test_review_priority_composes_from_decide_concerns_tags_when_nothing_is_gated(
    tags, expected_priority
):
    decisions = _decisions(tags)
    result = helpers.review_priority(decisions)
    assert result.priority == expected_priority
    expected_concerns = frozenset(
        label for label, tag in zip(helpers.LABELS, tags, strict=True) if tag
    )
    assert result.concerns == expected_concerns


# --------------------------------------------------------------------------------------------
# gold_concern_set
# --------------------------------------------------------------------------------------------


def test_gold_concern_set_reads_every_proposition_independently():
    label = {
        helpers.AUTHENTICATION_CONCERN: True,
        helpers.INPUT_VALIDATION_CONCERN: False,
        helpers.DATA_LOSS_CONCERN: False,
        "priority": helpers.ELEVATED,
    }
    assert helpers.gold_concern_set(label) == frozenset({helpers.AUTHENTICATION_CONCERN})


def test_gold_concern_set_is_empty_when_nothing_is_flagged():
    label = {
        helpers.AUTHENTICATION_CONCERN: False,
        helpers.INPUT_VALIDATION_CONCERN: False,
        helpers.DATA_LOSS_CONCERN: False,
        "priority": helpers.ROUTINE,
    }
    assert helpers.gold_concern_set(label) == frozenset()


# --------------------------------------------------------------------------------------------
# review_sort_key and queue_item
# --------------------------------------------------------------------------------------------


def test_review_sort_key_is_the_lowest_of_the_three_confidences():
    decisions = {
        helpers.AUTHENTICATION_CONCERN: _decision(
            helpers.AUTHENTICATION_CONCERN, 0.5, False, 0.2, True
        ),
        helpers.INPUT_VALIDATION_CONCERN: _decision(
            helpers.INPUT_VALIDATION_CONCERN, 0.6, True, 0.6, False
        ),
        helpers.DATA_LOSS_CONCERN: _decision(helpers.DATA_LOSS_CONCERN, 0.6, True, 0.4, False),
    }
    result = helpers.review_priority(decisions)
    assert helpers.review_sort_key(result) == pytest.approx(0.2)


def test_gating_label_names_the_proposition_with_the_lowest_confidence():
    # data_loss_concern (0.4) is the lowest of the three, not authentication_concern, even
    # though authentication_concern's own gate flag happens to be True here: the label that
    # actually gated a real patch is not always the first one in LABELS order, and
    # gating_label must point at whichever one review_sort_key's minimum came from.
    decisions = {
        helpers.AUTHENTICATION_CONCERN: _decision(
            helpers.AUTHENTICATION_CONCERN, 0.5, False, 0.6, True
        ),
        helpers.INPUT_VALIDATION_CONCERN: _decision(
            helpers.INPUT_VALIDATION_CONCERN, 0.6, True, 0.9, False
        ),
        helpers.DATA_LOSS_CONCERN: _decision(helpers.DATA_LOSS_CONCERN, 0.6, True, 0.4, False),
    }
    result = helpers.review_priority(decisions)
    assert helpers.gating_label(result) == helpers.DATA_LOSS_CONCERN
    assert result.data_loss_concern.confidence == pytest.approx(helpers.review_sort_key(result))


def test_gating_label_breaks_a_tie_in_labels_order():
    decisions = {
        helpers.AUTHENTICATION_CONCERN: _decision(
            helpers.AUTHENTICATION_CONCERN, 0.5, False, 0.3, True
        ),
        helpers.INPUT_VALIDATION_CONCERN: _decision(
            helpers.INPUT_VALIDATION_CONCERN, 0.6, True, 0.9, False
        ),
        helpers.DATA_LOSS_CONCERN: _decision(helpers.DATA_LOSS_CONCERN, 0.6, True, 0.3, False),
    }
    result = helpers.review_priority(decisions)
    assert helpers.gating_label(result) == helpers.AUTHENTICATION_CONCERN


def test_queue_item_shows_the_diff_and_all_three_label_decisions():
    decisions = {
        helpers.AUTHENTICATION_CONCERN: _decision(
            helpers.AUTHENTICATION_CONCERN, 0.5, False, 0.2, True
        ),
        helpers.INPUT_VALIDATION_CONCERN: _decision(
            helpers.INPUT_VALIDATION_CONCERN, 0.6, True, 0.4, False
        ),
        helpers.DATA_LOSS_CONCERN: _decision(helpers.DATA_LOSS_CONCERN, 0.9, True, 0.8, False),
    }
    result = helpers.review_priority(decisions)
    item = helpers.queue_item("v08", {"diff": "short diff"}, result)
    assert item["id"] == "v08"
    assert item["diff"] == "short diff"
    assert item[helpers.AUTHENTICATION_CONCERN] == {"noul": 0.5, "confidence": 0.2}
    assert item[helpers.INPUT_VALIDATION_CONCERN] == {"noul": 0.6, "confidence": 0.4}
    assert item[helpers.DATA_LOSS_CONCERN] == {"noul": 0.9, "confidence": 0.8}


# --------------------------------------------------------------------------------------------
# choose_label_threshold and choose_gate: the objective and its parameter are pinned, not
# inlined freely, so a swap cannot slip past every other test
# --------------------------------------------------------------------------------------------


def test_choose_label_threshold_selects_by_f1():
    source = inspect.getsource(helpers.choose_label_threshold)
    assert 'objective="f1"' in source


def test_choose_gate_selects_by_min_coverage_not_target_accuracy():
    source = inspect.getsource(helpers.choose_gate)
    assert "min_coverage=" in source
    assert "MIN_COVERAGE" in source
    assert "target_accuracy" not in source
    assert helpers.MIN_COVERAGE == pytest.approx(0.8)


# --------------------------------------------------------------------------------------------
# the strong form: a confidently wrong test answer the frozen gate does not catch
# --------------------------------------------------------------------------------------------


def _frozen_thresholds_and_gate():
    """``(thresholds, gate, backend, questions, examples)``, computed from the committed
    ``validation`` fixtures exactly as the notebook computes them: each per-label threshold
    chosen independently by ``helpers.choose_label_threshold``, then the one shared gate chosen
    afterwards from their pooled decisions by ``helpers.choose_gate``. Factored out here so the
    tests below do not each repeat it."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_ids = [e.id for e in validation]
    gold_by_label = {label: [labels[e.id][label] for e in validation] for label in helpers.LABELS}
    noul_by_label = {label: [decide(e)[label].noul for e in validation] for label in helpers.LABELS}
    thresholds = {
        label: helpers.choose_label_threshold(gold_by_label[label], noul_by_label[label])
        for label in helpers.LABELS
    }

    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )
    gate = helpers.choose_gate(correct, confidence)
    return thresholds, gate, backend, questions, examples


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    # caught every mistake. This mirrors the notebook's own selection exactly -- every per-label
    # business threshold chosen on validation by F1, then the shared confidence gate chosen on
    # the pooled (patch, concern) decisions by minimum coverage -- and requires a `test` patch
    # whose composed priority is wrong and whose own confidence, on all three concerns, still
    # clears that frozen gate. The derivation stays inline here (rather than behind
    # helpers.choose_label_threshold/helpers.choose_gate, which the notebook and the other tests
    # use) so this still re-derives the threshold and gate the way the strong-form guard (G1(c))
    # checks for: an assignment from select_confidence_threshold( bound to the comparison below.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_ids = [e.id for e in validation]
    val_gold_by_label = {
        label: [labels[e.id][label] for e in validation] for label in helpers.LABELS
    }
    val_noul_by_label = {
        label: [decide(e)[label].noul for e in validation] for label in helpers.LABELS
    }
    thresholds = {
        label: select_threshold(val_gold_by_label[label], val_noul_by_label[label], objective="f1")
        for label in helpers.LABELS
    }

    val_correct, val_confidence, _val_keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), val_gold_by_label, val_noul_by_label, thresholds
    )
    gate = select_confidence_threshold(
        val_correct, val_confidence, min_coverage=helpers.MIN_COVERAGE
    )

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_decisions = {e.id: helpers.decide_concerns(decide(e), thresholds, gate) for e in test}
    test_results = {eid: helpers.review_priority(d) for eid, d in test_decisions.items()}
    wrong_and_confident = [
        eid
        for eid, result in test_results.items()
        if result.priority != helpers.REVIEW
        and result.priority != labels[eid]["priority"]
        and all(test_decisions[eid][label].confidence >= gate for label in helpers.LABELS)
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


def test_the_committed_notebook_freezes_the_threshold_and_gate_this_recipe_selects():
    """Nothing else in this file pins what the *notebook's own* selection cell actually did
    unless something reads what it committed. This reads the committed notebook's own stdout
    for the ``python-rule`` cell (never re-executing it) and checks that the threshold and gate
    lines it printed match the independently-recomputed values above exactly. Swapping the
    notebook's own gate selection to a different objective (``target_accuracy=1.0``, say) would
    print a different gate there while the value recomputed here, through
    ``helpers.choose_gate``, would not change to match it -- which is what actually notices,
    not just the committed-output freshness check."""
    thresholds, gate, _backend, _questions, _examples = _frozen_thresholds_and_gate()
    nb = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in nb["cells"] if c.get("id") == "python-rule")
    text = "".join(
        "".join(o.get("text", ""))
        for o in cell.get("outputs", [])
        if o.get("output_type") == "stream"
    )
    assert text, "python-rule cell has no committed stdout to check"
    # Anchored to each printed line's own fixed wording, not a bare substring search over the
    # whole cell's stdout (which also prints noul readings and composed priorities that could,
    # in principle, happen to contain the same digits).
    for label in helpers.LABELS:
        assert f"{label} business threshold, frozen from here on: {thresholds[label]:.3f}" in text
    assert f"confidence gate, frozen from here on: {gate:.3f}" in text


# --------------------------------------------------------------------------------------------
# each concern is independently consequential on the real, committed fixtures: flipping one
# stored label decision, holding the other two fixed, changes review_priority's composed
# priority. Three real `test` fixtures, one per concern, each the lookalike this use case's
# own hard case names: a patch that genuinely has that one concern, described with a
# reassuring comment that reads confidently (and wrongly) as absent.
# --------------------------------------------------------------------------------------------


def test_authentication_concern_is_independently_consequential_on_the_fixtures():
    # t17 is a real, committed `test` fixture whose gold is an authentication concern alone
    # (input-validation and data-loss are both clean): the stored answer composes as
    # "routine" because its authentication reading, 0.06, falls confidently on the wrong side
    # of the frozen threshold -- the reassuring comment ("re-added upstream by the gateway")
    # the diff carries does not change what the diff itself still shows. Flipping only the
    # stored authentication_concern decision to a confident True, holding the real
    # input_validation_concern and data_loss_concern answers fixed, changes the composed
    # priority to "elevated" -- proof that authentication_concern alone, not merely the other
    # two, drives the result on this fixture.
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t17")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_priority(helpers.decide_concerns(real_answer, thresholds, gate))
    assert baseline.priority == helpers.ROUTINE

    flipped = {
        helpers.AUTHENTICATION_CONCERN: _FakeNoul(0.95),
        helpers.INPUT_VALIDATION_CONCERN: real_answer[helpers.INPUT_VALIDATION_CONCERN],
        helpers.DATA_LOSS_CONCERN: real_answer[helpers.DATA_LOSS_CONCERN],
    }
    changed = helpers.review_priority(helpers.decide_concerns(flipped, thresholds, gate))
    assert changed.priority != baseline.priority
    assert changed.priority == helpers.ELEVATED


def test_input_validation_concern_is_independently_consequential_on_the_fixtures():
    # t18 is a real, committed `test` fixture whose gold is an input-validation concern alone.
    # Flipping only the stored input_validation_concern decision to a confident True, holding
    # the real authentication_concern and data_loss_concern answers fixed, changes the composed
    # priority from "routine" to "elevated".
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t18")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_priority(helpers.decide_concerns(real_answer, thresholds, gate))
    assert baseline.priority == helpers.ROUTINE

    flipped = {
        helpers.AUTHENTICATION_CONCERN: real_answer[helpers.AUTHENTICATION_CONCERN],
        helpers.INPUT_VALIDATION_CONCERN: _FakeNoul(0.95),
        helpers.DATA_LOSS_CONCERN: real_answer[helpers.DATA_LOSS_CONCERN],
    }
    changed = helpers.review_priority(helpers.decide_concerns(flipped, thresholds, gate))
    assert changed.priority != baseline.priority
    assert changed.priority == helpers.ELEVATED


def test_data_loss_concern_is_independently_consequential_on_the_fixtures():
    # t19 is a real, committed `test` fixture whose gold is a data-loss concern alone. Flipping
    # only the stored data_loss_concern decision to a confident True, holding the real
    # authentication_concern and input_validation_concern answers fixed, changes the composed
    # priority from "routine" to "urgent" -- not "elevated", because this recipe's explicit
    # rule treats any data-loss concern as urgent on its own, unlike the other two.
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t19")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_priority(helpers.decide_concerns(real_answer, thresholds, gate))
    assert baseline.priority == helpers.ROUTINE

    flipped = {
        helpers.AUTHENTICATION_CONCERN: real_answer[helpers.AUTHENTICATION_CONCERN],
        helpers.INPUT_VALIDATION_CONCERN: real_answer[helpers.INPUT_VALIDATION_CONCERN],
        helpers.DATA_LOSS_CONCERN: _FakeNoul(0.95),
    }
    changed = helpers.review_priority(helpers.decide_concerns(flipped, thresholds, gate))
    assert changed.priority != baseline.priority
    assert changed.priority == helpers.URGENT
