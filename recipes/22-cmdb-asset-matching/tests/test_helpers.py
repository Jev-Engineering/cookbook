"""Tests for recipe 22's helpers. They load the helpers by file path."""

import math
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# A fixed shortlist used by most tests below, independent of retrieval itself (which has its
# own tests further down): two real candidates plus the no_match fallback.
CANDIDATES = ["CMDB-04", "CMDB-05"]


def answer(probabilities):
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def _confident(label, candidates=CANDIDATES):
    """A clearly confident answer naming ``label`` (a candidate id or no_match)."""
    options = [*candidates, helpers.NO_MATCH]
    others = [o for o in options if o != label]
    rest = (1.0 - 0.9) / len(others)
    return answer({label: 0.9, **{o: rest for o in others}})


def _low_confidence(label, candidates=CANDIDATES):
    """A barely-ahead answer naming ``label``, confidence well under the usual gate but still
    the argmax (above the uniform share for this many options)."""
    options = [*candidates, helpers.NO_MATCH]
    others = [o for o in options if o != label]
    rest = (1.0 - 0.40) / len(others)
    assert rest < 0.40  # otherwise `label` would not actually be the argmax
    return answer({label: 0.40, **{o: rest for o in others}})


def _confident_foreign(candidates=CANDIDATES):
    """A confident answer naming an option that is neither one of ``candidates`` nor
    ``no_match`` -- `match_record` must still reject it, even though `build_questions` never
    offers such an option (the check is defensive, not reachable through replay or live, the
    same guard recipe 07's word-sense rule and recipe 18's incident-matching rule keep)."""
    return answer({"CMDB-999-not-a-real-record": 0.90, "also-not-one": 0.10})


# --- retrieval: similarity_scores / shortlist -------------------------------------------------


def test_every_canonical_record_retrieves_itself_at_similarity_one():
    for record_id, record in helpers.CMDB_RECORDS.items():
        scores = helpers.similarity_scores(record["vendor"], record["product"])
        assert scores[record_id] == pytest.approx(1.0)


def test_shortlist_never_pads_with_zero_similarity_records():
    # Nothing in the catalog shares any wording with this text, so retrieval must return
    # nothing at all rather than padding the list out with unrelated records tied at zero.
    assert helpers.shortlist("Chorus Collective", "Chorus Meet") == []


def test_shortlist_is_capped_at_max_candidates():
    for record in helpers.CMDB_RECORDS.values():
        result = helpers.shortlist(record["vendor"], record["product"])
        assert 1 <= len(result) <= helpers.MAX_CANDIDATES
        assert len(set(result)) == len(result)
        assert all(r in helpers.CMDB_RECORDS for r in result)


def test_shortlist_ranks_the_self_match_first_when_it_is_unique():
    # Candlewood InkPress shares wording with its own record and, more thinly, with PixelForge (both
    # Candlewood), but never ties it: the self-match must rank first.
    result = helpers.shortlist("Candlewood", "InkPress")
    assert result[0] == "CMDB-04"
    assert "CMDB-05" in result  # the Candlewood sibling is still retrieved, thinner overlap


def test_shortlist_ties_the_version_family_and_breaks_on_id():
    # CMDB-01/02/03 (Northcastle LedgerStack Server 2017/2020/2023) are identical in vendor and product,
    # so retrieval -- which never looks at version -- always ties all three and breaks the tie
    # on id, whatever version the observed asset actually names.
    for vendor in ("Northcastle", "NSTL", "Northcastle Corporation"):
        assert helpers.shortlist(vendor, "LedgerStack Server") == ["CMDB-01", "CMDB-02", "CMDB-03"]


def test_shortlist_is_deterministic():
    assert helpers.shortlist("Thornfield", "VaultDB") == helpers.shortlist("Thornfield", "VaultDB")


def test_similarity_scores_covers_every_canonical_record():
    scores = helpers.similarity_scores("Candlewood", "InkPress")
    assert set(scores) == set(helpers.CMDB_RECORDS)
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_vendor_aliases_still_retrieve_the_canonical_record():
    # Different wordings of the same vendor name must normalize to the same tokens.
    for vendor in ("Redfern", "Redfern, Inc.", "Redfern Inc"):
        assert "CMDB-08" in helpers.shortlist(vendor, "Enterprise OS")
    # "RFOS" alone expands to "redfern enterprise os", covering vendor and product together.
    assert "CMDB-08" in helpers.shortlist("RFOS", "")


def test_a_lexical_lookalike_is_retrieved_but_is_not_the_canonical_products_own_pool():
    # InkPress Reader is a different, free product from the paid InkPress the catalog holds, but
    # shares enough wording with it to be retrieved as a candidate -- the trap this recipe's
    # fixtures use.
    result = helpers.shortlist("Candlewood", "InkPress Reader DC")
    assert "CMDB-04" in result


# --- build_questions / build_state -------------------------------------------------------------


def test_questions_are_built_from_the_given_candidates_plus_no_match():
    questions = helpers.build_questions(CANDIDATES)
    assert list(questions) == ["match"]
    match = questions["match"]
    assert list(match.criteria) == [*CANDIDATES, helpers.NO_MATCH]
    assert all(isinstance(d, str) and d for d in match.criteria.values())
    assert isinstance(match.instructions, str) and match.instructions


def test_the_option_list_changes_with_the_candidates():
    a = helpers.build_questions(["CMDB-01", "CMDB-02"])["match"]
    b = helpers.build_questions(["CMDB-06", "CMDB-11"])["match"]
    assert list(a.criteria) != list(b.criteria)


def test_build_questions_refuses_an_empty_candidate_list():
    # A Choice with zero real candidates would offer exactly one option (the fallback alone):
    # a forced answer belongs to Python, not a request, so this is refused rather than silently
    # building a single-option Choice.
    with pytest.raises(ValueError, match="at least one"):
        helpers.build_questions([])


def test_the_state_hides_the_asset_id():
    fields = {
        "asset_id": "AST-9",
        "vendor": "Candlewood",
        "product": "InkPress",
        "version": "11.0",
        "edition": "Pro",
    }
    assert helpers.build_state(fields) == {
        "vendor": "Candlewood",
        "product": "InkPress",
        "version": "11.0",
        "edition": "Pro",
    }


# --- no_candidate_resolution ---------------------------------------------------------------


def test_no_candidate_resolution_is_a_final_no_match_with_no_candidates():
    result = helpers.no_candidate_resolution("AST-1")
    assert result.asset_id == "AST-1"
    assert result.candidates == ()
    assert result.label == helpers.NO_MATCH
    assert result.outcome == helpers.NO_MATCH_OUTCOME
    assert (
        result.reason == "no candidate record shares any vendor or product wording with this asset"
    )


# --- match_record --------------------------------------------------------------------------


@pytest.mark.parametrize("label", CANDIDATES)
def test_a_confident_real_candidate_is_linked_whatever_the_label(label):
    a = _confident(label)
    result = helpers.match_record("A1", CANDIDATES, a, 0.3)
    assert (result.asset_id, result.label, result.outcome) == ("A1", label, helpers.LINKED)
    assert result.reason == "confident match"


@pytest.mark.parametrize("label", CANDIDATES)
def test_a_low_confidence_real_candidate_goes_to_review_whatever_the_label(label):
    a = _low_confidence(label)
    assert a.choice == label
    result = helpers.match_record("A1", CANDIDATES, a, 0.5)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "confidence below the threshold"


@pytest.mark.parametrize("top_probability", [0.95, 0.40])
def test_no_match_is_never_gated_on_confidence_whatever_its_value(top_probability):
    # top_probability=0.40 keeps no_match as the top option (above the uniform third, 0.333)
    # while its confidence, (0.40 - 1/3) / (2/3) =~ 0.10, is well below the 0.3 gate used here.
    # A mutation that exempted no_match from the gate only when it is also confident would still
    # fail this case, because it is checked at both ends.
    others = [*CANDIDATES]
    rest = (1.0 - top_probability) / len(others)
    a = answer({helpers.NO_MATCH: top_probability, **{o: rest for o in others}})
    assert a.choice == helpers.NO_MATCH
    result = helpers.match_record("A1", CANDIDATES, a, 0.3)
    assert result.outcome == helpers.NO_MATCH_OUTCOME
    assert result.label == helpers.NO_MATCH
    assert result.reason == "no canonical record matches"


def test_choosing_an_option_outside_the_candidates_goes_to_review_even_when_confident():
    a = _confident_foreign()
    assert a.choice not in CANDIDATES
    assert a.choice != helpers.NO_MATCH
    result = helpers.match_record("A1", CANDIDATES, a, 0.0)
    assert result.outcome == helpers.REVIEW
    assert result.reason == "not one of the retrieved candidates"


def test_the_threshold_is_inclusive():
    a = _confident("CMDB-04")
    t = a.confidence
    assert helpers.match_record("A1", CANDIDATES, a, t).outcome == helpers.LINKED
    assert helpers.match_record("A1", CANDIDATES, a, t + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.match_record("A1", CANDIDATES, _confident("CMDB-04"), bad)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. An example whose
    # shortlist is empty lists no replay key at all (no request is ever made for it).
    for example in load_inputs(RECIPE):
        candidates = helpers.shortlist(example.fields["vendor"], example.fields["product"])
        if not candidates:
            assert example.replay_keys == ()
            continue
        questions = helpers.build_questions(candidates)
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_no_replay_key_repeats_across_validation_and_test():
    # Because the option list is built fresh per asset, two assets sharing a replay key would
    # mean they asked Jev the literal same question -- the fixture validator's own leak rule
    # compares state/fields, not replay keys directly, so this checks it here instead.
    by_split = {"validation": [], "test": []}
    for example in load_inputs(RECIPE):
        if example.split in by_split:
            by_split[example.split].extend(example.replay_keys)
    val_keys, test_keys = set(by_split["validation"]), set(by_split["test"])
    assert not (val_keys & test_keys)


# --- record_resolution (the simulated side effects) --------------------------------------------


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
    a = _confident("CMDB-04")
    resolution = helpers.match_record("A1", CANDIDATES, a, 0.3)
    actions, backlog, queue = _FakeLog(), _FakeQueue(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, backlog, queue)
    assert len(actions.entries) == 1
    assert actions.entries[0][0] == "link_asset"
    assert actions.entries[0][1] == {"asset": "A1", "linked_to": "CMDB-04"}
    assert len(backlog.entries) == 0
    assert len(queue.entries) == 0


def test_a_review_resolution_is_queued_only():
    a = _low_confidence("CMDB-04")
    resolution = helpers.match_record("A1", CANDIDATES, a, 0.5)
    actions, backlog, queue = _FakeLog(), _FakeQueue(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, backlog, queue)
    assert len(actions.entries) == 0
    assert len(backlog.entries) == 0
    assert len(queue.entries) == 1
    assert queue.entries[0][0]["asset"] == "A1"


def test_a_no_match_resolution_goes_to_the_backlog_only():
    a = _confident(helpers.NO_MATCH)
    resolution = helpers.match_record("A1", CANDIDATES, a, 0.3)
    actions, backlog, queue = _FakeLog(), _FakeQueue(), _FakeQueue()
    helpers.record_resolution(resolution, a, actions, backlog, queue)
    assert len(actions.entries) == 0
    assert len(backlog.entries) == 1
    assert backlog.entries[0][0]["asset"] == "A1"
    assert len(queue.entries) == 0


def test_a_forced_no_candidate_resolution_also_goes_to_the_backlog_only():
    resolution = helpers.no_candidate_resolution("A1")
    actions, backlog, queue = _FakeLog(), _FakeQueue(), _FakeQueue()
    helpers.record_resolution(resolution, None, actions, backlog, queue)
    assert len(actions.entries) == 0
    assert len(backlog.entries) == 1
    assert len(queue.entries) == 0


def test_stored_answers_are_not_all_right():
    """At least one stored test answer is wrong, and at least one wrong answer sits at or above
    the confidence gate this recipe's own notebook freezes from validation -- the false link the
    evaluation section reports (``false_link_rate``). A fixture set where the gate always
    happens to catch every mistake would overstate what a confidence-only gate can do."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    inputs = load_inputs(RECIPE)

    def decide(example):
        candidates = helpers.shortlist(example.fields["vendor"], example.fields["product"])
        if not candidates:
            return candidates, None
        questions = helpers.build_questions(candidates)
        answer = backend.decide(helpers.build_state(example.fields), questions)["match"]
        return candidates, answer

    val_real = []
    for e in inputs:
        if e.split != "validation" or e.id not in labels:
            continue
        _candidates, a = decide(e)
        if a is not None and a.choice != helpers.NO_MATCH:
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
        label = helpers.NO_MATCH if a is None else a.choice
        if label != labels[e.id]:
            wrong.append(e.id)
            if a is not None and a.choice != helpers.NO_MATCH and a.confidence >= gate:
                wrong_above_gate.append(e.id)

    assert wrong, "the fixtures should contain some wrong answers"
    assert wrong_above_gate, (
        "at least one wrong answer should clear the confidence gate chosen from validation "
        "(a false link the gate does not catch)"
    )


# --- accepted_and_correct / false_link_rate -------------------------------------------------


def _resolution(asset_id, label, outcome):
    return helpers.Resolution(asset_id, tuple(CANDIDATES), label, outcome, "test fixture")


def test_accepted_and_correct_marks_review_as_not_accepted():
    results = [
        _resolution("a", "CMDB-04", helpers.LINKED),
        _resolution("b", helpers.NO_MATCH, helpers.NO_MATCH_OUTCOME),
        _resolution("c", "CMDB-05", helpers.REVIEW),
    ]
    gold = {"a": "CMDB-04", "b": "no_match", "c": "CMDB-05"}
    accepted, correct = helpers.accepted_and_correct(results, gold)
    assert accepted == [True, True, False]
    assert correct == [True, True, True]


def test_accepted_and_correct_feeds_evaluate_outcomes():
    # The shared jev_cookbook.evaluation.evaluate_outcomes helper is the one this recipe's
    # notebook uses for coverage/accuracy/risk; this pins that the two functions still agree.
    from jev_cookbook.evaluation import evaluate_outcomes

    results = [
        _resolution("a", "CMDB-04", helpers.LINKED),
        _resolution("b", "CMDB-05", helpers.LINKED),  # wrong link, gold is CMDB-04
        _resolution("c", helpers.NO_MATCH, helpers.NO_MATCH_OUTCOME),
        _resolution("d", "CMDB-01", helpers.REVIEW),
    ]
    gold = {"a": "CMDB-04", "b": "CMDB-04", "c": "no_match", "d": "CMDB-01"}
    accepted, correct = helpers.accepted_and_correct(results, gold)
    outcomes = evaluate_outcomes(accepted, correct)
    assert outcomes.n_total == 4
    assert outcomes.n_answered == 3
    assert outcomes.coverage == pytest.approx(0.75)
    assert outcomes.accuracy == pytest.approx(2 / 3)
    assert outcomes.risk == pytest.approx(1 / 3)


def test_false_link_rate_counts_a_wrong_link():
    # "a" is linked to CMDB-04, but the gold match is CMDB-05: a real, wrong link -- the one
    # way this recipe's simulated side effect can be wrong.
    results = [
        _resolution("a", "CMDB-04", helpers.LINKED),
        _resolution("b", "CMDB-05", helpers.LINKED),
    ]
    gold = {"a": "CMDB-05", "b": "CMDB-05"}
    assert helpers.false_link_rate(results, gold) == pytest.approx(0.5)


def test_false_link_rate_does_not_count_a_wrong_no_match():
    # "a" is wrongly called no_match (a missed match), but no_match never links anything, so it
    # costs accuracy/risk (via evaluate_outcomes) but leaves false_link_rate at 0: nothing was
    # actually linked.
    results = [
        _resolution("a", helpers.NO_MATCH, helpers.NO_MATCH_OUTCOME),
        _resolution("b", "CMDB-04", helpers.LINKED),
    ]
    gold = {"a": "CMDB-05", "b": "CMDB-04"}
    assert helpers.false_link_rate(results, gold) == pytest.approx(0.0)


def test_false_link_rate_is_nan_with_nothing_linked():
    results = [_resolution("a", helpers.NO_MATCH, helpers.NO_MATCH_OUTCOME)]
    assert math.isnan(helpers.false_link_rate(results, {"a": "no_match"}))


def test_false_link_rate_rejects_empty_input():
    with pytest.raises(ValueError, match="at least one"):
        helpers.false_link_rate([], {})


# --- baselines (pipeline checks the rule must clearly beat) -----------------------------------


def test_baseline_always_top_picks_the_first_candidate():
    assert helpers.baseline_always_top(["CMDB-01", "CMDB-02", "CMDB-03"]) == "CMDB-01"
    assert helpers.baseline_always_top([]) == helpers.NO_MATCH


def test_baseline_always_top_cannot_tell_the_version_family_apart():
    # Whatever version is actually observed, this baseline only ever sees the tied shortlist and
    # always names its lowest id -- it is wrong whenever the true match is CMDB-02 or CMDB-03.
    candidates = helpers.shortlist("Northcastle", "LedgerStack Server")
    assert helpers.baseline_always_top(candidates) == "CMDB-01"


def test_baseline_overlap_cutoff_links_a_clean_self_match():
    assert helpers.baseline_overlap_cutoff("Candlewood", "InkPress") == "CMDB-04"


def test_baseline_overlap_cutoff_reports_no_match_below_the_cutoff():
    assert helpers.baseline_overlap_cutoff("Chorus Collective", "Chorus Meet") == (helpers.NO_MATCH)


def test_baseline_overlap_cutoff_also_cannot_tell_the_version_family_apart():
    # Version plays no part in either baseline's input, so this one is exactly as unable to
    # distinguish CMDB-01/02/03 as baseline_always_top is.
    assert helpers.baseline_overlap_cutoff("Northcastle", "LedgerStack Server") == "CMDB-01"
