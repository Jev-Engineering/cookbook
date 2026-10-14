"""Tests for recipe 46's helpers. They load the helpers by file path."""

import json
import random
from pathlib import Path

import pytest

from jev_cookbook import Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import Store

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

# The confidence-gate objective. Must match the notebook's own call
# (select_confidence_threshold(..., min_coverage=MIN_COVERAGE)) -- see
# test_the_notebook_pins_the_min_coverage_objective_in_its_own_source below, which checks the
# committed notebook cell actually spells this, rather than trusting this comment.
MIN_COVERAGE = 0.85

_TIER_DECAY = {"high": 0.08, "medium": 0.35, "low": 0.5}


def _level_probs(peak: int, tier: str) -> list[float]:
    decay = _TIER_DECAY[tier]
    raw = [decay ** abs(i - peak) for i in range(4)]
    total = sum(raw)
    return [r / total for r in raw]


def _answer(peak: int, tier: str) -> ScoreAnswer:
    return ScoreAnswer.from_probabilities(
        _level_probs(peak, tier), list(helpers.RELEVANCE_LEVELS), Provenance.synthetic()
    )


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"relevance"}
    assert list(questions["relevance"].criteria) == [
        "The chunk has nothing to do with the current task: a different file, ticket, person, "
        "or topic than the task names. Nothing in it bears on the task at all.",
        "The chunk is about the same file, ticket, or topic as the task, but it does not state "
        "anything the task's own answer or action depends on.",
        "The chunk states something the task's answer or action depends on, but only part of "
        "it: a reader also needs another chunk to complete the task correctly.",
        "The chunk states, on its own, the specific fact, value, or step the task's answer or "
        "action depends on. Nothing else is needed to act on it correctly.",
    ]
    assert helpers.RETENTION_CUTOFF == 2
    assert helpers.BUDGET_SLOTS == 3


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate
    # caught every mistake. This mirrors the notebook's own threshold selection (min_coverage,
    # the same objective, over every validation example) and requires a wrong `test` answer at
    # or above it: a mistake the gate would still let through, which is what evaluating on
    # `test` exists to catch.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    name = next(iter(questions))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)[name]

    def predicted(answer):
        # A Score's own gold label is a level, so compare against score_level(answer) (the
        # most probable level), never answer.score (the probability-weighted expected value).
        return score_level(answer)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [predicted(val_answers[e.id]) == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=MIN_COVERAGE)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if predicted(decide(e)) != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


# --------------------------------------------------------------------------------------------
# classify_chunk: a grid of synthesized Score answers across every rubric level and a spread of
# confidences, not only the committed fixtures (the brief's own words: "driven by synthesised
# Score answers across the rubric levels and a grid of confidences").
#
# test_classify_chunk_rejects_a_gate_outside_zero_one is deliberately placed here, immediately
# after the strong-form test above and before the first @pytest.mark.parametrize-decorated
# function below: the recipe guard's own text-based function-body extraction
# (tests/test_recipe_guard.py::_find_function_body) stops at the next line matching
# r"\n(?:def |class )" and does not recognise a decorator line, so a strong-form test whose very
# next function in the file is decorated has its decorators folded into the extracted body,
# which fails to parse as Python. Keeping an undecorated def between them avoids that guard
# limitation without touching shared test code.
# --------------------------------------------------------------------------------------------


def test_classify_chunk_rejects_a_gate_outside_zero_one():
    answer = _answer(3, "high")
    with pytest.raises(ValueError):
        helpers.classify_chunk("x", answer, -0.1)
    with pytest.raises(ValueError):
        helpers.classify_chunk("x", answer, 1.1)


@pytest.mark.parametrize("confidence_gate", [0.0, 0.25, 0.4815, 0.6, 0.85, 1.0])
@pytest.mark.parametrize("peak", [0, 1, 2, 3])
@pytest.mark.parametrize("tier", ["high", "medium", "low"])
def test_classify_chunk_outcome_matches_the_gate_and_cutoff_on_a_grid(confidence_gate, peak, tier):
    answer = _answer(peak, tier)
    result = helpers.classify_chunk("x", answer, confidence_gate)
    assert result.level == peak
    if answer.confidence < confidence_gate:
        assert result.outcome == helpers.REVIEW
        assert result.reason == "confidence below the threshold"
    elif peak < helpers.RETENTION_CUTOFF:
        assert result.outcome == helpers.PAGED_OUT
    else:
        assert result.outcome == helpers.CANDIDATE


# --------------------------------------------------------------------------------------------
# allocate_budget: the budget is never exceeded, for any model answer. Fuzzed with random
# probability vectors (not only the committed fixtures) and checked over every fixture task too.
# --------------------------------------------------------------------------------------------


def _random_answer(rng: random.Random) -> ScoreAnswer:
    raw = [rng.random() + 0.01 for _ in range(4)]
    total = sum(raw)
    return ScoreAnswer.from_probabilities(
        [r / total for r in raw], list(helpers.RELEVANCE_LEVELS), Provenance.synthetic()
    )


def test_allocate_budget_never_exceeds_its_slots_for_any_model_answer():
    rng = random.Random(20261014)
    chunk_ids = [f"c{i}" for i in range(8)]
    for _ in range(300):
        answers = {cid: _random_answer(rng) for cid in chunk_ids}
        classifications = [
            helpers.classify_chunk(cid, a, confidence_gate=0.3) for cid, a in answers.items()
        ]
        expected_scores = {cid: a.score for cid, a in answers.items()}
        decisions, budget = helpers.allocate_budget(classifications, expected_scores, {}, slots=3)
        assert budget.used("slots") <= 3
        assert sum(1 for d in decisions if d.status == helpers.RETAINED) == budget.used("slots")
        assert {d.chunk_id for d in decisions} == set(chunk_ids)


def test_allocate_budget_never_exceeds_slots_over_every_fixture_task():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    by_task: dict[str, list] = {}
    for e in examples:
        if e.id in labels:
            by_task.setdefault(e.fields["task_id"], []).append(e)
    assert len(by_task) >= 10  # a mutation can't silently shrink this to nothing checked
    for texamples in by_task.values():
        answers = {
            e.fields["chunk_id"]: backend.decide(helpers.build_state(e.fields), questions)[
                "relevance"
            ]
            for e in texamples
        }
        classifications = [helpers.classify_chunk(cid, a, 0.0) for cid, a in answers.items()]
        expected_scores = {cid: a.score for cid, a in answers.items()}
        decisions, budget = helpers.allocate_budget(
            classifications, expected_scores, {}, slots=helpers.BUDGET_SLOTS
        )
        assert budget.used("slots") <= helpers.BUDGET_SLOTS


def test_allocate_budget_pages_out_the_lowest_scored_candidates_first():
    """A budget that actually binds: with four candidates and three slots, the lowest-scored
    candidate is the one paged out, ties broken by chunk_id -- not an arbitrary subset, and not
    "whatever came first"."""
    scored = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6}
    classifications = [
        helpers.Classification(cid, 3, helpers.CANDIDATE, "modal level clears the retention cutoff")
        for cid in scored
    ]
    decisions, budget = helpers.allocate_budget(classifications, scored, {}, slots=3)
    by_id = {d.chunk_id: d.status for d in decisions}
    assert by_id == {
        "a": helpers.RETAINED,
        "b": helpers.RETAINED,
        "c": helpers.RETAINED,
        "d": helpers.PAGED_OUT,
    }
    assert budget.used("slots") == 3

    # Prove the pin can fail: raising d's score above c's must move the paged-out chunk.
    scored_tied_up = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.75}
    decisions2, _ = helpers.allocate_budget(classifications, scored_tied_up, {}, slots=3)
    by_id2 = {d.chunk_id: d.status for d in decisions2}
    assert by_id2["c"] == helpers.PAGED_OUT
    assert by_id2["d"] == helpers.RETAINED


def test_allocate_budget_rejects_fewer_than_one_slot():
    with pytest.raises(ValueError):
        helpers.allocate_budget([], {}, {}, slots=0)


# --------------------------------------------------------------------------------------------
# content_preserved: only `status` may change between writes to the same key.
# --------------------------------------------------------------------------------------------


def test_content_preserved_detects_a_content_change():
    store = Store()
    store.put("x", {"content": "hello", "source": "s1", "status": "retained"}, writer="w", step=0)
    store.put("x", {"content": "hello", "source": "s1", "status": "paged_out"}, writer="w", step=1)
    assert helpers.content_preserved(store.history("x"))
    # Prove the check can fail: a write that changes content must be caught.
    store.put(
        "x", {"content": "DIFFERENT", "source": "s1", "status": "retained"}, writer="w", step=2
    )
    assert not helpers.content_preserved(store.history("x"))


def test_content_preserved_detects_a_source_change():
    store = Store()
    store.put("x", {"content": "hello", "source": "s1", "status": "retained"}, writer="w", step=0)
    store.put("x", {"content": "hello", "source": "s2", "status": "retained"}, writer="w", step=1)
    assert not helpers.content_preserved(store.history("x"))


def test_content_preserved_rejects_empty_history():
    with pytest.raises(ValueError):
        helpers.content_preserved([])


# --------------------------------------------------------------------------------------------
# The stateful session: a round trip through JSON serialisation, over the real fixtures, that
# includes a chunk being paged out and later rehydrated. This is the test the house rules warn
# a recipe can get wrong by comparing a live store object to itself -- it does not: it rebuilds
# a fresh Store from JSON-dumped-and-reloaded write records, and it tampers with that JSON
# before the final assertion to prove the comparison can actually disagree.
# --------------------------------------------------------------------------------------------

SESSION_TASKS = ("s-t1", "s-t2", "s-t3")


def _session_turns(backend, questions):
    examples = load_inputs(RECIPE)
    by_task: dict[str, list] = {}
    for e in examples:
        if e.fields.get("task_id") in SESSION_TASKS:
            by_task.setdefault(e.fields["task_id"], []).append(e)
    turns = []
    for task_id in SESSION_TASKS:
        turn = []
        for e in by_task[task_id]:
            answer = backend.decide(helpers.build_state(e.fields), questions)["relevance"]
            chunk = {"content": e.fields["chunk"], "source": e.fields["source"]}
            turn.append((e.fields["chunk_id"], chunk, answer))
        turns.append(turn)
    return turns


def _validation_gate(backend, questions):
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    answers = {
        e.id: backend.decide(helpers.build_state(e.fields), questions)["relevance"]
        for e in validation
    }
    correct = [score_level(answers[e.id]) == labels[e.id] for e in validation]
    confidence = [answers[e.id].confidence for e in validation]
    return select_confidence_threshold(correct, confidence, min_coverage=MIN_COVERAGE)


def test_the_session_round_trips_losslessly_through_serialisation_including_a_rehydration():
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    gate = _validation_gate(backend, questions)
    turns = _session_turns(backend, questions)

    store, per_turn = helpers.run_session(turns, confidence_gate=gate, slots=helpers.BUDGET_SLOTS)
    assert len(per_turn) == 3
    for _decisions, budget in per_turn:
        assert budget.used("slots") <= helpers.BUDGET_SLOTS

    status_by_turn = [{d.chunk_id: d.status for d in decisions} for decisions, _ in per_turn]
    # s-c3 is paged out on the first two turns (its own gold level is only BACKGROUND for the
    # first customer's case) and rehydrated on the third, when the same explanation becomes the
    # reusable evidence a second customer's case depends on.
    assert status_by_turn[0]["s-c3"] == helpers.PAGED_OUT
    assert status_by_turn[1]["s-c3"] == helpers.PAGED_OUT
    assert status_by_turn[2]["s-c3"] == helpers.RETAINED
    rehydrated = [d.chunk_id for d in per_turn[2][0] if d.rehydrated]
    assert rehydrated == ["s-c3"]

    all_chunk_ids = {d.chunk_id for decisions, _ in per_turn for d in decisions}
    assert all_chunk_ids == {"s-c1", "s-c2", "s-c3", "s-c4", "s-c5", "s-c6"}
    for chunk_id in all_chunk_ids:
        assert helpers.content_preserved(store.history(chunk_id))

    # Serialise through actual JSON text, then rebuild a fresh Store from that text alone.
    dumped = json.loads(json.dumps(store.to_dicts()))
    rebuilt = helpers.rebuild_store(dumped)
    assert rebuilt.snapshot() == store.snapshot()
    for chunk_id in all_chunk_ids:
        original = [r.to_dict() for r in store.history(chunk_id)]
        reconstructed = [r.to_dict() for r in rebuilt.history(chunk_id)]
        assert reconstructed == original
        assert helpers.content_preserved(rebuilt.history(chunk_id))

    # Prove the round trip can detect a loss: tamper with one serialised record's content before
    # rebuilding, and confirm the rebuilt store disagrees with the original on that key.
    tampered = json.loads(json.dumps(store.to_dicts()))
    for record in tampered:
        if record["key"] == "s-c3" and record["step"] == 2:
            record["value"]["content"] = "TAMPERED"
    tampered_store = helpers.rebuild_store(tampered)
    assert tampered_store.get("s-c3")["content"] != store.get("s-c3")["content"]
    assert tampered_store.snapshot() != store.snapshot()


# --------------------------------------------------------------------------------------------
# Pin the confidence-gate objective, two ways. A printed f-string literal or a pinned numeric
# RESULT is not a pin on its own: nothing compares the printed text to the real call, and the
# gate's own value is reachable by more than one objective. What holds is (1) the committed
# notebook cell's own SOURCE spells the objective, so a keyword or value swap there is a diff a
# reader sees, and (2) a measured response over a grid of candidate values, so the pinned value
# is shown to be one point on a real (not flat-everywhere) curve rather than an arbitrary choice
# nothing would have caught moving.
# --------------------------------------------------------------------------------------------


def _notebook_cell_source(cell_id: str) -> str:
    nb = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    for cell in nb["cells"]:
        if cell.get("id") == cell_id:
            source = cell["source"]
            return "".join(source) if isinstance(source, list) else source
    raise AssertionError(f"no cell with id {cell_id!r} in the committed notebook")


def test_the_notebook_pins_the_min_coverage_objective_in_its_own_source():
    # The source-spelling pin: parse the actual committed cell, not a copy of it kept here. A
    # keyword swap (to target_accuracy=...) or a value swap (to a different min_coverage) in the
    # notebook changes this cell's source and so fails this assertion -- proved by mutation
    # directly below, on a copy of the same text, rather than merely asserted.
    source = _notebook_cell_source("python-rule")
    assert f"min_coverage={MIN_COVERAGE}" in source

    # Prove the pin can fail: a keyword swap and a value swap must both be visible as a changed
    # source, which is what "the committed cell's source spells the objective" is a claim about.
    pinned = f"min_coverage={MIN_COVERAGE}"
    keyword_swapped = source.replace(pinned, "target_accuracy=1.0")
    assert pinned not in keyword_swapped
    value_swapped = source.replace(pinned, "min_coverage=0.95")
    assert pinned not in value_swapped


def test_the_min_coverage_objective_is_not_flat_everywhere_on_this_pool():
    # The response measurement rule-12's house note asks for: select_confidence_threshold is
    # piecewise constant in general, so a single value-change mutation (0.85 -> some other
    # value) can land in the same flat band and move nothing, which would look like a pin but
    # prove nothing. Measuring a grid shows where this pool's curve actually bends: everything
    # up to 0.93 lands on the same gate and numbers as 0.85 (the pinned value is not special
    # within that band), and crossing 0.9333 (the coverage the two low-confidence validation
    # rows would cost if excluded) moves the gate, the coverage and the accuracy together.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    answers = {
        e.id: backend.decide(helpers.build_state(e.fields), questions)["relevance"]
        for e in validation
    }
    correct = [score_level(answers[e.id]) == labels[e.id] for e in validation]
    confidence = [answers[e.id].confidence for e in validation]

    seen = {}
    for min_coverage in (0.5, 0.7, 0.85, 0.9, 0.93, 0.95, 0.97, 1.0):
        gate = select_confidence_threshold(correct, confidence, min_coverage=min_coverage)
        seen[min_coverage] = round(gate, 4)

    # The pinned value (0.85) and everything below the real bend (0.93) agree with it.
    for min_coverage in (0.5, 0.7, 0.85, 0.9, 0.93):
        assert seen[min_coverage] == seen[MIN_COVERAGE]
    # Past the bend, the gate genuinely moves: this is the measurement that would have caught a
    # flat-everywhere pool, which a single mutation (rule 12's house note) cannot rule out alone.
    for min_coverage in (0.95, 0.97, 1.0):
        assert seen[min_coverage] != seen[MIN_COVERAGE]
