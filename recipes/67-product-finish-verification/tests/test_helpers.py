"""Policies, request boundaries, baseline independence and the accepted failure case."""

import ast
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    DecisionResult,
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


def result(probabilities=None, distribution=(1, 0, 0, 0, 0)):
    probabilities = probabilities or dict.fromkeys(helpers.PROPOSITIONS, 0.99)
    answers = {name: NoulAnswer(p, Provenance.synthetic()) for name, p in probabilities.items()}
    answers["severity"] = ScoreAnswer.from_probabilities(
        distribution, helpers.RUBRIC, Provenance.synthetic()
    )
    return DecisionResult(answers, "synthetic")


FIELDS = {"reference": "present", "candidate": "present"}


def test_approval_requires_all_independent_propositions_and_the_score_gate():
    assert helpers.route(FIELDS, result(), 0.76).outcome == "approve"
    for name in helpers.PROPOSITIONS:
        for p in (0.0, 0.49, 0.5, 0.7):
            probabilities = dict.fromkeys(helpers.PROPOSITIONS, 0.99)
            probabilities[name] = p
            assert helpers.route(FIELDS, result(probabilities), 0.76).outcome == "review"
    for distribution in ((0, 0, 0, 1, 0), (0.2, 0.2, 0.2, 0.2, 0.2)):
        assert helpers.route(FIELDS, result(distribution=distribution), 0).outcome == "review"


def test_missing_reference_incomplete_answers_and_budget_failure_cannot_approve():
    assert helpers.route({"reference": None}, result(), 0).outcome == "review"
    assert helpers.route(FIELDS, None, 0).outcome == "review"
    assert helpers.route(FIELDS, result({"color_family_match": 1.0}), 0).outcome == "review"
    assert helpers.route(FIELDS, result(), None).outcome == "review"


def test_baseline_with_no_feasible_validation_policy_reviews_even_identical_pixels():
    policy = helpers.select_baseline(
        [(0.0, 0.0)], [False], objective="zero_false_approvals_then_coverage"
    )
    assert policy is None
    assert helpers.baseline_route((0.0, 0.0), policy) == "review"


def test_threshold_and_severity_boundaries_are_inclusive():
    clear = result(dict.fromkeys(helpers.PROPOSITIONS, 0.88))
    certainty = helpers.certainty(clear)
    assert certainty == pytest.approx(0.76)
    assert helpers.route(FIELDS, clear, certainty).outcome == "approve"
    assert helpers.route(FIELDS, clear, certainty + 1e-9).outcome == "review"
    at_limit = result(distribution=(0.25, 0.75, 0, 0, 0))
    beyond = result(distribution=(0.249, 0.751, 0, 0, 0))
    assert helpers.route(FIELDS, at_limit, 0).outcome == "approve"
    assert helpers.route(FIELDS, beyond, 0).outcome == "review"


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_thresholds_are_rejected(threshold):
    with pytest.raises(ValueError, match="threshold"):
        helpers.route(FIELDS, result(), threshold)


class CountingBackend:
    def __init__(self):
        self.calls = []

    def decide(self, state, questions, *, assets):
        self.calls.append((state, questions, assets))
        return result()


def test_budget_cache_missing_reference_and_simulated_action_interlocks():
    examples = load_inputs(RECIPE)
    available = [e for e in examples if e.fields["reference"]]
    absent = next(e for e in examples if e.fields["reference"] is None)
    backend = CountingBackend()
    run = helpers.InspectionRun(backend, RECIPE, max_requests=1)
    assert run.decide(absent) is None
    first = run.decide(available[0])
    assert run.decide(available[0]) is first
    assert run.decide(available[1]) is None
    assert run.requests == len(backend.calls) == 1
    run.apply(available[0], first, 0.76)
    run.apply(available[0], first, 0.76)
    run.apply(available[1], None, 0.76)
    run.apply(absent, result(), 0.76)
    assert len(run.actions) == 1
    assert len(run.reviews) == 2
    assert all(entry["executed"] is False for entry in run.actions.to_dicts())


def test_notebook_request_count_is_24_even_with_redisplays():
    backend = CountingBackend()
    run = helpers.InspectionRun(backend, RECIPE)
    for _ in range(2):
        for example in load_inputs(RECIPE):
            run.decide(example)
    assert run.requests == len(backend.calls) == 24
    assert all(len(questions) == 5 and len(assets) == 2 for _, questions, assets in backend.calls)


def test_every_replay_key_matches_and_state_never_contains_gold_or_renderer_metadata():
    for example in load_inputs(RECIPE):
        if example.fields["reference"] is None:
            assert example.replay_keys == ()
            continue
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert set(state) == {"task", "reference", "candidate"}
        assert all(state[role].startswith("image:sha256:") for role in ("reference", "candidate"))
        poisoned = dict(example.fields, gold="approve", split="test", seed=0, material="wood")
        assert helpers.build_state(poisoned, RECIPE) == state


def test_pixels_and_context_affect_replay_identity_and_cache(tmp_path):
    examples = load_inputs(RECIPE)
    e = next(e for e in examples if e.fields["reference"])
    fields = {}
    for role in ("reference", "candidate"):
        path = tmp_path / f"{role}.png"
        path.write_bytes((RECIPE / e.fields[role]).read_bytes())
        fields[role] = path.name
    sample = SimpleNamespace(id=e.id, fields=fields)
    backend = CountingBackend()
    run = helpers.InspectionRun(backend, tmp_path)
    run.decide(sample)
    state, questions, assets = helpers.build_request(fields, tmp_path)
    original = replay_key(state, questions, assets=assets)
    changed_state = dict(state, task="Compare only the left enclosure surface.")
    assert replay_key(changed_state, questions, assets=assets) != original
    with Image.open(tmp_path / fields["candidate"]) as image:
        changed = image.copy()
    changed.putpixel((190, 160), (255, 0, 0))
    changed.save(tmp_path / fields["candidate"])
    new_state, new_questions, new_assets = helpers.build_request(fields, tmp_path)
    assert replay_key(new_state, new_questions, assets=new_assets) != original
    run.decide(sample)
    assert len(backend.calls) == 2


def test_independent_image_lineages_and_pixels_do_not_cross_splits():
    source = (RECIPE / "build_fixtures.py").read_text("utf-8")
    assignment = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "ROWS" for t in node.targets)
    )
    rows = ast.literal_eval(assignment.value)
    lineage_seeds = {
        split: {row[2] for row in rows if row[1] == split} for split in ("validation", "test")
    }
    assert len(lineage_seeds["validation"]) == len(lineage_seeds["test"]) == 12
    assert not lineage_seeds["validation"] & lineage_seeds["test"]
    hashes = {"validation": set(), "test": set()}
    for example in load_inputs(RECIPE):
        if example.split not in hashes:
            continue
        for path in example.fields.values():
            if path is not None:
                with Image.open(RECIPE / path) as image:
                    assert image.size == (384, 320)
                    hashes[example.split].add(hashlib.sha256(image.tobytes()).hexdigest())
    assert len(hashes["validation"]) == len(hashes["test"]) == 23
    assert not hashes["validation"] & hashes["test"]


def test_baseline_uses_pixels_not_labels_ids_paths_or_drawing_metadata(tmp_path):
    example = load_inputs(RECIPE)[0]
    distances = helpers.baseline_distances(example.fields, RECIPE)
    fields = dict(example.fields, label=False, material="wood", color="red", split="test", seed=9)
    assert helpers.baseline_distances(fields, RECIPE) == distances
    for role in ("reference", "candidate"):
        renamed = tmp_path / f"arbitrary-{role}.png"
        renamed.write_bytes((RECIPE / fields[role]).read_bytes())
        fields[role] = renamed.name
    assert helpers.baseline_distances(fields, tmp_path) == distances
    Image.new("RGB", (384, 320), (244, 244, 240)).save(tmp_path / fields["candidate"])
    assert helpers.baseline_distances(fields, tmp_path) is None
    assert helpers.baseline_route(None, (1000, 1000)) == "review"


def test_stored_answers_are_not_all_right():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    run = helpers.InspectionRun(get_backend(fixtures=responses_path(RECIPE)), RECIPE)
    eligible = [
        (e, run.decide(e))
        for e in examples
        if e.split == "validation"
        and helpers.route(e.fields, run.decide(e), 0).outcome == "approve"
    ]
    threshold = select_confidence_threshold(
        [labels[e.id]["acceptable"] for e, _ in eligible],
        [helpers.certainty(r) for _, r in eligible],
        target_accuracy=1.0,
    )
    assert threshold == pytest.approx(0.76)
    mistakes = [
        e.id
        for e in examples
        if e.split == "test"
        and not labels[e.id]["acceptable"]
        and helpers.route(e.fields, run.decide(e), threshold).outcome == "approve"
        and helpers.certainty(run.decide(e)) >= threshold
    ]
    assert "t05" in mistakes


def test_threshold_objective_is_pinned_to_the_committed_call_source():
    nb = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "".join(next(c for c in nb["cells"] if c["id"] == "python-rule")["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords} == {"target_accuracy": 1.0}
    baseline_source = inspect.getsource(helpers.select_baseline)
    assert 'objective != "zero_false_approvals_then_coverage"' in baseline_source
    assert "a and not ok" in baseline_source
    assert "(-row[0], row[1])" in baseline_source


def test_actual_review_flags_define_coverage_and_unresolved_cases_are_not_approvals():
    labels = [{"acceptable": True}, {"acceptable": False}, {"acceptable": False}]
    metrics = helpers.report_outcomes(["approve", "review", "review"], labels)
    assert metrics["approved"] == 1
    assert metrics["review"] == 2
    assert metrics["coverage"] == pytest.approx(1 / 3, abs=0.0001)
    assert metrics["approved_accuracy"] == 1
    assert metrics["false_approvals"] == 0
