"""Tests for recipe 42's helpers. They load the helpers by file path.

A Noul's confidence (``jev_cookbook.evaluation.noul_confidence``) is ``|2p - 1|`` (docs/
evaluation.md, "Noul three-path pattern", S03). Tests that need a value near 0.5 call
``noul_confidence`` themselves rather than hardcoding a number, so they stay correct if the
formula is ever revisited.
"""

import math
from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    noul_confidence,
    pool_label_decisions,
    select_confidence_threshold,
    select_threshold,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# This recipe's own confidence-gate coverage floor (the notebook selects the gate with this same
# value); kept here, not imported, because the notebook's choice is a markdown-explained design
# decision, not a shared constant in helpers.py.
_MIN_COVERAGE = 0.75


def confidence_of(noul):
    return noul_confidence([noul])[0]


# --------------------------------------------------------------------------- questions


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"pricing", "contact"}
    pricing = questions["pricing"]
    contact = questions["contact"]
    assert pricing.instructions == helpers._STATEMENTS[helpers.PRICING]
    assert contact.instructions == helpers._STATEMENTS[helpers.CONTACT]
    for question in (pricing, contact):
        assert set(question.criteria) == {"true", "false"}
        assert all(isinstance(d, str) and d for d in question.criteria.values())
    # Literal expected text, not helpers' own data (which would make this self-referential):
    # both propositions are statements that can be true or false (CONTRIBUTING.md section 3),
    # never phrased as a question.
    assert pricing.instructions.startswith("This message states a specific price")
    assert contact.instructions.startswith("This message discloses a specific individual's")
    for question in (pricing, contact):
        assert "?" not in question.instructions


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per message
    # (the sharing-rule battery, both propositions together), so each example lists exactly one
    # key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_the_state_hides_thread_bookkeeping():
    fields = {"text": "No pricing or contact detail here.", "thread_id": "x", "sequence": 3}
    assert helpers.build_state(fields) == {"message": "No pricing or contact detail here."}


# --------------------------------------------------------------------------- verdict_for_rule


@pytest.mark.parametrize("noul", [0.55, 0.70, 0.90, 1.0])
def test_a_confident_noul_at_or_above_the_threshold_violates(noul):
    verdict = helpers.verdict_for_rule("pricing", noul, threshold=0.55, min_confidence=0.01)
    assert (verdict.verdict, verdict.noul) == (helpers.VIOLATES, noul)


@pytest.mark.parametrize("noul", [0.0, 0.10, 0.40, 0.549])
def test_a_confident_noul_below_the_threshold_is_clear(noul):
    verdict = helpers.verdict_for_rule("pricing", noul, threshold=0.55, min_confidence=0.01)
    assert verdict.verdict == helpers.CLEAR


def test_the_business_threshold_is_inclusive():
    at = helpers.verdict_for_rule("pricing", 0.55, threshold=0.55, min_confidence=0.01)
    below = helpers.verdict_for_rule("pricing", 0.55 - 1e-9, threshold=0.55, min_confidence=0.01)
    assert at.verdict == helpers.VIOLATES
    assert below.verdict == helpers.CLEAR


@pytest.mark.parametrize("noul", [0.48, 0.5, 0.52, 0.56, 0.58, 0.60])
def test_low_confidence_reviews_whichever_side_it_leans(noul):
    # Three of these (0.48, 0.5, 0.52) are below the business threshold (0.55) and three
    # (0.56, 0.58, 0.60) are above it: the gate has to win over the business decision on BOTH
    # sides, or this test would pass even if the threshold branch ran first.
    verdict = helpers.verdict_for_rule(
        "pricing", noul, threshold=0.55, min_confidence=confidence_of(noul) + 0.01
    )
    assert verdict.verdict == helpers.REVIEW
    assert verdict.reason == "confidence below the threshold"


def test_the_confidence_gate_is_inclusive():
    noul = 0.9
    exact = helpers.verdict_for_rule(
        "pricing", noul, threshold=0.55, min_confidence=confidence_of(noul)
    )
    just_above = helpers.verdict_for_rule(
        "pricing", noul, threshold=0.55, min_confidence=confidence_of(noul) + 1e-9
    )
    assert exact.verdict == helpers.VIOLATES  # confidence == min_confidence clears the gate
    assert just_above.verdict == helpers.REVIEW


def test_a_confident_wrong_leaning_noul_is_still_decided_not_reviewed():
    # The confidence gate protects against genuine ambiguity (noul near 0.5), not against a
    # confidently wrong answer (noul far from 0.5 on the "wrong" side) -- it has no way to tell
    # the two apart, which is the point this test pins. This recipe's "-adversarial" fixture is
    # exactly this shape.
    verdict = helpers.verdict_for_rule("pricing", 0.05, threshold=0.55, min_confidence=0.5)
    assert verdict.verdict == helpers.CLEAR


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        helpers.verdict_for_rule("pricing", 0.5, threshold=bad, min_confidence=0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_min_confidence_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
        helpers.verdict_for_rule("pricing", 0.5, threshold=0.5, min_confidence=bad)


# --------------------------------------------------------------------------- screen_message
#
# CONTRIBUTING.md section 4: Python owns every stop condition. These tests hold for ANY model
# answer: thread escalation is checked first, from a boolean alone, and never reads a verdict.


def _verdicts(pricing, contact):
    return (
        helpers.RuleVerdict("pricing", pricing, 0.5, "x"),
        helpers.RuleVerdict("contact", contact, 0.5, "x"),
    )


@pytest.mark.parametrize(
    "pricing,contact",
    [
        (helpers.CLEAR, helpers.CLEAR),
        (helpers.VIOLATES, helpers.VIOLATES),
        (helpers.REVIEW, helpers.CLEAR),
    ],
)
def test_thread_escalation_holds_whatever_the_verdicts_say(pricing, contact):
    result = helpers.screen_message("m1", _verdicts(pricing, contact), thread_escalated=True)
    assert (result.outcome, result.reason) == (helpers.HELD, "thread previously held")


def test_no_escalation_and_every_rule_clear_is_allowed():
    result = helpers.screen_message(
        "m1", _verdicts(helpers.CLEAR, helpers.CLEAR), thread_escalated=False
    )
    assert result.outcome == helpers.ALLOWED


def test_any_violation_holds_and_names_the_rule():
    result = helpers.screen_message(
        "m1", _verdicts(helpers.VIOLATES, helpers.CLEAR), thread_escalated=False
    )
    assert result.outcome == helpers.HELD
    assert "pricing" in result.reason


def test_any_uncertainty_holds_for_review_when_nothing_violates():
    result = helpers.screen_message(
        "m1", _verdicts(helpers.CLEAR, helpers.REVIEW), thread_escalated=False
    )
    assert result.outcome == helpers.HELD
    assert "contact" in result.reason


def test_violation_outranks_review_in_the_reason():
    # Both rules are unsettled in different ways; the message is held either way, but the
    # reason should name the more specific cause (a real violation) rather than "uncertain".
    result = helpers.screen_message(
        "m1", _verdicts(helpers.VIOLATES, helpers.REVIEW), thread_escalated=False
    )
    assert result.reason.startswith("violates")


# --------------------------------------------------------------------------- screen_thread


def test_screen_thread_escalates_after_the_first_held_message():
    entries = [
        ("a", {"pricing": 0.04, "contact": 0.90}),  # contact violates -> held
        ("b", {"pricing": 0.03, "contact": 0.03}),  # clean on its own content
    ]
    results = helpers.screen_thread(entries, {"pricing": 0.86, "contact": 0.50}, 0.14)
    assert [r.outcome for r in results] == [helpers.HELD, helpers.HELD]
    assert results[0].reason.startswith("violates")
    assert results[1].reason == "thread previously held"


def test_screen_thread_does_not_escalate_a_clean_thread():
    entries = [
        ("a", {"pricing": 0.03, "contact": 0.04}),
        ("b", {"pricing": 0.04, "contact": 0.03}),
    ]
    results = helpers.screen_thread(entries, {"pricing": 0.86, "contact": 0.50}, 0.14)
    assert [r.outcome for r in results] == [helpers.ALLOWED, helpers.ALLOWED]


def test_screen_thread_order_matters_a_later_hold_does_not_escalate_an_earlier_message():
    entries = [
        ("a", {"pricing": 0.03, "contact": 0.03}),  # clean, decided first
        ("b", {"pricing": 0.04, "contact": 0.90}),  # violates, decided second
    ]
    results = helpers.screen_thread(entries, {"pricing": 0.86, "contact": 0.50}, 0.14)
    assert results[0].outcome == helpers.ALLOWED  # nothing has held yet when "a" is decided
    assert results[1].outcome == helpers.HELD


def test_thread_escalation_on_the_committed_v_thread_fixture():
    """The stateful walkthrough the notebook replays: v13-thread violates on its own content,
    and v14-thread -- clean on its own content -- is held anyway because it shares a thread with
    v13 and is decided second. Real stored answers, not synthetic noul values."""
    examples = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    v13, v14 = examples["v13-thread"], examples["v14-thread"]
    assert v13.fields["thread_id"] == v14.fields["thread_id"]
    assert v13.fields["sequence"] < v14.fields["sequence"]
    assert labels["v14-thread"] == {"pricing": False, "contact": False}  # clean on its own

    def noul_by_rule(example):
        answers = backend.decide(helpers.build_state(example.fields), questions)
        return {rule: answers[rule].noul for rule in helpers.RULES}

    entries = [(v13.id, noul_by_rule(v13)), (v14.id, noul_by_rule(v14))]
    results = helpers.screen_thread(entries, {"pricing": 0.86, "contact": 0.50}, 0.14)
    by_id = {r.message_id: r for r in results}
    assert by_id["v13-thread"].outcome == helpers.HELD
    assert by_id["v13-thread"].reason.startswith("violates")
    assert by_id["v14-thread"].outcome == helpers.HELD
    assert by_id["v14-thread"].reason == "thread previously held"


# --------------------------------------------------------------------------- consequentiality
#
# Each rule must be independently able to change the composed outcome (rule 2 of the house
# briefing on multi-label Noul recipes): flipping one stored decision changes the result, shown
# on real committed fixtures rather than an in-test row built from scratch.


def test_pricing_alone_is_consequential_on_a_real_fixture():
    examples = {e.id: e for e in load_inputs(RECIPE)}
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    example = examples["v02-pricing"]  # gold: pricing violates, contact clear
    answers = backend.decide(helpers.build_state(example.fields), questions)
    thresholds, gate = {"pricing": 0.86, "contact": 0.50}, 0.14
    as_stored = tuple(
        helpers.verdict_for_rule(r, answers[r].noul, thresholds[r], gate) for r in helpers.RULES
    )
    stored_result = helpers.screen_message(example.id, as_stored, thread_escalated=False)
    assert stored_result.outcome == helpers.HELD  # the stored pricing noul (0.86) violates
    # Flip only the pricing noul below the threshold, leaving the real stored contact noul
    # untouched, and watch the composed outcome change.
    flipped = (
        helpers.verdict_for_rule("pricing", 0.05, thresholds["pricing"], gate),
        helpers.verdict_for_rule("contact", answers["contact"].noul, thresholds["contact"], gate),
    )
    flipped_result = helpers.screen_message(example.id, flipped, thread_escalated=False)
    assert flipped_result.outcome == helpers.ALLOWED


def test_contact_alone_is_consequential_on_a_real_fixture():
    examples = {e.id: e for e in load_inputs(RECIPE)}
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    example = examples["v03-contact"]  # gold: contact violates, pricing clear
    answers = backend.decide(helpers.build_state(example.fields), questions)
    thresholds, gate = {"pricing": 0.86, "contact": 0.50}, 0.14
    as_stored = tuple(
        helpers.verdict_for_rule(r, answers[r].noul, thresholds[r], gate) for r in helpers.RULES
    )
    stored_result = helpers.screen_message(example.id, as_stored, thread_escalated=False)
    assert stored_result.outcome == helpers.HELD  # the stored contact noul (0.87) violates
    flipped = (
        helpers.verdict_for_rule("pricing", answers["pricing"].noul, thresholds["pricing"], gate),
        helpers.verdict_for_rule("contact", 0.05, thresholds["contact"], gate),
    )
    flipped_result = helpers.screen_message(example.id, flipped, thread_escalated=False)
    assert flipped_result.outcome == helpers.ALLOWED


# --------------------------------------------------------------------------- screening_metrics


def test_screening_metrics_basic_rates():
    # 2 of 3 content-violating messages missed (allowed), 1 of 2 content-clear messages
    # falsely held, 2 of 5 total held.
    content_violates = [True, True, True, False, False]
    held = [True, False, False, True, False]
    m = helpers.screening_metrics(content_violates, held)
    assert m.missed_disclosure_rate == pytest.approx(2 / 3)
    assert m.false_hold_rate == pytest.approx(1 / 2)
    assert m.hold_rate == pytest.approx(2 / 5)
    assert (m.n_total, m.n_content_violates, m.n_content_clear, m.n_held) == (5, 3, 2, 2)


def test_screening_metrics_missed_rate_is_nan_when_nothing_violates():
    m = helpers.screening_metrics([False, False], [True, False])
    assert math.isnan(m.missed_disclosure_rate)
    assert m.false_hold_rate == pytest.approx(0.5)


def test_screening_metrics_false_hold_rate_is_nan_when_everything_violates():
    m = helpers.screening_metrics([True, True], [True, False])
    assert math.isnan(m.false_hold_rate)
    assert m.missed_disclosure_rate == pytest.approx(0.5)


def test_screening_metrics_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        helpers.screening_metrics([True], [True, False])


def test_screening_metrics_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one message"):
        helpers.screening_metrics([], [])


# --------------------------------------------------------------------------- pooling order


def test_pool_label_decisions_pools_label_then_example_with_correct_attribution():
    # docs/evaluation.md: "Labels are pooled outer-to-inner -- every example for one label,
    # then the next label." This recipe relies on that order to attribute a pooled (example,
    # label) pair back to its source; this test pins it against real committed data rather than
    # trusting the shared helper's own docstring alone.
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    val = select_split(examples, "validation")
    ids = [e.id for e in val]

    def nouls(rule):
        return [backend.decide(helpers.build_state(e.fields), questions)[rule].noul for e in val]

    gold_by_label = {rule: [labels[e.id][rule] for e in val] for rule in helpers.RULES}
    noul_by_label = {rule: nouls(rule) for rule in helpers.RULES}
    thresholds = {
        rule: select_threshold(gold_by_label[rule], noul_by_label[rule], objective="f1")
        for rule in helpers.RULES
    }
    correct, confidence, keys = pool_label_decisions(
        ids, list(helpers.RULES), gold_by_label, noul_by_label, thresholds
    )
    assert len(correct) == len(confidence) == len(keys) == len(ids) * len(helpers.RULES)
    # Every id, for pricing (the first label), then every id again, for contact.
    assert keys[: len(ids)] == [(i, "pricing") for i in ids]
    assert keys[len(ids) :] == [(i, "contact") for i in ids]
    # Attribution: the pooled confidence at a known key matches noul_confidence of the real
    # stored noul for that exact (example, label) pair, not some other example's.
    source_index = ids.index("v02-pricing")
    position = keys.index(("v02-pricing", "pricing"))
    assert confidence[position] == pytest.approx(
        confidence_of(noul_by_label["pricing"][source_index])
    )


# --------------------------------------------------------------------------- strong form


def test_stored_answers_are_not_all_right():
    """G1(c): re-derive both frozen cut-offs from ``validation`` -- the per-rule business
    threshold by F1, then the pooled confidence gate by a coverage floor -- and require a
    confidently wrong (example, rule) pair on ``test`` the frozen gate would still let through.
    Mirrors the notebook's own selection exactly, down to the pooling helper."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()

    def nouls(split, rule):
        return [backend.decide(helpers.build_state(e.fields), questions)[rule].noul for e in split]

    def gold(split, rule):
        return [labels[e.id][rule] for e in split]

    validation = select_split(examples, "validation")
    threshold = {
        rule: select_threshold(gold(validation, rule), nouls(validation, rule), objective="f1")
        for rule in helpers.RULES
    }
    val_ids = [e.id for e in validation]
    val_gold_by_label = {rule: gold(validation, rule) for rule in helpers.RULES}
    val_noul_by_label = {rule: nouls(validation, rule) for rule in helpers.RULES}
    val_correct, val_confidence, _ = pool_label_decisions(
        val_ids, list(helpers.RULES), val_gold_by_label, val_noul_by_label, threshold
    )
    gate = select_confidence_threshold(val_correct, val_confidence, min_coverage=_MIN_COVERAGE)

    test = select_split(examples, "test")
    test_ids = [e.id for e in test]
    test_gold_by_label = {rule: gold(test, rule) for rule in helpers.RULES}
    test_noul_by_label = {rule: nouls(test, rule) for rule in helpers.RULES}
    test_correct, test_confidence, test_keys = pool_label_decisions(
        test_ids, list(helpers.RULES), test_gold_by_label, test_noul_by_label, threshold
    )
    wrong_above_gate = [
        key
        for key, ok, conf in zip(test_keys, test_correct, test_confidence, strict=True)
        if conf >= gate and not ok
    ]
    assert wrong_above_gate, "expected at least one confidently wrong (example, rule) test pair"
