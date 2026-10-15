"""Behavioral checks for inspection interlocks, image identity, and evaluation boundaries."""

import ast
import importlib.util
import inspect
import itertools
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import (
    DecisionResult,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ScoreAnswer,
    load_helpers,
    replay_key,
)
from jev_cookbook.fixtures import load_inputs, load_labels

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(flags=(False, False, False, False), level=0, visible=True, p=1.0, severity=None):
    provenance = Provenance.synthetic()
    values = {
        name: NoulAnswer(p if flag else 1 - p, provenance)
        for name, flag in zip((*helpers.DEFECTS, "inspectable"), (*flags, visible), strict=True)
    }
    if severity is None:
        severity = [float(i == level) for i in range(4)]
    values["severity"] = ScoreAnswer.from_probabilities(severity, helpers.RUBRIC, provenance)
    return DecisionResult(values, "synthetic")


def replay():
    return helpers.InspectionRun(
        ReplayBackend.from_json(RECIPE / "fixtures/responses.json"), RECIPE
    )


def validation_policy():
    examples = [e for e in load_inputs(RECIPE) if e.split == "validation"]
    labels = load_labels(RECIPE)
    run = replay()
    results = {e.id: run.decide(e) for e in examples}
    threshold, _rows = helpers.choose_policy(
        examples, labels, results, objective="zero_errors_max_coverage"
    )
    return threshold


def test_arbitrary_certain_answers_cannot_bypass_interlocks():
    for flags in itertools.product((False, True), repeat=4):
        for level, visible in itertools.product(range(4), (False, True)):
            prediction = helpers.inspect(answer(flags, level, visible), 0.6)
            must_review = (
                not visible
                or any(flags) != (level > 0)
                or flags[2] != (level == 3)
                or ((flags[1] or flags[3]) and level < 2)
            )
            assert (prediction.outcome == helpers.REVIEW) == must_review
            actions, reviews = helpers.simulated_queues()
            helpers.disposition(prediction, "panel", actions, reviews)
            assert len(actions) == int(not must_review)
            assert len(reviews) == int(must_review)
            assert all(entry["executed"] is False for entry in actions.to_dicts())


def test_confidence_boundary_is_inclusive_and_zero_is_not_an_exemption():
    low = answer(flags=(True, False, False, False), level=1, p=0.8)
    certainty = helpers.inspect(low, 0).certainty
    assert helpers.inspect(low, certainty).outcome == "defect_candidate"
    assert helpers.inspect(low, certainty + 1e-9).reason == "confidence below the threshold"
    negative = answer(p=0.7)
    assert helpers.inspect(negative, 0.6).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf")])
def test_invalid_thresholds_raise(bad):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.inspect(answer(), bad)


def test_noul_and_score_ties_always_review_even_at_zero_threshold():
    assert helpers.inspect(answer(p=0.5), 0).outcome == helpers.REVIEW
    assert helpers.inspect(answer(severity=[0.25] * 4), 0).outcome == helpers.REVIEW
    assert helpers.inspect(answer(severity=[0.5, 0.5, 0, 0]), 0).outcome == helpers.REVIEW


def test_missing_parts_require_highest_severity_and_cannot_be_benign():
    flags = (False, False, True, False)
    assert helpers.inspect(answer(flags, 3), 0.6).outcome == "defect_candidate"
    assert helpers.inspect(answer(flags, 2), 0.6).outcome == helpers.REVIEW
    assert helpers.inspect(answer(level=3), 0.6).outcome == helpers.REVIEW


def test_review_is_not_complete_inspection_correctness():
    gold = {
        "defects": dict.fromkeys(helpers.DEFECTS, False),
        "severity": 0,
        "requires_review": True,
    }
    clear = helpers.inspect(answer(), 0.6)
    covered = helpers.inspect(answer(visible=False), 0.6)
    assert not helpers.correct_complete(clear, gold)
    assert not helpers.disposition_correct(clear, gold)
    assert helpers.disposition_correct(covered, gold)


def test_request_budget_cache_and_failure_accounting():
    class Counter:
        calls = 0

        def decide(self, state, questions, *, assets):
            self.calls += 1
            return answer()

    backend = Counter()
    examples = load_inputs(RECIPE)
    run = helpers.InspectionRun(backend, RECIPE, max_requests=1)
    assert run.decide(examples[0]) is run.decide(examples[0])
    assert backend.calls == run.attempts == 1
    with pytest.raises(RuntimeError, match="budget"):
        run.decide(examples[1])
    assert backend.calls == 1

    class Fails:
        def decide(self, *args, **kwargs):
            raise ValueError("invalid answer")

    run = helpers.InspectionRun(Fails(), RECIPE, max_requests=1)
    with pytest.raises(ValueError, match="invalid"):
        run.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        run.decide(examples[0])


def test_state_and_baseline_cannot_read_gold_or_drawing_metadata():
    fields = load_inputs(RECIPE)[0].fields
    injected = dict(fields, label="missing_component", split="test", scene={"covered": True})
    state, questions, assets = helpers.build_request(fields, RECIPE)
    assert helpers.build_request(injected, RECIPE) == (state, questions, assets)
    assert set(state) == {"panel", "approved_reference", "inspection_specification"}
    assert "v01" not in json.dumps(state)
    assert helpers.pixel_features(fields, RECIPE) == helpers.pixel_features(injected, RECIPE)
    source = inspect.getsource(helpers.pixel_features)
    assert "load_labels" not in source and "ROWS" not in source and 'fields["image"]' in source


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    run = replay()
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        result = run.decide(example)
        assert set(result.answers) == {*helpers.DEFECTS, "inspectable", "severity"}


def test_state_reference_and_query_pixels_each_change_replay_identity(tmp_path):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    fields = load_inputs(RECIPE)[0].fields
    state, questions, assets = helpers.build_request(fields, tmp_path)
    original = replay_key(state, questions, assets=assets)
    changed_state = dict(state, observation="second camera position")
    assert replay_key(changed_state, questions, assets=assets) != original
    for field in ("image", "reference"):
        file = tmp_path / fields[field]
        with Image.open(file) as image:
            image = image.copy()
        image.putpixel((100, 100), (1, 2, 3))
        image.save(file)
        state, questions, assets = helpers.build_request(fields, tmp_path)
        changed = replay_key(state, questions, assets=assets)
        assert changed != original
        original = changed


def test_unique_query_pixels_and_valid_geometry_across_splits():
    seen = set()
    reference_pixels = Image.open(RECIPE / "assets/reference.png").tobytes()
    for example in load_inputs(RECIPE):
        with Image.open(RECIPE / example.fields["image"]) as image:
            assert image.size == (480, 360)
            pixels = image.tobytes()
            assert pixels not in seen and pixels != reference_pixels
            seen.add(pixels)
    assert len(seen) == 26


def test_policy_selection_refuses_test_rows_and_objective_changes():
    examples = load_inputs(RECIPE)
    with pytest.raises(ValueError, match="validation"):
        helpers.choose_policy(examples, {}, {})
    with pytest.raises(ValueError, match="validation"):
        helpers.choose_baseline(examples, {}, {})
    validation = [e for e in examples if e.split == "validation"]
    with pytest.raises(ValueError, match="objective"):
        helpers.choose_policy(validation, {}, {}, objective="accuracy")
    with pytest.raises(ValueError, match="objective"):
        helpers.choose_baseline(validation, {}, {}, objective="risk")


def test_notebook_pins_both_selection_objectives_and_families():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    calls = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.walk(ast.parse("".join(cell["source"]))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"choose_policy", "choose_baseline"}:
                    calls[node.func.attr] = {
                        kw.arg: ast.literal_eval(kw.value) for kw in node.keywords
                    }
    assert calls == {
        "choose_policy": {"objective": "zero_errors_max_coverage"},
        "choose_baseline": {"objective": "complete_disposition_accuracy"},
    }
    assert helpers.POLICY_CANDIDATES == (0.0, 0.4, 0.6, 0.8, 1.0)
    assert helpers.BASELINE_CANDIDATES == (0.4, 0.6, 1.0, 1.5)
    assert validation_policy() == 0.6


def test_stored_answers_are_not_all_right():
    threshold = validation_policy()
    labels, run = load_labels(RECIPE), replay()
    wrong_and_confident = []
    for example in load_inputs(RECIPE):
        if example.split != "test":
            continue
        prediction = helpers.inspect(run.decide(example), threshold)
        if prediction.outcome != helpers.REVIEW and not helpers.correct_complete(
            prediction, labels[example.id]
        ):
            wrong_and_confident.append((example.id, prediction.certainty >= threshold))
    assert wrong_and_confident
    assert all(above_threshold for _ident, above_threshold in wrong_and_confident)


def test_baseline_can_detect_each_obvious_defect_and_broad_gouge():
    examples = {e.id: e for e in load_inputs(RECIPE) if e.split == "validation"}
    expected = {
        "v03": ("scratch", 1),
        "v04": ("dent", 2),
        "v05": ("missing_component", 3),
        "v06": ("incorrect_assembly", 2),
        "v12": ("scratch", 2),
    }
    for ident, (label, severity) in expected.items():
        features = helpers.pixel_features(examples[ident].fields, RECIPE)
        prediction = helpers.pixel_baseline(features, 0.4)
        assert prediction.defects[label] and prediction.severity == severity
    clean = helpers.pixel_baseline(helpers.pixel_features(examples["v01"].fields, RECIPE), 0.4)
    assert not any(clean.defects.values())


def test_images_are_reproducible_from_the_authored_generator(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "recipe63_images_test", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for ident, _split, scene, _gold, _spec in module.ROWS:
        path = tmp_path / f"{ident}.png"
        module.draw_panel(scene).save(path)
        assert path.read_bytes() == (RECIPE / "assets" / path.name).read_bytes()
