"""Tests for recipe 50's helpers. They load the helpers by file path.

Order matters in one respect: no test function in this file carries a decorator. The recipe
guard's own strong-form check extracts a named test function's body by scanning forward in the
raw text to the next line starting with "def " or "class "; a decorator line starts with neither,
so a decorated function placed immediately after ``test_stored_answers_are_not_all_right`` would
be swallowed into that scan and the resulting text would fail to parse as Python, which is a
defect in the extraction rather than in this recipe. Keeping every test here undecorated
sidesteps it entirely rather than relying on ordering.
"""

import json
from pathlib import Path

from jev_cookbook import (
    ChoiceAnswer,
    NoulAnswer,
    Provenance,
    ScoreAnswer,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

PROV = Provenance.synthetic()


def choice_answer(top, top_p=0.9):
    """A Choice answer with ``top_p`` on ``top`` and the remainder split evenly, matching
    ``build_fixtures.py``'s own ``_choice_probs``."""
    rest = (1.0 - top_p) / 3.0
    full = {name: (top_p if name == top else rest) for name in helpers.CATEGORIES}
    return ChoiceAnswer.from_probabilities(full, PROV)


def noul_answer(p):
    return NoulAnswer(p, PROV)


def score_answer(level, top_p=0.8):
    rest = (1.0 - top_p) / 3.0
    probs = [top_p if i == level else rest for i in range(4)]
    return ScoreAnswer.from_probabilities(probs, list(helpers.SPECIFICITY_LEVELS), PROV)


# --------------------------------------------------------------------------------------------
# The questions are built by Python, against literal expected values (not helpers' own data,
# which would make the assertion self-referential).
# --------------------------------------------------------------------------------------------


def test_questions_a_are_built_by_python():
    questions = helpers.build_questions_a()
    assert set(questions) == {"category", "verifiable", "names_control"}
    assert list(questions["category"].criteria) == [
        "data_handling",
        "security_controls",
        "business_continuity",
        "other",
    ]
    assert questions["verifiable"].criteria is None
    assert questions["names_control"].criteria is None


def test_questions_b_are_built_by_python():
    questions = helpers.build_questions_b()
    assert set(questions) == {"specificity"}
    assert len(questions["specificity"].criteria) == 4
    assert list(questions["specificity"].criteria) == list(helpers.SPECIFICITY_LEVELS)


def test_the_state_hides_nothing_but_the_bookkeeping_fields():
    fields = {"statement": "We encrypt data.", "resubmission": True}
    assert helpers.build_state(fields) == {"statement": "We encrypt data."}


# --------------------------------------------------------------------------------------------
# Every replay key in the fixtures matches what the current questions would ask. A row with
# one key asks only request A; a row with two asks A then B, in that order.
# --------------------------------------------------------------------------------------------


def test_every_replay_key_in_the_fixtures_matches_the_current_questions():
    questions_a = helpers.build_questions_a()
    questions_b = helpers.build_questions_b()
    for example in load_inputs(RECIPE):
        state = helpers.build_state(example.fields)
        key_a = replay_key(state, questions_a)
        if len(example.replay_keys) == 1:
            assert example.replay_keys == (key_a,)
        else:
            assert len(example.replay_keys) == 2
            assert example.replay_keys == (key_a, replay_key(state, questions_b))


# --------------------------------------------------------------------------------------------
# needs_followup depends only on the earlier answer.
# --------------------------------------------------------------------------------------------


def test_needs_followup_is_false_only_for_other():
    assert helpers.needs_followup(choice_answer(helpers.OTHER, 0.7)) is False
    for category in (helpers.DATA_HANDLING, helpers.SECURITY_CONTROLS, helpers.BUSINESS_CONTINUITY):
        assert helpers.needs_followup(choice_answer(category, 0.7)) is True


# --------------------------------------------------------------------------------------------
# noul_gate: the two-sided band. The accept side is symmetric; validate the arithmetic at the
# boundary (inclusive) and just inside it (review), on both sides.
# --------------------------------------------------------------------------------------------


def test_noul_gate_accepts_both_sides_of_the_band():
    assert helpers.noul_gate(0.75, 0.5) == "true"  # (1+0.5)/2 = 0.75, inclusive
    assert helpers.noul_gate(0.7499999, 0.5) == "review"
    assert helpers.noul_gate(0.25, 0.5) == "false"  # (1-0.5)/2 = 0.25, inclusive
    assert helpers.noul_gate(0.2500001, 0.5) == "review"


def test_noul_gate_width_zero_never_reviews():
    # (1+0)/2 == (1-0)/2 == 0.5, and the "true" check runs first, so 0.5 itself resolves to
    # "true" rather than landing in an empty review band.
    assert helpers.noul_gate(0.5, 0.0) == "true"
    assert helpers.noul_gate(0.500001, 0.0) == "true"
    assert helpers.noul_gate(0.499999, 0.0) == "false"


def test_noul_gate_width_one_reviews_everything_strictly_between_the_endpoints():
    # (1+1)/2 = 1.0 and (1-1)/2 = 0.0: only the two endpoints themselves are ever decided.
    assert helpers.noul_gate(1.0, 1.0) == "true"
    assert helpers.noul_gate(0.0, 1.0) == "false"
    for p in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert helpers.noul_gate(p, 1.0) == "review"


def test_noul_gate_rejects_a_width_outside_zero_to_one():
    import pytest

    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="between 0 and 1"):
            helpers.noul_gate(0.5, bad)


def test_noul_gate_grid_reaches_every_branch_at_least_once():
    """A randomised-looking sweep over a grid must prove it actually reaches the branch it
    claims to cover, not merely run without error: a fuzz or grid sweep whose inputs never
    reach the branch under test has measured nothing, however many iterations it ran. This
    grid is not random, but the same obligation applies to any swept check: assert the count
    of each outcome is non-zero, not just that the loop completed."""
    import random

    rng = random.Random(50)
    counts = {"true": 0, "false": 0, "review": 0}
    iterations = 2000
    for _ in range(iterations):
        p = rng.random()
        width = rng.random()
        counts[helpers.noul_gate(p, width)] += 1
    assert iterations == sum(counts.values())
    for outcome, count in counts.items():
        assert count > 0, f"grid of {iterations} points never reached outcome {outcome!r}"


# --------------------------------------------------------------------------------------------
# triage: every branch, and the stateful escalation.
# --------------------------------------------------------------------------------------------

_DEFAULTS = dict(choice_threshold=0.5, gate_width=0.3, resubmission=False)


def test_triage_reviews_a_low_confidence_category():
    result = helpers.triage(
        "x",
        choice_answer(helpers.SECURITY_CONTROLS, 0.3),
        noul_answer(0.9),
        noul_answer(0.9),
        None,
        **_DEFAULTS,
    )
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.CONFIDENCE_REASON


def test_triage_clears_other():
    result = helpers.triage(
        "x",
        choice_answer(helpers.OTHER, 0.9),
        noul_answer(0.5),
        noul_answer(0.5),
        None,
        **_DEFAULTS,
    )
    assert result.outcome == helpers.CLEARED
    assert result.reason == "no compliance category applies"


def test_triage_reviews_when_a_noul_proposition_is_in_the_band():
    result = helpers.triage(
        "x",
        choice_answer(helpers.SECURITY_CONTROLS, 0.9),
        noul_answer(0.55),  # inside the review band for gate_width=0.3 ((1+0.3)/2 = 0.65)
        noul_answer(0.9),
        None,
        **_DEFAULTS,
    )
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.CONFIDENCE_REASON


def test_triage_clears_a_confident_but_not_both_true_pair():
    result = helpers.triage(
        "x",
        choice_answer(helpers.SECURITY_CONTROLS, 0.9),
        noul_answer(0.05),  # confidently false
        noul_answer(0.9),  # confidently true
        None,
        **_DEFAULTS,
    )
    assert result.outcome == helpers.CLEARED
    assert result.reason == "not a verifiable, specific claim"


def test_triage_flags_specific_enough_and_needs_detail_otherwise():
    base = dict(
        statement_id="x",
        category_answer=choice_answer(helpers.SECURITY_CONTROLS, 0.9),
        verifiable_answer=noul_answer(0.9),
        names_control_answer=noul_answer(0.9),
        **_DEFAULTS,
    )
    flagged = helpers.triage(specificity_answer=score_answer(helpers.SPECIFICITY_CUTOFF), **base)
    assert flagged.outcome == helpers.FLAGGED
    needs_detail = helpers.triage(
        specificity_answer=score_answer(helpers.SPECIFICITY_CUTOFF - 1), **base
    )
    assert needs_detail.outcome == helpers.NEEDS_DETAIL
    no_followup = helpers.triage(specificity_answer=None, **base)
    assert no_followup.outcome == helpers.NEEDS_DETAIL


def test_triage_escalates_a_resubmission_still_under_review():
    kwargs = dict(_DEFAULTS)
    kwargs["resubmission"] = True
    result = helpers.triage(
        "x",
        choice_answer(helpers.SECURITY_CONTROLS, 0.3),
        noul_answer(0.9),
        noul_answer(0.9),
        None,
        **kwargs,
    )
    assert result.outcome == helpers.ESCALATE_REVIEW
    assert result.reason == "resubmission still below the threshold"


def test_triage_does_not_escalate_a_resubmission_that_is_not_reviewed():
    kwargs = dict(_DEFAULTS)
    kwargs["resubmission"] = True
    result = helpers.triage(
        "x",
        choice_answer(helpers.OTHER, 0.9),
        noul_answer(0.5),
        noul_answer(0.5),
        None,
        **kwargs,
    )
    assert result.outcome == helpers.CLEARED


def test_triage_rejects_a_threshold_outside_zero_to_one():
    import pytest

    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.triage(
            "x",
            choice_answer(helpers.OTHER, 0.9),
            noul_answer(0.5),
            noul_answer(0.5),
            None,
            choice_threshold=1.5,
            gate_width=0.3,
            resubmission=False,
        )


# --------------------------------------------------------------------------------------------
# Every proposition and the category answer must be independently consequential, on real
# committed fixtures: flipping one stored decision changes at least one composed outcome.
# --------------------------------------------------------------------------------------------


def _decide_row(backend, example_id, questions_a, questions_b):
    examples = {e.id: e for e in load_inputs(RECIPE)}
    example = examples[example_id]
    state = helpers.build_state(example.fields)
    answers_a = backend.decide(state, questions_a)
    answer_b = None
    if helpers.needs_followup(answers_a["category"]):
        answer_b = backend.decide(state, questions_b)["specificity"]
    return answers_a, answer_b


def test_flipping_the_category_answer_changes_the_composed_outcome():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions_a, questions_b = helpers.build_questions_a(), helpers.build_questions_b()
    answers_a, answer_b = _decide_row(backend, "t07", questions_a, questions_b)
    kwargs = dict(choice_threshold=0.5, gate_width=0.3, resubmission=False)
    original = helpers.triage(
        "t07",
        answers_a["category"],
        answers_a["verifiable"],
        answers_a["names_control"],
        answer_b,
        **kwargs,
    )
    flipped_category = choice_answer(helpers.OTHER, 0.9)
    mutated = helpers.triage(
        "t07",
        flipped_category,
        answers_a["verifiable"],
        answers_a["names_control"],
        answer_b,
        **kwargs,
    )
    assert mutated.outcome != original.outcome


def test_flipping_verifiable_or_names_control_changes_the_composed_outcome():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions_a, questions_b = helpers.build_questions_a(), helpers.build_questions_b()
    answers_a, answer_b = _decide_row(backend, "t07", questions_a, questions_b)
    kwargs = dict(choice_threshold=0.5, gate_width=0.3, resubmission=False)
    original = helpers.triage(
        "t07",
        answers_a["category"],
        answers_a["verifiable"],
        answers_a["names_control"],
        answer_b,
        **kwargs,
    )
    flipped_verifiable = helpers.triage(
        "t07",
        answers_a["category"],
        noul_answer(0.05),
        answers_a["names_control"],
        answer_b,
        **kwargs,
    )
    flipped_names = helpers.triage(
        "t07",
        answers_a["category"],
        answers_a["verifiable"],
        noul_answer(0.05),
        answer_b,
        **kwargs,
    )
    assert flipped_verifiable.outcome != original.outcome
    assert flipped_names.outcome != original.outcome


def test_flipping_the_specificity_answer_changes_the_composed_outcome():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions_a, questions_b = helpers.build_questions_a(), helpers.build_questions_b()
    answers_a, answer_b = _decide_row(backend, "t07", questions_a, questions_b)
    assert answer_b is not None
    kwargs = dict(choice_threshold=0.5, gate_width=0.3, resubmission=False)
    flagged = helpers.triage(
        "t07",
        answers_a["category"],
        answers_a["verifiable"],
        answers_a["names_control"],
        score_answer(helpers.SPECIFICITY_CUTOFF),
        **kwargs,
    )
    needs_detail = helpers.triage(
        "t07",
        answers_a["category"],
        answers_a["verifiable"],
        answers_a["names_control"],
        score_answer(0),
        **kwargs,
    )
    assert flagged.outcome != needs_detail.outcome


# --------------------------------------------------------------------------------------------
# docs/glossary.md#review: the outcome value is exactly "review", and a confidence-gated
# review always carries the exact reason string.
# --------------------------------------------------------------------------------------------


def test_review_constant_is_exactly_review():
    assert helpers.REVIEW == "review"


def test_confidence_reason_is_exact():
    assert helpers.CONFIDENCE_REASON == "confidence below the threshold"


# --------------------------------------------------------------------------------------------
# G1(c), the strong form: re-derive the frozen Choice confidence threshold the notebook's
# calibration cell computes for the "jev" backend, and require a confidently wrong test
# answer -- a mistake the gate would still let through.
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions_a = helpers.build_questions_a()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def category_answer(example):
        return backend.decide(helpers.build_state(example.fields), questions_a)["category"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: category_answer(e) for e in validation}
    val_correct = [val_answers[e.id].choice == labels[e.id]["category"] for e in validation]
    val_confidence = [val_answers[e.id].confidence for e in validation]
    choice_threshold = select_confidence_threshold(val_correct, val_confidence, min_coverage=0.8)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if category_answer(e).choice != labels[e.id]["category"]
        and category_answer(e).confidence >= choice_threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test category answer"


def test_the_notebook_calibration_cells_pin_min_coverage_not_target_accuracy():
    """What pins the calibration OBJECTIVE is the committed notebook cell source itself: a
    printed literal beside a select_confidence_threshold call is hand-written and nothing
    compares it to the call it describes, and a test asserting only the resulting threshold
    VALUE pins the objective only if no other objective could produce that same value on this
    data, which is not checked by a value-only assertion. Both of this recipe's two
    select_confidence_threshold call sites -- the Choice threshold loop and the Noul
    gate-width loop -- are checked against the real, committed cell text instead."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "calibrate")
    source = "".join(cell["source"])
    assert "min_coverage=CHOICE_MIN_COVERAGE" in source
    assert "min_coverage=GATE_MIN_COVERAGE" in source
    assert "target_accuracy" not in source
