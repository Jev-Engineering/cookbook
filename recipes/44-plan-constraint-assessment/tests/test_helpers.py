"""Tests for recipe 44's helpers. They load the helpers by file path.

Layout: the questions and the state; ``decide_labels`` (business threshold and confidence
gate, per constraint); ``decide``, the composed rule, and its precedence; the four
constraints' independent consequentiality on the real fixtures; gold outcome, correctness and
coverage accounting; the named hard case (satisfies every constraint but one); the three
zero-request baselines; the stateful walkthrough's own bookkeeping function; the frozen
threshold and gate pin sites (value and notebook-cell-source); a mutation proof for each; the
Noul-gate band measured by grid, by side; the ``min_coverage`` sweep; and the pooling-order /
attribution check for the pooled (plan, constraint) decisions.
"""

import json
from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    evaluate_threshold,
    multilabel_from_noul,
    multilabel_metrics,
    noul_confidence,
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
    assert set(questions) == {"budget", "timeline", "vendor", "data_handling"}
    for name in helpers.CONSTRAINTS:
        assert set(questions[name].criteria) == {"true", "false"}
    assert questions[helpers.BUDGET].instructions == (
        "The plan violates the user's stated budget constraint: its own described costs "
        "exceed the limit the constraint states, or the plan's own text leaves it unclear "
        "that it stays within that limit."
    )
    assert questions[helpers.DATA_HANDLING].instructions == (
        "The plan violates the user's stated data handling constraint: it shares the user's "
        "personal data with a party the constraint does not approve, or the plan's own text "
        "leaves unclear who the data actually reaches."
    )


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per plan
    # (all four propositions together): every example lists exactly one key.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_build_state_carries_only_the_constraints_and_the_plan():
    fields = {
        "user_constraints": {
            "budget": "Budget constraint: total plan cost must not exceed $1.",
            "timeline": "Timeline constraint: every step must be completed by Jan 1.",
            "vendor": "Vendor constraint: only these vendors are pre-approved for this task: X.",
            "data_handling": "Data handling constraint: the user's personal data may be shared only with X.",
        },
        "plan": "Do the one approved thing.",
        "cost": 1,
    }
    state = helpers.build_state(fields)
    assert state == {"user_constraints": fields["user_constraints"], "plan": fields["plan"]}
    assert "cost" not in state


# --------------------------------------------------------------------------------------------
# decide_labels: the business tag and the confidence gate, per constraint
# --------------------------------------------------------------------------------------------


def _thresholds(budget=0.5, timeline=0.5, vendor=0.5, data_handling=0.5):
    return {
        helpers.BUDGET: budget,
        helpers.TIMELINE: timeline,
        helpers.VENDOR: vendor,
        helpers.DATA_HANDLING: data_handling,
    }


def _noul(budget=0.05, timeline=0.05, vendor=0.05, data_handling=0.05):
    return {
        helpers.BUDGET: budget,
        helpers.TIMELINE: timeline,
        helpers.VENDOR: vendor,
        helpers.DATA_HANDLING: data_handling,
    }


def test_decide_labels_tags_each_constraint_against_its_own_threshold():
    decisions = helpers.decide_labels(
        _noul(budget=0.95, timeline=0.10), _thresholds(), confidence_gate=0.3
    )
    assert decisions[helpers.BUDGET].tag is True
    assert decisions[helpers.TIMELINE].tag is False
    assert decisions[helpers.BUDGET].gated is False
    assert decisions[helpers.TIMELINE].gated is False


def test_decide_labels_tag_is_inclusive_at_the_threshold():
    # A mutation to `noul > threshold` passes most other tests here but changes real notebook
    # numbers on re-execution, so it is pinned directly rather than left to the freshness check.
    decisions = helpers.decide_labels(
        _noul(budget=0.5, timeline=0.5), _thresholds(budget=0.5, timeline=0.5), confidence_gate=0.0
    )
    assert decisions[helpers.BUDGET].tag is True
    assert decisions[helpers.TIMELINE].tag is True


def test_decide_labels_gates_on_confidence_whatever_the_tag_says():
    # noul 0.44 is below a 0.5 threshold (tag False), but its confidence, |2*0.44-1|=0.12, is
    # below a 0.3 gate, so it must be marked gated regardless of the tag.
    decisions = helpers.decide_labels(_noul(budget=0.44), _thresholds(), confidence_gate=0.3)
    assert decisions[helpers.BUDGET].tag is False
    assert decisions[helpers.BUDGET].gated is True


@pytest.mark.parametrize("bad_gate", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_confidence_gate(bad_gate):
    with pytest.raises(ValueError):
        helpers.decide_labels(_noul(), _thresholds(), bad_gate)


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_threshold(bad_threshold):
    with pytest.raises(ValueError):
        helpers.decide_labels(_noul(), _thresholds(budget=bad_threshold), 0.3)


@pytest.mark.parametrize("bad_noul", [-0.1, 1.1])
def test_decide_labels_rejects_an_out_of_range_noul(bad_noul):
    with pytest.raises(ValueError):
        helpers.decide_labels(_noul(budget=bad_noul), _thresholds(), 0.3)


def test_decide_labels_rejects_values_that_do_not_name_exactly_constraints():
    with pytest.raises(ValueError):
        helpers.decide_labels({helpers.BUDGET: 0.5}, _thresholds(), 0.3)
    with pytest.raises(ValueError):
        helpers.decide_labels(_noul(), {helpers.BUDGET: 0.5}, 0.3)


# --------------------------------------------------------------------------------------------
# decide: the composed rule, and the precedence between its branches -- a confident violation
# on ANY constraint is ineligible even when another constraint is gated; only once nothing is
# confidently violated does a gated constraint send the plan to review.
# --------------------------------------------------------------------------------------------


def test_decide_is_eligible_when_every_constraint_clears_confidently():
    result = helpers.decide(_noul(), _thresholds(), confidence_gate=0.3)
    assert result.outcome == helpers.ELIGIBLE
    assert result.reason == helpers.REASON_ELIGIBLE


def test_decide_is_ineligible_on_one_confident_violation_with_every_other_clear():
    # The named hard case in its unit form: one constraint violated, the other three clear.
    result = helpers.decide(_noul(vendor=0.95), _thresholds(), confidence_gate=0.3)
    assert result.outcome == helpers.INELIGIBLE
    assert result.reason == "confidently violates: vendor"


def test_decide_names_every_confidently_violated_constraint_in_order():
    result = helpers.decide(
        _noul(budget=0.95, data_handling=0.9), _thresholds(), confidence_gate=0.3
    )
    assert result.outcome == helpers.INELIGIBLE
    assert result.reason == "confidently violates: budget, data_handling"


def test_decide_reviews_on_low_confidence_whatever_the_tag_when_nothing_else_violates():
    result = helpers.decide(_noul(timeline=0.44), _thresholds(), confidence_gate=0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_REVIEW_CONFIDENCE


def test_decide_is_ineligible_even_when_a_different_constraint_is_gated():
    # The precedence this recipe's whole policy rests on: a confident violation on vendor makes
    # the plan ineligible even though budget's own judgment here is too uncertain to trust.
    result = helpers.decide(_noul(budget=0.47, vendor=0.95), _thresholds(), confidence_gate=0.3)
    assert result.outcome == helpers.INELIGIBLE
    assert result.reason == "confidently violates: vendor"


def test_decide_rejects_values_that_do_not_name_exactly_constraints():
    with pytest.raises(ValueError):
        helpers.decide({helpers.BUDGET: 0.5}, _thresholds(), 0.3)


# --------------------------------------------------------------------------------------------
# each constraint is independently consequential on the real, committed fixtures: flipping one
# stored decision, holding the others fixed, changes decide's composed outcome. v02-v05 are
# this recipe's named hard case fixtures (single violation, each a different constraint).
# --------------------------------------------------------------------------------------------


def _frozen():
    """``(thresholds, gate, backend, questions, examples, labels)`` computed from the committed
    ``validation`` fixtures exactly as the notebook computes them."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_gold = {c: [labels[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_noul = {c: [decide_answer(e)[c].noul for e in validation] for c in helpers.CONSTRAINTS}
    thresholds = {
        c: select_threshold(val_gold[c], val_noul[c], objective="f1") for c in helpers.CONSTRAINTS
    }
    val_ids = [e.id for e in validation]
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.CONSTRAINTS), val_gold, val_noul, thresholds
    )
    gate = select_confidence_threshold(correct, confidence, min_coverage=0.95)
    return thresholds, gate, backend, questions, examples, labels


@pytest.mark.parametrize(
    ("constraint", "example_id"),
    [
        (helpers.BUDGET, "v02-budget"),
        (helpers.TIMELINE, "v03-timeline"),
        (helpers.VENDOR, "v04-vendor"),
        (helpers.DATA_HANDLING, "v05-data"),
    ],
)
def test_each_constraint_is_independently_consequential_on_its_named_hard_case(
    constraint, example_id
):
    thresholds, gate, backend, questions, examples, labels = _frozen()
    example = next(e for e in examples if e.id == example_id)
    gold = labels[example.id]
    assert sum(gold.values()) == 1 and gold[constraint] is True  # satisfies every one but this
    real_answer = backend.decide(helpers.build_state(example.fields), questions)
    noul_values = {c: real_answer[c].noul for c in helpers.CONSTRAINTS}

    baseline = helpers.decide(noul_values, thresholds, gate)
    assert baseline.outcome == helpers.INELIGIBLE

    flipped = dict(noul_values)
    flipped[constraint] = 0.02  # confidently clear instead
    changed = helpers.decide(flipped, thresholds, gate)
    assert changed.outcome != baseline.outcome
    assert changed.outcome == helpers.ELIGIBLE


# --------------------------------------------------------------------------------------------
# gold_outcome, task_correct, accepted_and_correct
# --------------------------------------------------------------------------------------------


def test_gold_outcome_is_ineligible_when_any_constraint_is_actually_violated():
    assert (
        helpers.gold_outcome(
            {"budget": True, "timeline": False, "vendor": False, "data_handling": False}
        )
        == helpers.INELIGIBLE
    )
    assert (
        helpers.gold_outcome(
            {"budget": False, "timeline": False, "vendor": False, "data_handling": True}
        )
        == helpers.INELIGIBLE
    )


def test_gold_outcome_is_eligible_when_no_constraint_is_violated():
    assert helpers.gold_outcome({c: False for c in helpers.CONSTRAINTS}) == helpers.ELIGIBLE


def test_gold_outcome_rejects_values_that_do_not_name_exactly_constraints():
    with pytest.raises(ValueError):
        helpers.gold_outcome({helpers.BUDGET: True})


def test_accepted_and_correct_counts_ineligible_and_eligible_as_coverage_review_as_not():
    resolutions = [
        helpers.Resolution(helpers.INELIGIBLE, "x"),
        helpers.Resolution(helpers.ELIGIBLE, "x"),
        helpers.Resolution(helpers.REVIEW, "x"),
    ]
    golds = [helpers.INELIGIBLE, helpers.ELIGIBLE, helpers.ELIGIBLE]
    accepted, correct = helpers.accepted_and_correct(resolutions, golds)
    assert accepted == [True, True, False]
    assert correct == [True, True, False]  # the review row's "correct" is computed, unused


def test_accepted_and_correct_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        helpers.accepted_and_correct([], [helpers.INELIGIBLE])


# --------------------------------------------------------------------------------------------
# the strong form (recipe guard G1(c)): re-derive the frozen confidence gate from validation,
# independently of _frozen() above (CONTRIBUTING's note on an independent strong-form check
# never routing through the production path it audits), and bind an assert to a
# wrong-answer-at-or-above-the-gate comparison.
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    validation = [e for e in examples if e.split == "validation"]
    val_gold = {c: [labels[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_noul = {c: [decide_answer(e)[c].noul for e in validation] for c in helpers.CONSTRAINTS}
    thresholds = {
        c: select_threshold(val_gold[c], val_noul[c], objective="f1") for c in helpers.CONSTRAINTS
    }
    val_ids = [e.id for e in validation]
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.CONSTRAINTS), val_gold, val_noul, thresholds
    )
    gate = select_confidence_threshold(correct, confidence, min_coverage=0.95)

    test = [e for e in examples if e.split == "test"]
    test_results = {}
    for e in test:
        noul_values = {c: decide_answer(e)[c].noul for c in helpers.CONSTRAINTS}
        test_results[e.id] = helpers.decide(noul_values, thresholds, gate)

    wrong_and_confident = [
        eid
        for eid, result in test_results.items()
        if result.outcome != helpers.REVIEW
        and result.outcome != helpers.gold_outcome(labels[eid])
        and min(d.confidence for d in result.decisions.values()) >= gate
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
    assert "t09-adversarial-data" in wrong_and_confident


# --------------------------------------------------------------------------------------------
# the named hard case: present on both committed splits, confirmed by decide, not merely by
# the gold labels alone
# --------------------------------------------------------------------------------------------


def test_the_named_hard_case_is_present_on_both_splits():
    thresholds, gate, backend, questions, examples, labels = _frozen()

    def decide_answer(e):
        return backend.decide(helpers.build_state(e.fields), questions)

    for split, expected_minimum in (("validation", 4), ("test", 4)):
        split_examples = [e for e in examples if e.split == split and e.id in labels]
        resolutions = {}
        for e in split_examples:
            noul_values = {c: decide_answer(e)[c].noul for c in helpers.CONSTRAINTS}
            resolutions[e.id] = helpers.decide(noul_values, thresholds, gate)
        gold_by_label = {
            c: {e.id: labels[e.id][c] for e in split_examples} for c in helpers.CONSTRAINTS
        }
        ids = helpers.single_violation_ineligible_ids(
            [e.id for e in split_examples], resolutions, gold_by_label
        )
        assert len(ids) >= expected_minimum, f"expected the hard case on {split}"
        for item_id in ids:
            assert resolutions[item_id].outcome == helpers.INELIGIBLE
            assert sum(gold_by_label[c][item_id] for c in helpers.CONSTRAINTS) == 1


# --------------------------------------------------------------------------------------------
# the three zero-request baselines
# --------------------------------------------------------------------------------------------


def test_approve_all_is_always_eligible():
    assert helpers.approve_all_outcome() == helpers.ELIGIBLE


def test_reject_all_is_always_ineligible():
    assert helpers.reject_all_outcome() == helpers.INELIGIBLE


def test_always_review_is_always_review():
    assert helpers.always_review_outcome() == helpers.REVIEW


# --------------------------------------------------------------------------------------------
# the stateful walkthrough: Python's own running remaining-budget bookkeeping, and its
# agreement with the committed demo sequence's own hand-written numbers
# --------------------------------------------------------------------------------------------


def test_remaining_budget_after_an_eligible_plan_spends_its_cost():
    assert helpers.remaining_budget_after(5000, helpers.ELIGIBLE, 3000) == 2000


@pytest.mark.parametrize("outcome", [helpers.INELIGIBLE, helpers.REVIEW])
def test_remaining_budget_after_a_non_eligible_plan_is_unchanged(outcome):
    assert helpers.remaining_budget_after(5000, outcome, 3000) == 5000


def test_remaining_budget_matches_the_committed_stateful_sequence():
    # d03-seq1, d04-seq2 and d05-seq3 (build_fixtures.py) hand-write the running remaining
    # budget baked into each later plan's own constraint text ($5000, $2000, $500). This test
    # proves Python's own bookkeeping function reproduces exactly those numbers from the
    # earlier plans' own outcome and cost, rather than merely asserting the fixture file
    # happens to agree with itself.
    inputs = {row.id: row for row in load_inputs(RECIPE)}
    remaining = 5000
    assert inputs["d03-seq1"].fields["user_constraints"]["budget"].endswith(f"${remaining}.")
    remaining = helpers.remaining_budget_after(remaining, helpers.ELIGIBLE, 3000)
    assert remaining == 2000
    assert inputs["d04-seq2"].fields["user_constraints"]["budget"].endswith(f"${remaining}.")
    remaining = helpers.remaining_budget_after(remaining, helpers.ELIGIBLE, 1500)
    assert remaining == 500
    assert inputs["d05-seq3"].fields["user_constraints"]["budget"].endswith(f"${remaining}.")


# --------------------------------------------------------------------------------------------
# review_sort_key and queue_item
# --------------------------------------------------------------------------------------------


def test_review_sort_key_is_the_lowest_of_the_four_confidences():
    result = helpers.decide(_noul(timeline=0.44), _thresholds(), confidence_gate=0.3)
    assert result.outcome == helpers.REVIEW
    assert result.decisions[helpers.TIMELINE].confidence == pytest.approx(
        noul_confidence([0.44])[0]
    )
    assert helpers.review_sort_key(result) == pytest.approx(
        result.decisions[helpers.TIMELINE].confidence
    )


def test_review_sort_key_rejects_a_resolution_with_no_label_decisions():
    with pytest.raises(ValueError):
        helpers.review_sort_key(helpers.Resolution(helpers.REVIEW, "x"))


def test_queue_item_shows_the_plan_the_constraints_and_every_label_decision():
    result = helpers.decide(_noul(vendor=0.95), _thresholds(), confidence_gate=0.3)
    fields = {
        "user_constraints": {c: f"{c} text" for c in helpers.CONSTRAINTS},
        "plan": "Do the plan.",
    }
    item = helpers.queue_item("p01", fields, result)
    assert item["id"] == "p01"
    assert item["plan"] == "Do the plan."
    assert item["user_constraints"] == fields["user_constraints"]
    assert item[helpers.VENDOR]["noul"] == pytest.approx(0.95)


# --------------------------------------------------------------------------------------------
# the frozen thresholds and gate: two independent pin sites each (this file, and the committed
# notebook cell source), both keyword and value
# --------------------------------------------------------------------------------------------


def test_the_frozen_business_thresholds_and_gate_are_pinned_to_their_values():
    thresholds, gate, *_ = _frozen()
    assert thresholds[helpers.BUDGET] == pytest.approx(0.47)
    assert thresholds[helpers.TIMELINE] == pytest.approx(0.86)
    assert thresholds[helpers.VENDOR] == pytest.approx(0.9)
    assert thresholds[helpers.DATA_HANDLING] == pytest.approx(0.89)
    assert gate == pytest.approx(0.06000000000000005)


def _notebook_code_source() -> str:
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    return "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")


def test_notebook_pins_f1_as_the_business_threshold_objective_for_every_constraint():
    # One call site (a dict comprehension looping over helpers.CONSTRAINTS), not four separate
    # literal calls: the notebook computes all four thresholds with select_threshold(...,
    # objective="f1") inside one comprehension, so the literal appears once in source even
    # though it runs four times -- the four distinct frozen VALUES are pinned separately, in
    # test_notebook_pins_the_frozen_threshold_and_gate_values_in_its_committed_output below.
    source = _notebook_code_source()
    assert source.count('objective="f1"') == 1
    assert "for c in helpers.CONSTRAINTS" in source
    assert "target_accuracy" not in source


def test_notebook_pins_min_coverage_not_target_accuracy_for_the_gate():
    source = _notebook_code_source()
    assert "min_coverage=0.95" in source


def test_notebook_pins_the_frozen_threshold_and_gate_values_in_its_committed_output():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    outputs = []
    for c in notebook["cells"]:
        if c["cell_type"] != "code":
            continue
        for out in c.get("outputs", []):
            text = out.get("text")
            if text:
                outputs.append("".join(text))
    joined = "\n".join(outputs)
    assert "0.4700" in joined
    assert "0.8600" in joined
    assert "0.9000" in joined
    assert "0.8900" in joined
    assert "0.0600" in joined


# --------------------------------------------------------------------------------------------
# mutation proofs: each pin site actually matters. Changing the keyword, re-deriving with a
# different objective, or changing a frozen value changes a real, checkable thing.
# --------------------------------------------------------------------------------------------


def test_mutation_the_objective_keyword_changes_the_selected_threshold():
    _, _, backend, questions, examples, labels = _frozen()
    validation = [e for e in examples if e.split == "validation"]
    val_gold = [labels[e.id][helpers.BUDGET] for e in validation]
    val_noul = [
        backend.decide(helpers.build_state(e.fields), questions)[helpers.BUDGET].noul
        for e in validation
    ]
    f1_threshold = select_threshold(val_gold, val_noul, objective="f1")
    recall_at_precision_threshold = select_threshold(
        val_gold, val_noul, objective="recall_at_precision", target=0.95
    )
    assert f1_threshold != pytest.approx(recall_at_precision_threshold)


def test_mutation_a_different_min_coverage_can_select_a_different_gate():
    thresholds, frozen_gate, backend, questions, examples, labels = _frozen()
    validation = [e for e in examples if e.split == "validation"]
    val_gold = {c: [labels[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_noul = {
        c: [backend.decide(helpers.build_state(e.fields), questions)[c].noul for e in validation]
        for c in helpers.CONSTRAINTS
    }
    val_ids = [e.id for e in validation]
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.CONSTRAINTS), val_gold, val_noul, thresholds
    )
    full_coverage_gate = select_confidence_threshold(correct, confidence, min_coverage=1.0)
    assert full_coverage_gate != pytest.approx(frozen_gate)


def test_mutation_the_frozen_threshold_value_is_not_a_decoration():
    # The budget threshold (0.4700) sits exactly at the lowest TRUE positive's own noul
    # (v14-gated-violation, an ambiguous but gold-True row): that one ambiguous positive is
    # what pulls the F1-optimal threshold down from the clean positives' own 0.89-0.95 band.
    # Nudging it to a confidently-clear value (changing the underlying answer the selector
    # sees, not the pin) removes the only reason the threshold sits where it does, so the
    # re-derived value must move -- proving the pinned 0.4700 is a real computation, not a
    # hand-typed literal nothing checks.
    thresholds, gate, backend, questions, examples, labels = _frozen()
    validation = [e for e in examples if e.split == "validation"]
    val_gold = [labels[e.id][helpers.BUDGET] for e in validation]
    val_noul = [
        backend.decide(helpers.build_state(e.fields), questions)[helpers.BUDGET].noul
        for e in validation
    ]
    nudged = list(val_noul)
    lowest_true_positive_index = min(
        (i for i in range(len(validation)) if val_gold[i]), key=lambda i: nudged[i]
    )
    nudged[lowest_true_positive_index] = 0.01  # the one ambiguous positive, now unreachable
    nudged_threshold = select_threshold(val_gold, nudged, objective="f1")
    assert nudged_threshold != pytest.approx(thresholds[helpers.BUDGET])


# --------------------------------------------------------------------------------------------
# per-cell precision and recall on test: not saturated for any constraint -- each has a real
# miss (a false positive or a false negative), confirmed directly rather than asserted.
# --------------------------------------------------------------------------------------------


def test_per_cell_precision_and_recall_on_test_are_not_saturated_for_any_constraint():
    thresholds, _gate, backend, questions, examples, labels = _frozen()
    test = [e for e in examples if e.split == "test"]
    test_noul = {
        c: [backend.decide(helpers.build_state(e.fields), questions)[c].noul for e in test]
        for c in helpers.CONSTRAINTS
    }
    test_gold = {c: [labels[e.id][c] for e in test] for c in helpers.CONSTRAINTS}
    for c in helpers.CONSTRAINTS:
        point = evaluate_threshold(test_gold[c], test_noul[c], thresholds[c])
        assert not (point.precision == pytest.approx(1.0) and point.recall == pytest.approx(1.0)), (
            f"{c} is saturated: nothing in the committed fixtures could make it fall"
        )
        assert point.fp > 0 or point.fn > 0


def test_multilabel_metrics_micro_and_macro_are_computed_from_the_same_business_tags():
    # The "per-cell" multi-label framing (CONTRIBUTING.md's multi-label Noul pattern) and the
    # per-constraint evaluate_threshold loop above describe the same business-tag decisions;
    # this test pins that the multi-label view is not a separate, silently-diverging
    # computation.
    thresholds, _gate, backend, questions, examples, labels = _frozen()
    test = [e for e in examples if e.split == "test"]
    test_noul = {
        c: [backend.decide(helpers.build_state(e.fields), questions)[c].noul for e in test]
        for c in helpers.CONSTRAINTS
    }
    gold_sets = [frozenset(c for c in helpers.CONSTRAINTS if labels[e.id][c]) for e in test]
    predicted_sets = multilabel_from_noul(test_noul, thresholds)
    metrics = multilabel_metrics(gold_sets, predicted_sets, labels=list(helpers.CONSTRAINTS))
    for c in helpers.CONSTRAINTS:
        point = evaluate_threshold([labels[e.id][c] for e in test], test_noul[c], thresholds[c])
        assert metrics["per_label"][c].tp == point.tp
        assert metrics["per_label"][c].fp == point.fp
        assert metrics["per_label"][c].fn == point.fn


# --------------------------------------------------------------------------------------------
# the Noul-gate band: measured by a 401-point grid, with and without the gate, per constraint,
# counted by side. This is a MEASUREMENT of this recipe's own composition, not a derivation --
# whether a gate is inert depends on how decide wires it in, not on the band alone.
# --------------------------------------------------------------------------------------------


def _gate_grid_changes(thresholds, gate, constraint, n_points=401):
    grid = [i / (n_points - 1) for i in range(n_points)]
    changes = []
    for n in grid:
        noul_values = {c: (n if c == constraint else 0.02) for c in helpers.CONSTRAINTS}
        with_gate = helpers.decide(noul_values, thresholds, gate).outcome
        without_gate = helpers.decide(noul_values, thresholds, 0.0).outcome
        if with_gate != without_gate:
            side = "accept" if n >= 0.5 else "reject"
            changes.append((n, side, with_gate, without_gate))
    return changes


def test_the_gate_measurably_changes_outcomes_on_both_sides_for_every_constraint():
    thresholds, gate, *_ = _frozen()
    for constraint in helpers.CONSTRAINTS:
        changes = _gate_grid_changes(thresholds, gate, constraint)
        sides = {side for _n, side, _w, _wo in changes}
        assert len(changes) > 0, f"the gate changes nothing for {constraint}"
        assert sides == {"accept", "reject"}, (
            f"{constraint}: expected the band to change outcomes on both sides, got {sides}"
        )
        # every changed point goes FROM review (with the gate) TO something else (without it):
        # the gate can only ever add a review, never remove one, by construction of decide.
        for _n, _side, with_gate, without_gate in changes:
            assert with_gate == helpers.REVIEW
            assert without_gate != helpers.REVIEW


def test_the_gate_grid_measurement_can_detect_no_change_a_zero_gate_changes_nothing():
    # Proves the measurement itself can report zero (CONTRIBUTING's fail-open family): with the
    # "with-gate" argument also forced to 0.0, there is no gate to add, so every grid point
    # agrees with itself.
    thresholds, _gate, *_ = _frozen()
    changes = _gate_grid_changes(thresholds, 0.0, helpers.BUDGET)
    assert changes == []


# --------------------------------------------------------------------------------------------
# min_coverage sweep: the selector actually selects (not a no-op across the parameter's whole
# range), and the direction is right -- raising min_coverage never raises the selected gate.
# --------------------------------------------------------------------------------------------


def test_min_coverage_sweep_the_selector_actually_selects_and_the_direction_is_right():
    thresholds, _gate, backend, questions, examples, labels = _frozen()
    validation = [e for e in examples if e.split == "validation"]
    val_gold = {c: [labels[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_noul = {
        c: [backend.decide(helpers.build_state(e.fields), questions)[c].noul for e in validation]
        for c in helpers.CONSTRAINTS
    }
    val_ids = [e.id for e in validation]
    correct, confidence, _keys = pool_label_decisions(
        val_ids, list(helpers.CONSTRAINTS), val_gold, val_noul, thresholds
    )

    swept = [i / 100.0 for i in range(0, 101)]  # the parameter's whole range
    gates = [select_confidence_threshold(correct, confidence, min_coverage=mc) for mc in swept]

    assert len({round(g, 9) for g in gates}) > 1  # not a no-op

    for lower, higher in zip(gates, gates[1:], strict=False):
        assert higher <= lower + 1e-12  # raising min_coverage never raises the selected gate


# --------------------------------------------------------------------------------------------
# pooling order vs. attribution: pool_label_decisions pools label-then-example, and this
# recipe reports per-constraint metrics separately from the pooled gate selection. This test
# confirms, on the real committed fixtures, that the (plan, constraint) key pool_label_decisions
# attributes to entry j is actually the pair that correct[j]/confidence[j] describe -- the
# failure this guards against is counts staying right while the printed attribution is wrong.
# --------------------------------------------------------------------------------------------


def test_pooling_order_matches_its_own_attribution_on_the_real_fixtures():
    thresholds, _gate, backend, questions, examples, labels = _frozen()
    validation = [e for e in examples if e.split == "validation"]
    val_gold = {c: [labels[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_noul_by_id = {
        e.id: {
            c: backend.decide(helpers.build_state(e.fields), questions)[c].noul
            for c in helpers.CONSTRAINTS
        }
        for e in validation
    }
    val_noul = {c: [val_noul_by_id[e.id][c] for e in validation] for c in helpers.CONSTRAINTS}
    val_ids = [e.id for e in validation]
    correct, confidence, keys = pool_label_decisions(
        val_ids, list(helpers.CONSTRAINTS), val_gold, val_noul, thresholds
    )
    assert len(keys) == len(validation) * len(helpers.CONSTRAINTS)
    for j, (item_id, label) in enumerate(keys):
        expected_noul = val_noul_by_id[item_id][label]
        expected_tag = expected_noul >= thresholds[label]
        expected_correct = expected_tag == labels[item_id][label]
        expected_confidence = noul_confidence([expected_noul])[0]
        assert correct[j] == expected_correct, (j, item_id, label)
        assert confidence[j] == pytest.approx(expected_confidence), (j, item_id, label)
    # label-then-example order: the first len(validation) keys all share the first label.
    first_label = list(helpers.CONSTRAINTS)[0]
    assert all(label == first_label for _id, label in keys[: len(validation)])
