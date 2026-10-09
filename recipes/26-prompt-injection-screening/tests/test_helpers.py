"""Tests for recipe 26's helpers. They load the helpers by file path."""

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
    assert set(questions) == {"redirect", "discusses"}
    redirect = questions[helpers.REDIRECT]
    discusses = questions[helpers.DISCUSSES]
    assert redirect.instructions == (
        "The passage contains an instruction directed at the reader's assistant to "
        "change or ignore its instructions."
    )
    assert discusses.instructions == (
        "The passage quotes or discusses such a redirect instruction without issuing one itself."
    )
    assert set(redirect.criteria) == {"true", "false"}
    assert set(discusses.criteria) == {"true", "false"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # (both propositions together): every example lists exactly one key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --------------------------------------------------------------------------------------------
# excerpt: Python builds the state from the retrieved passage
# --------------------------------------------------------------------------------------------


def test_excerpt_returns_a_short_document_unchanged():
    short = "This document is short."
    assert helpers.excerpt(short) == short


def test_excerpt_cuts_a_long_document_at_a_word_boundary_with_a_marker():
    long_document = "word " * 200  # far longer than MAX_EXCERPT_CHARS
    cut = helpers.excerpt(long_document)
    assert len(cut) <= helpers.MAX_EXCERPT_CHARS + len(" […]")
    assert cut.endswith(" […]")
    assert not cut[: -len(" […]")].endswith(" ")  # cut at a whole word, not mid-word


def test_excerpt_keeps_the_key_sentence_of_the_long_test_fixture():
    # ta05 is deliberately longer than MAX_EXCERPT_CHARS; the instruction that makes it
    # adversarial sits early enough to survive the cut, and the padding after it does not.
    examples = {e.id: e for e in load_inputs(RECIPE)}
    document = examples["ta05"].fields["document"]
    assert len(document) > helpers.MAX_EXCERPT_CHARS
    excerpted = helpers.excerpt(document)
    assert "OVERRIDE" in excerpted
    assert "thanks in advance" not in excerpted


def test_build_state_only_ever_carries_the_excerpt():
    fields = {"document": "word " * 200}
    state = helpers.build_state(fields)
    assert set(state) == {"passage"}
    assert state["passage"] == helpers.excerpt(fields["document"])


# --------------------------------------------------------------------------------------------
# decide_labels: the business tag and the confidence gate, per label
# --------------------------------------------------------------------------------------------


class _FakeNoul:
    def __init__(self, noul):
        self.noul = noul


def _answers(redirect_noul, discusses_noul):
    return {
        helpers.REDIRECT: _FakeNoul(redirect_noul),
        helpers.DISCUSSES: _FakeNoul(discusses_noul),
    }


def test_decide_labels_tags_each_label_against_its_own_threshold():
    thresholds = {helpers.REDIRECT: 0.9, helpers.DISCUSSES: 0.7}
    decisions = helpers.decide_labels(_answers(0.95, 0.10), thresholds, confidence_gate=0.3)
    assert decisions[helpers.REDIRECT].tag is True
    assert decisions[helpers.DISCUSSES].tag is False
    assert decisions[helpers.REDIRECT].gated is False
    assert decisions[helpers.DISCUSSES].gated is False


def test_decide_labels_gates_on_confidence_whatever_the_tag_says():
    thresholds = {helpers.REDIRECT: 0.9, helpers.DISCUSSES: 0.7}
    # noul 0.55 is below the redirect threshold (tag False) but its confidence, |2*0.55-1|=0.1,
    # is below a 0.3 gate, so it must be marked gated regardless of the tag.
    decisions = helpers.decide_labels(_answers(0.55, 0.10), thresholds, confidence_gate=0.3)
    assert decisions[helpers.REDIRECT].tag is False
    assert decisions[helpers.REDIRECT].gated is True


@pytest.mark.parametrize("bad_gate", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_confidence_gate(bad_gate):
    thresholds = {helpers.REDIRECT: 0.9, helpers.DISCUSSES: 0.7}
    with pytest.raises(ValueError):
        helpers.decide_labels(_answers(0.5, 0.5), thresholds, confidence_gate=bad_gate)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_threshold(bad_threshold):
    thresholds = {helpers.REDIRECT: bad_threshold, helpers.DISCUSSES: 0.7}
    with pytest.raises(ValueError):
        helpers.decide_labels(_answers(0.5, 0.5), thresholds, confidence_gate=0.3)


def test_decide_labels_rejects_thresholds_that_do_not_name_exactly_labels():
    with pytest.raises(ValueError):
        helpers.decide_labels(_answers(0.5, 0.5), {helpers.REDIRECT: 0.9}, confidence_gate=0.3)
    with pytest.raises(ValueError):
        helpers.decide_labels(
            _answers(0.5, 0.5),
            {helpers.REDIRECT: 0.9, helpers.DISCUSSES: 0.7, "extra": 0.5},
            confidence_gate=0.3,
        )


# --------------------------------------------------------------------------------------------
# screen: the deterministic composition, every label/outcome combination
# --------------------------------------------------------------------------------------------


def _decision(label, noul, tag, confidence, gated):
    return helpers.LabelDecision(label, noul, tag, confidence, gated)


def test_screen_reviews_when_redirect_alone_is_gated():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.5, False, 0.1, True),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.1, False, 0.9, False),
    }
    result = helpers.screen(decisions)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW


def test_screen_reviews_when_discusses_alone_is_gated():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.95, True, 0.9, False),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.5, False, 0.1, True),
    }
    result = helpers.screen(decisions)
    assert result.outcome == helpers.REVIEW


def test_screen_reviews_when_both_are_gated():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.5, False, 0.1, True),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.5, False, 0.1, True),
    }
    assert helpers.screen(decisions).outcome == helpers.REVIEW


def test_screen_flags_a_confident_redirect_tag():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.95, True, 0.9, False),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.05, False, 0.9, False),
    }
    result = helpers.screen(decisions)
    assert result.outcome == helpers.FLAG
    assert result.reason == helpers.REASON_FLAG


def test_screen_flags_redirect_even_when_discusses_also_reads_true():
    # Gated-redirect-wins-over-discusses only applies to the review branch; once both labels
    # are confident, a confident redirect tag takes precedence over a confident discusses tag
    # (a passage can in principle quote one attack while issuing a second, live one).
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.95, True, 0.9, False),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.95, True, 0.9, False),
    }
    assert helpers.screen(decisions).outcome == helpers.FLAG


def test_screen_passes_a_confident_discusses_only_tag():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.05, False, 0.9, False),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.95, True, 0.9, False),
    }
    result = helpers.screen(decisions)
    assert result.outcome == helpers.PASS
    assert result.reason == helpers.REASON_PASS_DISCUSSES


def test_screen_passes_when_neither_label_reads_true():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.05, False, 0.9, False),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.05, False, 0.9, False),
    }
    result = helpers.screen(decisions)
    assert result.outcome == helpers.PASS
    assert result.reason == helpers.REASON_PASS_CLEAR


# --------------------------------------------------------------------------------------------
# review_sort_key and queue_item
# --------------------------------------------------------------------------------------------


def test_review_sort_key_is_the_lower_of_the_two_confidences():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.5, False, 0.2, True),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.6, False, 0.6, False),
    }
    result = helpers.screen(decisions)
    assert helpers.review_sort_key(result) == pytest.approx(0.2)


def test_queue_item_shows_the_excerpt_and_both_label_decisions():
    decisions = {
        helpers.REDIRECT: _decision(helpers.REDIRECT, 0.5, False, 0.2, True),
        helpers.DISCUSSES: _decision(helpers.DISCUSSES, 0.6, True, 0.4, False),
    }
    result = helpers.screen(decisions)
    item = helpers.queue_item("ta08", {"document": "short passage"}, result)
    assert item["id"] == "ta08"
    assert item["passage"] == "short passage"
    assert item[helpers.REDIRECT] == {"noul": 0.5, "confidence": 0.2}
    assert item[helpers.DISCUSSES] == {"noul": 0.6, "confidence": 0.4}


# --------------------------------------------------------------------------------------------
# the strong form: a confidently wrong test answer the frozen gate does not catch
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    # caught every mistake. This mirrors the notebook's own selection exactly -- both per-label
    # business thresholds chosen on validation by F1, then the shared confidence gate chosen on
    # the pooled (example, label) decisions -- and requires a `test` passage whose composed
    # outcome is wrong and whose own confidence, on both labels, still clears that frozen gate.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_gold_redirect = [labels[e.id]["redirect"] for e in validation]
    val_gold_discusses = [labels[e.id]["discusses"] for e in validation]
    val_redirect = [decide(e)[helpers.REDIRECT].noul for e in validation]
    val_discusses = [decide(e)[helpers.DISCUSSES].noul for e in validation]

    t_redirect = select_threshold(val_gold_redirect, val_redirect, objective="f1")
    t_discusses = select_threshold(val_gold_discusses, val_discusses, objective="f1")
    thresholds = {helpers.REDIRECT: t_redirect, helpers.DISCUSSES: t_discusses}

    val_ids = [e.id for e in validation]
    gold_by_label = {helpers.REDIRECT: val_gold_redirect, helpers.DISCUSSES: val_gold_discusses}
    noul_by_label = {helpers.REDIRECT: val_redirect, helpers.DISCUSSES: val_discusses}
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )
    gate = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_results = {
        e.id: helpers.screen(helpers.decide_labels(decide(e), thresholds, gate)) for e in test
    }
    wrong_and_confident = [
        eid
        for eid, result in test_results.items()
        if result.outcome != helpers.REVIEW
        and result.outcome != labels[eid]["outcome"]
        and result.redirect.confidence >= gate
        and result.discusses.confidence >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
