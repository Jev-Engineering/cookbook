"""Rules must hold for arbitrary typed answers, not only the authored replay cases."""

import ast
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from jev_cookbook import BoxAnswer, NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
PROVENANCE = Provenance.synthetic()
BOX = {"top": 0.3, "bottom": 0.5, "left": 0.3, "right": 0.6}


def answers(p=0.99, unique=0.99, clear=0.99):
    return {
        name: NoulAnswer(value, PROVENANCE)
        for name, value in zip(("present", "unique", "clear"), (p, unique, clear), strict=True)
    }


def replay_inspector(max_requests=60):
    return helpers.Inspector(
        get_backend(fixtures=responses_path(RECIPE)), RECIPE, max_requests=max_requests
    )


@pytest.mark.parametrize(
    "p,unique,clear", [(0.99, 0.1, 0.99), (0.99, 0.99, 0.2), (0.86, 0.99, 0.99), (0.01, 0.99, 0.99)]
)
def test_review_interlocks_override_even_certain_box(p, unique, clear):
    result = helpers.route(
        answers(p, unique, clear), BoxAnswer(BOX, 1.0, PROVENANCE), helpers.Policy(0.9, 0.8)
    )
    assert result.outcome == "review" and not result.accepted and result.box is None


@pytest.mark.parametrize("confidence", [None, 0.0, 0.79])
def test_missing_or_low_box_confidence_is_review(confidence):
    result = helpers.route(
        answers(), BoxAnswer(BOX, confidence, PROVENANCE), helpers.Policy(0.9, 0.8)
    )
    assert result.outcome == "review" and result.box is None


def test_inclusive_policy_and_absence_suppress_coordinates():
    assert (
        helpers.route(
            answers(0.9, 0.9, 0.9), BoxAnswer(BOX, 0.8, PROVENANCE), helpers.Policy(0.9, 0.8)
        ).outcome
        == "located"
    )
    absent = helpers.route(
        answers(0.01, 0.01), BoxAnswer(BOX, 1, PROVENANCE), helpers.Policy(0.9, 0.8)
    )
    assert absent.outcome == "absent" and absent.accepted and absent.box is None


@pytest.mark.parametrize(
    "presence,box",
    [(0.79, 0.8), (1.1, 0.8), (0.9, -1), (0.9, 1.1), (float("nan"), 0.8), (0.9, float("nan"))],
)
def test_invalid_policies_fail_closed(presence, box):
    with pytest.raises(ValueError):
        helpers.Policy(presence, box)


def test_acquisition_stops_before_box_for_absent_multiple_and_occluded():
    inspector = replay_inspector()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    for ident in ("v06", "v09", "v10"):
        first, box = inspector.acquire(examples[ident].fields)
        assert box is None
        assert not helpers.eligible(first.answers)
    assert inspector.calls == 3


def test_budget_and_cached_calls_are_enforced():
    inspector = replay_inspector(max_requests=1)
    example = next(e for e in load_inputs(RECIPE) if e.id == "d01")
    with pytest.raises(RuntimeError, match="budget"):
        inspector.acquire(example.fields)
    assert inspector.calls == 1
    triple = helpers.request(example.fields, RECIPE)
    inspector.decide(triple)
    assert inspector.calls == 1


def test_no_real_side_effects_and_review_is_not_coverage():
    inspector = replay_inspector()
    examples = {e.id: e for e in load_inputs(RECIPE)}
    policy = helpers.Policy(0.9, 0.8)
    located = inspector.inspect("d01", examples["d01"].fields, policy)
    review = inspector.inspect("d02", examples["d02"].fields, policy)
    assert located.accepted and not review.accepted
    assert len(inspector.actions) == len(inspector.reviews) == 1
    assert inspector.actions.to_dicts()[0]["executed"] is False
    metrics = helpers.summarize(
        [located, review],
        [{"outcome": "located", "box": located.box}, {"outcome": "review", "box": None}],
    )
    assert metrics["coverage"] == 0.5 and metrics["accuracy"] == 1


def test_every_replay_key_matches_actual_dependent_requests():
    inspector = replay_inspector()
    for example in load_inputs(RECIPE):
        first, box = inspector.acquire(example.fields)
        triples = [helpers.request(example.fields, RECIPE)]
        if helpers.eligible(first.answers):
            assert box is not None
            triples.append(helpers.request(example.fields, RECIPE, locate=True))
        assert example.replay_keys == tuple(replay_key(s, q, assets=a) for s, q, a in triples)
    assert inspector.calls == 48


def test_state_and_asset_identity_change_replay_keys(tmp_path):
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.request(example.fields, RECIPE)
    assert set(state) == {"image", "requested_defect", "inspection_window"}
    assert example.id not in json.dumps(state)
    key = replay_key(state, questions, assets=assets)
    changed = dict(state, requested_defect="dent")
    assert replay_key(changed, questions, assets=assets) != key
    with Image.open(RECIPE / example.fields["image"]) as original:
        image = original.copy()
    image.putpixel((150, 150), (255, 0, 0))
    path = tmp_path / "changed.png"
    image.save(path)
    # Deliberately preserve the reference string; the asset bytes still bind the key.
    assert replay_key(state, questions, assets={state["image"]: image_asset(path)}) != key


def test_baseline_moves_with_pixels_and_has_no_metadata_input():
    image = Image.new("RGB", (480, 360), "white")
    assert helpers.pixel_baseline(image).outcome == "absent"
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 130, 150, 145), fill="black")
    first = helpers.pixel_baseline(image)
    shifted = Image.new("RGB", image.size, "white")
    ImageDraw.Draw(shifted).rectangle((220, 130, 250, 145), fill="black")
    second = helpers.pixel_baseline(shifted)
    assert second.box["left"] - first.box["left"] == pytest.approx(100 / 480)
    assert first.box["top"] == second.box["top"]


def test_stored_answers_are_not_all_right():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    inspector = replay_inspector()
    validation = [e for e in examples if e.split == "validation"]
    policy, _ = helpers.select_policy(
        [inspector.acquire(e.fields) for e in validation],
        [labels[e.id] for e in validation],
        target_accuracy=0.9,
    )
    assert policy == helpers.Policy(0.9, 0.8)
    accepted_errors = []
    for example in (e for e in examples if e.split == "test"):
        first, box = inspector.acquire(example.fields)
        outcome = helpers.route(first.answers, box, policy)
        if outcome.accepted and not helpers.correct(outcome, labels[example.id]):
            accepted_errors.append(example.id)
            if box is not None:
                assert box.confidence >= policy.box
    assert accepted_errors == ["t08", "t12", "t13"]


def test_notebook_pins_validation_only_selection_objective_and_freezes_before_test():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    tree = ast.parse(cells["evaluation-validation"])
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select_policy"
    ]
    assert len(calls) == 1
    assert {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords} == {
        "target_accuracy": 0.9
    }
    assert ast.unparse(calls[0].args[0]) == "validation_observations"
    assert "if e.split == 'validation'" in ast.unparse(tree)
    assert "select_policy" not in cells["evaluation-test"]
    assert helpers.CANDIDATES == tuple((p, b) for p in (0.8, 0.9, 0.95) for b in (0.6, 0.8, 0.9))


def test_selection_stops_if_no_candidate_meets_the_objective():
    inspector = replay_inspector()
    example = next(e for e in load_inputs(RECIPE) if e.id == "d01")
    with pytest.raises(ValueError, match="no candidate"):
        helpers.select_policy(
            [inspector.acquire(example.fields)],
            [{"outcome": "absent", "box": None}],
            target_accuracy=1,
        )


def test_recorded_branching_regenerates_manifest_from_actual_answers(tmp_path):
    from jev_cookbook import LiveBackend
    from jev_cookbook.fixtures import validate_recipe

    class Client:
        def __init__(self):
            self.count = 0

        def system_one(self, **kwargs):
            self.count += 1
            if "defect" in kwargs["questions"]:
                payload = {"defect": {"type": "box", "box": BOX, "confidence": 0.98}}
            else:
                # Reverse the authored paths: v01 loses its Box; t06 gains one.
                values = (0.01, 0.01, 0.99) if self.count == 1 else (0.99, 0.99, 0.99)
                payload = {
                    name: {"type": "noul", "noul": value}
                    for name, value in zip(("present", "unique", "clear"), values, strict=True)
                }
            return {
                "model": "jev-1.14.0",
                "answers": payload,
                "usage": {"input_tokens": 123, "output_tokens": 4},
            }

    examples = [e for e in load_inputs(RECIPE) if e.id in ("v01", "t06")]
    destination = tmp_path / "capture" / "fixtures" / "responses.json"
    backend = LiveBackend("jev-1.14.0", client=Client(), images=True, max_requests=3)
    manifest = helpers.record_corpus(backend, examples, destination, root=RECIPE)
    assert [len(row["replay_keys"]) for row in manifest] == [1, 2]
    assert backend.requests_made == 3
    captured = json.loads(destination.read_text("utf-8"))
    assert set(captured) == {key for row in manifest for key in row["replay_keys"]}
    assert all(row["model"] == "jev-1.14.0" for row in captured.values())
    assert all(row["usage"]["input_tokens"] == 123 for row in captured.values())
    assert not validate_recipe(destination.parent.parent)


def test_all_present_geometry_counts_review_as_missing_delivery():
    outcomes = [
        helpers.Outcome("located", "test", BOX),
        helpers.Outcome("absent", "test"),
        helpers.Outcome("review", "test"),
        helpers.Outcome("located", "test", BOX),
        helpers.Outcome("located", "test", BOX),
    ]
    labels = [{"outcome": "located", "box": BOX} for _ in range(3)] + [
        {"outcome": "absent", "box": None},
        {"outcome": "review", "box": None},
    ]
    metrics = helpers.summarize(outcomes, labels)
    assert metrics["geometry_n"] == 4 and metrics["present"] == 3 and metrics["absent"] == 1
    assert metrics["mean_iou"] == pytest.approx(1 / 3)
    assert metrics["missed"] == 2 and metrics["accepted_misses"] == metrics["reviewed_present"] == 1
    assert metrics["false_positives"] == metrics["invalid_scene_boxes"] == 1
    assert metrics["resolved_present"] == 2 and metrics["resolved_mean_iou"] == 0.5
    assert metrics["coverage"] == 0.8
