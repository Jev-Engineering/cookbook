"""Tests for recipe 34's helpers. They load the helpers by file path."""

import importlib.util
import json
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

EXPECTED_OPTIONS = (
    "works_for",
    "founder_of",
    "acquired_by",
    "supplier_of",
    "no_supported_relation",
)


def test_the_notebook_selects_the_gate_by_min_coverage_not_target_accuracy():
    """The frozen gate's objective is chosen once, in the notebook's own `python-threshold`
    cell, by calling ``select_confidence_threshold(..., min_coverage=MIN_COVERAGE)``. Nothing
    ties a notebook cell's source to an importable value, so an edit that swapped only that
    call to ``target_accuracy=1.0`` -- which is feasible on this validation pool and returns a
    real threshold, forcing validation accuracy to 1.0000 by construction -- would otherwise
    leave every other test in this file green while the notebook ran a different selection than
    the one these tests describe. Parse the committed notebook's cell directly and pin both the
    objective and its keyword, not just the pinned constant's value."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-threshold")
    source = "".join(cell["source"])
    assert "min_coverage=MIN_COVERAGE" in source
    assert "target_accuracy" not in source
    assert helpers.MIN_COVERAGE == pytest.approx(0.85)


def test_options_are_the_fixed_set_the_use_case_names():
    # A literal expected tuple, not helpers' own OPTIONS compared to itself: this would fail if
    # a later edit silently reordered or renamed an option.
    assert helpers.OPTIONS == EXPECTED_OPTIONS
    assert helpers.RELATIONS == EXPECTED_OPTIONS[:-1]
    assert helpers.OPTIONS[-1] == helpers.NO_SUPPORTED_RELATION


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"relation"}
    relation = questions["relation"]
    assert tuple(relation.criteria) == EXPECTED_OPTIONS
    assert all(isinstance(text, str) and text for text in relation.criteria.values())
    assert isinstance(relation.instructions, str) and relation.instructions


def test_build_state_keeps_the_two_entity_names_and_the_passage_and_nothing_else():
    fields = {"pair_id": "p99", "entity_a": "A Co", "entity_b": "B Co", "passage": "A and B."}
    state = helpers.build_state(fields)
    assert state == {"entity_a": "A Co", "entity_b": "B Co", "passage": "A and B."}
    assert "pair_id" not in state


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. Every task example lists
    # one key per evidence passage, in the order helpers.passage_states yields them.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        expected = tuple(
            replay_key(state, questions)
            for _passage_id, state in helpers.passage_states(example.fields)
        )
        assert example.replay_keys == expected


def _load_build_fixtures():
    """Import build_fixtures.py by file path so its ROWS are plain Python objects, independent
    of what main() actually wrote to disk."""
    path = RECIPE / "build_fixtures.py"
    spec = importlib.util.spec_from_file_location("recipe34_build_fixtures_for_helpers_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_stored_answers_top_choice_is_the_one_its_row_names():
    # Rule: in any fixture-spec shorthand, the label-bearing argument is required, never
    # defaulted. build_fixtures.py's ``_passage`` takes ``predicted`` as a required positional
    # argument and ``_probs`` puts the given ``p_top`` on exactly that option, so this checks the
    # generator's own spec did not silently mislabel a row: for every passage in every row of
    # ``ROWS``, the choice ``ChoiceAnswer.from_probabilities`` derives from that row's own
    # ``probs`` (independent of whatever ``build_responses`` happens to do with them) equals
    # the row's ``predicted``, never its ``gold`` (which may legitimately differ -- that is how
    # a deliberately wrong stored answer is written). This checks the generator's spec, not the
    # committed ``fixtures/responses.json`` file itself; that file's byte-identity to what this
    # same ``ROWS`` produces is what ``tests/test_build_fixtures.py`` separately guards, so the
    # two tests together cover both halves.
    module = _load_build_fixtures()
    assert len(module.ROWS) > 1
    checked = 0
    for row in module.ROWS:
        for passage in row["passages"]:
            answer = ChoiceAnswer.from_probabilities(passage["probs"], Provenance.synthetic())
            assert answer.choice == passage["predicted"], passage["passage_id"]
            checked += 1
    assert checked > 1


def test_passage_gold_and_task_gold_read_the_label_record_directly():
    record = {"task": "founder_of", "passages": {"p1": "founder_of", "p2": "no_supported_relation"}}
    assert helpers.task_gold(record) == "founder_of"
    assert helpers.passage_gold(record, "p1") == "founder_of"
    assert helpers.passage_gold(record, "p2") == "no_supported_relation"


# --- classify_passage: the confidence gate -------------------------------------------------


class _Answer:
    def __init__(self, choice, confidence):
        self.choice = choice
        self.confidence = confidence


def test_classify_passage_accepts_at_or_above_the_gate_and_reviews_below_it():
    at_gate = helpers.classify_passage("p1", _Answer("works_for", 0.60), 0.60)
    assert at_gate.outcome == helpers.ACCEPTED
    just_below = helpers.classify_passage("p1", _Answer("works_for", 0.5999), 0.60)
    assert just_below.outcome == helpers.REVIEW
    assert just_below.reason == helpers.REASON_GATE


def test_classify_passage_rejects_an_out_of_range_gate():
    with pytest.raises(ValueError):
        helpers.classify_passage("p1", _Answer("works_for", 0.9), 1.5)
    with pytest.raises(ValueError):
        helpers.classify_passage("p1", _Answer("works_for", 0.9), -0.1)


def test_classify_passage_label_is_whatever_the_answer_named_even_the_fallback():
    # no_supported_relation is a real, reportable label, not treated specially by the gate.
    decision = helpers.classify_passage("p1", _Answer("no_supported_relation", 0.9), 0.5)
    assert decision.outcome == helpers.ACCEPTED
    assert decision.label == "no_supported_relation"


# --- compose_relation: the task-level composition ------------------------------------------


def _decision(passage_id, label, confidence, outcome=None):
    outcome = outcome or (helpers.ACCEPTED if confidence >= 0.5 else helpers.REVIEW)
    reason = "confident match" if outcome == helpers.ACCEPTED else helpers.REASON_GATE
    return helpers.PassageDecision(passage_id, label, confidence, outcome, reason)


def test_compose_relation_needs_at_least_one_decision():
    with pytest.raises(ValueError):
        helpers.compose_relation("p1", ())


def test_compose_relation_one_passage_naming_a_real_relation_is_accepted():
    decisions = (_decision("e1", "founder_of", 0.9),)
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.ACCEPTED
    assert result.label == "founder_of"
    assert result.evidence == ("e1",)


def test_compose_relation_every_accepted_passage_naming_the_fallback_is_accepted_as_fallback():
    decisions = (
        _decision("e1", "no_supported_relation", 0.9),
        _decision("e2", "no_supported_relation", 0.8),
    )
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.ACCEPTED
    assert result.label == "no_supported_relation"
    assert result.evidence == ("e1", "e2")


def test_compose_relation_agreement_across_passages_is_accepted_with_every_agreeing_passage_as_evidence():
    decisions = (
        _decision("e1", "founder_of", 0.9),
        _decision("e2", "founder_of", 0.85),
        _decision("e3", "no_supported_relation", 0.8),
    )
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.ACCEPTED
    assert result.label == "founder_of"
    assert result.evidence == ("e1", "e2")  # e3 named the fallback, not the agreed relation


def test_compose_relation_any_gated_passage_sends_the_whole_task_to_review():
    decisions = (
        _decision("e1", "founder_of", 0.9),
        _decision("e2", "founder_of", 0.2, outcome=helpers.REVIEW),
    )
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.REVIEW
    assert result.label is None
    assert result.reason == helpers.REASON_GATE
    assert result.evidence == ()


def test_compose_relation_disagreement_between_confident_passages_sends_the_task_to_review():
    decisions = (_decision("e1", "founder_of", 0.9), _decision("e2", "works_for", 0.85))
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.REVIEW
    assert result.label is None
    assert result.reason == helpers.REASON_DISAGREE


def test_compose_relation_gate_check_runs_before_the_disagreement_check():
    # Two confident, disagreeing passages plus one gated passage: still a gate review, not a
    # disagreement review, because an unconfident passage is reviewed whatever the others say.
    decisions = (
        _decision("e1", "founder_of", 0.9),
        _decision("e2", "works_for", 0.85),
        _decision("e3", "founder_of", 0.1, outcome=helpers.REVIEW),
    )
    result = helpers.compose_relation("p1", decisions)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_GATE


# --- Consequentiality on the recipe's own committed fixtures --------------------------------
# Rule: every stage is independently consequential, proved on a REAL committed fixture by
# flipping one stored decision and watching the composed outcome change, with each test failing
# for its own cause (never a test helper that reimplements compose_relation).


def _decide_task(example_id, backend, questions, threshold):
    """The real decisions for one committed task, replayed from fixtures/responses.json --
    never hand-built -- gated at ``threshold``."""
    examples = {e.id: e for e in load_inputs(RECIPE)}
    example = examples[example_id]
    decisions = []
    for passage_id, state in helpers.passage_states(example.fields):
        answer = backend.decide(state, questions)["relation"]
        decisions.append(helpers.classify_passage(passage_id, answer, threshold))
    return tuple(decisions)


def test_flipping_the_confidence_gate_changes_the_real_agreement_tasks_composed_outcome():
    # v08-agree is a committed two-passage task whose two real stored answers both agree on
    # founder_of above any reasonable gate. Composing its real decisions accepts founder_of; a
    # gate set just above both of their confidences sends the same real decisions to review
    # instead -- the gate is independently consequential on real data, not only in a synthetic
    # unit test.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    low_decisions = _decide_task("v08-agree", backend, questions, 0.10)
    accepted = helpers.compose_relation("v08-agree", low_decisions)
    assert accepted.outcome == helpers.ACCEPTED
    assert accepted.label == "founder_of"

    confidences = [d.confidence for d in low_decisions]
    high_gate = max(confidences) + 0.001
    high_decisions = _decide_task("v08-agree", backend, questions, high_gate)
    reviewed = helpers.compose_relation("v08-agree", high_decisions)
    assert reviewed.outcome == helpers.REVIEW
    assert reviewed.reason == helpers.REASON_GATE


def test_flipping_one_passages_label_turns_the_real_agreement_task_into_a_disagreement():
    # v08-agree's two real passages both name founder_of. Replacing only the second decision's
    # label (keeping its real, gate-clearing confidence) with a different real relation flips
    # the composed outcome to review-by-disagreement -- proving the disagreement branch is
    # reached by a real passage decision, not only by the synthetic fixtures in the unit tests
    # above.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    decisions = _decide_task("v08-agree", backend, questions, 0.10)
    assert helpers.compose_relation("v08-agree", decisions).label == "founder_of"

    first, second = decisions
    mutated_second = helpers.PassageDecision(
        second.passage_id, "works_for", second.confidence, second.outcome, second.reason
    )
    mutated = helpers.compose_relation("v08-agree", (first, mutated_second))
    assert mutated.outcome == helpers.REVIEW
    assert mutated.reason == helpers.REASON_DISAGREE


# --- The review queue -----------------------------------------------------------------------


class _FakeQueue:
    def __init__(self):
        self.items = []

    def submit(self, item, reason, *, answer=None, step=None):
        self.items.append((item, reason, answer))
        return len(self.items) - 1


class _Example:
    def __init__(self, id, fields):
        self.id = id
        self.fields = fields


def test_submit_reviews_queues_only_the_review_outcomes_with_full_context():
    fields = {"entity_a": "A Co", "entity_b": "B Co", "passages": []}
    accepted = helpers.TaskOutcome(
        "p1",
        "founder_of",
        helpers.ACCEPTED,
        "composed from its evidence",
        ("e1",),
        (_decision("e1", "founder_of", 0.9),),
    )
    reviewed = helpers.TaskOutcome(
        "p2",
        None,
        helpers.REVIEW,
        helpers.REASON_DISAGREE,
        (),
        (_decision("e1", "founder_of", 0.9), _decision("e2", "works_for", 0.85)),
    )
    examples = [_Example("p1", fields), _Example("p2", fields)]
    outcomes = {"p1": accepted, "p2": reviewed}
    queue = _FakeQueue()
    helpers.submit_reviews(queue, examples, outcomes)
    assert len(queue.items) == 1
    item, reason, answer = queue.items[0]
    assert item["pair_id"] == "p2"
    assert reason == helpers.REASON_DISAGREE
    assert len(item["decisions"]) == 2
    assert set(answer) == {"e1", "e2"}


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if the confidence gate
    # caught every mistake. This mirrors the notebook's own threshold selection exactly --
    # select_confidence_threshold(..., min_coverage=helpers.MIN_COVERAGE) over every scored
    # VALIDATION passage (per-question granularity, the gate's own level) -- and requires a
    # wrong TEST passage at or above the frozen gate: a mistake the gate would still let
    # through, which is what evaluating on test exists to catch.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)

    def passage_rows(split):
        rows = []
        for example in load_inputs(RECIPE):
            if example.split != split:
                continue
            for passage_id, state in helpers.passage_states(example.fields):
                answer = backend.decide(state, questions)["relation"]
                gold = helpers.passage_gold(labels[example.id], passage_id)
                rows.append((passage_id, answer, gold))
        return rows

    validation = passage_rows("validation")
    val_correct = [answer.choice == gold for _pid, answer, gold in validation]
    val_confidence = [answer.confidence for _pid, answer, gold in validation]
    threshold = select_confidence_threshold(
        val_correct, val_confidence, min_coverage=helpers.MIN_COVERAGE
    )

    test = passage_rows("test")
    wrong_and_confident = [
        pid
        for pid, answer, gold in test
        if answer.choice != gold and answer.confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test passage"
