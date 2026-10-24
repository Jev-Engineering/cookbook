"""Policy, sampling, pixel baseline and replay identity tests."""

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def examples():
    return load_inputs(RECIPE)


def fields():
    return copy.deepcopy(examples()[0].fields)


def answer(choice, probability=0.94):
    return ChoiceAnswer.from_probabilities(
        {o: probability if o == choice else (1 - probability) / 3 for o in helpers.OPTIONS},
        Provenance.synthetic(),
    )


def test_options_and_private_fields_are_not_model_inputs():
    original = fields()
    contaminated = {**original, "label": "closed", "split": "test", "drawing": "opened"}
    state, questions, assets = helpers.build_request(contaminated, RECIPE)
    assert list(questions["transition"].criteria) == ["opened", "closed", "unchanged", "uncertain"]
    assert state == helpers.build_request(original, RECIPE)[0]
    assert set(state) == {"frames", "task"}
    assert all(f["image"].startswith("image:sha256:") for f in state["frames"])
    assert len(assets) == 3


@pytest.mark.parametrize(
    "times",
    [(2, 1, 0), (0, 0, 1), (0, float("nan"), 1), (0, float("inf"), 1), (-1, 0, 1), (False, 1, 2)],
)
def test_invalid_times_are_rejected_before_any_backend_call(times):
    item = fields()
    for frame, time in zip(item["frames"], times, strict=True):
        frame["timestamp_seconds"] = time
    backend = SimpleNamespace(decide=lambda *a, **k: pytest.fail("must not call inference"))
    session = helpers.Session(backend, RECIPE)
    assert session.decide(SimpleNamespace(fields=item)) is None
    result = helpers.route(item, answer("opened", 1.0), 0)
    assert not result.accepted and result.interval is None
    assert session.requests == 0


def test_sampling_uses_actual_times_and_preserves_endpoints():
    demo = next(e for e in examples() if e.id == "d01")
    sampled = helpers.sample_frames(demo.fields)
    assert [f["timestamp_seconds"] for f in sampled] == [8.0, 9.4, 10.8]
    assert sampled == [demo.fields["frames"][i] for i in (0, 2, 4)]
    mutated = copy.deepcopy(demo.fields)
    mutated["frames"][1]["timestamp_seconds"] = 99.0
    with pytest.raises(ValueError, match="strictly increasing"):
        helpers.sample_frames(mutated)


def test_sparse_sampling_and_one_frame_stop_in_python():
    item = fields()
    item["frames"] = item["frames"][:1]
    assert helpers.preflight_reason(item)
    item = fields()
    item["frames"][-1]["timestamp_seconds"] = 40.0
    assert "gap" in helpers.preflight_reason(item)


@pytest.mark.parametrize("choice", ["opened", "closed", "unchanged"])
def test_gate_is_inclusive_and_low_confidence_never_logs_an_observation(choice):
    a = answer(choice)
    assert helpers.route(fields(), a, a.confidence).accepted
    outcome = helpers.route(fields(), a, a.confidence + 1e-8)
    assert not outcome.accepted
    assert outcome.reason == "confidence below the threshold"
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.log_outcome("sample", outcome, a, actions, reviews)
    assert len(actions) == 0 and len(reviews) == 1


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -0.1, 1.1, True, "1"])
def test_missing_or_malformed_confidence_cannot_authorize_an_observation(bad):
    assert not helpers.route(fields(), SimpleNamespace(choice="opened", confidence=bad), 0).accepted


@pytest.mark.parametrize("choice", ["uncertain", "unlock", "other"])
def test_deferral_and_foreign_options_never_pass(choice):
    assert not helpers.route(fields(), SimpleNamespace(choice=choice, confidence=1), 0).accepted


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan"), float("inf"), True])
def test_invalid_threshold_raises(threshold):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route(fields(), answer("opened"), threshold)


def test_accepted_events_only_write_simulation_records_with_interval_bounds():
    a = answer("opened")
    outcome = helpers.route(fields(), a, 0.5)
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.log_outcome("sample", outcome, a, actions, reviews)
    entry = actions.to_dicts()[0]
    assert entry["executed"] is False
    assert entry["kind"] == "record_observation"
    assert entry["payload"]["interval"] == [8.0, 9.4]
    assert len(reviews) == 0


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in examples():
        if helpers.preflight_reason(example.fields):
            assert example.replay_keys == ()
        else:
            state, questions, assets = helpers.build_request(example.fields, RECIPE)
            assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_state_and_image_bytes_both_change_replay_identity(tmp_path):
    item = fields()
    state, questions, assets = helpers.build_request(item, RECIPE)
    original = replay_key(state, questions, assets=assets)
    changed_time = copy.deepcopy(item)
    changed_time["frames"][0]["timestamp_seconds"] = 7.9
    state2, questions2, assets2 = helpers.build_request(changed_time, RECIPE)
    assert replay_key(state2, questions2, assets=assets2) != original
    changed_pixels = copy.deepcopy(item)
    with Image.open(RECIPE / item["frames"][0]["path"]) as image:
        image.putpixel((0, 0), (1, 2, 3))
        image.save(tmp_path / "frame.png")
    changed_pixels["frames"][0]["path"] = str(tmp_path / "frame.png")
    state3, questions3, assets3 = helpers.build_request(changed_pixels, RECIPE)
    assert replay_key(state3, questions3, assets=assets3) != original


def test_no_decoded_image_content_is_shared_between_validation_and_test():
    hashes = {}
    for split in ("validation", "test"):
        hashes[split] = set()
        for example in examples():
            if example.split == split:
                for frame in example.fields["frames"]:
                    with Image.open(RECIPE / frame["path"]) as image:
                        assert image.size == (400, 320)
                        hashes[split].add(hashlib.sha256(image.tobytes()).hexdigest())
    assert not hashes["validation"] & hashes["test"]


def test_budget_cache_and_failed_attempts_are_enforced():
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.Session(backend, RECIPE, max_requests=1)
    first, second = examples()[:2]
    assert session.decide(first) is session.decide(first)
    assert session.requests == 1
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(second)
    assert session.requests == 1

    def fail(*args, **kwargs):
        raise ConnectionError("synthetic failure")

    failed = helpers.Session(SimpleNamespace(decide=fail), RECIPE, max_requests=1)
    with pytest.raises(ConnectionError):
        failed.decide(first)
    with pytest.raises(RuntimeError, match="budget"):
        failed.decide(first)
    assert failed.requests == 1


def test_full_run_uses_exactly_25_distinct_requests():
    session = helpers.Session(get_backend(fixtures=responses_path(RECIPE)), RECIPE)
    for example in examples():
        session.decide(example)
        session.decide(example)
    assert session.requests == 25
    assert len(session.cache) == 25


def test_baseline_reacts_to_door_pixels_and_does_not_read_labels_or_names(tmp_path):
    first, second = examples()[:2]
    assert helpers.baseline(first.fields, (0.12, 25), RECIPE) == "opened"
    assert helpers.baseline(second.fields, (0.12, 25), RECIPE) == "closed"
    item = fields()
    item.update(label="closed", split="untrusted", drawing="occluded")
    for index, frame in enumerate(item["frames"]):
        target = tmp_path / f"arbitrary-{index}.png"
        target.write_bytes((RECIPE / frame["path"]).read_bytes())
        frame["path"] = str(target)
    assert helpers.baseline(item, (0.12, 25), RECIPE) == "opened"
    for frame in item["frames"]:
        frame["path"] = item["frames"][0]["path"]
    assert helpers.baseline(item, (0.12, 25), RECIPE) == "unchanged"


def test_stored_answers_are_not_all_right():
    session = helpers.Session(get_backend(fixtures=responses_path(RECIPE)), RECIPE)
    labels = load_labels(RECIPE)
    validation = [e for e in examples() if e.split == "validation"]
    val_answers = {e.id: session.decide(e)["transition"] for e in validation}
    named = [e for e in validation if val_answers[e.id].choice != "uncertain"]
    threshold = select_confidence_threshold(
        [val_answers[e.id].choice == labels[e.id] for e in named],
        [val_answers[e.id].confidence for e in named],
        target_accuracy=1.0,
    )
    test = [e for e in examples() if e.split == "test"]
    test_answers = {e.id: session.decide(e)["transition"] for e in test}
    wrong_and_confident = [
        e.id
        for e in test
        if test_answers[e.id].choice != labels[e.id]
        and test_answers[e.id].confidence >= threshold
        and helpers.route(e.fields, test_answers[e.id], threshold).accepted
    ]
    assert wrong_and_confident == ["t10"]


def test_notebook_objective_is_target_accuracy():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


@pytest.mark.parametrize("choice,probability", [("uncertain", 1.0), ("unchanged", 0.4)])
def test_routing_demo_cell_handles_a_deferred_live_answer(choice, probability):
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-routing")
    items = examples()
    namespace = {
        "ActionLog": ActionLog,
        "ReviewQueue": ReviewQueue,
        "helpers": helpers,
        "demo": next(e for e in items if e.id == "d01"),
        "demo_result": {"transition": answer(choice, probability)},
        "threshold": 0.7,
        "examples": items,
        "session": SimpleNamespace(decide=lambda e: None),
    }
    exec("".join(cell["source"]), namespace)
    assert len(namespace["actions"]) == 0
    assert len(namespace["reviews"]) == 2
