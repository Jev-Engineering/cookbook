"""Exercise progression, evidence boundaries, request budgets and imperfect held-out responses."""

import ast
import base64
import copy
import inspect
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ReplayBackend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answers(stages=("base", "posts", "bridge"), confidence=1.0):
    return [SimpleNamespace(choice=stage, confidence=confidence) for stage in stages]


def test_allowed_steps_and_stable_sequences():
    for stages in (("base", "posts", "bridge"), ("posts", "bridge", "cap"), ("cap",) * 3):
        result = helpers.route(answers(stages), 0.8)
        assert result.accepted and result.stage == stages[-1]
    assert helpers.event_for(["posts", "posts", "posts"]) == "stable"


@pytest.mark.parametrize(
    "stages,event",
    [
        (("cap", "bridge", "posts"), "regression"),
        (("base", "bridge", "cap"), "skipped"),
        (("base", "cap", "posts"), "regression"),
        (("posts", "bridge", "uncertain"), "unresolved"),
        (("posts", "unknown_parts", "cap"), "unresolved"),
        (("posts", "grant_permission", "cap"), "unresolved"),
        (("posts", "cap"), "unresolved"),
    ],
)
def test_interlocks_hold_even_at_perfect_confidence(stages, event):
    result = helpers.route(answers(stages), 0.0)
    assert not result.accepted and result.stage == "review" and result.event == event
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.apply_outcome("sample", result, actions, reviews)
    assert len(actions) == 0 and len(reviews) == 1


@pytest.mark.parametrize("confidence", [None, True, False, float("nan"), float("inf"), -1, 2, 0.79])
def test_every_frame_must_have_finite_sufficient_confidence(confidence):
    for index in range(3):
        values = answers()
        values[index].confidence = confidence
        assert not helpers.route(values, 0.8).accepted


def test_inclusive_gate_and_invalid_thresholds():
    assert helpers.route(answers(confidence=0.8), 0.8).accepted
    for threshold in (-0.1, 1.1, float("nan"), float("inf"), None, True, False):
        with pytest.raises(ValueError):
            helpers.route(answers(), threshold)
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.apply_outcome("sample", helpers.route(answers(), 0.8), actions, reviews)
    assert actions.to_dicts()[0]["executed"] is False
    assert len(reviews) == 0


def test_every_replay_key_matches_pixels_state_and_questions():
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert len(backend.decide(state, questions, assets=assets).answers) == 3
        assert set(state) == {"assembly", "frames"}
        assert all(
            list(q.criteria) == ["base", "posts", "bridge", "cap", "unknown_parts", "uncertain"]
            for q in questions.values()
        )


def test_labels_and_draw_metadata_do_not_enter_requests():
    example = load_inputs(RECIPE)[0]
    changed = dict(example.fields, label="cap", split="test", seed=999, scene="foreign")
    assert helpers.build_request(changed, RECIPE) == helpers.build_request(example.fields, RECIPE)
    state, _, _ = helpers.build_request(changed, RECIPE)
    assert all(set(f) == {"timestamp_seconds", "image"} for f in state["frames"])
    assert all(f["image"].startswith("image:sha256:") for f in state["frames"])


def test_timestamp_order_and_asset_bytes_affect_identity():
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields, RECIPE)
    key = replay_key(state, questions, assets=assets)
    changed = copy.deepcopy(state)
    changed["frames"][1]["timestamp_seconds"] += 0.1
    assert replay_key(changed, questions, assets=assets) != key
    changed = copy.deepcopy(assets)
    ref = next(iter(changed))
    with Image.open(io.BytesIO(base64.b64decode(changed[ref]["data_base64"]))) as source:
        image = source.convert("RGB")
    image.putpixel((0, 0), (1, 2, 3))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    changed[ref]["data_base64"] = base64.b64encode(buffer.getvalue()).decode()
    assert replay_key(state, questions, assets=changed) != key
    for bad_times in ((0, 0, 1), (1, 0, 2), (0, float("nan"), 2)):
        fields = copy.deepcopy(example.fields)
        for frame, timestamp in zip(fields["frames"], bad_times, strict=True):
            frame["timestamp_seconds"] = timestamp
        with pytest.raises(ValueError):
            helpers.build_request(fields, RECIPE)


def test_sequences_have_disjoint_pixels_across_splits():
    hashes = {}
    for example in load_inputs(RECIPE):
        for frame in example.fields["frames"]:
            with Image.open(RECIPE / frame["path"]) as image:
                assert image.size == (384, 320)
                pixels = image.tobytes()
            assert pixels not in hashes, "every camera texture is independently generated"
            hashes[pixels] = example.split


def test_budget_cache_and_failure_accounting():
    examples = load_inputs(RECIPE)
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    runner = helpers.SequenceRunner(backend, RECIPE, max_requests=1)
    assert runner.decide(examples[0]) is runner.decide(examples[0])
    assert runner.attempts == 1
    with pytest.raises(RuntimeError, match="budget"):
        runner.decide(examples[1])

    class Failing:
        def decide(self, *args, **kwargs):
            raise OSError("simulated transport failure")

    runner = helpers.SequenceRunner(Failing(), RECIPE, max_requests=1)
    with pytest.raises(OSError):
        runner.decide(examples[0])
    with pytest.raises(RuntimeError, match="budget"):
        runner.decide(examples[0])
    assert runner.attempts == 1


def test_baseline_reads_pixels_and_confuses_loose_components(tmp_path):
    examples = {e.id: e for e in load_inputs(RECIPE)}
    frame = examples["t10"].fields["frames"][-1]
    assert helpers.pixel_stage(RECIPE / frame["path"]) == "cap"
    renamed = tmp_path / "unrelated.png"
    renamed.write_bytes((RECIPE / frame["path"]).read_bytes())
    assert helpers.pixel_stage(renamed) == "cap"
    Image.new("RGB", (384, 320), "white").save(renamed)
    assert helpers.pixel_stage(renamed) == "base"
    assert "labels" not in inspect.getsource(helpers.pixel_stage)


def test_stored_answers_are_not_all_right():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    runner = helpers.SequenceRunner(
        ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json"), RECIPE
    )
    validation = [e for e in examples if e.split == "validation"]
    val_answers = [helpers.sequence_answers(runner.decide(e)) for e in validation]
    eligible = [
        (a, labels[e.id])
        for e, a in zip(validation, val_answers, strict=True)
        if helpers.route(a, 0).accepted
    ]
    threshold = select_confidence_threshold(
        [[a.choice for a in seq] == label["stages"] for seq, label in eligible],
        [helpers.sequence_confidence(seq) for seq, _ in eligible],
        target_accuracy=1.0,
    )
    assert threshold == helpers.select_policy(val_answers, [labels[e.id] for e in validation])
    wrong_and_accepted = []
    for example in (e for e in examples if e.split == "test"):
        seq = helpers.sequence_answers(runner.decide(example))
        result = helpers.route(seq, threshold)
        if (
            helpers.sequence_confidence(seq) >= threshold
            and result.accepted
            and result.stage != labels[example.id]["stages"][-1]
        ):
            wrong_and_accepted.append(example.id)
    assert wrong_and_accepted == ["t10"]


def test_policy_objective_is_pinned_to_actual_helper_source():
    source = inspect.getsource(helpers.select_policy)
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    tree = ast.parse(source)
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    )
    assert [(kw.arg, ast.literal_eval(kw.value)) for kw in call.keywords] == [
        ("target_accuracy", 1.0)
    ]


def test_notebook_freezes_policy_before_first_test_access():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert source.index("threshold = helpers.select_policy") < source.index(
        'select_split(examples, "test")'
    )
