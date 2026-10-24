"""Policy interlocks, data separation, crop lineage and held-out failure tests."""

import ast
import hashlib
import importlib.util
import inspect
import io
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    BoxAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    ReplayMiss,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, select_split
from jev_cookbook.vision import image_asset, image_reference, validate_image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
EXAMPLES = load_inputs(RECIPE)
LABELS = load_labels(RECIPE)
DEMO = next(e for e in EXAMPLES if e.id == "d01")
P = Provenance.synthetic()
BOX = dict(left=0.3, top=0.2, right=0.6, bottom=0.7)


def backend():
    return helpers.CachedBackend(get_backend(fixtures=RECIPE / "fixtures" / "responses.json"))


class FakeBackend:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def decide(self, state, questions, *, assets):
        self.calls.append((state, questions, assets))
        answers = {}
        for key in questions:
            if key == "target":
                answers[key] = BoxAnswer(BOX, 0.99, P)
            else:
                answers[key] = NoulAnswer(0.01 if key in helpers.EDGES else 0.99, P)
            answers[key] = self.overrides.get(key, answers[key])
        return SimpleNamespace(answers=answers)


@pytest.mark.parametrize(
    "p,expected", [(0, "absent"), (0.1, "review"), (0.5, "review"), (0.88, "review")]
)
def test_presence_guard_blocks_box(p, expected):
    fake = FakeBackend(
        {"present": NoulAnswer(p, P), "unique": NoulAnswer(0.01 if p < 0.5 else 0.99, P)}
    )
    result = helpers.run(DEMO.fields, fake, 0.83, RECIPE)
    assert result.outcome == expected
    assert len(fake.calls) == 1


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -1, 1.1, "high", True])
def test_missing_or_invalid_box_confidence_never_accepts(confidence):
    fake = FakeBackend({"target": SimpleNamespace(box=BOX, confidence=confidence)})
    outcome = helpers.run(DEMO.fields, fake, 0.83, RECIPE)
    assert outcome.outcome == "review"
    assert outcome.requests == 2


@pytest.mark.parametrize("bad", [None, {}, {**BOX, "right": 0.2}, {**BOX, "left": -1}])
def test_invalid_coordinates_go_to_review(bad):
    result = helpers.run(
        DEMO.fields,
        FakeBackend({"target": SimpleNamespace(box=bad, confidence=0.99)}),
        0.83,
        RECIPE,
    )
    assert result.outcome == "review"


@pytest.mark.parametrize("stage", ["left", "right", "top", "bottom", "complete", "identity"])
@pytest.mark.parametrize("value", [None, float("nan"), 1.01, 0.5])
def test_any_uncertain_or_invalid_independent_judgment_goes_to_review(stage, value):
    result = helpers.run(
        DEMO.fields, FakeBackend({stage: SimpleNamespace(noul=value)}), 0.83, RECIPE
    )
    assert result.outcome == "review"


def test_edge_questions_are_batched_and_crop_evaluation_is_dependent():
    fake = FakeBackend()
    result = helpers.run(DEMO.fields, fake, 0.83, RECIPE)
    assert result.outcome == "located"
    assert [set(q) for _, q, _ in fake.calls] == [
        {"present", "unique"},
        {"target"},
        set(helpers.EDGES),
        {"identity", "complete"},
    ]
    assert "candidate" not in fake.calls[1][0]
    assert fake.calls[2][0]["candidate"] == BOX
    assert set(fake.calls[3][0]) == {"crop"}


@pytest.mark.parametrize("cap", range(7))
def test_request_budget_holds_for_arbitrary_answers(cap):
    fake = FakeBackend({"bottom": NoulAnswer(1, P)})
    result = helpers.run(DEMO.fields, fake, 0.83, RECIPE, max_requests=cap)
    assert result.outcome == "review"
    assert len(fake.calls) <= cap
    assert result.adjustments <= helpers.MAX_ADJUSTMENTS


@pytest.mark.parametrize("bad", [-1, 7, True, 2.5])
def test_invalid_request_limits_raise_before_inference(bad):
    fake = FakeBackend()
    with pytest.raises(ValueError):
        helpers.run(DEMO.fields, fake, 0.83, RECIPE, max_requests=bad)
    assert not fake.calls


def test_growth_area_and_boundary_interlocks():
    flags = dict.fromkeys(helpers.EDGES, True)
    large = dict(left=0.01, top=0.01, right=0.99, bottom=0.99)
    assert helpers.adjust_box(large, flags, large)[0] is None
    boundary = {**BOX, "left": 0}
    assert (
        helpers.adjust_box(
            boundary, {**dict.fromkeys(helpers.EDGES, False), "left": True}, boundary
        )[0]
        is None
    )
    assert helpers.adjust_box(BOX, flags, dict(left=0.4, top=0.3, right=0.5, bottom=0.4))[0] is None
    changed, _ = helpers.adjust_box(
        BOX, {**dict.fromkeys(helpers.EDGES, False), "bottom": True}, BOX
    )
    assert changed["bottom"] > BOX["bottom"]
    assert all(changed[edge] == BOX[edge] for edge in ("left", "top", "right"))


def test_threshold_is_inclusive_and_invalid_thresholds_fail():
    fake = FakeBackend({"target": BoxAnswer(BOX, 0.83, P)})
    assert helpers.run(DEMO.fields, fake, 0.83, RECIPE).outcome == "located"
    assert helpers.run(DEMO.fields, fake, 0.831, RECIPE).outcome == "review"
    for bad in [None, float("nan"), -0.1, 0.49, 1.01, True]:
        with pytest.raises(ValueError):
            helpers.run(DEMO.fields, fake, bad, RECIPE)


def test_exact_dependency_paths_replay_and_never_receive_gold_or_split():
    cached = backend()
    threshold, _ = helpers.choose_threshold(
        select_split(EXAMPLES, "validation"), LABELS, cached, RECIPE
    )
    for example in EXAMPLES:
        gate = threshold if example.split == "test" else 0.5
        result = helpers.run(example.fields, cached, gate, RECIPE)
        keys = []

        class Capture:
            def decide(self, state, questions, *, assets, captured=keys):
                captured.append(replay_key(state, questions, assets=assets))
                assert set(state) <= {"image", "original", "crop", "candidate", "crop_display"}
                assert "data_base64" not in json.dumps(state)
                return cached.decide(state, questions, assets=assets)

        repeated = helpers.run(
            {**example.fields, "gold": LABELS.get(example.id), "split": "ignored"},
            Capture(),
            gate,
            RECIPE,
        )
        assert tuple(keys) == example.replay_keys
        assert repeated.outcome == result.outcome
    assert len(cached.cache) == 85


def test_state_and_image_content_both_change_replay_identity(tmp_path):
    replay = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    state, assets = helpers.build_state(DEMO.fields, RECIPE)
    questions = helpers.build_questions()
    replay.decide(state, questions, assets=assets)
    with pytest.raises(ReplayMiss):
        replay.decide({**state, "context": "different bench"}, questions, assets=assets)
    with Image.open(RECIPE / DEMO.fields["image"]) as opened:
        image = opened.convert("RGB")
    image.putpixel((5, 5), (1, 2, 3))
    image.save(tmp_path / "changed.png")
    asset = image_asset(tmp_path / "changed.png")
    with pytest.raises(ReplayMiss):
        replay.decide(state, questions, assets={state["image"]: asset})
    assert image_reference(asset) != state["image"]


def test_crops_are_real_valid_assets_and_independent_source_images_have_no_split_leak():
    hashes = {}
    for example in EXAMPLES:
        payload = validate_image_asset(image_asset(RECIPE / example.fields["image"]))
        digest = hashlib.sha256(payload).hexdigest()
        assert digest not in hashes
        hashes[digest] = example.split
    with Image.open(RECIPE / DEMO.fields["image"]) as image:
        first = helpers.crop_asset(image, BOX)
        second = helpers.crop_asset(image, {**BOX, "bottom": 0.8})
    assert image_reference(first) != image_reference(second)
    with Image.open(io.BytesIO(validate_image_asset(first))) as image:
        assert image.size == (480, 360)


def test_pixel_baseline_reads_pixels_and_is_invariant_to_labels_and_filename(tmp_path):
    fields = DEMO.fields
    baseline = helpers.pixel_baseline(fields, RECIPE)
    assert baseline is not None
    shutil.copyfile(RECIPE / fields["image"], tmp_path / "renamed.png")
    assert (
        helpers.pixel_baseline({"image": "renamed.png", "box": None, "split": "test"}, tmp_path)
        == baseline
    )
    Image.new("RGB", (480, 360), "white").save(tmp_path / "renamed.png")
    assert helpers.pixel_baseline({"image": "renamed.png"}, tmp_path) is None
    source = inspect.getsource(helpers.pixel_baseline)
    assert "labels" not in source.split('"""')[-1]
    assert "build_fixtures" not in source


def test_stored_answers_are_not_all_right():
    cached = backend()
    validation = select_split(EXAMPLES, "validation")
    traces = [helpers.run(e.fields, cached, 0.5, RECIPE) for e in validation]
    eligible = [(e, r) for e, r in zip(validation, traces, strict=True) if r.outcome != "review"]
    threshold = select_confidence_threshold(
        [helpers.correct(r, LABELS[e.id]) for e, r in eligible],
        [r.confidence for _, r in eligible],
        target_accuracy=1.0,
    )
    assert helpers.choose_threshold(validation, LABELS, cached, RECIPE)[0] == threshold
    failures = []
    for example in select_split(EXAMPLES, "test"):
        result = helpers.run(example.fields, cached, threshold, RECIPE)
        if result.outcome != "review" and result.confidence >= threshold:
            if not helpers.correct(result, LABELS[example.id]):
                failures.append(example.id)
    assert set(failures) == {"t07", "t08", "t12"}


def test_threshold_objective_is_pinned_to_actual_source():
    source = inspect.getsource(helpers.choose_threshold)
    assert "target_accuracy=1.0" in source
    calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert {k.arg: ast.literal_eval(k.value) for k in calls[0].keywords} == {"target_accuracy": 1.0}


def test_reports_use_actual_outcomes_and_simulated_logs_keep_review_separate():
    cached = backend()
    threshold, _ = helpers.choose_threshold(
        select_split(EXAMPLES, "validation"), LABELS, cached, RECIPE
    )
    examples = select_split(EXAMPLES, "test")
    outcomes = [helpers.run(e.fields, cached, threshold, RECIPE) for e in examples]
    report = helpers.report(outcomes, [LABELS[e.id] for e in examples])
    assert (report["answered"], report["review"]) == (9, 3)
    assert report["resolved_localization"]["false_positives"] == 1
    assert report["resolved_localization"]["missed"] == 1
    assert report["initial_clipped"] == 6 and report["final_clipped"] == 1
    assert report["accepted_accuracy"] == pytest.approx(2 / 3)
    actions, reviews = helpers.simulate(examples, outcomes)
    assert len(reviews) == 3
    assert len(actions) == 7
    assert all(not a["executed"] for a in actions.to_dicts())
    assert not {r["item"]["id"] for r in reviews.to_dicts()} & {
        a["payload"]["id"] for a in actions.to_dicts()
    }


def test_live_recording_adapter_keeps_the_same_asset_bound_triples(tmp_path, monkeypatch):
    calls = []

    def fake_record(backend, requests, path):
        for state, questions, assets in requests:
            calls.append((state, questions, assets))
            result = DecisionResult(
                {"present": NoulAnswer(0.98, P), "unique": NoulAnswer(0.98, P)}, "synthetic"
            )
            path.write_text(
                json.dumps({replay_key(state, questions, assets=assets): result.to_dict()})
            )

    monkeypatch.setattr(helpers, "record", fake_record)
    wrapper = helpers.RecordingBackend(object(), tmp_path / "responses.json")
    state, assets = helpers.build_state(DEMO.fields, RECIPE)
    result = wrapper.decide(state, helpers.build_questions(), assets=assets)
    assert result["present"].noul == 0.98
    assert calls[0][0] == state and calls[0][2] == assets


def test_authored_assets_reproduce_without_existing_images(tmp_path):
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, tmp_path / name)
    spec = importlib.util.spec_from_file_location(
        "fixture84_assets", tmp_path / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.build_assets(module.ROWS)
    expected = sorted(p.name for p in (RECIPE / "assets").glob("*.png"))
    assert sorted(p.name for p in (tmp_path / "assets").glob("*.png")) == expected
    assert all(
        (tmp_path / "assets" / name).read_bytes() == (RECIPE / "assets" / name).read_bytes()
        for name in expected
    )


@pytest.mark.parametrize(
    "present,unique,reason",
    [
        (0.98, 0.02, "multiple targets"),
        (0.02, 0.98, "inconsistent"),
        (0.98, 0.5, "confidence below"),
    ],
)
def test_nonunique_or_inconsistent_presence_never_becomes_absence(present, unique, reason):
    fake = FakeBackend({"present": NoulAnswer(present, P), "unique": NoulAnswer(unique, P)})
    result = helpers.run(DEMO.fields, fake, 0.83, RECIPE)
    assert result.outcome == "review" and reason in result.reason
    assert result.requests == 1


def test_confidently_correct_two_clamp_fixture_goes_to_review():
    example = next(e for e in EXAMPLES if e.id == "t09")
    result = helpers.run(example.fields, backend(), 0.83, RECIPE)
    assert result.trace[0]["result"]["present"].noul == 0.98
    assert result.trace[0]["result"]["unique"].noul == 0.02
    assert result.outcome == "review" and result.requests == 1
