"""Policy, image lineage, imperfect held-out answers, and label-free baseline checks."""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import Provenance, ReplayBackend, ScoreAnswer, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, select_split
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def make_answers(peak=3, p=0.96):
    probs = [(1 - p) / 3] * 4
    probs[peak] = p
    return {
        d: ScoreAnswer.from_probabilities(probs, helpers.RUBRIC[d], Provenance.synthetic())
        for d in helpers.DIMENSIONS
    }


@pytest.mark.parametrize("peak", range(4))
@pytest.mark.parametrize("dimension", helpers.DIMENSIONS)
def test_every_dimension_must_clear_gate_even_for_low_style_scores(peak, dimension):
    answers = make_answers(peak)
    answers[dimension] = make_answers(peak, 0.25)[dimension]
    actions, reviews = ActionLog(), ReviewQueue()
    outcome = helpers.dispatch("item", answers, 0.5, actions, reviews)
    assert outcome.outcome == "review" and outcome.combined is None
    assert len(actions) == 0 and len(reviews) == 1
    assert reviews.pending()[0].reason == "confidence below the threshold"


@pytest.mark.parametrize("threshold", [-1, 1.01, float("nan"), float("inf"), None, True])
def test_invalid_policy_is_rejected(threshold):
    with pytest.raises(ValueError):
        helpers.report_scores(make_answers(), threshold)


def test_arithmetic_retains_components_and_reports_no_publication():
    answers = make_answers(0)
    threshold = helpers.min_confidence(answers)
    actions, reviews = ActionLog(), ReviewQueue()
    result = helpers.dispatch("item", answers, threshold, actions, reviews)
    assert result.outcome == "reported"
    assert result.combined == pytest.approx(sum(a.score for a in answers.values()) / 9)
    assert set(result.scores) == set(helpers.DIMENSIONS)
    assert len(reviews) == 0
    assert actions.to_dicts()[0]["executed"] is False
    assert actions.to_dicts()[0]["kind"] == "report_style_scores"
    assert helpers.report_scores(answers, threshold + 0.001).outcome == "review"


def test_missing_malformed_and_wrong_rubric_answers_fail_closed():
    answers = make_answers()
    assert helpers.report_scores({}, 0).outcome == "review"
    answers["surface"] = SimpleNamespace(score=3, confidence=1)
    assert helpers.report_scores(answers, 0).outcome == "review"
    answers["surface"] = ScoreAnswer.from_probabilities(
        [0, 1], ["low", "high"], Provenance.synthetic()
    )
    assert helpers.report_scores(answers, 0).outcome == "review"


def replay():
    examples = load_inputs(RECIPE)
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    cache = helpers.RequestCache(backend, RECIPE)
    return examples, load_labels(RECIPE), cache


def test_stored_answers_are_not_all_right():
    examples, labels, cache = replay()
    validation = select_split(examples, "validation")
    answers = [cache.decide(e).answers for e in validation]
    threshold = select_confidence_threshold(
        [helpers.agrees(a, labels[e.id]) for e, a in zip(validation, answers, strict=True)],
        [helpers.min_confidence(a) for a in answers],
        target_accuracy=1.0,
    )
    heldout = select_split(examples, "test")
    heldout_answers = [cache.decide(e).answers for e in heldout]
    accepted_wrong = [
        not helpers.agrees(a, labels[e.id])
        and helpers.min_confidence(a) >= threshold
        and helpers.report_scores(a, threshold).outcome == "reported"
        for e, a in zip(heldout, heldout_answers, strict=True)
    ]
    assert any(accepted_wrong)
    assert any(helpers.report_scores(a, threshold).outcome == "review" for a in heldout_answers)


def test_threshold_objective_is_pinned_to_committed_call():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-policy")
    tree = ast.parse("".join(cell["source"]))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords} == {"target_accuracy": 1.0}


def test_all_images_valid_unique_across_splits_and_reference_examples_independent():
    examples, _, _ = replay()
    seen = set()
    for e in examples:
        path = RECIPE / e.fields["image"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest not in seen
        seen.add(digest)
        assert image_asset(path)["format"] == "png"
        with Image.open(path) as image:
            assert image.size == (480, 360)
    refs = [
        hashlib.sha256((RECIPE / path).read_bytes()).hexdigest()
        for path in examples[0].fields["moodboard"]
    ]
    assert len(set(refs)) == 3
    assert not set(refs) & seen


def test_request_excludes_gold_seed_split_and_uses_images_inside_score_criteria():
    examples, _, _ = replay()
    e = examples[0]
    fields = {**e.fields, "gold": [0, 0, 0], "seed": 123, "split": "test", "variant": "foreign"}
    state, questions, assets = helpers.build_request(fields, RECIPE)
    assert set(state) == {"candidate_image", "art_direction"}
    assert len(assets) == 4
    for q in questions.values():
        assert len(q.criteria) == 4
        refs = q.criteria[3]["moodboard_examples"]
        assert len(refs) == 3 and all(r in assets for r in refs)
        assert state["candidate_image"] not in refs
        assert all(level["observable_level"] for level in q.criteria)
    assert replay_key(state, questions, assets=assets) == e.replay_keys[0]


def test_state_reference_and_candidate_pixel_identity_change_replay(tmp_path):
    examples, _, _ = replay()
    state, questions, assets = helpers.build_request(examples[0].fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    assert (
        replay_key({**state, "art_direction": "different brief"}, questions, assets=assets)
        != original
    )
    for ref in list(assets):
        # Keep the same opaque name: changing bytes must still alter the replay identity.
        with Image.open(RECIPE / examples[0].fields["image"]) as image:
            modified = image.copy()
        modified.putpixel((0, 0), (1, 2, 3))
        path = tmp_path / "changed.png"
        modified.save(path)
        changed = dict(assets)
        changed[ref] = image_asset(path)
        assert replay_key(state, questions, assets=changed) != original
        assert image_reference(changed[ref]) != ref


def test_baseline_reads_same_pixels_and_ignores_labels_and_variant_names():
    examples, _, _ = replay()
    first = examples[0].fields
    actual = helpers.baseline(first, RECIPE)
    poisoned = {**first, "levels": [0, 0, 0], "label": "foreign", "seed": -1, "split": "test"}
    assert helpers.baseline(poisoned, RECIPE) == actual
    foreign = next(e for e in examples if e.id == "v12")
    assert helpers.baseline(foreign.fields, RECIPE) != actual


def test_review_is_excluded_and_undefined_is_not_given_fake_zero_gold():
    result = helpers.summarize(
        [{"levels": [3, 3, 3]}, {"levels": None}],
        [[3, 3, 3], [3, 3, 3]],
        [[3, 3, 3], [3, 3, 3]],
        [True, False],
    )
    assert result["N"] == 2 and result["N_defined"] == 1
    assert result["coverage"] == 0.5 and result["agreement_reported"] == 1
    assert result["dimensions"]["palette"]["mae"] == 0
    accepted = helpers.summarize(
        [{"levels": [3, 3, 3]}, {"levels": None}],
        [[3, 3, 3], [3, 3, 3]],
        [[3, 3, 3], [3, 3, 3]],
        [True, True],
    )
    assert accepted["accepted_undefined"] == 1 and accepted["agreement_reported"] == 0.5


def test_cache_and_budget_bound_requests():
    examples, _, _ = replay()

    class CountingBackend:
        def __init__(self):
            self.calls = 0

        def decide(self, state, questions, *, assets):
            self.calls += 1
            return "sentinel"

    backend = CountingBackend()
    cache = helpers.RequestCache(backend, RECIPE, max_requests=1)
    assert cache.decide(examples[0]) == "sentinel"
    assert cache.decide(examples[0]) == "sentinel"
    with pytest.raises(RuntimeError, match="budget"):
        cache.decide(examples[1])
    assert backend.calls == 1


def test_failed_request_consumes_recipe_budget():
    examples, _, _ = replay()

    class FailingBackend:
        calls = 0

        def decide(self, state, questions, *, assets):
            self.calls += 1
            raise ValueError("simulated response failure")

    backend = FailingBackend()
    cache = helpers.RequestCache(backend, RECIPE, max_requests=1)
    with pytest.raises(ValueError, match="simulated"):
        cache.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        cache.decide(examples[0])
    assert backend.calls == 1


def test_authored_seed_lineage_is_disjoint_across_splits():
    import importlib.util

    spec = importlib.util.spec_from_file_location("recipe75_lineage", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    groups = {
        split: {row[2] for row in module.ROWS if row[1] == split}
        for split in ("validation", "test", "demo")
    }
    assert not groups["validation"] & groups["test"]
    assert not groups["validation"] & groups["demo"]
    assert not groups["test"] & groups["demo"]
    assert not set.union(*groups.values()) & {41, 48, 55}
