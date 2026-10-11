"""Tests for recipe 30's helpers. They load the helpers by file path."""

from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer_for(choice: str, confidence: float = 0.9):
    """A synthetic Choice answer naming ``choice`` at ``confidence``, the rest of the mass
    split evenly over the other two options."""
    p_max = (confidence + 0.5) / 1.5
    rest = (1.0 - p_max) / 2.0
    probabilities = {name: (p_max if name == choice else rest) for name in helpers.OPTIONS}
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def test_the_options_come_from_options():
    # Against a literal expected value, not helpers.OPTIONS itself: comparing against the
    # module's own data would still pass if OPTIONS and the options it feeds drifted together.
    options = list(helpers.build_questions()["relation"].criteria)
    assert options == ["supported", "unsupported", "contradicted"]


def test_resolve_citation_finds_a_known_passage():
    passage = helpers.resolve_citation({"doc": "RATE-LIMITS", "section": "1", "claim": "x"})
    assert passage == helpers.CORPUS["RATE-LIMITS"]["1"]


@pytest.mark.parametrize(
    "fields",
    [
        {"doc": "NO-SUCH-DOC", "section": "1", "claim": "x"},
        {"doc": "RATE-LIMITS", "section": "99", "claim": "x"},
    ],
)
def test_resolve_citation_is_none_for_an_unknown_document_or_section(fields):
    assert helpers.resolve_citation(fields) is None


def test_citation_label_formats_doc_and_section():
    assert helpers.citation_label({"doc": "RATE-LIMITS", "section": "4"}) == "RATE-LIMITS§4"


def test_build_state_hides_the_citation_and_keeps_only_claim_and_passage():
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "A claim."}
    state = helpers.build_state(fields)
    assert set(state) == {"claim", "passage"}
    assert state["claim"] == "A claim."
    assert state["passage"] == helpers.CORPUS["RATE-LIMITS"]["1"]
    assert "doc" not in state and "section" not in state


def test_build_state_raises_for_a_citation_that_does_not_resolve():
    fields = {"doc": "NO-SUCH-DOC", "section": "1", "claim": "A claim."}
    with pytest.raises(ValueError, match="does not resolve"):
        helpers.build_state(fields)


def test_an_unresolved_citation_is_flagged_without_ever_reaching_a_question():
    # answer=None is how classify learns a citation never resolved: no Choice was ever built
    # for it, so there is no confidence to gate and no review branch -- Python decided alone.
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "NO-SUCH-DOC", "section": "1", "claim": "x"}
    result = helpers.classify("c1", fields, None, 0.5, actions=actions, queue=queue)
    assert result.citation_resolved is False
    assert result.verdict == helpers.UNSUPPORTED
    assert result.action == helpers.ACTION_FLAG
    assert result.reason == helpers.REASON_NOT_RESOLVED
    assert len(actions) == 1
    assert len(queue) == 0
    assert actions.to_dicts()[0]["kind"] == helpers.ACTION_FLAG


@pytest.mark.parametrize("choice", helpers.OPTIONS)
def test_low_confidence_goes_to_review_whatever_the_choice(choice):
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    result = helpers.classify(
        "c1", fields, answer_for(choice, 0.3), 0.5, actions=actions, queue=queue
    )
    assert result.citation_resolved is True
    assert result.verdict == helpers.REVIEW
    assert result.action is None
    assert result.reason == helpers.REASON_LOW_CONFIDENCE
    assert len(actions) == 0
    assert len(queue) == 1
    assert queue.to_dicts()[0]["reason"] == helpers.REASON_LOW_CONFIDENCE


def test_confident_supported_is_kept():
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    result = helpers.classify(
        "c1", fields, answer_for(helpers.SUPPORTED), 0.5, actions=actions, queue=queue
    )
    assert (result.verdict, result.action) == (helpers.SUPPORTED, helpers.ACTION_KEEP)
    assert len(actions) == 1
    assert len(queue) == 0
    assert actions.to_dicts()[0]["kind"] == helpers.ACTION_KEEP


@pytest.mark.parametrize("choice", [helpers.UNSUPPORTED, helpers.CONTRADICTED])
def test_confident_unsupported_or_contradicted_is_flagged_naming_which(choice):
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    result = helpers.classify("c1", fields, answer_for(choice), 0.5, actions=actions, queue=queue)
    assert (result.verdict, result.action) == (choice, helpers.ACTION_FLAG)
    assert len(actions) == 1
    assert len(queue) == 0
    entry = actions.to_dicts()[0]
    assert entry["kind"] == helpers.ACTION_FLAG
    assert choice in result.reason


def test_the_threshold_is_inclusive():
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    a = answer_for(helpers.SUPPORTED, 0.7)
    at = helpers.classify("c1", fields, a, a.confidence, actions=ActionLog(), queue=ReviewQueue())
    assert at.verdict == helpers.SUPPORTED
    just_below = helpers.classify(
        "c1", fields, a, a.confidence + 1e-9, actions=ActionLog(), queue=ReviewQueue()
    )
    assert just_below.verdict == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_a_threshold_outside_zero_to_one_is_an_error(bad):
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify(
            "c1",
            fields,
            answer_for(helpers.SUPPORTED),
            bad,
            actions=ActionLog(),
            queue=ReviewQueue(),
        )


def test_accepted_and_correct_marks_review_as_not_accepted_and_unresolved_as_accepted():
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    verdicts = [
        helpers.classify(
            "c1", fields, answer_for(helpers.SUPPORTED), 0.5, actions=actions, queue=queue
        ),
        helpers.classify(
            "c2", fields, answer_for(helpers.CONTRADICTED), 0.5, actions=actions, queue=queue
        ),
        helpers.classify(
            "c3", fields, answer_for(helpers.SUPPORTED, 0.3), 0.5, actions=actions, queue=queue
        ),
        helpers.classify(
            "c4",
            {"doc": "NO-SUCH-DOC", "section": "1", "claim": "x"},
            None,
            0.5,
            actions=actions,
            queue=queue,
        ),
    ]
    gold = {
        "c1": helpers.SUPPORTED,
        "c2": helpers.SUPPORTED,
        "c3": helpers.SUPPORTED,
        "c4": helpers.UNSUPPORTED,
    }
    accepted, correct = helpers.accepted_and_correct(verdicts, gold)
    assert accepted == [True, True, False, True]
    assert correct == [True, False, False, True]


def test_should_flag_reads_the_gold_label():
    assert helpers.should_flag(helpers.SUPPORTED) is False
    assert helpers.should_flag(helpers.UNSUPPORTED) is True
    assert helpers.should_flag(helpers.CONTRADICTED) is True


def test_actual_flag_treats_review_as_neither_kept_nor_flagged():
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    kept = helpers.classify(
        "c1", fields, answer_for(helpers.SUPPORTED), 0.5, actions=actions, queue=queue
    )
    flagged = helpers.classify(
        "c2", fields, answer_for(helpers.CONTRADICTED), 0.5, actions=actions, queue=queue
    )
    reviewed = helpers.classify(
        "c3", fields, answer_for(helpers.SUPPORTED, 0.3), 0.5, actions=actions, queue=queue
    )
    assert helpers.actual_flag(kept) is False
    assert helpers.actual_flag(flagged) is True
    assert helpers.actual_flag(reviewed) is None


def test_flag_agreement_reads_the_gold_label_not_the_raw_choice():
    actions, queue = ActionLog(), ReviewQueue()
    fields = {"doc": "RATE-LIMITS", "section": "1", "claim": "x"}
    # c1: gold unsupported, answered contradicted -- different raw labels, same flag decision
    # (both flagged), so this agrees even though the raw choice is wrong.
    # c2: gold supported, gated to review for low confidence -- review always disagrees.
    verdicts = [
        helpers.classify(
            "c1", fields, answer_for(helpers.CONTRADICTED), 0.5, actions=actions, queue=queue
        ),
        helpers.classify(
            "c2", fields, answer_for(helpers.SUPPORTED, 0.3), 0.5, actions=actions, queue=queue
        ),
    ]
    gold = {"c1": helpers.UNSUPPORTED, "c2": helpers.SUPPORTED}
    assert helpers.flag_agreement(verdicts, gold) == 0.5


def test_flag_agreement_rejects_empty_input():
    with pytest.raises(ValueError, match="empty"):
        helpers.flag_agreement([], {})


# -------------------------------------------------------------------------------------------
# Independent-consequence proof, on real committed fixtures (not a synthetic in-test row):
# the citation-resolution stage and the model's Choice answer each change the composed
# verdict and action on their own, holding the other fixed.
# -------------------------------------------------------------------------------------------


def _decide(backend, questions, example):
    return backend.decide(helpers.build_state(example.fields), questions)["relation"]


def test_citation_resolution_is_independently_consequential_on_a_real_fixture():
    """``v-s1`` is a real, committed validation fixture whose citation resolves and whose
    stored answer confidently supports the claim. Holding that same stored answer fixed and
    only flipping whether the citation resolved (the one thing ``classify`` reads ``answer``
    for) changes the composed verdict and action, proving the citation-resolution stage is
    consequential on its own."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    v_s1 = examples["v-s1"]
    answer = _decide(backend, questions, v_s1)

    resolved = helpers.classify(
        "v-s1", v_s1.fields, answer, 0.45, actions=ActionLog(), queue=ReviewQueue()
    )
    assert (resolved.verdict, resolved.action) == (helpers.SUPPORTED, helpers.ACTION_KEEP)

    not_resolved = helpers.classify(
        "v-s1", v_s1.fields, None, 0.45, actions=ActionLog(), queue=ReviewQueue()
    )
    assert (not_resolved.verdict, not_resolved.action) == (helpers.UNSUPPORTED, helpers.ACTION_FLAG)
    assert not_resolved.verdict != resolved.verdict
    assert not_resolved.action != resolved.action


def test_the_models_choice_is_independently_consequential_on_a_real_fixture():
    """``v-broken-01`` is a real, committed validation fixture whose citation never resolves
    (its forced verdict, ``unsupported``/flagged, is what the committed labels record). Holding
    the citation fixed as unresolved and instead asking what would happen if a resolved
    citation's own real stored answer (``v-s1``'s, confidently ``supported``) applied here shows
    the model's answer is independently consequential too: the composed verdict and action flip
    from the forced ``unsupported``/flag to ``supported``/keep."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    v_broken_01 = examples["v-broken-01"]
    v_s1 = examples["v-s1"]
    assert helpers.resolve_citation(v_broken_01.fields) is None

    forced = helpers.classify(
        "v-broken-01", v_broken_01.fields, None, 0.45, actions=ActionLog(), queue=ReviewQueue()
    )
    assert (forced.verdict, forced.action) == (helpers.UNSUPPORTED, helpers.ACTION_FLAG)

    other_answer = _decide(backend, questions, v_s1)
    as_if_resolved = helpers.classify(
        "v-broken-01",
        v_broken_01.fields,
        other_answer,
        0.45,
        actions=ActionLog(),
        queue=ReviewQueue(),
    )
    assert (as_if_resolved.verdict, as_if_resolved.action) == (
        helpers.SUPPORTED,
        helpers.ACTION_KEEP,
    )
    assert as_if_resolved.verdict != forced.verdict
    assert as_if_resolved.action != forced.action


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. A citation that does not
    # resolve never reaches a question at all, so it carries no replay key (docs/fixtures.md,
    # "Replay and scripted recipes"); every other example carries exactly one.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        if helpers.resolve_citation(example.fields) is None:
            assert example.replay_keys == ()
        else:
            key = replay_key(helpers.build_state(example.fields), questions)
            assert example.replay_keys == (key,)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. This mirrors the notebook's own threshold selection: only claims
    # whose citation resolves have a confidence to select on (a citation that never resolves is
    # never asked a question, so it is left out of this selection entirely, exactly as
    # docs/recipe-template.md's "selected-confidence-threshold" guidance requires for a case
    # Python resolves on its own before any Choice is built). The frozen threshold then applies
    # to every example, resolved or not; this test only needs a wrong `test` answer the model
    # was actually asked about that clears the gate.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def resolved_with_label(split):
        return [
            e
            for e in examples
            if e.split == split
            and e.id in labels
            and helpers.resolve_citation(e.fields) is not None
        ]

    validation = resolved_with_label("validation")
    val_answers = {e.id: _decide(backend, questions, e) for e in validation}
    correct = [val_answers[e.id].choice == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.75)

    test = resolved_with_label("test")
    test_answers = {e.id: _decide(backend, questions, e) for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if test_answers[e.id].choice != labels[e.id] and test_answers[e.id].confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
