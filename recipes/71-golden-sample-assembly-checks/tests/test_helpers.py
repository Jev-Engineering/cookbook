"""Policy, pixel identity, held-out failures and label-separation checks."""

import ast
import hashlib
import inspect
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ReplayMiss,
    ScoreAnswer,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import score_level, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def result(level, visible=1, confidence_mass=1):
    probabilities = [(1 - confidence_mass) / 3] * 4
    probabilities[level] = confidence_mass
    return {
        "conformity": ScoreAnswer.from_probabilities(
            probabilities, helpers.LEVEL_TEXT, Provenance.synthetic()
        ),
        "inspectable": NoulAnswer(visible, Provenance.synthetic()),
    }


@pytest.mark.parametrize("level", range(4))
@pytest.mark.parametrize("visibility", [0, 0.5, 0.84999])
def test_occlusion_reviews_even_certain_score(level, visibility):
    routed = helpers.route(result(level, visibility), 0)
    assert routed.outcome == helpers.REVIEW and routed.level is None


@pytest.mark.parametrize("level", range(4))
def test_every_outcome_is_gated_and_never_releases(level):
    answer = result(level, confidence_mass=0.8)
    confidence = answer["conformity"].confidence
    assert helpers.route(answer, confidence).level == level
    assert helpers.route(answer, confidence + 1e-5).outcome == helpers.REVIEW
    routes, actions, reviews = helpers.apply_policy(["sample"], [answer], confidence)
    assert not reviews.to_dicts()
    assert actions.to_dicts()[0]["executed"] is False
    assert actions.to_dicts()[0]["kind"] == "record_inspection_candidate"
    assert routes[0].outcome in ("conforming_candidate", "nonconforming_candidate")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, None])
def test_invalid_threshold_is_refused(bad):
    with pytest.raises(ValueError):
        helpers.route(result(3), bad)


def test_visibility_boundary_and_tied_distribution():
    assert helpers.route(result(3, 0.85), 0.8).outcome == "conforming_candidate"
    answer = result(3)
    answer["conformity"] = ScoreAnswer.from_probabilities(
        [0.0, 0.0, 0.5, 0.5], helpers.LEVEL_TEXT, Provenance.synthetic()
    )
    assert helpers.route(answer, 0).outcome == helpers.REVIEW


def test_foreign_rubric_and_untyped_answer_cannot_create_candidate():
    answer = result(3)
    answer["conformity"] = SimpleNamespace(score=3, confidence=1)
    assert helpers.route(answer, 0).outcome == helpers.REVIEW
    answer["conformity"] = ScoreAnswer.from_probabilities(
        [0, 1], ["a", "b"], Provenance.synthetic()
    )
    assert helpers.route(answer, 0).outcome == helpers.REVIEW


def test_request_contains_pixels_and_reference_rubric_only():
    fields = {"image": "assets/d01.png"}
    expected = helpers.build_request(fields, RECIPE)
    poisoned = dict(fields, label=3, split="test", condition="good", bolt_count=4, id="PASS")
    assert helpers.build_request(poisoned, RECIPE) == expected
    state, questions, assets = expected
    assert set(state) == {"query_image", "task"}
    assert len(questions["conformity"].criteria) == 4
    assert len(assets) == 8
    for level, criterion in enumerate(questions["conformity"].criteria):
        assert criterion.startswith(f"{level}:")
        assert "image:sha256:" in criterion
        for reference in criterion.split("Visual examples: ")[1].split(", "):
            assert reference in assets
    assert all(set(asset) == {"type", "format", "data_base64"} for asset in assets.values())
    assert "condition" not in json.dumps(state)


def test_query_pixels_are_unique_across_splits_and_reference_images():
    digests = []
    for path in sorted((RECIPE / "assets").glob("*.png")):
        with Image.open(path) as image:
            assert image.size == (480, 360)
            digests.append(hashlib.sha256(image.tobytes()).hexdigest())
    assert len(digests) == 33 == len(set(digests))


def test_every_replay_key_matches_request_and_all_assets_are_bound(tmp_path):
    backend = ReplayBackend.from_json(RECIPE / "fixtures/responses.json")
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert backend.decide(state, questions, assets=assets)["conformity"].type == "score"
    copy = tmp_path / "recipe"
    shutil.copytree(RECIPE / "assets", copy / "assets")
    fields = {"image": "assets/d01.png"}
    state, questions, assets = helpers.build_request(fields, copy)
    original = replay_key(state, questions, assets=assets)
    changed_state = dict(state, task="Assess another assembly family.")
    assert replay_key(changed_state, questions, assets=assets) != original
    for name in ("d01.png", "r20.png"):
        before_state, before_questions, before_assets = helpers.build_request(fields, copy)
        before_key = replay_key(before_state, before_questions, assets=before_assets)
        path = copy / "assets" / name
        with Image.open(path) as image:
            changed = image.copy()
        changed.putpixel((160, 145), (250, 10, 10))
        changed.save(path)
        state2, questions2, assets2 = helpers.build_request(fields, copy)
        assert replay_key(state2, questions2, assets=assets2) != before_key
        with pytest.raises(ReplayMiss):
            backend.decide(state2, questions2, assets=assets2)


def test_pixel_baseline_uses_the_image_and_not_its_name(tmp_path):
    for source in ("r00.png", "r10.png", "r20.png", "r30.png"):
        original = helpers.pixel_baseline(RECIPE / "assets" / source, RECIPE)
        renamed = tmp_path / "gold-is-three.png"
        renamed.write_bytes((RECIPE / "assets" / source).read_bytes())
        copied = helpers.pixel_baseline(renamed, RECIPE)
        assert original["conformity"].to_dict() == copied["conformity"].to_dict()
        assert score_level(original["conformity"]) == int(source[1])


def test_session_counts_failed_attempts_caches_and_stops_before_call():
    class Backend:
        def __init__(self):
            self.calls = 0

        def decide(self, state, questions, *, assets):
            self.calls += 1
            return result(3)

    backend = Backend()
    session = helpers.Session(backend, RECIPE, max_requests=1)
    examples = load_inputs(RECIPE)
    assert session.decide(examples[0]) is session.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(examples[1])
    assert backend.calls == 1

    class FailingBackend:
        def decide(self, state, questions, *, assets):
            raise RuntimeError("unavailable")

    failed = helpers.Session(FailingBackend(), RECIPE, max_requests=1)
    with pytest.raises(RuntimeError, match="unavailable"):
        failed.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        failed.decide(examples[0])


def test_stored_answers_are_not_all_right():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    session = helpers.Session(ReplayBackend.from_json(RECIPE / "fixtures/responses.json"), RECIPE)
    val = select_split(examples, "validation")
    eligible = [
        (session.decide(e), labels[e.id]) for e in val if helpers.eligible(session.decide(e))
    ]
    correct = [g["inspectable"] and score_level(r["conformity"]) == g["level"] for r, g in eligible]
    confidence = [r["conformity"].confidence for r, _ in eligible]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)
    assert threshold == helpers.fit_threshold(
        [session.decide(e) for e in val], [labels[e.id] for e in val]
    )
    assert threshold == pytest.approx(0.66)
    wrong_and_confident = [
        e.id
        for e in select_split(examples, "test")
        if session.decide(e)["conformity"].confidence >= threshold
        and score_level(session.decide(e)["conformity"]) != labels[e.id]["level"]
        and helpers.route(session.decide(e), threshold).outcome != helpers.REVIEW
    ]
    assert wrong_and_confident == ["t10"]


def test_threshold_objective_is_pinned_to_production_source():
    tree = ast.parse(inspect.getsource(helpers.fit_threshold))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    assert "target_accuracy" in keywords
    assert ast.literal_eval(keywords["target_accuracy"]) == 1.0
    assert "min_coverage" not in keywords


def test_no_feasible_validation_cutoff_falls_back_to_review_all():
    answer = result(3)
    threshold = helpers.fit_threshold([answer], [{"level": 2, "inspectable": True}])
    assert threshold > 1
    assert helpers.route(answer, threshold).outcome == helpers.REVIEW
    obscured = result(3, visible=0)
    threshold = helpers.fit_threshold([obscured], [{"level": None, "inspectable": False}])
    assert helpers.route(obscured, threshold).outcome == helpers.REVIEW


def test_review_is_excluded_from_coverage_even_when_score_is_certain():
    answers = [result(3), result(3, visible=0)]
    gold = [{"level": 3, "inspectable": True}, {"level": None, "inspectable": False}]
    routes, actions, reviews = helpers.apply_policy(["one", "two"], answers, 0.6)
    metrics = helpers.metrics(answers, gold, routes)
    assert metrics["coverage"] == 0.5
    assert metrics["ordinal_N"] == 1
    assert metrics["wrong_accepted"] == 0
    assert len(actions) == len(reviews) == 1
