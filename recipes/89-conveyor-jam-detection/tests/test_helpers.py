"""Interlocks and event policy must hold independently of any visual answer."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import NoulAnswer, Provenance, ScoreAnswer, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
EXAMPLES = load_inputs(RECIPE)


def example(ident):
    return next(e for e in EXAMPLES if e.id == ident)


def answers(visible=0.99, present=0.99, movement=0.01, blocked=False):
    provenance = Provenance.synthetic()
    values = {"visible": visible, "present": present, "movement": movement}
    result = {name: NoulAnswer(value, provenance) for name, value in values.items()}
    result["obstruction"] = ScoreAnswer.from_probabilities(
        [0, 0, 0, 1] if blocked else [1, 0, 0, 0], helpers.RUBRIC, provenance
    )
    return result


def prepare(ident="v04"):
    return helpers.prepare(example(ident).fields, RECIPE)


@pytest.mark.parametrize("ident", ["v06", "v07", "t07"])
@pytest.mark.parametrize("blocked", [False, True])
def test_hard_interlocks_override_certain_answers(ident, blocked):
    assert helpers.route(prepare(ident), answers(blocked=blocked), 0).event == "review"


def test_stationary_does_not_imply_a_jam():
    assert helpers.route(prepare(), answers(), 0.8).event == "halted_cause_unobserved"
    assert helpers.route(prepare("v03"), answers(), 0.8).event == "stopped_as_commanded"
    assert helpers.route(prepare(), answers(blocked=True), 0.8).event == "jam_indication"
    assert helpers.route(prepare("v03"), answers(blocked=True), 0).event == "review"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"visible": 0.01},
        {"present": 0.01, "movement": 0.99},
        {"movement": 0.99, "blocked": True},
        {"movement": 0.5},
    ],
)
def test_inconsistent_or_unobservable_answers_always_review(kwargs):
    assert helpers.route(prepare(), answers(**kwargs), 0).event == "review"


def test_no_parcel_is_a_gated_complete_answer():
    result = answers(present=0.01)
    assert helpers.route(prepare(), result, 0.8).event == "empty_lane"
    result["present"] = NoulAnswer(0.3, Provenance.synthetic())
    assert helpers.route(prepare(), result, 0.8).event == "review"


def test_gate_is_inclusive_and_missing_confidence_cannot_pass():
    result = answers()
    certainty = helpers.candidate(prepare(), result).confidence
    assert helpers.route(prepare(), result, certainty).accepted
    assert not helpers.route(prepare(), result, certainty + 0.0001).accepted
    result["obstruction"] = SimpleNamespace(score=0, confidence=None)
    assert not helpers.route(prepare(), result, 0).accepted


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_threshold_is_rejected(bad):
    with pytest.raises(ValueError):
        helpers.route(prepare(), answers(), bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 2, None, "yes"])
def test_invalid_arbitrary_answers_are_never_flags(bad):
    result = answers(blocked=True)
    result["movement"] = SimpleNamespace(noul=bad)
    assert helpers.route(prepare(), result, 0).event == "review"


@pytest.mark.parametrize(
    "times",
    [
        [0, 0, 1],
        [1, 0.5, 0],
        [-0.1, 0.4, 0.9],
        [0, float("nan"), 1],
        [0, 0.1, 0.2],
        [0, 0.9, 1.4],
        [0, 1.1, 2.2],
    ],
)
def test_bad_timing_is_rejected_before_call(times):
    fields = copy.deepcopy(example("v01").fields)
    for frame, time in zip(fields["frames"], times, strict=True):
        frame["timestamp_seconds"] = time
    with pytest.raises(ValueError):
        helpers.prepare(fields, RECIPE)


def test_sampling_is_bounded_and_checks_discarded_timestamps():
    fields = copy.deepcopy(example("v01").fields)
    first, middle, last = fields["frames"]
    fields["frames"] = [
        first,
        {**middle, "timestamp_seconds": 0.25},
        middle,
        {**middle, "timestamp_seconds": 0.75},
        last,
    ]
    sampled = helpers.prepare(fields, RECIPE)
    assert [f["timestamp_seconds"] for f in sampled.state["frames"]] == [0.0, 0.5, 1.0]
    fields["frames"][1]["timestamp_seconds"] = 2
    with pytest.raises(ValueError, match="increasing"):
        helpers.prepare(fields, RECIPE)
    fields["frames"] = [first] * 10
    with pytest.raises(ValueError, match="3 to 9"):
        helpers.prepare(fields, RECIPE)


@pytest.mark.parametrize(
    "name,value",
    [
        ("operation", "start_motor"),
        ("telemetry_age_seconds", -1),
        ("telemetry_age_seconds", float("nan")),
        ("telemetry_age_seconds", True),
    ],
)
def test_operating_metadata_is_validated(name, value):
    fields = copy.deepcopy(example("v01").fields)
    fields[name] = value
    with pytest.raises(ValueError):
        helpers.prepare(fields, RECIPE)


def test_inference_state_excludes_authoring_and_gold_fields():
    fields = copy.deepcopy(example("v01").fields)
    original = helpers.prepare(fields, RECIPE)
    fields.update(
        {
            "id": "gold-id",
            "split": "test",
            "label": "jam_indication",
            "scene": "pile",
            "drawing_parameters": {"speed": 0},
        }
    )
    changed = helpers.prepare(fields, RECIPE)
    assert changed.state == original.state
    assert "assets/" not in json.dumps(changed.state)
    assert set(changed.state) == {
        "frames",
        "operation",
        "telemetry_age_seconds",
        "sampled_duration_seconds",
        "view",
    }


def test_replay_identity_binds_pixels_order_and_context(tmp_path):
    prepared = prepare("v01")
    questions = helpers.build_questions()
    key = replay_key(prepared.state, questions, assets=prepared.assets)
    state = copy.deepcopy(prepared.state)
    state["operation"] = "stopped"
    assert replay_key(state, questions, assets=prepared.assets) != key
    state = copy.deepcopy(prepared.state)
    state["frames"] = list(reversed(state["frames"]))
    assert replay_key(state, questions, assets=prepared.assets) != key
    fields = copy.deepcopy(example("v01").fields)
    (tmp_path / "assets").mkdir()
    for row in fields["frames"]:
        with Image.open(RECIPE / row["path"]) as image:
            image.putpixel((0, 0), (1, 2, 3))
            image.save(tmp_path / row["path"])
    altered = helpers.prepare(fields, tmp_path)
    assert replay_key(altered.state, questions, assets=altered.assets) != key


def test_all_fixture_replay_keys_and_split_image_lineage():
    references = {}
    for e in EXAMPLES:
        prepared = helpers.prepare(e.fields, RECIPE)
        keys = (
            ()
            if prepared.interlock
            else (replay_key(prepared.state, helpers.build_questions(), assets=prepared.assets),)
        )
        assert e.replay_keys == keys
        if e.split != "demo":
            for ref in prepared.assets:
                assert references.get(ref, e.split) == e.split
                references[ref] = e.split


def test_pixel_baseline_uses_displacement_not_fields_or_gold():
    prepared = prepare("v01")
    features = helpers.pixel_features(prepared)
    assert features["max_displacement_pixels"] == 24.0
    assert helpers.pixel_baseline(prepared, 2) == "movement_observed"
    assert helpers.pixel_baseline(prepare("v03"), 2) == "stopped_as_commanded"
    assert helpers.pixel_baseline(prepare("v02"), 2) == "jam_indication"
    assert helpers.pixel_baseline(prepare("t10"), 2) == "empty_lane"
    assert helpers.pixel_baseline(prepare("v09"), 6) == "halted_cause_unobserved"


def test_budget_interlocks_and_cache_hold_without_live_calls():
    class CountingBackend:
        calls = 0

        def decide(self, state, questions, assets):
            self.calls += 1
            return answers()

    backend = CountingBackend()
    session = helpers.Session(backend, max_requests=1)
    assert session.decide(example("v06"), RECIPE)[1] is None
    session.decide(example("v01"), RECIPE)
    session.decide(example("v01"), RECIPE)
    assert backend.calls == 1
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(example("v02"), RECIPE)
    assert backend.calls == 1


def test_failed_attempt_consumes_budget_and_cannot_be_retried_unboundedly():
    class FailingBackend:
        def decide(self, state, questions, assets):
            raise ValueError("simulated transport error")

    session = helpers.Session(FailingBackend(), max_requests=1)
    with pytest.raises(ValueError):
        session.decide(example("v01"), RECIPE)
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(example("v01"), RECIPE)
    assert session.calls == 1


def test_dispatch_has_only_simulated_flags_and_real_review_accounting():
    actions, reviews = ActionLog(), ReviewQueue()
    for event in helpers.EVENTS:
        helpers.dispatch("sequence", helpers.Outcome(event, "fixture test", 1.0), actions, reviews)
    assert len(actions) == len(reviews) == 1
    assert actions.to_dicts()[0]["kind"] == "simulated_jam_flag"
    assert actions.to_dicts()[0]["executed"] is False
    with pytest.raises(ValueError):
        helpers.dispatch("sequence", helpers.Outcome("restart_belt", "bad", 1), actions, reviews)


def test_stored_answers_are_not_all_right():
    session = helpers.Session(get_backend(fixtures=responses_path(RECIPE)))
    labels = load_labels(RECIPE)
    validation = [e for e in EXAMPLES if e.split == "validation"]
    eligible = []
    for e in validation:
        candidate = helpers.candidate(*session.decide(e, RECIPE))
        if candidate.accepted:
            eligible.append((candidate, labels[e.id]["event"]))
    threshold = select_confidence_threshold(
        [out.event == gold for out, gold in eligible],
        [out.confidence for out, _ in eligible],
        target_accuracy=1.0,
    )
    test = [e for e in EXAMPLES if e.split == "test"]
    decisions = [(e, helpers.route(*session.decide(e, RECIPE), threshold)) for e in test]
    wrong_and_confident = [
        e.id
        for e, out in decisions
        if out.accepted and out.event != labels[e.id]["event"] and out.confidence >= threshold
    ]
    assert wrong_and_confident == ["t09"]


def test_notebook_pins_the_selection_objective_and_test_follows_freeze():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "evaluation-validation")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    assert 'e.split == "validation"' in source
    assert "max(baseline_candidates" in source
    assert "key=lambda row: (row[1], -row[0])" in source
    ids = [c["id"] for c in notebook["cells"]]
    assert ids.index("evaluation-validation") < ids.index("evaluation-test")


def test_recording_triples_match_the_notebook_and_fit_budget():
    triples = helpers.recording_requests(EXAMPLES, RECIPE)
    assert len(triples) == 22
    assert len(triples) <= helpers.MAX_REQUESTS
    keys = {replay_key(state, questions, assets=assets) for state, questions, assets in triples}
    assert keys == {key for e in EXAMPLES for key in e.replay_keys}


def test_authored_png_assets_reproduce_byte_for_byte():
    import hashlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location(
        "conveyor_generator", RECIPE / "build_fixtures.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    for ident, _split, scene, seed, _operation, _age, _label, _profile in generator.ROWS:
        for frame in range(3):
            opaque = hashlib.sha256(f"conveyor:{ident}:{frame}".encode()).hexdigest()[:16]
            buffer = io.BytesIO()
            generator.frame_image(scene, seed, frame).save(buffer, format="PNG", optimize=False)
            assert buffer.getvalue() == (RECIPE / "assets" / f"{opaque}.png").read_bytes()


def test_asset_path_escape_and_mismatched_sizes_are_rejected(tmp_path):
    fields = copy.deepcopy(example("v01").fields)
    fields["frames"][0]["path"] = "../outside.png"
    with pytest.raises(ValueError, match="inside"):
        helpers.prepare(fields, RECIPE)
    fields = copy.deepcopy(example("v01").fields)
    (tmp_path / "assets").mkdir()
    for index, frame in enumerate(fields["frames"]):
        with Image.open(RECIPE / frame["path"]) as image:
            if index == 2:
                image = image.resize((400, 320))
            image.save(tmp_path / frame["path"])
    with pytest.raises(ValueError, match="equal dimensions"):
        helpers.prepare(fields, tmp_path)


@pytest.mark.parametrize("blocked", [False, True])
def test_unmet_validation_objective_disables_acceptance(blocked):
    result = answers(blocked=blocked)
    assert helpers.route(prepare(), result, None).event == "review"
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    source = "".join(
        next(c for c in notebook["cells"] if c["id"] == "evaluation-validation")["source"]
    )
    assert "except ValueError:" in source
    assert "threshold = None" in source
