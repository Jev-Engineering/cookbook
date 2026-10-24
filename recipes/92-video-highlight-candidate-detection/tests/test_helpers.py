"""Policy, temporal sampling, leakage boundaries and replay identity checks."""

import ast
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def fixtures():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    scorer = helpers.WindowScorer(get_backend(fixtures=responses_path(RECIPE)))
    return examples, labels, scorer


def arbitrary(score=3.0, confidence=1.0):
    return {n: SimpleNamespace(score=score, confidence=confidence) for n in helpers.SIGNALS}


def fields():
    return {
        "frames": [{"timestamp_seconds": t, "path": "unused"} for t in (0, 0.45, 0.95, 1.55, 2.05)]
    }


def test_sampling_uses_actual_times_not_invented_uniform_times():
    rows = helpers.sample_frames(fields()["frames"])
    assert [r["timestamp_seconds"] for r in rows] == [0, 0.95, 2.05]
    assert helpers.window_interval(fields()) == (0, 2.05)


@pytest.mark.parametrize("times", [(0, 0, 1), (1, 0, 2), (-1, 0, 1), (0, 1, float("nan")), (0, 1)])
def test_bad_timestamps_fail_before_inference(times):
    with pytest.raises(ValueError):
        helpers.sample_frames([{"timestamp_seconds": t} for t in times])


@pytest.mark.parametrize("score", [0.0, 1.0, 2.0, 3.0])
def test_low_confidence_is_review_whatever_the_score(score):
    outcome = helpers.route("x", fields(), arbitrary(score, 0.2), 0.8)
    assert outcome.outcome == "review"
    assert outcome.reason == "confidence below the threshold"


def test_explicit_uncertainty_is_not_coverage_even_at_certain_confidence():
    assert helpers.route("x", fields(), arbitrary(2.0), 0.0).outcome == "review"
    assert helpers.route("x", fields(), arbitrary(0.0), 0.0).outcome == "none_suitable"


def test_confidence_and_strength_boundaries_are_inclusive():
    assert helpers.route("x", fields(), arbitrary(2.4, 0.8), 0.8).outcome == "candidate"
    assert helpers.route("x", fields(), arbitrary(2.4, 0.8), 0.80001).outcome == "review"


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -0.1, 1.01])
def test_invalid_confidence_cannot_be_accepted(value):
    assert helpers.route("x", fields(), arbitrary(3.0, value), 0.0).outcome == "review"


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -0.1, 3.01])
def test_invalid_score_cannot_be_accepted(value):
    assert helpers.route("x", fields(), arbitrary(value), 0.0).outcome == "review"


def test_exact_budget_counts_failed_calls_and_cached_successes():
    examples, _, scorer = fixtures()
    scorer.max_requests = 1
    first = scorer.decide(examples[0].fields)
    assert scorer.decide(examples[0].fields) is first
    assert scorer.requests_made == 1
    assert scorer.decide(examples[1].fields) is None
    assert helpers.route("x", fields(), None, 0).reason == "request budget exhausted"

    class FailingBackend:
        calls = 0

        def decide(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("failed attempt")

    backend = FailingBackend()
    failed = helpers.WindowScorer(backend, max_requests=1)
    with pytest.raises(RuntimeError):
        failed.decide(examples[0].fields)
    assert failed.decide(examples[0].fields) is None
    assert backend.calls == 1


def test_shortlist_cap_order_and_review_are_enforced():
    outcomes = [helpers.route(str(i), fields(), arbitrary(3, 1), 0.5) for i in range(8)]
    outcomes.append(helpers.route("ambiguous", fields(), arbitrary(2, 1), 0.5))
    selected, review, log = helpers.shortlist(reversed(outcomes), limit=2)
    assert [x.window for x in selected] == ["0", "1"]
    assert len(review) == 1
    assert len(log) == 2
    assert all(not row["executed"] for row in log.to_dicts())
    assert helpers.shortlist(outcomes, limit=0)[0] == []
    with pytest.raises(ValueError):
        helpers.shortlist(outcomes, limit=-1)


def test_state_allowlist_hides_drawing_metadata_labels_and_paths():
    examples, _, _ = fixtures()
    polluted = {**examples[0].fields, "split": "test", "label": "candidate", "scenario": "arms_up"}
    state, questions, assets = helpers.request(polluted)
    assert set(state) == {"frames"}
    assert all(set(r) == {"timestamp_seconds", "image"} for r in state["frames"])
    assert all(r["image"].startswith("image:sha256:") for r in state["frames"])
    assert set(questions) == {"reaction", "scene_change", "victory"}
    assert len(assets) in (2, 3)
    assert not any(word in json.dumps(state) for word in ("label", "scenario", "path", "split"))


def test_pixels_times_and_question_changes_affect_replay_identity():
    examples, _, _ = fixtures()
    state, questions, assets = helpers.request(examples[0].fields)
    original = replay_key(state, questions, assets=assets)
    changed = deepcopy(state)
    changed["frames"][0]["timestamp_seconds"] += 0.1
    assert replay_key(changed, questions, assets=assets) != original
    changed_assets = dict(assets)
    reference = next(iter(changed_assets))
    changed_assets[reference] = image_asset(RECIPE / examples[1].fields["frames"][0]["path"])
    assert replay_key(state, questions, assets=changed_assets) != original
    assert replay_key(state, {"reaction": questions["reaction"]}, assets=assets) != original


def test_every_stored_key_matches_current_multiframe_request():
    examples, _, _ = fixtures()
    for example in examples:
        state, questions, assets = helpers.request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_baseline_uses_pixels_not_label_metadata():
    examples, _, _ = fixtures()
    original = examples[0].fields
    polluted = {**original, "label": "opposite", "split": "different", "scenario": "unrelated"}
    assert helpers.pixel_change(original) == helpers.pixel_change(polluted)
    duplicate = deepcopy(original)
    for frame in duplicate["frames"]:
        frame["path"] = original["frames"][0]["path"]
    assert helpers.pixel_change(duplicate) == 0
    assert helpers.pixel_change(original) > 0


def test_stored_answers_are_not_all_right():
    examples, labels, scorer = fixtures()
    validation = [e for e in examples if e.split == "validation"]
    answers = [scorer.decide(e.fields) for e in validation]
    threshold = select_confidence_threshold(
        [
            helpers.raw_event(a) == labels[e.id]["event"]
            for e, a in zip(validation, answers, strict=True)
        ],
        [helpers.confidence(a) for a in answers],
        target_accuracy=1.0,
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if helpers.confidence(scorer.decide(e.fields)) >= threshold
        and helpers.route(e.id, e.fields, scorer.decide(e.fields), threshold).outcome
        != helpers.REVIEW
        and helpers.raw_event(scorer.decide(e.fields)) != labels[e.id]["event"]
    ]
    assert wrong_and_confident == ["t10", "t11"]
    assert threshold == pytest.approx(0.81)


def test_notebook_selection_objectives_are_pinned_to_real_cell_source():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert 'objective="f1"' in source
    assert "min_coverage" not in source
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    confidence_call = next(n for n in calls if n.func.id == "select_confidence_threshold")
    baseline_call = next(n for n in calls if n.func.id == "select_threshold")
    assert any(
        k.arg == "target_accuracy" and k.value.value == 1.0 for k in confidence_call.keywords
    )
    assert any(k.arg == "objective" and k.value.value == "f1" for k in baseline_call.keywords)


def test_rank_uses_strength_then_timestamp_and_never_promotes_review():
    make = helpers.WindowOutcome
    outcomes = [
        make("later", 9, 11, "candidate", "resolved", 2.8),
        make("strong", 20, 22, "candidate", "resolved", 2.9),
        make("earlier", 1, 3, "candidate", "resolved", 2.8),
        make("unresolved", 0, 2, "review", "confidence below the threshold", 3.0),
    ]
    selected, review, log = helpers.shortlist(outcomes, limit=3)
    assert [o.window for o in selected] == ["strong", "earlier", "later"]
    assert len(review) == 1 and len(log) == 3


def test_already_present_signals_are_explicit_negative_examples():
    examples, labels, scorer = fixtures()
    for ident in ("v05", "v12"):
        example = next(e for e in examples if e.id == ident)
        assert labels[ident]["event"] == "none_suitable"
        assert (
            helpers.route(ident, example.fields, scorer.decide(example.fields), 0.81).outcome
            == "none_suitable"
        )
    assert "already raised throughout" in helpers.RUBRICS["reaction"][0]
    assert "already present throughout" in helpers.RUBRICS["victory"][0]
