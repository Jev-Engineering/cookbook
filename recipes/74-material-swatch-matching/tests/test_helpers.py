"""Policy, image identity, and frozen-selection checks for material matching."""

import json
import math
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(choice, confidence=0.95):
    return SimpleNamespace(choice=choice, confidence=confidence)


def test_questions_use_actual_images_for_each_material_criterion():
    question = helpers.build_questions()["swatch"]
    assert list(question.criteria) == ["M-17", "M-28", "M-39", "M-46", "no_match", "uncertain"]
    for name, path in helpers.REFERENCES.items():
        assert question.criteria[name] == image_reference(image_asset(RECIPE / path))


@pytest.mark.parametrize("choice", ["M-17", "M-28", "M-39", "M-46", "no_match"])
def test_every_complete_answer_is_confidence_gated(choice):
    assert helpers.route(answer(choice, 0.8), 0.8).outcome == "accepted"
    assert helpers.route(answer(choice, 0.79), 0.8).outcome == "review"


@pytest.mark.parametrize("choice", ["uncertain", "buy_now", "", None])
def test_uncertain_and_arbitrary_choices_always_defer(choice):
    assert helpers.route(answer(choice, 1.0), 0).outcome == "review"


@pytest.mark.parametrize("confidence", [None, math.nan, math.inf, -1, 2, "certain"])
def test_missing_or_invalid_confidence_never_passes(confidence):
    assert helpers.route(answer("M-17", confidence), 0.5).outcome == "review"


@pytest.mark.parametrize("threshold", [math.nan, -1, 2, None])
def test_invalid_policy_is_rejected(threshold):
    with pytest.raises(ValueError):
        helpers.route(answer("M-17"), threshold)


def test_only_simulated_visual_suggestions_are_logged():
    queue, actions = ReviewQueue(), ActionLog()
    for choice in helpers.OPTIONS:
        probabilities = {name: (0.95 if name == choice else 0.01) for name in helpers.OPTIONS}
        typed = ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())
        helpers.apply_decision("sample", typed, 0.8, queue, actions)
    assert len(queue) == 1
    assert len(actions) == 4
    assert all(row["kind"] == "suggest_visual_candidate" for row in actions.to_dicts())
    assert all(row["executed"] is False for row in actions.to_dicts())


def test_state_drops_labels_split_ids_and_drawing_parameters():
    clean = {"image": "assets/v01.png"}
    poisoned = {**clean, "label": "M-28", "split": "test", "pattern": "rib", "id": "wrong"}
    assert helpers.build_state(clean) == helpers.build_state(poisoned)
    assert set(helpers.build_state(clean)) == {"query", "task"}
    assert helpers.baseline(clean, 0.12) == helpers.baseline(poisoned, 0.12)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert len(assets) == 5


def test_query_reference_and_state_changes_invalidate_replay(tmp_path):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    fields = {"image": "assets/v01.png"}
    state, questions, assets = helpers.build_request(fields, tmp_path)
    original = replay_key(state, questions, assets=assets)
    changed_state = {**state, "task": "A different appearance question"}
    assert replay_key(changed_state, questions, assets=assets) != original
    for path in [fields["image"], "assets/reference-17.png"]:
        with Image.open(tmp_path / path) as source:
            image = source.copy()
        image.putpixel((0, 0), (255, 0, 0))
        image.save(tmp_path / path)
        new_state, new_questions, new_assets = helpers.build_request(fields, tmp_path)
        changed = replay_key(new_state, new_questions, assets=new_assets)
        assert changed != original
        original = changed


def test_baseline_uses_color_and_texture_and_can_reject_or_defer():
    first, _, _ = helpers.pixel_features(RECIPE / "assets/reference-17.png")
    second, _, _ = helpers.pixel_features(RECIPE / "assets/reference-28.png")
    third, _, _ = helpers.pixel_features(RECIPE / "assets/reference-39.png")
    assert max(abs(first[:3] - second[:3])) < 0.01
    assert abs(first[3] - second[3]) > 0.01
    assert max(abs(first[:3] - third[:3])) > 0.2
    assert helpers.baseline({"image": "assets/v10-glare.png"}, 0.12).outcome == "review"
    assert helpers.baseline({"image": "assets/v11-cover.png"}, 0.12).outcome == "review"
    assert helpers.baseline({"image": "assets/v08-unknown.png"}, 0.04).label == "no_match"


def test_radius_selector_refuses_test_rows():
    examples = load_inputs(RECIPE)
    with pytest.raises(ValueError, match="validation"):
        helpers.choose_radius([e for e in examples if e.split == "test"], load_labels(RECIPE))


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        state, questions, assets = helpers.build_request(example.fields)
        return backend.decide(state, questions, assets=assets)["swatch"]

    validation = [e for e in examples if e.split == "validation"]
    named = [(e, decide(e)) for e in validation if decide(e).choice != "uncertain"]
    threshold = select_confidence_threshold(
        [a.choice == labels[e.id] for e, a in named],
        [a.confidence for _, a in named],
        target_accuracy=0.9,
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if decide(e).choice != labels[e.id]
        and decide(e).confidence >= threshold
        and helpers.route(decide(e), threshold).outcome == "accepted"
    ]
    assert wrong_and_confident == ["t07-lookalike"]


def test_selection_objective_is_pinned_to_committed_source():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=0.9" in source
    assert "min_coverage" not in source
    assert "if answers[e.id].choice != helpers.UNCERTAIN" in source


def test_baseline_selection_objective_and_family():
    import inspect

    source = inspect.getsource(helpers.choose_radius)
    assert "(1 if ok else -3)" in source
    assert "(row[1], -row[0])" in source
    assert helpers.RADII == (0.04, 0.08, 0.12, 0.18, 0.26)
