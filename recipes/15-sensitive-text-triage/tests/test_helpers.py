"""Tests for recipe 15's helpers. They load the helpers by file path.

A Noul's confidence (``jev_cookbook.evaluation.noul_confidence``) is ``|2p - 1|``, the same
Choice confidence formula applied to a yes/no Choice (docs/evaluation.md, "Noul three-path
pattern", S03). Tests that need a value near 0.5 still call ``noul_confidence`` themselves and
set ``min_confidence`` relative to what it returns, rather than hardcoding the number, so they
stay correct if the formula's exact value is ever revisited again. Tests that only need a
*far-from-0.5* probability (confidence close to 1) use plain numbers instead, since no
plausible formula revision would move those.
"""

from pathlib import Path

import pytest

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import noul_confidence, select_confidence_threshold, select_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(noul):
    return NoulAnswer(noul, Provenance.synthetic())


def confidence_of(noul):
    return noul_confidence([noul])[0]


def test_noul_confidence_is_pinned_to_the_published_formula():
    # A literal, not derived from noul_confidence itself: pins |2p - 1| (equivalently
    # 2 * max(p, 1 - p) - 1) rather than only pinning that helpers and evaluation agree with
    # each other. 0.65 and 0.35 are this recipe's own "-moderate" fixtures.
    assert noul_confidence([0.65])[0] == pytest.approx(0.30)
    assert noul_confidence([0.35])[0] == pytest.approx(0.30)


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["contains_pii"]
    proposition = questions["contains_pii"]
    assert proposition.instructions == helpers.STATEMENT
    assert set(proposition.criteria) == {"true", "false"}
    assert all(isinstance(d, str) and d for d in proposition.criteria.values())


# min_confidence=0.01 is low enough that a far-from-0.5 noul (0.0, 0.1, 0.9, 1.0) clears the
# confidence gate, so these two tests exercise only the business threshold, not the gate.


@pytest.mark.parametrize("noul", [0.55, 0.70, 0.90, 1.0])
def test_a_confident_document_at_or_above_the_threshold_is_flagged(noul):
    result = helpers.triage("D1", answer(noul), threshold=0.55, min_confidence=0.01)
    assert (result.doc_id, result.outcome, result.may_contain_pii) == (
        "D1",
        helpers.FLAGGED,
        True,
    )


@pytest.mark.parametrize("noul", [0.0, 0.10, 0.40, 0.549])
def test_a_confident_document_below_the_threshold_is_cleared(noul):
    result = helpers.triage("D1", answer(noul), threshold=0.55, min_confidence=0.01)
    assert (result.doc_id, result.outcome, result.may_contain_pii) == (
        "D1",
        helpers.CLEARED,
        False,
    )


def test_the_business_threshold_is_inclusive():
    confident = helpers.triage("D1", answer(0.55), threshold=0.55, min_confidence=0.01)
    just_below = helpers.triage("D1", answer(0.55 - 1e-9), threshold=0.55, min_confidence=0.01)
    assert (confident.outcome, confident.may_contain_pii) == (helpers.FLAGGED, True)
    assert (just_below.outcome, just_below.may_contain_pii) == (helpers.CLEARED, False)


@pytest.mark.parametrize("noul", [0.48, 0.5, 0.52])
def test_low_confidence_goes_to_review_whichever_side_it_leans(noul):
    # Set min_confidence just above this noul's own confidence, computed rather than hardcoded.
    result = helpers.triage(
        "D1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul) + 0.01
    )
    assert result.outcome == helpers.REVIEW
    # may_contain_pii still reports what the business threshold alone would have decided.
    assert result.may_contain_pii == (noul >= 0.55)


def test_the_confidence_gate_is_inclusive():
    noul = 0.9
    exact = helpers.triage("D1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul))
    just_above = helpers.triage(
        "D1", answer(noul), threshold=0.55, min_confidence=confidence_of(noul) + 1e-9
    )
    assert exact.outcome == helpers.FLAGGED  # confidence == min_confidence clears the gate
    assert just_above.outcome == helpers.REVIEW


def test_a_high_confidence_wrong_leaning_document_is_still_decided_not_reviewed():
    # The confidence gate protects against genuine ambiguity (noul near 0.5), not against a
    # confidently wrong answer (noul far from 0.5 on the "wrong" side of the gold label): it has
    # no way to tell the two apart, which is the point this test pins. This recipe's
    # "-adversarial" fixtures (a document that tries to instruct the triage to clear it despite
    # containing real personal information) are exactly this shape.
    noul = 0.12
    result = helpers.triage("D1", answer(noul), threshold=0.55, min_confidence=0.5)
    assert result.outcome == helpers.CLEARED
    assert result.may_contain_pii is False


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        helpers.triage("D1", answer(0.5), threshold=bad, min_confidence=0.5)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_min_confidence_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="min_confidence must be between 0 and 1"):
        helpers.triage("D1", answer(0.5), threshold=0.5, min_confidence=bad)


def test_the_state_hides_the_doc_id():
    fields = {"doc_id": "D9", "text": "Quarterly roadmap update with no personal details."}
    assert helpers.build_state(fields) == {
        "document": "Quarterly roadmap update with no personal details."
    }


def test_candidate_spans_find_email_phone_and_street_patterns():
    text = (
        "Contact a.rossi@examplemail.test or call 555-0148; the package ships to "
        "12 Birchwood Lane this week."
    )
    spans = helpers.find_candidate_spans(text)
    assert spans == ["a.rossi@examplemail.test", "555-0148", "12 Birchwood Lane"]


def test_candidate_spans_do_not_match_a_bare_order_number_differently_from_a_phone_number():
    # The heuristic cannot tell a tracking reference from a phone number -- that is the point
    # "-lookalike" fixtures make: the pattern matches either way, and only the model's judgment
    # (not this scan) is supposed to tell them apart.
    assert helpers.find_candidate_spans("Tracking reference 555-0288 will update soon.") == [
        "555-0288"
    ]


def test_candidate_spans_are_empty_for_a_narrative_detail_with_no_matching_token():
    text = "The caller mentioned she is the only tenant on the top floor of the old mill."
    assert helpers.find_candidate_spans(text) == []


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# This recipe's own confidence-gate coverage floor (the notebook selects the gate with this
# same value); kept here, not imported, because the notebook's choice is a markdown-explained
# design decision, not a shared constant in helpers.py.
_MIN_COVERAGE = 0.80


def test_stored_answers_are_not_all_right():
    """The committed fixtures must give the confidence gate something real to catch, on the
    split this recipe reports: at least one `test` document whose confidence clears the frozen
    gate is nonetheless wrong, so the selective coverage/accuracy/risk numbers in the evaluation
    are not vacuous (a fixture set where every stored answer is right would not teach anything
    about where this recipe's rule can be fooled). This mirrors the selection the notebook
    performs: the business threshold is chosen on `validation` by F1, the confidence gate is
    chosen on `validation` by a coverage floor, and both are frozen before `test` is touched."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()

    def noul_of(example):
        state = helpers.build_state(example.fields)
        return backend.decide(state, questions)["contains_pii"].noul

    val_examples = select_split(examples, "validation")
    val_gold = [labels[e.id] for e in val_examples]
    val_noul = [noul_of(e) for e in val_examples]
    threshold = select_threshold(val_gold, val_noul, objective="f1")
    would_flag = [n >= threshold for n in val_noul]
    raw_correct = [w == bool(g) for w, g in zip(would_flag, val_gold, strict=True)]
    gate = select_confidence_threshold(
        raw_correct, noul_confidence(val_noul), min_coverage=_MIN_COVERAGE
    )

    test_examples = select_split(examples, "test")
    test_gold = [labels[e.id] for e in test_examples]
    test_noul = [noul_of(e) for e in test_examples]
    test_confidence = noul_confidence(test_noul)
    test_correct = [(n >= threshold) == bool(g) for n, g in zip(test_noul, test_gold, strict=True)]
    wrong_but_cleared_the_gate = [
        conf >= gate and not correct
        for conf, correct in zip(test_confidence, test_correct, strict=True)
    ]
    assert any(wrong_but_cleared_the_gate)
