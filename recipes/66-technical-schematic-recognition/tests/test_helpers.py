"""Check annotation interlocks, image identity and validation-only policy selection."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, BudgetExceeded, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def typed(choice, top=0.9):
    return ChoiceAnswer.from_probabilities(
        {name: top if name == choice else (1 - top) / 7 for name in helpers.OPTIONS},
        Provenance.synthetic(),
    )


@pytest.mark.parametrize("choice", helpers.SYMBOLS)
def test_every_named_symbol_obeys_the_inclusive_gate(choice):
    answer = typed(choice)
    assert helpers.classify(answer, answer.confidence).label == choice
    assert helpers.classify(answer, answer.confidence + 1e-9).outcome == "review"


@pytest.mark.parametrize("choice", ["none", "uncertain", "energize_circuit", None])
def test_fallback_and_foreign_answers_cannot_annotate(choice):
    answer = SimpleNamespace(choice=choice, confidence=1.0)
    outcome = helpers.classify(answer, 0)
    assert outcome.outcome == "review"
    assert outcome.label is None


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1, 2, "0.9", True])
def test_unknown_or_invalid_confidence_fails_closed(value):
    assert (
        helpers.classify(SimpleNamespace(choice="resistor", confidence=value), 0).outcome
        == "review"
    )


@pytest.mark.parametrize("value", [-0.01, 1.01, float("nan"), float("inf"), "0.7"])
def test_invalid_threshold_raises(value):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.classify(typed("resistor"), value)


def test_annotations_and_reviews_use_different_simulated_containers():
    actions, reviews = ActionLog(), ReviewQueue()
    for index, answer in enumerate((typed("resistor"), typed("none"), typed("terminal", 0.4))):
        helpers.annotate(str(index), answer, 0.7, actions, reviews)
    assert len(actions) == 1 and len(reviews) == 2
    entry = actions.to_dicts()[0]
    assert entry["payload"] == {"crop_id": "0", "label": "resistor"}
    assert entry["kind"] == "propose_symbol_label"
    assert entry["executed"] is False
    assert all(r.status == "pending" for r in reviews.pending())


def test_state_reveals_only_opaque_pixels_and_the_legend():
    fields = {"image": "assets/crop-v01.png", "gold": "capacitor", "split": "test", "angle": 99}
    state, assets = helpers.build_state(fields, RECIPE)
    assert set(state) == {"crop", "legend"}
    assert list(assets) == [state["crop"]]
    assert state["crop"].startswith("image:sha256:")
    assert "capacitor" not in json.dumps(state)
    assert set(helpers.build_questions()["symbol"].criteria) == {
        "resistor",
        "capacitor",
        "terminal",
        "open_switch",
        "junction",
        "crossing",
        "none",
        "uncertain",
    }


def test_every_replay_key_matches_pixels_and_current_question():
    backend = get_backend(fixtures=responses_path(RECIPE))
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_state(example.fields, RECIPE)
        questions = helpers.build_questions()
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        backend.decide(state, questions, assets=assets)


def test_state_and_image_bytes_each_change_replay_identity(tmp_path):
    state, assets = helpers.build_state({"image": "assets/crop-v01.png"}, RECIPE)
    questions = helpers.build_questions()
    original = replay_key(state, questions, assets=assets)
    assert replay_key({**state, "legend": "different legend"}, questions, assets=assets) != original
    with Image.open(RECIPE / "assets/crop-v01.png") as image:
        changed = image.copy()
    changed.putpixel((0, 0), (0, 0, 0))
    path = tmp_path / "changed.png"
    changed.save(path)
    asset = image_asset(path)
    # Hold the reference constant to prove the uploaded bytes themselves participate.
    assert replay_key(state, questions, assets={state["crop"]: asset}) != original
    assert image_reference(asset) != state["crop"]


def test_image_sizes_pixels_and_independent_query_lineages():
    import importlib.util

    spec = importlib.util.spec_from_file_location("recipe66_lineage", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lineage = {split: set() for split in ("validation", "test")}
    for row in module.ROWS:
        if row[1] in lineage:
            lineage[row[1]].add(tuple(row[2:7]))
    assert lineage["validation"].isdisjoint(lineage["test"])
    seen = set()
    for path in (RECIPE / "assets").glob("*.png"):
        image_asset(path)
        with Image.open(path) as image:
            assert image.size == (384, 320)
            assert image.tobytes() not in seen
            seen.add(image.tobytes())
    assert len(seen) == 36


def test_baseline_reads_pixels_and_never_gold_or_path_names(tmp_path):
    baseline = helpers.PixelBaseline(RECIPE)
    for name in ("resistor", "capacitor", "terminal", "junction", "crossing"):
        with Image.open(RECIPE / "assets" / f"legend-{name}.png") as image:
            expected = baseline.predict(image)
            assert expected.choice == name and expected.confidence == 1.0
            image.save(tmp_path / "unrelated-name.png")
        fields = {"image": "unrelated-name.png", "label": "wrong", "id": "wrong", "split": "wrong"}
        assert helpers.baseline_answer(baseline, fields, tmp_path) == expected
    assert baseline.predict(Image.new("RGB", (384, 320), "white")).choice == "none"


def test_cache_and_request_budget_hold_even_after_failure():
    examples = load_inputs(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.RequestSession(backend, RECIPE, max_requests=1)
    first = session.decide(examples[0].fields)
    assert session.decide(examples[0].fields) is first
    assert session.requests == 1
    with pytest.raises(BudgetExceeded):
        session.decide(examples[1].fields)
    assert session.requests == 1

    class FailedBackend:
        def decide(self, *args, **kwargs):
            raise RuntimeError("simulated failed attempt")

    failed = helpers.RequestSession(FailedBackend(), RECIPE, max_requests=1)
    with pytest.raises(RuntimeError, match="simulated"):
        failed.decide(examples[0].fields)
    with pytest.raises(BudgetExceeded):
        failed.decide(examples[0].fields)


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.RequestSession(backend, RECIPE)
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    named = [
        (session.decide(e.fields)["symbol"], labels[e.id])
        for e in validation
        if session.decide(e.fields)["symbol"].choice in helpers.SYMBOLS
    ]
    threshold = select_confidence_threshold(
        [a.choice == gold for a, gold in named],
        [a.confidence for a, _ in named],
        target_accuracy=1.0,
    )
    assert math.isclose(threshold, (0.82 - 0.125) / 0.875)
    wrong_and_confident = [
        e.id
        for e in examples
        if e.split == "test"
        if session.decide(e.fields)["symbol"].choice != labels[e.id]
        and session.decide(e.fields)["symbol"].confidence >= threshold
        and helpers.classify(session.decide(e.fields)["symbol"], threshold).outcome != "review"
    ]
    assert wrong_and_confident == ["t06"]


def test_notebook_pins_both_threshold_objectives_to_target_accuracy():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert source.count("target_accuracy=1.0") == 2
    assert "min_coverage" not in source
    assert 'select_split(examples, "test")' not in source
