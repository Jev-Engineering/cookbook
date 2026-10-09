"""Tests for recipe 18's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

INCIDENTS = list(helpers.OPEN_INCIDENTS)

# A fixed shortlist used by most tests below, independent of the retrieval function itself
# (which has its own tests further down): three real candidates plus the no_match fallback is
# the shape every question actually asked by this recipe has.
CANDIDATES = ["INC-101", "INC-102", "INC-103"]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label, candidates=CANDIDATES):
    """A clearly confident answer naming ``label`` (a candidate id or no_match)."""
    options = [*candidates, helpers.NO_MATCH]
    others = [o for o in options if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label, candidates=CANDIDATES):
    """A barely-ahead answer naming ``label``, confidence well under the usual gate."""
    options = [*candidates, helpers.NO_MATCH]
    others = [o for o in options if o != label]
    rest = (1.0 - 0.30) / len(others)
    return answer({label: 0.30, **{o: rest for o in others}})


def _confident_foreign(candidates=CANDIDATES):
    """A confident answer naming an option that is neither one of ``candidates`` nor
    ``no_match`` -- `match_incident` must still reject it, even though `build_questions` never
    offers such an option (the check is defensive, not reachable through replay or live, the
    same guard recipe 07's word-sense rule keeps)."""
    return answer({"INC-999-not-a-real-candidate": 0.90, "also-not-one": 0.10})


# --- shortlist / retrieval ---------------------------------------------------------------


def test_shortlist_returns_fixed_size_from_the_open_pool():
    for symptoms in (
        "Checkout fails with a 500 error when a promo code is applied at payment confirmation.",
        "Something nobody has ever reported before, about a service that does not exist.",
    ):
        result = helpers.shortlist(symptoms)
        assert len(result) == helpers.SHORTLIST_SIZE
        assert len(set(result)) == helpers.SHORTLIST_SIZE
        assert all(r in helpers.OPEN_INCIDENTS for r in result)


def test_shortlist_ranks_the_true_duplicate_first():
    # Wording close to INC-101's own text should retrieve INC-101 as the top candidate,
    # whatever service the new ticket itself names (retrieval ranks on symptom text alone).
    symptoms = (
        "Customers see a 500 error at payment confirmation when they apply a promo code "
        "during checkout."
    )
    assert helpers.shortlist(symptoms)[0] == "INC-101"


def test_shortlist_ignores_service_and_can_retrieve_a_different_service_incident():
    # A ticket that is textually close to INC-103 (search-index) but is not about search at all
    # still retrieves INC-103, because retrieval never looks at the service field -- that
    # discrimination is left to the question, not pre-filtered away by Python's retrieval.
    symptoms = (
        "Searches on the partner portal return zero results for terms that matched yesterday."
    )
    assert "INC-103" in helpers.shortlist(symptoms)


def test_shortlist_is_deterministic():
    symptoms = "The mobile app crashes right after it is opened on the newest OS."
    assert helpers.shortlist(symptoms) == helpers.shortlist(symptoms)


def test_shortlist_ties_break_on_incident_id():
    # No shared words with any open incident: every similarity is 0.0, so the tie-break (the
    # incident id itself) decides, and the three lowest ids win.
    assert helpers.shortlist("Completely unrelated issue about nothing in particular.") == [
        "INC-101",
        "INC-102",
        "INC-103",
    ]


# --- build_questions / build_state --------------------------------------------------------


def test_questions_are_built_from_the_given_candidates_plus_no_match():
    questions = helpers.build_questions(CANDIDATES)
    assert list(questions) == ["match"]
    match = questions["match"]
    assert list(match.criteria) == [*CANDIDATES, helpers.NO_MATCH]
    assert all(isinstance(d, str) and d for d in match.criteria.values())
    assert isinstance(match.instructions, str) and match.instructions


def test_the_option_list_changes_with_the_candidates():
    a = helpers.build_questions(["INC-101", "INC-102", "INC-103"])["match"]
    b = helpers.build_questions(["INC-104", "INC-105", "INC-106"])["match"]
    assert list(a.criteria) != list(b.criteria)


def test_the_state_hides_the_ticket_id():
    fields = {
        "ticket_id": "TCK-9",
        "service": "checkout-api",
        "symptoms": "Checkout fails with a 500 error.",
    }
    assert helpers.build_state(fields) == {
        "symptoms": "Checkout fails with a 500 error.",
        "service": "checkout-api",
    }


# --- match_incident --------------------------------------------------------------------------


@pytest.mark.parametrize("label", CANDIDATES)
def test_a_confident_real_candidate_is_linked_whatever_the_label(label):
    a = _confident(label)
    result = helpers.match_incident("T1", CANDIDATES, a, 0.3)
    assert (result.ticket_id, result.label, result.outcome) == ("T1", label, helpers.LINKED)


@pytest.mark.parametrize("label", CANDIDATES)
def test_a_low_confidence_real_candidate_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    result = helpers.match_incident("T1", CANDIDATES, a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert "threshold" in result.reason


@pytest.mark.parametrize("top_probability", [0.95, 0.30])
def test_no_match_is_never_gated_on_confidence_whatever_its_value(top_probability):
    # top_probability=0.30 keeps no_match as the top option (barely ahead of an even fourth,
    # 0.25) while its confidence, (0.30 - 0.25) / 0.75 =~ 0.067, is well below the 0.3 gate used
    # here. A mutation that exempted no_match from the gate only when it is also confident
    # would still fail this case, because it is checked at both ends.
    others = [*CANDIDATES]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NO_MATCH: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NO_MATCH
    result = helpers.match_incident("T1", CANDIDATES, a, 0.3)
    assert result.outcome == helpers.NO_DUPLICATE
    assert result.label == helpers.NO_MATCH


def test_choosing_an_option_outside_the_shortlist_goes_to_review_even_when_confident():
    a = _confident_foreign()
    assert a.choice not in CANDIDATES
    assert a.choice != helpers.NO_MATCH
    result = helpers.match_incident("T1", CANDIDATES, a, 0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "not one of the retrieved candidates"


def test_the_threshold_is_inclusive():
    a = _confident("INC-101")
    t = a.confidence
    assert helpers.match_incident("T1", CANDIDATES, a, t).outcome == helpers.LINKED
    assert helpers.match_incident("T1", CANDIDATES, a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.match_incident("T1", CANDIDATES, _confident("INC-101"), bad)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example,
    # built from that example's own symptoms (the candidates, and so the replay key, depend on
    # the retrieved shortlist for those symptoms).
    for example in load_inputs(RECIPE):
        candidates = helpers.shortlist(example.fields["symptoms"])
        questions = helpers.build_questions(candidates)
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


# --- record_resolution (the simulated side effect) --------------------------------------------


class _FakeLog:
    def __init__(self):
        self.entries = []

    def record(self, kind, payload=None, *, step=None, answer=None, rule=None):
        self.entries.append((kind, payload, rule))


class _FakeQueue:
    def __init__(self):
        self.entries = []

    def submit(self, item, reason, *, answer=None, step=None):
        self.entries.append((item, reason))


def test_a_linked_resolution_is_recorded_in_the_action_log_only():
    a = _confident("INC-101")
    resolution = helpers.match_incident("T1", CANDIDATES, a, 0.3)
    actions, queue = _FakeLog(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, queue)
    assert len(actions.entries) == 1
    assert actions.entries[0][0] == "link_incident"
    assert actions.entries[0][1] == {"new_incident": "T1", "linked_to": "INC-101"}
    assert len(queue.entries) == 0


def test_a_review_resolution_is_queued_only():
    a = _low_confidence("INC-101")
    resolution = helpers.match_incident("T1", CANDIDATES, a, 0.5)
    actions, queue = _FakeLog(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, queue)
    assert len(actions.entries) == 0
    assert len(queue.entries) == 1
    assert queue.entries[0][0]["new_incident"] == "T1"


def test_a_no_duplicate_resolution_records_nothing():
    a = _confident(helpers.NO_MATCH)
    resolution = helpers.match_incident("T1", CANDIDATES, a, 0.3)
    actions, queue = _FakeLog(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, queue)
    assert len(actions.entries) == 0
    assert len(queue.entries) == 0


def test_stored_answers_are_not_all_right():
    """At least one stored test answer is wrong, and at least one wrong answer sits at or above
    the confidence gate this recipe's own notebook freezes from validation -- the false merge the
    evaluation section reports (``OutcomeSummary.false_merge_rate``). A fixture set where the
    gate always happens to catch every mistake would overstate what a confidence-only gate can
    do."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    inputs = load_inputs(RECIPE)

    def decide(example):
        candidates = helpers.shortlist(example.fields["symptoms"])
        questions = helpers.build_questions(candidates)
        answer = backend.decide(helpers.build_state(example.fields), questions)["match"]
        return candidates, answer

    val_real = []
    for e in inputs:
        if e.split != "validation" or e.id not in labels:
            continue
        _candidates, a = decide(e)
        if a.choice != helpers.NO_MATCH:
            val_real.append((a.choice == labels[e.id], a.confidence))
    gate = select_confidence_threshold(
        [correct for correct, _ in val_real],
        [conf for _, conf in val_real],
        target_accuracy=1.0,
    )

    wrong = []
    wrong_above_gate = []
    for e in inputs:
        if e.id not in labels:
            continue
        _candidates, a = decide(e)
        if a.choice != labels[e.id]:
            wrong.append(e.id)
            if a.choice != helpers.NO_MATCH and a.confidence >= gate:
                wrong_above_gate.append(e.id)

    assert wrong, "the fixtures should contain some wrong answers"
    assert wrong_above_gate, (
        "at least one wrong answer should clear the confidence gate chosen from validation "
        "(a false merge the gate does not catch)"
    )


# --- summarize_outcomes ------------------------------------------------------------------------


def _resolution(ticket_id, label, outcome):
    return helpers.Resolution(ticket_id, tuple(CANDIDATES), label, outcome, "test fixture")


def test_summarize_outcomes_counts_linked_and_no_duplicate_as_answered():
    results = [
        _resolution("a", "INC-101", helpers.LINKED),
        _resolution("b", helpers.NO_MATCH, helpers.NO_DUPLICATE),
        _resolution("c", "INC-102", helpers.REVIEW),
    ]
    gold = {"a": "INC-101", "b": "no_match", "c": "INC-102"}
    summary = helpers.summarize_outcomes(results, gold)
    assert summary.n_total == 3
    assert summary.n_linked == 1
    assert summary.n_reviewed == 1
    assert summary.n_no_duplicate == 1
    assert summary.coverage == pytest.approx(2 / 3)
    assert summary.accuracy == pytest.approx(1.0)
    assert summary.risk == pytest.approx(0.0)
    assert summary.false_merge_rate == pytest.approx(0.0)


def test_summarize_outcomes_counts_a_wrong_link_as_a_false_merge():
    # "a" is linked to INC-101, but the gold match is INC-102: a real, wrong link -- the one way
    # this recipe's simulated side effect can be wrong, so it counts against false_merge_rate,
    # not only against the general risk.
    results = [
        _resolution("a", "INC-101", helpers.LINKED),
        _resolution("b", "INC-102", helpers.LINKED),
    ]
    gold = {"a": "INC-102", "b": "INC-102"}
    summary = helpers.summarize_outcomes(results, gold)
    assert summary.n_linked == 2
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.risk == pytest.approx(0.5)
    assert summary.false_merge_rate == pytest.approx(0.5)


def test_summarize_outcomes_does_not_count_a_wrong_no_duplicate_as_a_false_merge():
    # "a" is wrongly called no_match (a missed duplicate), but no_match never links anything, so
    # it costs accuracy/risk above but leaves false_merge_rate at 0: nothing was actually merged.
    results = [
        _resolution("a", helpers.NO_MATCH, helpers.NO_DUPLICATE),
        _resolution("b", "INC-101", helpers.LINKED),
    ]
    gold = {"a": "INC-102", "b": "INC-101"}
    summary = helpers.summarize_outcomes(results, gold)
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.risk == pytest.approx(0.5)
    assert summary.false_merge_rate == pytest.approx(0.0)


def test_summarize_outcomes_false_merge_rate_is_nan_with_nothing_linked():
    results = [_resolution("a", helpers.NO_MATCH, helpers.NO_DUPLICATE)]
    summary = helpers.summarize_outcomes(results, {"a": "no_match"})
    assert summary.n_linked == 0
    assert math.isnan(summary.false_merge_rate)


def test_summarize_outcomes_is_nan_when_nothing_was_answered():
    results = [_resolution("a", "INC-101", helpers.REVIEW)]
    summary = helpers.summarize_outcomes(results, {"a": "INC-101"})
    assert summary.n_linked == 0 and summary.n_no_duplicate == 0
    assert summary.coverage == 0.0
    assert math.isnan(summary.accuracy)
    assert math.isnan(summary.risk)
    assert math.isnan(summary.false_merge_rate)


def test_summarize_outcomes_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one"):
        helpers.summarize_outcomes([], {})
