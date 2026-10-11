"""Tests for recipe 30's helpers. They load the helpers by file path."""

import importlib.util
import json
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


def _decide(backend, questions, example):
    return backend.decide(helpers.build_state(example.fields), questions)["relation"]


def _load_module_at(path, name):
    """A module loaded by file path, the way ``tests/test_build_fixtures.py`` already does --
    its functions and module-level values (``ROWS``, ``QUESTIONS``) as plain Python objects,
    independent of whatever ``main()`` last wrote to disk."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_frozen_threshold():
    """The threshold this recipe's own notebook freezes, recomputed independently from the
    real, committed fixtures with ``helpers.choose_threshold`` (``select_confidence_threshold``
    pinned to ``helpers.MIN_COVERAGE``) -- the same inputs and the same objective the
    notebook's own selection cell uses, so every test below that needs "the frozen gate" reads
    it from here rather than a bare literal that could silently stop matching what the
    notebook actually does."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    resolved = helpers.resolved_subset(validation)
    answers = {e.id: _decide(backend, questions, e) for e in resolved}
    correct = [answers[e.id].choice == labels[e.id] for e in resolved]
    confidence = [answers[e.id].confidence for e in resolved]
    return helpers.choose_threshold(correct, confidence)


# Computed once, from the real fixtures, at collection time: every test below that needs "the
# frozen gate" uses this, never a bare literal, so a change to MIN_COVERAGE, to the resolved-
# citation filter, or to the fixtures themselves moves every test that depends on it together.
REAL_THRESHOLD = _real_frozen_threshold()


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


def test_resolved_subset_keeps_only_examples_whose_citation_resolves():
    class Example:
        def __init__(self, fields):
            self.fields = fields

    resolving = Example({"doc": "RATE-LIMITS", "section": "1", "claim": "x"})
    not_resolving = Example({"doc": "NO-SUCH-DOC", "section": "1", "claim": "x"})
    assert helpers.resolved_subset([resolving, not_resolving]) == [resolving]


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
# Fixture-generation consistency (Wave 3 batch 1 rule 11): the committed responses.json must
# store the top choice each ROWS entry actually names, checked against the committed file
# itself -- never by calling answers_for/build_responses again, which would reproduce a
# mislabelling identically on both sides.
# -------------------------------------------------------------------------------------------

_DELIBERATELY_WRONG = {"v-c5-wrong-low", "v-u3-wrongpassage", "t-c5-wrong", "t-u3-wrongpassage"}


def test_every_stored_choice_matches_the_rows_it_came_from():
    """For every row in ``build_fixtures.py``'s ``ROWS`` whose citation resolves, the stored
    answer's own ``choice`` -- read directly from the committed ``fixtures/responses.json``,
    not recomputed through ``answers_for`` -- must equal the top label ``spec`` names; for
    every row not named in ``_DELIBERATELY_WRONG``, that top must also equal the row's own
    gold label. Mutation: change ``v-c1``'s spec in ``build_fixtures.py`` from
    ``(CONTRADICTED, 0.82)`` to ``(SUPPORTED, 0.82)``, run ``python build_fixtures.py
    --force``, and this test fails naming ``v-c1`` (both assertions: the stored choice no
    longer matches gold, and -- since ``v-c1`` is not in ``_DELIBERATELY_WRONG`` -- the row's
    own declared top no longer matches its gold label either)."""
    build_fixtures = _load_module_at(
        RECIPE / "build_fixtures.py", "recipe30_build_fixtures_for_consistency_test"
    )
    stored = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    mismatches = []
    for ident, _split, fields, label, spec in build_fixtures.ROWS:
        if spec is None:
            continue
        top, _confidence = spec
        key = replay_key(build_fixtures.helpers.build_state(fields), build_fixtures.QUESTIONS)
        stored_choice = stored[key]["answers"]["relation"]["choice"]
        if stored_choice != top:
            mismatches.append(f"{ident}: stored choice {stored_choice!r} != spec top {top!r}")
        if ident not in _DELIBERATELY_WRONG and label is not None and top != label:
            mismatches.append(
                f"{ident}: spec top {top!r} != gold {label!r}, but not in _DELIBERATELY_WRONG"
            )
    assert not mismatches, "; ".join(mismatches)


# -------------------------------------------------------------------------------------------
# Independent-consequence proof, on real committed fixtures (not a synthetic in-test row).
# Each test below varies exactly one of the two stages and fails under a mutation to that
# stage alone -- proved in the PR description by the corresponding mutation.
# -------------------------------------------------------------------------------------------


def test_citation_resolution_is_independently_consequential_on_a_real_fixture():
    """``v-s1`` (citation resolves) and ``v-broken-01`` (citation does not) are both real,
    committed validation fixtures. Both sides of the comparison are built by actually calling
    ``helpers.resolve_citation`` on each example's own fields -- never by handing ``classify``
    a bare ``None`` by hand -- so a mutation that neuters ``resolve_citation`` (makes it return
    a passage for every citation, ``v-broken-01``'s fabricated one included) breaks this test
    directly: the derivation below would then try to decide ``v-broken-01`` against the
    backend, which holds no stored answer for it, and raise."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}

    def answer_via_resolution(example):
        passage = helpers.resolve_citation(example.fields)
        if passage is None:
            return None
        return backend.decide(helpers.build_state(example.fields), questions)["relation"]

    v_s1 = examples["v-s1"]
    v_broken_01 = examples["v-broken-01"]

    resolved = helpers.classify(
        "v-s1",
        v_s1.fields,
        answer_via_resolution(v_s1),
        REAL_THRESHOLD,
        actions=ActionLog(),
        queue=ReviewQueue(),
    )
    not_resolved = helpers.classify(
        "v-broken-01",
        v_broken_01.fields,
        answer_via_resolution(v_broken_01),
        REAL_THRESHOLD,
        actions=ActionLog(),
        queue=ReviewQueue(),
    )
    assert (resolved.verdict, resolved.action) == (helpers.SUPPORTED, helpers.ACTION_KEEP)
    assert (not_resolved.verdict, not_resolved.action) == (
        helpers.UNSUPPORTED,
        helpers.ACTION_FLAG,
    )
    assert not_resolved.verdict != resolved.verdict
    assert not_resolved.action != resolved.action


def test_the_models_choice_is_independently_consequential_on_a_real_fixture():
    """``t-c5-wrong`` is a real, committed test fixture whose citation resolves (so this never
    touches ``resolve_citation``'s branch) and whose stored answer confidently (0.52) names
    ``supported`` -- wrong; ``RETRY-POLICY§3`` contradicts the claim. Holding the citation and
    the confidence fixed and rebuilding only the answer's top choice, to ``contradicted`` at
    the identical confidence, shows the model's own choice is independently consequential: the
    composed verdict, the recorded action and ``flag_agreement`` all flip. A mutation that
    makes ``classify`` ignore ``answer.choice`` (treat every resolved claim as ``supported``
    regardless of what Jev answered) breaks this test directly, because the rebuilt
    ``contradicted`` answer would then be kept as cited instead of flagged."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    t_c5 = examples["t-c5-wrong"]
    state = helpers.build_state(t_c5.fields)
    stored_answer = backend.decide(state, questions)["relation"]
    assert stored_answer.choice == helpers.SUPPORTED  # the real, committed, wrong answer

    rebuilt_answer = answer_for(helpers.CONTRADICTED, stored_answer.confidence)
    assert rebuilt_answer.confidence == pytest.approx(stored_answer.confidence)

    original = helpers.classify(
        "t-c5-wrong", t_c5.fields, stored_answer, REAL_THRESHOLD, actions=ActionLog(), queue=ReviewQueue()
    )
    rebuilt = helpers.classify(
        "t-c5-wrong", t_c5.fields, rebuilt_answer, REAL_THRESHOLD, actions=ActionLog(), queue=ReviewQueue()
    )

    assert (original.verdict, original.action) == (helpers.SUPPORTED, helpers.ACTION_KEEP)
    assert (rebuilt.verdict, rebuilt.action) == (helpers.CONTRADICTED, helpers.ACTION_FLAG)
    assert original.verdict != rebuilt.verdict
    assert original.action != rebuilt.action

    gold = {"t-c5-wrong": helpers.CONTRADICTED}
    assert helpers.flag_agreement([original], gold) == 0.0
    assert helpers.flag_agreement([rebuilt], gold) == 1.0


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
    # caught every mistake. This mirrors the notebook's own threshold selection exactly:
    # helpers.resolved_subset is the same filter the notebook's "Python's part" cell applies
    # (only claims whose citation resolves have a confidence to select on -- a citation that
    # never resolves is never asked a question, so it is left out of this selection entirely,
    # per docs/recipe-template.md's guidance for a case Python resolves on its own before any
    # Choice is built), and helpers.MIN_COVERAGE is the same objective parameter. The call to
    # select_confidence_threshold stays inline (rather than behind helpers.choose_threshold)
    # so this still re-derives the threshold the way the strong-form guard (G1(c)) checks for.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    validation = helpers.resolved_subset(
        [e for e in examples if e.split == "validation" and e.id in labels]
    )
    val_answers = {e.id: _decide(backend, questions, e) for e in validation}
    correct = [val_answers[e.id].choice == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=helpers.MIN_COVERAGE)
    assert threshold == pytest.approx(REAL_THRESHOLD)

    test = helpers.resolved_subset([e for e in examples if e.split == "test" and e.id in labels])
    test_answers = {e.id: _decide(backend, questions, e) for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if test_answers[e.id].choice != labels[e.id] and test_answers[e.id].confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


def test_the_committed_notebook_freezes_the_threshold_this_recipe_selects():
    """Rule 12: nothing in this file pins what the *notebook's own* selection cell actually
    does unless something reads what it committed. This reads the committed
    ``notebook.ipynb``'s own stdout for the ``python-rule`` cell (never re-executing it --
    recipe tests never execute notebooks) and checks that the threshold line it prints matches
    ``REAL_THRESHOLD`` exactly. Swapping the notebook's own selection to a different objective
    (``target_accuracy=1.0``, say) and re-executing it would print a different value there
    (0.7500, forcing validation accuracy to 1.0000) while ``REAL_THRESHOLD`` above -- derived
    independently through ``helpers.choose_threshold`` -- stays 0.4500, so this test is what
    actually notices, not just the committed-output freshness check."""
    nb = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in nb["cells"] if c.get("id") == "python-rule")
    text = "".join(
        "".join(o.get("text", ""))
        for o in cell.get("outputs", [])
        if o.get("output_type") == "stream"
    )
    assert text, "python-rule cell has no committed stdout to check"
    assert f"{REAL_THRESHOLD:.4f}" in text
    assert REAL_THRESHOLD == pytest.approx(0.45)
