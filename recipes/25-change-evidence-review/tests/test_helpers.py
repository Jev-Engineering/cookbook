"""Tests for recipe 25's helpers. They load the helpers by file path."""

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
        "implementation_evidence",
        "validation_evidence",
        "rollback_evidence",
    }
    implementation = questions[helpers.IMPLEMENTATION_EVIDENCE]
    validation = questions[helpers.VALIDATION_EVIDENCE]
    rollback = questions[helpers.ROLLBACK_EVIDENCE]
    assert implementation.instructions == (
        "The change record describes what was actually implemented in enough concrete detail "
        "to identify the change that was made."
    )
    assert validation.instructions == (
        "The change record describes how the change was tested or validated before being "
        "proposed for deployment, including what was checked and what the result was."
    )
    assert rollback.instructions == (
        "The change record describes the concrete steps that would be taken to roll the "
        "change back if it needed to be reversed."
    )
    for question in (implementation, validation, rollback):
        assert set(question.criteria) == {"true", "false"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # (all three propositions together): every example lists exactly one key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --------------------------------------------------------------------------------------------
# build_state: Jev sees the record unchanged
# --------------------------------------------------------------------------------------------


def test_build_state_carries_only_the_record():
    fields = {"record": "Some change.\n\nImplementation: did it.\n\nValidation: tested it."}
    state = helpers.build_state(fields)
    assert set(state) == {"record"}
    assert state["record"] == fields["record"]


# --------------------------------------------------------------------------------------------
# decide_labels: the business tag and the confidence gate, per proposition
# --------------------------------------------------------------------------------------------


class _FakeNoul:
    def __init__(self, noul):
        self.noul = noul


def _answers(implementation_noul, validation_noul, rollback_noul):
    return {
        helpers.IMPLEMENTATION_EVIDENCE: _FakeNoul(implementation_noul),
        helpers.VALIDATION_EVIDENCE: _FakeNoul(validation_noul),
        helpers.ROLLBACK_EVIDENCE: _FakeNoul(rollback_noul),
    }


_THRESHOLDS = {
    helpers.IMPLEMENTATION_EVIDENCE: 0.83,
    helpers.VALIDATION_EVIDENCE: 0.85,
    helpers.ROLLBACK_EVIDENCE: 0.84,
}


def test_decide_labels_tags_each_proposition_against_its_own_threshold():
    decisions = helpers.decide_labels(_answers(0.90, 0.10, 0.90), _THRESHOLDS, confidence_gate=0.3)
    assert decisions[helpers.IMPLEMENTATION_EVIDENCE].tag is True
    assert decisions[helpers.VALIDATION_EVIDENCE].tag is False
    assert decisions[helpers.ROLLBACK_EVIDENCE].tag is True
    assert decisions[helpers.IMPLEMENTATION_EVIDENCE].gated is False
    assert decisions[helpers.VALIDATION_EVIDENCE].gated is False


def test_decide_labels_gates_on_confidence_whatever_the_tag_says():
    # noul 0.55 is below the implementation threshold (tag False) but its confidence,
    # |2*0.55-1|=0.1, is below a 0.3 gate, so it must be marked gated regardless of the tag.
    decisions = helpers.decide_labels(_answers(0.55, 0.90, 0.90), _THRESHOLDS, confidence_gate=0.3)
    assert decisions[helpers.IMPLEMENTATION_EVIDENCE].tag is False
    assert decisions[helpers.IMPLEMENTATION_EVIDENCE].gated is True


@pytest.mark.parametrize("bad_gate", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_confidence_gate(bad_gate):
    with pytest.raises(ValueError):
        helpers.decide_labels(_answers(0.5, 0.5, 0.5), _THRESHOLDS, confidence_gate=bad_gate)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_threshold(bad_threshold):
    thresholds = {**_THRESHOLDS, helpers.IMPLEMENTATION_EVIDENCE: bad_threshold}
    with pytest.raises(ValueError):
        helpers.decide_labels(_answers(0.5, 0.5, 0.5), thresholds, confidence_gate=0.3)


def test_decide_labels_rejects_thresholds_that_do_not_name_exactly_labels():
    with pytest.raises(ValueError):
        helpers.decide_labels(
            _answers(0.5, 0.5, 0.5),
            {helpers.IMPLEMENTATION_EVIDENCE: 0.9, helpers.VALIDATION_EVIDENCE: 0.9},
            confidence_gate=0.3,
        )
    with pytest.raises(ValueError):
        helpers.decide_labels(
            _answers(0.5, 0.5, 0.5),
            {**_THRESHOLDS, "extra": 0.5},
            confidence_gate=0.3,
        )


def test_decide_labels_tag_is_inclusive_at_the_threshold():
    decisions = helpers.decide_labels(_answers(0.83, 0.85, 0.84), _THRESHOLDS, confidence_gate=0.0)
    assert decisions[helpers.IMPLEMENTATION_EVIDENCE].tag is True
    assert decisions[helpers.VALIDATION_EVIDENCE].tag is True
    assert decisions[helpers.ROLLBACK_EVIDENCE].tag is True


# --------------------------------------------------------------------------------------------
# review_checklist: the deterministic composition, every label/outcome combination
# --------------------------------------------------------------------------------------------


def _decision(label, noul, tag, confidence, gated):
    return helpers.LabelDecision(label, noul, tag, confidence, gated)


def _decisions(tags, gated=(False, False, False)):
    """``{label: LabelDecision}`` for the three propositions, in ``helpers.LABELS`` order,
    from plain ``tags``/``gated`` booleans; ``noul``/``confidence`` are filler values that do
    not matter once ``gated`` is given explicitly."""
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
def test_review_checklist_reviews_whenever_any_label_is_gated(gated):
    decisions = _decisions((True, True, True), gated=gated)
    result = helpers.review_checklist(decisions)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW
    assert result.gaps == frozenset()


@pytest.mark.parametrize(
    "tags,expected_gaps",
    [
        ((True, True, True), frozenset()),
        ((False, True, True), frozenset({"implementation_evidence"})),
        ((True, False, True), frozenset({"validation_evidence"})),
        ((True, True, False), frozenset({"rollback_evidence"})),
        ((False, False, True), frozenset({"implementation_evidence", "validation_evidence"})),
        ((False, True, False), frozenset({"implementation_evidence", "rollback_evidence"})),
        ((True, False, False), frozenset({"validation_evidence", "rollback_evidence"})),
        (
            (False, False, False),
            frozenset({"implementation_evidence", "validation_evidence", "rollback_evidence"}),
        ),
    ],
)
def test_review_checklist_reports_every_gap_combination_when_nothing_is_gated(tags, expected_gaps):
    decisions = _decisions(tags)
    result = helpers.review_checklist(decisions)
    assert result.gaps == expected_gaps
    if expected_gaps:
        assert result.outcome == helpers.GAPS
        assert result.reason == helpers.reason_gaps(expected_gaps)
    else:
        assert result.outcome == helpers.READY
        assert result.reason == helpers.REASON_READY


def test_reason_gaps_is_sorted_so_dict_order_never_changes_the_wording():
    assert helpers.reason_gaps(frozenset({"rollback_evidence", "implementation_evidence"})) == (
        "missing evidence: implementation_evidence, rollback_evidence"
    )


# --------------------------------------------------------------------------------------------
# gold_gap_set
# --------------------------------------------------------------------------------------------


def test_gold_gap_set_reads_every_proposition_independently():
    label = {
        helpers.IMPLEMENTATION_EVIDENCE: True,
        helpers.VALIDATION_EVIDENCE: False,
        helpers.ROLLBACK_EVIDENCE: False,
        "outcome": helpers.GAPS,
    }
    assert helpers.gold_gap_set(label) == frozenset(
        {helpers.VALIDATION_EVIDENCE, helpers.ROLLBACK_EVIDENCE}
    )


def test_gold_gap_set_is_empty_when_every_proposition_is_sufficient():
    label = {
        helpers.IMPLEMENTATION_EVIDENCE: True,
        helpers.VALIDATION_EVIDENCE: True,
        helpers.ROLLBACK_EVIDENCE: True,
        "outcome": helpers.READY,
    }
    assert helpers.gold_gap_set(label) == frozenset()


# --------------------------------------------------------------------------------------------
# review_sort_key and queue_item
# --------------------------------------------------------------------------------------------


def test_review_sort_key_is_the_lowest_of_the_three_confidences():
    decisions = {
        helpers.IMPLEMENTATION_EVIDENCE: _decision(
            helpers.IMPLEMENTATION_EVIDENCE, 0.5, False, 0.2, True
        ),
        helpers.VALIDATION_EVIDENCE: _decision(helpers.VALIDATION_EVIDENCE, 0.6, True, 0.6, False),
        helpers.ROLLBACK_EVIDENCE: _decision(helpers.ROLLBACK_EVIDENCE, 0.6, True, 0.4, False),
    }
    result = helpers.review_checklist(decisions)
    assert helpers.review_sort_key(result) == pytest.approx(0.2)


def test_queue_item_shows_the_record_and_all_three_label_decisions():
    decisions = {
        helpers.IMPLEMENTATION_EVIDENCE: _decision(
            helpers.IMPLEMENTATION_EVIDENCE, 0.5, False, 0.2, True
        ),
        helpers.VALIDATION_EVIDENCE: _decision(helpers.VALIDATION_EVIDENCE, 0.6, True, 0.4, False),
        helpers.ROLLBACK_EVIDENCE: _decision(helpers.ROLLBACK_EVIDENCE, 0.9, True, 0.8, False),
    }
    result = helpers.review_checklist(decisions)
    item = helpers.queue_item("v08", {"record": "short record"}, result)
    assert item["id"] == "v08"
    assert item["record"] == "short record"
    assert item[helpers.IMPLEMENTATION_EVIDENCE] == {"noul": 0.5, "confidence": 0.2}
    assert item[helpers.VALIDATION_EVIDENCE] == {"noul": 0.6, "confidence": 0.4}
    assert item[helpers.ROLLBACK_EVIDENCE] == {"noul": 0.9, "confidence": 0.8}


# --------------------------------------------------------------------------------------------
# the strong form: a confidently wrong test answer the frozen gate does not catch
# --------------------------------------------------------------------------------------------


def _frozen_thresholds_and_gate():
    """``(thresholds, gate, backend, questions, examples)``, computed from the committed
    ``validation`` fixtures exactly as the notebook computes them: each per-label threshold
    chosen independently by F1, then the one shared gate chosen afterwards from their pooled
    decisions at ``target_accuracy=1.0``. Factored out here so the tests below do not each
    repeat it."""
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
        label: select_threshold(gold_by_label[label], noul_by_label[label], objective="f1")
        for label in helpers.LABELS
    }

    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )
    gate = select_confidence_threshold(correct, confidence, target_accuracy=1.0)
    return thresholds, gate, backend, questions, examples


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    # caught every mistake. This mirrors the notebook's own selection exactly -- every per-label
    # business threshold chosen on validation by F1, then the shared confidence gate chosen on
    # the pooled (example, label) decisions -- and requires a `test` change record whose
    # composed outcome is wrong and whose own confidence, on all three propositions, still
    # clears that frozen gate.
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
    gate = select_confidence_threshold(val_correct, val_confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_decisions = {e.id: helpers.decide_labels(decide(e), thresholds, gate) for e in test}
    test_results = {eid: helpers.review_checklist(d) for eid, d in test_decisions.items()}
    wrong_and_confident = [
        eid
        for eid, result in test_results.items()
        if result.outcome != helpers.REVIEW
        and result.outcome != labels[eid]["outcome"]
        and all(test_decisions[eid][label].confidence >= gate for label in helpers.LABELS)
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


# --------------------------------------------------------------------------------------------
# each proposition is independently consequential on the real, committed fixtures: flipping
# one stored label decision, holding the other two fixed, changes review_checklist's composed
# outcome. Three real `test` fixtures, one per proposition, each a clean single-gap record
# answered (not sent to review) at the frozen thresholds and gate.
# --------------------------------------------------------------------------------------------


def test_implementation_evidence_is_independently_consequential_on_the_fixtures():
    # t09 is a real, committed `test` fixture whose gold is insufficient implementation
    # evidence alone (validation and rollback evidence are both sufficient): the stored answer
    # composes as "gaps: implementation_evidence" because implementation_evidence's own tag is
    # False while the other two are confidently True. Flipping only the stored
    # implementation_evidence decision to a confident True, holding the real validation_evidence
    # and rollback_evidence answers fixed, changes the composed outcome to "ready" -- proof that
    # implementation_evidence alone, not merely the other two, drives the result on this fixture.
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t09")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_checklist(helpers.decide_labels(real_answer, thresholds, gate))
    assert baseline.outcome == helpers.GAPS
    assert baseline.gaps == frozenset({helpers.IMPLEMENTATION_EVIDENCE})

    flipped = {
        helpers.IMPLEMENTATION_EVIDENCE: _FakeNoul(0.97),
        helpers.VALIDATION_EVIDENCE: real_answer[helpers.VALIDATION_EVIDENCE],
        helpers.ROLLBACK_EVIDENCE: real_answer[helpers.ROLLBACK_EVIDENCE],
    }
    changed = helpers.review_checklist(helpers.decide_labels(flipped, thresholds, gate))
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.READY


def test_validation_evidence_is_independently_consequential_on_the_fixtures():
    # t05 is a real, committed `test` fixture whose gold is insufficient validation evidence
    # alone. Flipping only the stored validation_evidence decision to a confident True, holding
    # the real implementation_evidence and rollback_evidence answers fixed, changes the composed
    # outcome from "gaps: validation_evidence" to "ready".
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t05")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_checklist(helpers.decide_labels(real_answer, thresholds, gate))
    assert baseline.outcome == helpers.GAPS
    assert baseline.gaps == frozenset({helpers.VALIDATION_EVIDENCE})

    flipped = {
        helpers.IMPLEMENTATION_EVIDENCE: real_answer[helpers.IMPLEMENTATION_EVIDENCE],
        helpers.VALIDATION_EVIDENCE: _FakeNoul(0.97),
        helpers.ROLLBACK_EVIDENCE: real_answer[helpers.ROLLBACK_EVIDENCE],
    }
    changed = helpers.review_checklist(helpers.decide_labels(flipped, thresholds, gate))
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.READY


def test_rollback_evidence_is_independently_consequential_on_the_fixtures():
    # t03 is a real, committed `test` fixture whose gold is insufficient rollback evidence
    # alone. Flipping only the stored rollback_evidence decision to a confident True, holding
    # the real implementation_evidence and validation_evidence answers fixed, changes the
    # composed outcome from "gaps: rollback_evidence" to "ready".
    thresholds, gate, backend, questions, examples = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "t03")
    real_answer = backend.decide(helpers.build_state(example.fields), questions)

    baseline = helpers.review_checklist(helpers.decide_labels(real_answer, thresholds, gate))
    assert baseline.outcome == helpers.GAPS
    assert baseline.gaps == frozenset({helpers.ROLLBACK_EVIDENCE})

    flipped = {
        helpers.IMPLEMENTATION_EVIDENCE: real_answer[helpers.IMPLEMENTATION_EVIDENCE],
        helpers.VALIDATION_EVIDENCE: real_answer[helpers.VALIDATION_EVIDENCE],
        helpers.ROLLBACK_EVIDENCE: _FakeNoul(0.97),
    }
    changed = helpers.review_checklist(helpers.decide_labels(flipped, thresholds, gate))
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.READY
