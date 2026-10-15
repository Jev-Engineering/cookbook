"""Tests for recipe 49's helpers. They load the helpers by file path.

The constraint fuzz and its mutation proofs live in ``tests/test_constraints.py``, not here:
the recipe guard's strong-form check walks THIS file's own
``test_stored_answers_are_not_all_right`` function body as text, scanning forward to the next
top-level ``def``/``class`` to find where it ends. A decorated test function placed immediately
after it would fold the decorator line into that scan (a decorator is neither ``def`` nor
``class``), and parsing the result can raise on otherwise-unrelated source. So this file keeps
the strong-form test last, and nothing that needs a decorator anywhere near it.
"""

import importlib.util
from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def _load_build_fixtures():
    """Load build_fixtures.py by file path (never ``import build_fixtures``: it is not on
    ``sys.path`` under pytest's import mode, and every recipe has a module of that name)."""
    spec = importlib.util.spec_from_file_location(
        "recipe49_build_fixtures_for_helpers_test", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert set(questions) == {"suitability"}
    question = questions["suitability"]
    assert list(question.criteria) == [
        helpers.UNSUITABLE,
        helpers.TANGENTIAL,
        helpers.UNPROVEN_FIT,
        helpers.STRONG_FIT,
        helpers.IDEAL_FIT,
    ]
    # Dependency and budget are structured data Python already has; Jev is never asked about
    # either, or about a specific skill tag ("code", "docs", "security").
    for forbidden in ("budget", "capacity", "depend", "code", "docs", "security"):
        assert forbidden not in question.instructions.lower()
        for level in question.criteria:
            assert forbidden not in level.lower()


def test_build_state_carries_only_the_two_text_fields():
    fields = {
        "scenario": "validation",
        "agent_id": "nova",
        "subtask_id": "s1-api-schema",
        "agent_profile": "profile text",
        "subtask_description": "description text",
    }
    assert helpers.build_state(fields) == {
        "agent_profile": "profile text",
        "subtask_description": "description text",
    }


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_every_stored_answers_top_choice_matches_its_own_spec():
    # A fixture-building shorthand must never default the field that carries the label. Here
    # that is ROWS' own (gold, shape, peak) tuple: check the committed stored answer's modal
    # level equals the peak the row's spec named, for every scored and demo row.
    bf = _load_build_fixtures()
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    for ident, split, agent_id, subtask_id, _label, _shape, peak in bf.ROWS:
        fields = bf._fields(split, agent_id, subtask_id)
        answer = backend.decide(helpers.build_state(fields), questions)["suitability"]
        assert score_level(answer) == peak, f"{ident}: stored top choice does not match its spec"


def test_review_is_the_glossary_spelling():
    assert helpers.REVIEW == "review"


def test_the_confidence_gate_reason_is_exact():
    assert helpers.BELOW_CONFIDENCE_THRESHOLD == "confidence below the threshold"


def test_topological_order_respects_every_dependency():
    for _agents, subtasks in (
        (helpers.VALIDATION_AGENTS, helpers.VALIDATION_SUBTASKS),
        (helpers.TEST_AGENTS, helpers.TEST_SUBTASKS),
    ):
        order = helpers.topological_order(subtasks)
        position = {s.id: i for i, s in enumerate(order)}
        assert set(position) == {s.id for s in subtasks}
        for subtask in subtasks:
            for dep in subtask.depends_on:
                assert position[dep] < position[subtask.id]


def test_topological_order_rejects_a_cycle():
    a = helpers.Subtask("a", "code", 1, ("b",), "")
    b = helpers.Subtask("b", "code", 1, ("a",), "")
    with pytest.raises(ValueError, match="cycle"):
        helpers.topological_order((a, b))


def test_gold_best_agent_is_derived_from_labels_not_authored_separately():
    labels = load_labels(RECIPE)
    gold_levels = {
        (e.fields["agent_id"], e.fields["subtask_id"]): labels[e.id]
        for e in load_inputs(RECIPE)
        if e.id in labels
    }
    # s1-api-schema: nova=4 is the highest gold level among the capable agents (nova, iris,
    # orin, zephyr); wren and sable hold no "code" skill and are correctly excluded.
    assert (
        helpers.gold_best_agent("s1-api-schema", helpers.VALIDATION_AGENTS, gold_levels) == "nova"
    )


def test_gold_best_agent_returns_none_with_no_capable_agent():
    gold_levels = {("nova", "d1-security-review"): 3, ("zephyr", "d1-security-review"): 2}
    assert (
        helpers.gold_best_agent("d1-security-review", helpers.VALIDATION_AGENTS, gold_levels)
        is None
    )


def test_assign_by_capacity_spends_no_requests_and_respects_capability_and_budget():
    out = helpers.assign_by_capacity(helpers.VALIDATION_AGENTS, helpers.VALIDATION_SUBTASKS)
    by_id = helpers.agents_by_id(helpers.VALIDATION_AGENTS)
    by_sub = helpers.subtasks_by_id(helpers.VALIDATION_SUBTASKS)
    used = {}
    for subtask_id, agent_id in out.items():
        if agent_id is None:
            continue
        assert by_sub[subtask_id].required_skill in by_id[agent_id].skills
        used[agent_id] = used.get(agent_id, 0) + by_sub[subtask_id].cost
    for agent_id, spent in used.items():
        assert spent <= by_id[agent_id].capacity


def test_stored_answers_are_not_all_right():
    # The strong form (G1(c)): re-derive the confidence threshold from `validation`'s pair-level
    # correctness (does Jev's modal suitability level match the gold level for that pair?) and
    # require a `test` pair that is both wrong and confident enough to clear the gate -- a
    # mistake the frozen threshold would still let through, which is what evaluating on `test`
    # is for. A wrong answer anywhere is a weak guard (it would pass even if the gate caught
    # every mistake); this binds the assertion to the threshold itself.
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        return backend.decide(helpers.build_state(example.fields), questions)["suitability"]

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: decide(e) for e in validation}
    correct = [score_level(val_answers[e.id]) == labels[e.id] for e in validation]
    confidence = [val_answers[e.id].confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.9)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = [
        e.id
        for e in test
        if score_level(decide(e)) != labels[e.id] and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
