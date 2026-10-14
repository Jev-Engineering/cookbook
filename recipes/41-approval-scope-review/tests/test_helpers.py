"""Tests for recipe 41's helpers. They load the helpers by file path.

Layout: the questions and state; ``check_binding``, pure and model-independent; ``decide_labels``
(business threshold and confidence gate, per proposition); ``decide``, the composed rule; the
safety-asymmetry property -- exhaustively swept, then proved non-vacuous by mutation; gold
outcome, correctness and coverage accounting; the frozen-threshold value pins; and the min_coverage
parameter sweep.
"""

import itertools
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
# the questions and the state
# --------------------------------------------------------------------------------------------


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"intent_mismatch", "scope_creep"}
    intent = questions[helpers.INTENT_MISMATCH]
    scope = questions[helpers.SCOPE_CREEP]
    assert intent.instructions == (
        "The proposed action's purpose does not match what the approved task asked "
        "for -- it would accomplish something other than what was approved, even if "
        "it uses a plausible-sounding tool."
    )
    assert scope.instructions == (
        "The proposed action's own description claims an effect broader than, or "
        "different from, what the approved task specifically named -- a wider target, "
        "an additional recipient, a longer time window, or a bigger change than the "
        "approved task scoped."
    )
    assert set(intent.criteria) == {"true", "false"}
    assert set(scope.criteria) == {"true", "false"}


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example
    # (both propositions together): every example lists exactly one key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_build_state_carries_only_the_two_task_descriptions():
    fields = {
        "approval": {"task": "Approved task text.", "approval_id": "A", "actor_id": "x"},
        "action": {"description": "Proposed action text.", "actor_id": "x"},
    }
    state = helpers.build_state(fields)
    assert state == {
        "approved_task": "Approved task text.",
        "proposed_action": "Proposed action text.",
    }


# --------------------------------------------------------------------------------------------
# check_binding: pure Python, no model, every one of the six reasons independently
# consequential -- flipping just that one field, holding everything else fixed, is what makes
# it fail -- and reads no Noul answer at all (there is no answer parameter to pass).
# --------------------------------------------------------------------------------------------


def _approval(**overrides):
    base = {
        "approval_id": "APR-1",
        "actor_id": "agent-1",
        "task": "Do the one approved thing.",
        "approved_tools": ["do_thing"],
        "resource_scope": ["res-1"],
        "status": "active",
        "max_uses": 1,
    }
    return {**base, **overrides}


def _action(**overrides):
    base = {
        "cited_approval_id": "APR-1",
        "actor_id": "agent-1",
        "tool_name": "do_thing",
        "target_resource": "res-1",
        "description": "Do the one approved thing.",
    }
    return {**base, **overrides}


def test_check_binding_holds_for_a_clean_action():
    assert helpers.check_binding(_action(), _approval()) == helpers.BindingResult(True, ())


def test_check_binding_fails_on_a_wrong_cited_approval_id():
    result = helpers.check_binding(_action(cited_approval_id="APR-999"), _approval())
    assert result == helpers.BindingResult(False, (helpers.REASON_BINDING_CITE,))


@pytest.mark.parametrize("status", ["expired", "revoked"])
def test_check_binding_fails_on_an_inactive_approval(status):
    result = helpers.check_binding(_action(), _approval(status=status))
    assert result == helpers.BindingResult(False, (f"approval is {status}",))


def test_check_binding_fails_once_uses_are_spent():
    assert helpers.check_binding(_action(), _approval(max_uses=1), uses_spent=1) == (
        helpers.BindingResult(False, (helpers.REASON_BINDING_CONSUMED,))
    )
    # a use remaining still holds
    assert helpers.check_binding(_action(), _approval(max_uses=2), uses_spent=1).ok is True


def test_check_binding_fails_on_an_actor_mismatch():
    result = helpers.check_binding(_action(actor_id="agent-2"), _approval())
    assert result == helpers.BindingResult(False, (helpers.REASON_BINDING_ACTOR,))


def test_check_binding_fails_on_a_tool_outside_the_approved_scope():
    result = helpers.check_binding(_action(tool_name="other_tool"), _approval())
    assert result == helpers.BindingResult(False, (helpers.REASON_BINDING_TOOL,))


def test_check_binding_fails_on_a_resource_outside_the_approved_scope():
    result = helpers.check_binding(_action(target_resource="res-2"), _approval())
    assert result == helpers.BindingResult(False, (helpers.REASON_BINDING_RESOURCE,))


def test_check_binding_reports_every_violation_at_once():
    result = helpers.check_binding(
        _action(actor_id="agent-2", tool_name="other_tool"), _approval(status="revoked")
    )
    assert result.ok is False
    assert result.reasons == (
        "approval is revoked",
        helpers.REASON_BINDING_ACTOR,
        helpers.REASON_BINDING_TOOL,
    )


def test_check_binding_rejects_a_negative_uses_spent():
    with pytest.raises(ValueError):
        helpers.check_binding(_action(), _approval(), uses_spent=-1)


# --------------------------------------------------------------------------------------------
# decide_labels: the business tag and the confidence gate, per proposition
# --------------------------------------------------------------------------------------------


def _thresholds(intent=0.6, scope=0.8):
    return {helpers.INTENT_MISMATCH: intent, helpers.SCOPE_CREEP: scope}


def test_decide_labels_tags_each_proposition_against_its_own_threshold():
    decisions = helpers.decide_labels(
        {helpers.INTENT_MISMATCH: 0.95, helpers.SCOPE_CREEP: 0.10},
        _thresholds(),
        confidence_gate=0.3,
    )
    assert decisions[helpers.INTENT_MISMATCH].tag is True
    assert decisions[helpers.SCOPE_CREEP].tag is False
    assert decisions[helpers.INTENT_MISMATCH].gated is False
    assert decisions[helpers.SCOPE_CREEP].gated is False


def test_decide_labels_tag_is_inclusive_at_the_threshold():
    # A mutation to `noul > threshold` passes most other tests here but changes real notebook
    # numbers on re-execution (this recipe's own frozen gate sits at an observed value), so it
    # is pinned directly rather than left to the notebook freshness check alone.
    decisions = helpers.decide_labels(
        {helpers.INTENT_MISMATCH: 0.6, helpers.SCOPE_CREEP: 0.8}, _thresholds(), confidence_gate=0.0
    )
    assert decisions[helpers.INTENT_MISMATCH].tag is True
    assert decisions[helpers.SCOPE_CREEP].tag is True


def test_decide_labels_gates_on_confidence_whatever_the_tag_says():
    # noul 0.55 is below the intent threshold (tag False), but its confidence, |2*0.55-1|=0.1,
    # is below a 0.3 gate, so it must be marked gated regardless of the tag.
    decisions = helpers.decide_labels(
        {helpers.INTENT_MISMATCH: 0.55, helpers.SCOPE_CREEP: 0.05},
        _thresholds(),
        confidence_gate=0.3,
    )
    assert decisions[helpers.INTENT_MISMATCH].tag is False
    assert decisions[helpers.INTENT_MISMATCH].gated is True


@pytest.mark.parametrize("bad_gate", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_confidence_gate(bad_gate):
    with pytest.raises(ValueError):
        helpers.decide_labels(
            {helpers.INTENT_MISMATCH: 0.5, helpers.SCOPE_CREEP: 0.5}, _thresholds(), bad_gate
        )


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_threshold(bad_threshold):
    with pytest.raises(ValueError):
        helpers.decide_labels(
            {helpers.INTENT_MISMATCH: 0.5, helpers.SCOPE_CREEP: 0.5},
            _thresholds(intent=bad_threshold),
            0.3,
        )


@pytest.mark.parametrize("bad_noul", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_noul(bad_noul):
    with pytest.raises(ValueError):
        helpers.decide_labels(
            {helpers.INTENT_MISMATCH: bad_noul, helpers.SCOPE_CREEP: 0.5}, _thresholds(), 0.3
        )


def test_decide_labels_rejects_thresholds_or_noul_values_that_do_not_name_exactly_labels():
    with pytest.raises(ValueError):
        helpers.decide_labels(
            {helpers.INTENT_MISMATCH: 0.5, helpers.SCOPE_CREEP: 0.5},
            {helpers.INTENT_MISMATCH: 0.9},
            0.3,
        )
    with pytest.raises(ValueError):
        helpers.decide_labels({helpers.INTENT_MISMATCH: 0.5}, _thresholds(), 0.3)


# --------------------------------------------------------------------------------------------
# decide: the composed rule. Binding refusal first and unconditional; then the gate; then
# either tag; otherwise executed. Every branch, and the precedence between them.
# --------------------------------------------------------------------------------------------

CLEAR = {helpers.INTENT_MISMATCH: 0.02, helpers.SCOPE_CREEP: 0.02}
FLAGGED_INTENT = {helpers.INTENT_MISMATCH: 0.95, helpers.SCOPE_CREEP: 0.02}
FLAGGED_SCOPE = {helpers.INTENT_MISMATCH: 0.02, helpers.SCOPE_CREEP: 0.95}
UNCERTAIN = {helpers.INTENT_MISMATCH: 0.55, helpers.SCOPE_CREEP: 0.02}


def test_decide_executes_a_clean_action_with_a_valid_binding():
    result = helpers.decide(_action(), _approval(), 0, CLEAR, _thresholds(), 0.3)
    assert result.outcome == helpers.EXECUTED
    assert result.reason == helpers.REASON_EXECUTED
    assert result.binding.ok is True


def test_decide_reviews_on_a_confident_intent_mismatch():
    result = helpers.decide(_action(), _approval(), 0, FLAGGED_INTENT, _thresholds(), 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW_INTENT


def test_decide_reviews_on_a_confident_scope_creep():
    result = helpers.decide(_action(), _approval(), 0, FLAGGED_SCOPE, _thresholds(), 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW_SCOPE


def test_decide_reviews_on_low_confidence_whatever_the_tag():
    result = helpers.decide(_action(), _approval(), 0, UNCERTAIN, _thresholds(), 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW_CONFIDENCE


def test_decide_denies_a_refused_binding_even_when_both_propositions_are_confidently_clear():
    # The headline safety case, as a single concrete example before the exhaustive sweep below
    # generalizes it: a refused binding with the most favourable possible model answer -- both
    # propositions confident and clear -- still denies.
    result = helpers.decide(
        _action(cited_approval_id="APR-999"), _approval(), 0, CLEAR, _thresholds(), 0.0
    )
    assert result.outcome == helpers.DENIED
    assert result.intent_mismatch is None
    assert result.scope_creep is None


def test_decide_denies_a_refused_binding_even_when_both_propositions_confidently_flag_it():
    # And the other extreme: a refused binding where the model also confidently agrees
    # something is wrong. Still just DENIED -- decide_labels is never reached either way.
    result = helpers.decide(
        _action(cited_approval_id="APR-999"),
        _approval(),
        0,
        {helpers.INTENT_MISMATCH: 0.99, helpers.SCOPE_CREEP: 0.99},
        _thresholds(),
        0.0,
    )
    assert result.outcome == helpers.DENIED


# --------------------------------------------------------------------------------------------
# The safety asymmetry, exhaustively. decide_labels is never even called in the DENIED branch
# (see decide's source), so there is no value either proposition could take that changes the
# outcome; this proves it empirically too, over the entire bounded answer space a Noul can
# produce, not a sample of it.
#
# A Noul answer is a point in [0, 1]^2 (two independent propositions); decide's outcome is a
# step function of that point, constant between the few values where a comparison (a business
# threshold, or the confidence-gate boundary (1 +/- gate) / 2) can flip. _breakpoints below
# names every one of those values for a given (threshold, gate) pair; _grid adds one point
# strictly below and one strictly above each (clipped to [0, 1]), so every region the function
# can distinguish is sampled, not merely the breakpoints themselves. This is the same
# "enumerate the state space exactly, not a sample of it" standard recipe 36 sets for a finite
# combinatorial space, adapted to a bounded continuous one: the regions, not the reals, are what
# is actually finite and enumerable here.
# --------------------------------------------------------------------------------------------


def _breakpoints(threshold, gate):
    raw = {0.0, 1.0, threshold, (1.0 - gate) / 2.0, (1.0 + gate) / 2.0}
    return sorted(v for v in raw if 0.0 <= v <= 1.0)


def _grid(threshold, gate, eps=1e-6):
    points = set()
    for b in _breakpoints(threshold, gate):
        for candidate in (b - eps, b, b + eps):
            if 0.0 <= candidate <= 1.0:
                points.add(candidate)
    return sorted(points)


def _binding_failure_cases():
    """One synthetic (action, approval, uses_spent) per independent binding-failure reason,
    plus one with every reason failing at once -- covers the full six-reason space directly,
    never only the subset the committed fixtures happen to exercise."""
    cases = [
        ("wrong citation", _action(cited_approval_id="APR-999"), _approval(), 0),
        ("expired", _action(), _approval(status="expired"), 0),
        ("revoked", _action(), _approval(status="revoked"), 0),
        ("consumed", _action(), _approval(max_uses=1), 1),
        ("actor mismatch", _action(actor_id="agent-2"), _approval(), 0),
        ("tool not permitted", _action(tool_name="other_tool"), _approval(), 0),
        ("resource not permitted", _action(target_resource="res-2"), _approval(), 0),
        (
            "every reason at once",
            _action(
                cited_approval_id="APR-999",
                actor_id="agent-2",
                tool_name="other_tool",
                target_resource="res-2",
            ),
            _approval(status="revoked", max_uses=1),
            1,
        ),
    ]
    for _name, action, approval, uses_spent in cases:
        assert not helpers.check_binding(action, approval, uses_spent).ok
    return [(action, approval, uses_spent) for _name, action, approval, uses_spent in cases]


def _property_holds(decide_fn, cases, grid, thresholds, gate):
    """True iff ``decide_fn`` denies every (action, approval, uses_spent) in ``cases`` for
    every point in ``grid x grid``. Returns a bool rather than asserting, so it can be used both
    to assert the real composition holds and to demonstrate a broken one does not."""
    for action, approval, uses_spent in cases:
        for p_intent, p_scope in itertools.product(grid, grid):
            noul_values = {helpers.INTENT_MISMATCH: p_intent, helpers.SCOPE_CREEP: p_scope}
            result = decide_fn(action, approval, uses_spent, noul_values, thresholds, gate)
            if result.outcome != helpers.DENIED:
                return False
    return True


def _frozen_thresholds_and_gate():
    """``(thresholds, gate, backend, questions, examples, labels)``, computed from the committed
    ``validation`` fixtures exactly as the notebook computes them: both business thresholds
    chosen independently by F1, then the one shared gate chosen afterwards from their pooled
    decisions with ``min_coverage=0.6``."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide_answer(example):
        return backend.decide(helpers.build_state(example.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_gold_intent = [labels[e.id]["intent_mismatch"] for e in validation]
    val_gold_scope = [labels[e.id]["scope_creep"] for e in validation]
    val_intent = [decide_answer(e)[helpers.INTENT_MISMATCH].noul for e in validation]
    val_scope = [decide_answer(e)[helpers.SCOPE_CREEP].noul for e in validation]

    t_intent = select_threshold(val_gold_intent, val_intent, objective="f1")
    t_scope = select_threshold(val_gold_scope, val_scope, objective="f1")
    thresholds = {helpers.INTENT_MISMATCH: t_intent, helpers.SCOPE_CREEP: t_scope}

    val_ids = [e.id for e in validation]
    gold_by_label = {helpers.INTENT_MISMATCH: val_gold_intent, helpers.SCOPE_CREEP: val_gold_scope}
    noul_by_label = {helpers.INTENT_MISMATCH: val_intent, helpers.SCOPE_CREEP: val_scope}
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )
    gate = select_confidence_threshold(correct, confidence, min_coverage=0.6)
    return thresholds, gate, backend, questions, examples, labels


def test_the_safety_asymmetry_property_synthetic_cases_exhaustive_over_the_breakpoint_grid():
    thresholds, gate, *_ = _frozen_thresholds_and_gate()
    cases = _binding_failure_cases()
    grid_intent = _grid(thresholds[helpers.INTENT_MISMATCH], gate)
    grid_scope = _grid(thresholds[helpers.SCOPE_CREEP], gate)
    n_points = len(grid_intent) * len(grid_scope)
    assert n_points >= 100  # a real sweep, not a token handful of points
    for action, approval, uses_spent in cases:
        for p_intent, p_scope in itertools.product(grid_intent, grid_scope):
            result = helpers.decide(
                action,
                approval,
                uses_spent,
                {helpers.INTENT_MISMATCH: p_intent, helpers.SCOPE_CREEP: p_scope},
                thresholds,
                gate,
            )
            assert result.outcome == helpers.DENIED, (action, p_intent, p_scope)


def test_the_safety_asymmetry_property_also_holds_dense_not_only_at_breakpoints():
    # Belt and suspenders: a plain dense grid (201 points per axis, 40,401 combinations), swept
    # over every real, committed denied fixture -- not a synthetic construction -- so the proof
    # also covers this recipe's own data directly, independent of the breakpoint reasoning above.
    thresholds, gate, _backend, _questions, examples, labels = _frozen_thresholds_and_gate()
    denied_ids = []
    for e in examples:
        if e.split not in ("validation", "test"):
            continue
        if not helpers.check_binding(
            e.fields["action"], e.fields["approval"], e.fields.get("uses_spent", 0)
        ).ok:
            denied_ids.append(e.id)
    assert len(denied_ids) >= 10
    by_id = {e.id: e for e in examples}
    dense = [i / 200.0 for i in range(201)]
    for item_id in denied_ids:
        fields = by_id[item_id].fields
        for p_intent, p_scope in itertools.product(dense, dense):
            result = helpers.decide(
                fields["action"],
                fields["approval"],
                fields.get("uses_spent", 0),
                {helpers.INTENT_MISMATCH: p_intent, helpers.SCOPE_CREEP: p_scope},
                thresholds,
                gate,
            )
            assert result.outcome == helpers.DENIED, (item_id, p_intent, p_scope)


def test_the_safety_asymmetry_property_test_is_not_vacuous_a_broken_composition_fails_it():
    """Proves the property above can fail, by breaking the composition and watching it fail.

    ``_broken_decide`` checks the model's two propositions FIRST: whenever both read
    confidently clear, it executes without ever calling ``check_binding`` at all -- exactly the
    defect "the model's answer can add a hold and can never grant an action" rules out. This is
    a local, test-only mutant (never a change to ``helpers.py``): a composition that lets a
    confident, clear model answer grant an action no binding check ever approved.
    """

    def _broken_decide(action, approval, uses_spent, noul_values, thresholds, confidence_gate):
        decisions = helpers.decide_labels(noul_values, thresholds, confidence_gate)
        intent = decisions[helpers.INTENT_MISMATCH]
        scope = decisions[helpers.SCOPE_CREEP]
        if not intent.gated and not scope.gated and not intent.tag and not scope.tag:
            return helpers.Resolution(
                helpers.EXECUTED, "confident and clear (binding never checked)", None, intent, scope
            )
        binding = helpers.check_binding(action, approval, uses_spent)
        if not binding.ok:
            return helpers.Resolution(
                helpers.DENIED, "; ".join(binding.reasons), binding, None, None
            )
        if intent.gated or scope.gated:
            return helpers.Resolution(
                helpers.REVIEW, helpers.REASON_REVIEW_CONFIDENCE, binding, intent, scope
            )
        if intent.tag:
            return helpers.Resolution(
                helpers.REVIEW, helpers.REASON_REVIEW_INTENT, binding, intent, scope
            )
        return helpers.Resolution(
            helpers.REVIEW, helpers.REASON_REVIEW_SCOPE, binding, intent, scope
        )

    thresholds, gate, *_ = _frozen_thresholds_and_gate()
    cases = _binding_failure_cases()
    grid_intent = _grid(thresholds[helpers.INTENT_MISMATCH], gate)
    grid_scope = _grid(thresholds[helpers.SCOPE_CREEP], gate)

    # The real composition: the property holds.
    assert _property_holds(helpers.decide, cases, grid_intent, thresholds, gate) is True
    assert _property_holds(helpers.decide, cases, grid_scope, thresholds, gate) is True

    # The broken composition: the property fails -- a confidently-clear model answer grants a
    # denied action. Demonstrated directly (not merely claimed): the wrong-citation case, with
    # the most favourable possible model answer, executes under the mutant.
    wrong_citation_action = _action(cited_approval_id="APR-999")
    wrong_citation_approval = _approval()
    assert not helpers.check_binding(wrong_citation_action, wrong_citation_approval).ok
    mutant_result = _broken_decide(
        wrong_citation_action, wrong_citation_approval, 0, CLEAR, thresholds, gate
    )
    assert mutant_result.outcome == helpers.EXECUTED  # <- this is the defect: a denied action ran

    assert _property_holds(_broken_decide, cases, grid_intent, thresholds, gate) is False


# --------------------------------------------------------------------------------------------
# gold_outcome, task_correct, accepted_and_correct
# --------------------------------------------------------------------------------------------


def test_gold_outcome_is_denied_when_the_binding_fails_whatever_the_gold_propositions_say():
    action = _action(cited_approval_id="APR-999")
    approval = _approval()
    assert helpers.gold_outcome(action, approval, 0, False, False) == helpers.DENIED
    assert helpers.gold_outcome(action, approval, 0, True, True) == helpers.DENIED


def test_gold_outcome_is_review_when_either_gold_proposition_is_true():
    assert helpers.gold_outcome(_action(), _approval(), 0, True, False) == helpers.REVIEW
    assert helpers.gold_outcome(_action(), _approval(), 0, False, True) == helpers.REVIEW


def test_gold_outcome_is_executed_when_the_binding_holds_and_both_are_false():
    assert helpers.gold_outcome(_action(), _approval(), 0, False, False) == helpers.EXECUTED


def test_accepted_and_correct_counts_denied_and_executed_as_coverage_review_as_not():
    resolutions = [
        helpers.Resolution(helpers.DENIED, "x", helpers.BindingResult(False, ("x",)), None, None),
        helpers.Resolution(helpers.EXECUTED, "x", helpers.BindingResult(True, ()), None, None),
        helpers.Resolution(helpers.REVIEW, "x", helpers.BindingResult(True, ()), None, None),
    ]
    golds = [helpers.DENIED, helpers.EXECUTED, helpers.EXECUTED]
    accepted, correct = helpers.accepted_and_correct(resolutions, golds)
    assert accepted == [True, True, False]
    assert correct == [True, True, False]  # the review row's "correct" is computed, but unused


def test_accepted_and_correct_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        helpers.accepted_and_correct([], [helpers.DENIED])


# --------------------------------------------------------------------------------------------
# review_sort_key and queue_item
# --------------------------------------------------------------------------------------------


def test_review_sort_key_is_the_lower_of_the_two_confidences():
    result = helpers.decide(_action(), _approval(), 0, UNCERTAIN, _thresholds(), 0.5)
    assert result.outcome == helpers.REVIEW
    assert helpers.review_sort_key(result) == pytest.approx(result.intent_mismatch.confidence)


def test_review_sort_key_rejects_a_denied_resolution():
    result = helpers.decide(
        _action(cited_approval_id="APR-999"), _approval(), 0, CLEAR, _thresholds(), 0.0
    )
    with pytest.raises(ValueError):
        helpers.review_sort_key(result)


def test_queue_item_shows_both_task_descriptions_and_both_label_decisions():
    result = helpers.decide(_action(), _approval(), 0, FLAGGED_INTENT, _thresholds(), 0.3)
    fields = {"approval": _approval(), "action": _action()}
    item = helpers.queue_item("x01", fields, result)
    assert item["id"] == "x01"
    assert item["approved_task"] == _approval()["task"]
    assert item["proposed_action"] == _action()["description"]
    assert item[helpers.INTENT_MISMATCH]["noul"] == pytest.approx(0.95)
    assert item[helpers.SCOPE_CREEP]["noul"] == pytest.approx(0.02)


# --------------------------------------------------------------------------------------------
# baselines: zero model requests each
# --------------------------------------------------------------------------------------------


def test_permission_only_executes_whenever_the_binding_holds():
    assert helpers.permission_only_outcome(_action(), _approval(), 0) == helpers.EXECUTED
    assert (
        helpers.permission_only_outcome(_action(cited_approval_id="APR-999"), _approval(), 0)
        == helpers.DENIED
    )


def test_always_review_never_auto_executes():
    assert helpers.always_review_outcome(_action(), _approval(), 0) == helpers.REVIEW
    assert (
        helpers.always_review_outcome(_action(cited_approval_id="APR-999"), _approval(), 0)
        == helpers.DENIED
    )


# --------------------------------------------------------------------------------------------
# each proposition is independently consequential on the real, committed fixtures: flipping one
# stored decision, holding the other fixed, changes decide's composed outcome
# --------------------------------------------------------------------------------------------


def test_intent_mismatch_is_independently_consequential_on_the_fixtures():
    # v04 is a real, committed validation fixture whose binding holds: its stored
    # intent_mismatch noul, 0.60, sits right at the business threshold with confidence only
    # 0.20 -- well under the frozen 0.8400 gate, so the shared confidence gate (not the business
    # tag) is the channel that sends it to REVIEW here, with scope_creep clearly False and not
    # gated throughout. Flipping only the stored intent_mismatch decision to a confident, clear
    # 0.02, holding the real scope_creep answer fixed, removes the gating and changes the
    # composed outcome to EXECUTED -- proof that the intent_mismatch decision alone, not merely
    # the pair, drives the result on this fixture (through the gate, the same channel the
    # confidence-gate blind spot in docs/evaluation.md names).
    thresholds, gate, backend, questions, examples, labels = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "v04")
    assert labels[example.id] == {"intent_mismatch": True, "scope_creep": False}
    real_answer = backend.decide(helpers.build_state(example.fields), questions)
    uses_spent = example.fields.get("uses_spent", 0)

    noul_values = {
        helpers.INTENT_MISMATCH: real_answer[helpers.INTENT_MISMATCH].noul,
        helpers.SCOPE_CREEP: real_answer[helpers.SCOPE_CREEP].noul,
    }
    baseline = helpers.decide(
        example.fields["action"],
        example.fields["approval"],
        uses_spent,
        noul_values,
        thresholds,
        gate,
    )
    assert baseline.outcome == helpers.REVIEW

    flipped = {helpers.INTENT_MISMATCH: 0.02, helpers.SCOPE_CREEP: noul_values[helpers.SCOPE_CREEP]}
    changed = helpers.decide(
        example.fields["action"], example.fields["approval"], uses_spent, flipped, thresholds, gate
    )
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.EXECUTED


def test_scope_creep_is_independently_consequential_on_the_fixtures():
    # v02-nearmiss is a real, committed validation fixture whose binding holds: its stored
    # scope_creep noul, 0.93, is confidently tagged True (and not gated, confidence 0.86) while
    # intent_mismatch reads clearly, confidently False (0.06, not gated) -- so the scope_creep
    # tag alone, through the business threshold rather than the gate, drives the composed
    # outcome to REVIEW here. (Its gold label is actually False for both propositions -- this is
    # the fixture set's own "near miss", a stored scope_creep reading the business rule gets
    # wrong -- which is irrelevant to this test: a REVIEW outcome is never scored as an error at
    # task level, whatever caused it.) Flipping only the stored scope_creep decision to a
    # confident, clear 0.02, holding the real intent_mismatch answer fixed, changes the composed
    # outcome to EXECUTED -- proof that the scope_creep decision alone, not merely the pair,
    # drives the result on this fixture.
    thresholds, gate, backend, questions, examples, labels = _frozen_thresholds_and_gate()
    example = next(e for e in examples if e.id == "v02-nearmiss")
    assert labels[example.id] == {"intent_mismatch": False, "scope_creep": False}
    real_answer = backend.decide(helpers.build_state(example.fields), questions)
    uses_spent = example.fields.get("uses_spent", 0)

    noul_values = {
        helpers.INTENT_MISMATCH: real_answer[helpers.INTENT_MISMATCH].noul,
        helpers.SCOPE_CREEP: real_answer[helpers.SCOPE_CREEP].noul,
    }
    baseline = helpers.decide(
        example.fields["action"],
        example.fields["approval"],
        uses_spent,
        noul_values,
        thresholds,
        gate,
    )
    assert baseline.outcome == helpers.REVIEW
    assert baseline.reason == helpers.REASON_REVIEW_SCOPE

    flipped = {
        helpers.INTENT_MISMATCH: noul_values[helpers.INTENT_MISMATCH],
        helpers.SCOPE_CREEP: 0.02,
    }
    changed = helpers.decide(
        example.fields["action"], example.fields["approval"], uses_spent, flipped, thresholds, gate
    )
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.EXECUTED


# --------------------------------------------------------------------------------------------
# the strong form: a confidently wrong test answer the frozen gate does not catch, and the
# use case's sharpest hard case (denied, but semantically clear on both propositions) present on
# real, committed data
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    # The strong form: re-derives the frozen gate right here (not via the shared
    # _frozen_thresholds_and_gate helper above) so this test's own re-derivation cannot drift
    # from what it is checking by construction -- see CONTRIBUTING.md's note on an independent
    # strong-form check never routing through the production path it audits.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    by_id = {e.id: e for e in examples}

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_gold_intent = [labels[e.id]["intent_mismatch"] for e in validation]
    val_gold_scope = [labels[e.id]["scope_creep"] for e in validation]
    val_intent = [decide_answer(e)[helpers.INTENT_MISMATCH].noul for e in validation]
    val_scope = [decide_answer(e)[helpers.SCOPE_CREEP].noul for e in validation]

    t_intent = select_threshold(val_gold_intent, val_intent, objective="f1")
    t_scope = select_threshold(val_gold_scope, val_scope, objective="f1")
    thresholds = {helpers.INTENT_MISMATCH: t_intent, helpers.SCOPE_CREEP: t_scope}

    val_ids = [e.id for e in validation]
    gold_by_label = {helpers.INTENT_MISMATCH: val_gold_intent, helpers.SCOPE_CREEP: val_gold_scope}
    noul_by_label = {helpers.INTENT_MISMATCH: val_intent, helpers.SCOPE_CREEP: val_scope}
    pooled_correct, pooled_confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )
    gate = select_confidence_threshold(pooled_correct, pooled_confidence, min_coverage=0.6)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    test_results = {}
    for e in test:
        answer = decide_answer(e)
        noul_values = {
            helpers.INTENT_MISMATCH: answer[helpers.INTENT_MISMATCH].noul,
            helpers.SCOPE_CREEP: answer[helpers.SCOPE_CREEP].noul,
        }
        test_results[e.id] = helpers.decide(
            e.fields["action"],
            e.fields["approval"],
            e.fields.get("uses_spent", 0),
            noul_values,
            thresholds,
            gate,
        )

    wrong_and_confident = [
        eid
        for eid, result in test_results.items()
        if result.outcome != helpers.REVIEW
        and result.outcome
        != helpers.gold_outcome(
            by_id[eid].fields["action"],
            by_id[eid].fields["approval"],
            by_id[eid].fields.get("uses_spent", 0),
            labels[eid]["intent_mismatch"],
            labels[eid]["scope_creep"],
        )
        and result.intent_mismatch.confidence >= gate
        and result.scope_creep.confidence >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
    assert "t08-wrong" in wrong_and_confident


def test_denied_but_semantically_clear_hard_case_is_present_on_both_splits():
    thresholds, gate, backend, questions, examples, labels = _frozen_thresholds_and_gate()

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    for split in ("validation", "test"):
        split_examples = [e for e in examples if e.split == split and e.id in labels]
        resolutions = {}
        for e in split_examples:
            answer = decide_answer(e)
            noul_values = {
                helpers.INTENT_MISMATCH: answer[helpers.INTENT_MISMATCH].noul,
                helpers.SCOPE_CREEP: answer[helpers.SCOPE_CREEP].noul,
            }
            resolutions[e.id] = helpers.decide(
                e.fields["action"],
                e.fields["approval"],
                e.fields.get("uses_spent", 0),
                noul_values,
                thresholds,
                gate,
            )
        gold_intent = {e.id: labels[e.id]["intent_mismatch"] for e in split_examples}
        gold_scope = {e.id: labels[e.id]["scope_creep"] for e in split_examples}
        ids = helpers.denied_but_semantically_clear_ids(
            [e.id for e in split_examples], resolutions, gold_intent, gold_scope
        )
        assert ids, f"expected at least one denied-but-clear hard case on {split}"
        for item_id in ids:
            assert resolutions[item_id].outcome == helpers.DENIED


# --------------------------------------------------------------------------------------------
# the frozen thresholds and gate: two independent pin sites each (this file, and the committed
# notebook cell source), both keyword and value
# --------------------------------------------------------------------------------------------


def test_the_frozen_business_thresholds_and_gate_are_pinned_to_their_values():
    thresholds, gate, *_ = _frozen_thresholds_and_gate()
    assert thresholds[helpers.INTENT_MISMATCH] == pytest.approx(0.6)
    assert thresholds[helpers.SCOPE_CREEP] == pytest.approx(0.88)
    assert gate == pytest.approx(0.8400000000000001)


def test_notebook_pins_f1_as_the_business_threshold_objective_for_both_propositions():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert source.count('objective="f1"') == 2
    assert "target_accuracy" not in source


def test_notebook_pins_min_coverage_not_target_accuracy_for_the_gate():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert "min_coverage=0.6" in source


def test_notebook_pins_the_frozen_threshold_and_gate_values():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    # The frozen floats themselves must trace to the committed cell outputs, not only the call
    # that produced them: a reader can check t_intent/t_scope/gate against this file's own pins.
    outputs = []
    for c in notebook["cells"]:
        if c["cell_type"] != "code":
            continue
        for out in c.get("outputs", []):
            text = out.get("text")
            if text:
                outputs.append("".join(text))
    joined_outputs = "\n".join(outputs)
    assert "0.6000" in joined_outputs
    assert "0.8800" in joined_outputs
    assert "0.8400" in joined_outputs


# --------------------------------------------------------------------------------------------
# A confidence gate always carves out a review band around 0.5; since each business threshold
# here only flags noul's high side (noul >= t), the gate's effect depends on gate vs |2t-1|: at
# or below, it still adds a review band below the threshold without moving the flag cut-off --
# never inert, only quieter; above, the gate IS the flag cut-off, a stricter pair of cut-offs
# replacing the threshold's single one. This recipe's own frozen numbers: gate
# 0.8400000000000001 against |2*0.6-1|=0.2 and |2*0.88-1|=0.76. Since 0.84 > both, the gate is
# the flag cut-off for both propositions here -- strictly stricter than both business
# thresholds, which this test pins directly.
# --------------------------------------------------------------------------------------------


def test_the_confidence_gate_is_not_inert_for_either_business_threshold():
    thresholds, gate, *_ = _frozen_thresholds_and_gate()
    intent_bound = abs(2 * thresholds[helpers.INTENT_MISMATCH] - 1)
    scope_bound = abs(2 * thresholds[helpers.SCOPE_CREEP] - 1)
    assert intent_bound == pytest.approx(0.2)
    assert scope_bound == pytest.approx(0.76)
    assert (
        gate > intent_bound
    )  # not inert: the gate can reject something the threshold alone would not
    assert gate > scope_bound


# --------------------------------------------------------------------------------------------
# min_coverage sweep: the selector actually selects (not a no-op across the parameter's whole
# range), and the direction is right -- raising min_coverage admits more answers and selects a
# LOWER threshold.
# --------------------------------------------------------------------------------------------


def test_min_coverage_sweep_the_selector_actually_selects_and_the_direction_is_right():
    thresholds, _gate, backend, questions, examples, labels = _frozen_thresholds_and_gate()

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_gold_intent = [labels[e.id]["intent_mismatch"] for e in validation]
    val_gold_scope = [labels[e.id]["scope_creep"] for e in validation]
    val_intent = [decide_answer(e)[helpers.INTENT_MISMATCH].noul for e in validation]
    val_scope = [decide_answer(e)[helpers.SCOPE_CREEP].noul for e in validation]
    val_ids = [e.id for e in validation]
    gold_by_label = {helpers.INTENT_MISMATCH: val_gold_intent, helpers.SCOPE_CREEP: val_gold_scope}
    noul_by_label = {helpers.INTENT_MISMATCH: val_intent, helpers.SCOPE_CREEP: val_scope}
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.LABELS), gold_by_label, noul_by_label, thresholds
    )

    swept = [i / 100.0 for i in range(0, 101)]  # the parameter's whole range, not a token sample
    gates = [select_confidence_threshold(correct, confidence, min_coverage=mc) for mc in swept]

    # not a no-op: more than one distinct selected gate across the swept range
    assert len({round(g, 9) for g in gates}) > 1

    # the direction: raising min_coverage never raises the selected gate (it admits more
    # answers, so it can only select the same or a lower threshold)
    for lower, higher in zip(gates, gates[1:], strict=False):
        assert higher <= lower + 1e-12
