"""Policy, image isolation, and genuinely accepted mistakes."""

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    BoxAnswer,
    DecisionResult,
    NoulAnswer,
    Provenance,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
P = Provenance.synthetic()
BOX = {"left": 0.1, "top": 0.2, "right": 0.15, "bottom": 0.3}


def make_trace(p=0.98, u=0.97, confidence=0.95, box=None):
    first = DecisionResult({"present": NoulAnswer(p, P), "unique": NoulAnswer(u, P)}, "synthetic")
    second = DecisionResult({"component": BoxAnswer(box or BOX, confidence, P)}, "synthetic")
    return helpers.Trace(first, second, 2, ())


def fixtures():
    return load_inputs(RECIPE), load_labels(RECIPE), get_backend(fixtures=responses_path(RECIPE))


@pytest.mark.parametrize(
    "p,u", [(0.02, 0.01), (0.98, 0.02), (0.02, 0.98), (0.61, 0.95), (0.95, 0.64)]
)
def test_box_is_never_requested_without_confident_presence_and_unique_binding(p, u):
    class Spy:
        mode = "synthetic"
        calls = 0

        def decide(self, state, questions, assets):
            self.calls += 1
            assert set(questions) == {"present", "unique"}
            return make_trace(p, u).first

    backend = Spy()
    example = load_inputs(RECIPE)[0]
    trace = helpers.collect(example.fields, backend, RECIPE)
    assert backend.calls == trace.requests == 1
    assert trace.second is None


def test_threshold_is_inclusive_and_missing_confidence_never_passes():
    trace = make_trace(confidence=0.8)
    assert helpers.decide(trace, 0.8).status == "located"
    assert helpers.decide(trace, 0.80001).status == helpers.REVIEW
    assert helpers.decide(make_trace(confidence=None), 0.4).status == helpers.REVIEW


@pytest.mark.parametrize(
    "box",
    [
        {"left": 0, "top": 0.2, "right": 0.1, "bottom": 0.3},
        {"left": 0.2, "top": 0.2, "right": 1, "bottom": 0.3},
        {"left": 0.1, "top": 0.1, "right": 0.9, "bottom": 0.9},
    ],
)
def test_border_and_large_rectangles_never_create_actions(box):
    outcome = helpers.decide(make_trace(box=box), 0.78)
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.simulate("sample", outcome, (640, 420), actions, reviews)
    assert len(actions) == 0
    assert len(reviews) == 1


@pytest.mark.parametrize("bad", [float("nan"), -1, 2, None])
def test_untrusted_malformed_confidence_goes_to_review(bad):
    original = make_trace()
    second = {"component": SimpleNamespace(box=BOX, confidence=bad)}
    trace = helpers.Trace(original.first, second, 2, ())
    assert helpers.decide(trace, 0.78).status == helpers.REVIEW


@pytest.mark.parametrize(
    "box", [dict(BOX, left=float("nan")), dict(BOX, right=0.01), dict(BOX, top=-0.1)]
)
def test_untrusted_invalid_edges_go_to_review(box):
    original = make_trace()
    trace = helpers.Trace(
        original.first, {"component": SimpleNamespace(box=box, confidence=0.99)}, 2, ()
    )
    assert helpers.decide(trace, 0.78).status == helpers.REVIEW


@pytest.mark.parametrize("bad", [0, 0.39, 1.01, float("nan")])
def test_acquisition_floor_and_upper_bound_are_enforced(bad):
    with pytest.raises(ValueError):
        helpers.decide(make_trace(), bad)


def test_annotation_is_simulated_and_absence_has_no_action():
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.simulate("sample", helpers.decide(make_trace(), 0.78), (640, 420), actions, reviews)
    assert actions.to_dicts()[0]["payload"]["pixels"] == [64, 84, 96, 126]
    assert actions.to_dicts()[0]["executed"] is False
    helpers.simulate(
        "absent", helpers.decide(make_trace(0.01, 0.02), 0.78), (640, 420), actions, reviews
    )
    assert len(actions) == 1 and len(reviews) == 0


def test_fixed_targets_and_allowlisted_state():
    assert list(helpers.TARGETS) == ["V-101", "V-102", "C-201", "P-301"]
    fields = dict(load_inputs(RECIPE)[0].fields, label="leak", split="test", coordinates=BOX)
    state, _ = helpers.build_state(fields, RECIPE)
    assert set(state) == {"diagram", "target_label", "target_kind", "scope"}
    assert "assets/" not in str(state)
    with pytest.raises(ValueError):
        helpers.build_state(dict(fields, target="OPEN_ALL"), RECIPE)


def test_replay_keys_bind_questions_target_and_asset_bytes():
    examples, _, backend = fixtures()
    for e in examples:
        state, assets = helpers.build_state(e.fields, RECIPE)
        trace = helpers.collect(e.fields, backend, RECIPE)
        keys = [replay_key(state, helpers.build_questions(), assets=assets)]
        if trace.second is not None:
            keys.append(replay_key(state, helpers.build_box_question(), assets=assets))
        assert tuple(keys) == e.replay_keys
    state, assets = helpers.build_state(examples[0].fields, RECIPE)
    first = replay_key(state, helpers.build_questions(), assets=assets)
    assert (
        replay_key(dict(state, target_label="V-102"), helpers.build_questions(), assets=assets)
        != first
    )
    _, other_assets = helpers.build_state(examples[1].fields, RECIPE)
    different = {next(iter(assets)): next(iter(other_assets.values()))}
    assert replay_key(state, helpers.build_questions(), assets=different) != first


def test_image_content_is_distinct_between_validation_and_test():
    examples = load_inputs(RECIPE)
    by_split = {}
    for e in examples:
        with Image.open(RECIPE / e.fields["image"]) as image:
            assert image.size == (640, 420)
            assert not image.info
            pixels = image.tobytes()
        by_split.setdefault(e.split, set()).add(pixels)
    assert not by_split["validation"] & by_split["test"]


def test_baseline_consumes_only_pixels_and_target():
    assert list(inspect.signature(helpers.baseline).parameters) == ["image", "target"]
    image = Image.new("RGB", (640, 420), helpers.PAPER)
    image.paste(helpers.symbol("valve"), (180, 150))
    from PIL import ImageDraw

    ImageDraw.Draw(image).text((176, 126), "V-101", font=helpers.FONT, fill=helpers.INK)
    assert helpers.baseline(image, "V-101").status == "located"
    assert helpers.baseline(Image.new("RGB", image.size, helpers.PAPER), "V-101").status == "absent"
    names = helpers.baseline.__code__.co_names
    assert all(word not in names for word in ("load_labels", "open", "ROWS", "drawing"))


def test_stored_answers_are_not_all_right():
    examples, labels, backend = fixtures()
    validation = [e for e in examples if e.split == "validation"]
    traces = [helpers.collect(e.fields, backend, RECIPE) for e in validation]
    candidates = [
        (t, labels[e.id])
        for t, e in zip(traces, validation, strict=True)
        if helpers.score(t) is not None
    ]
    threshold = select_confidence_threshold(
        [
            helpers.correct(helpers.decide(t, helpers.ACQUISITION_FLOOR), gold)
            for t, gold in candidates
        ],
        [helpers.score(t) for t, _ in candidates],
        target_accuracy=0.9,
    )
    assert threshold == helpers.choose_threshold(traces, [labels[e.id] for e in validation]) == 0.78
    wrong_and_accepted = []
    for e in examples:
        if e.split != "test":
            continue
        trace = helpers.collect(e.fields, backend, RECIPE, threshold)
        outcome = helpers.decide(trace, threshold)
        if helpers.score(trace) is not None and helpers.score(trace) >= threshold:
            if outcome.status != helpers.REVIEW and not helpers.correct(outcome, labels[e.id]):
                wrong_and_accepted.append(e.id)
    assert wrong_and_accepted == [
        "t05-missed-pump",
        "t08-wrong-binding",
        "t09-junction-false-positive",
    ]


def test_threshold_objective_is_pinned_to_actual_helper_source():
    source = ast.parse(inspect.getsource(helpers.choose_threshold))
    call = next(
        n
        for n in ast.walk(source)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    )
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
    assert keywords == {"target_accuracy": 0.9}


def test_reviews_do_not_count_as_answers_or_absence():
    outcomes = [
        helpers.Outcome("review", None, "unclear"),
        helpers.Outcome("located", BOX, "found"),
    ]
    labels = [{"status": "located", "box": BOX}, {"status": "absent", "box": None}]
    report = helpers.summarize(outcomes, labels)
    assert report["answered"] == 1
    assert report["localization_N"] == 1
    assert report["false_positive_absence"] == 1
    assert report["present_unlocalized_including_review"] == 1
    assert report["accuracy"] == 0


def test_capture_uses_actual_first_answers_before_dependent_boxes(tmp_path):
    class RecordingSpy:
        requests_made = 0
        records = []
        model = "jev-1.14.0"
        seen = []

        def decide(self, state, questions, assets):
            self.requests_made += 1
            self.seen.append(set(questions))
            self.records.append(None)
            assert state["diagram"] in assets
            provenance = Provenance.recorded(self.model, "2026-10-15")
            if "present" in questions:
                p = 0.98 if self.requests_made == 1 else 0.02
                answers = {
                    "present": NoulAnswer(p, provenance),
                    "unique": NoulAnswer(p, provenance),
                }
            else:
                answers = {"component": BoxAnswer(BOX, 0.95, provenance)}
            return DecisionResult(answers, self.model)

    examples = load_inputs(RECIPE)[:2]
    backend = RecordingSpy()
    destination = tmp_path / "capture.json"
    reports = helpers.record_examples(backend, examples, destination, RECIPE, threshold=0.78)
    assert backend.seen == [{"present", "unique"}, {"present", "unique"}, {"component"}]
    assert sum(len(report.written) for report in reports) == backend.requests_made == 3
    replay = get_backend(fixtures=destination)
    assert replay.mode == "recorded"
    assert replay.model == "jev-1.14.0"
    assert helpers.collect(examples[0].fields, replay, RECIPE, threshold=0.78).requests == 2
    assert helpers.collect(examples[1].fields, replay, RECIPE, threshold=0.78).requests == 1


def test_capture_rejects_synthetic_destination_before_any_request():
    with pytest.raises(ValueError, match="fresh or already recorded"):
        helpers.record_examples(None, [], responses_path(RECIPE), RECIPE)
