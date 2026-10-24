"""Evidence policy, isolation, budgets and deliberately accepted held-out mistakes."""

import copy
import inspect
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def data():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    results = {}
    for e in examples:
        state, questions, assets = helpers.build_request(e.fields, RECIPE)
        results[e.id] = backend.decide(state, questions, assets=assets)
    return examples, labels, results


def answers(values):
    return {name: SimpleNamespace(noul=p) for name, p in zip(helpers.CLAIMS, values, strict=True)}


def test_replay_keys_bind_current_questions_and_assets():
    for e in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(e.fields, RECIPE)
        assert e.replay_keys == (replay_key(state, questions, assets=assets),)
        assert len(questions) == 4
        assert all(q.to_dict()["type"] == "noul" for q in questions.values())


def test_state_and_image_bytes_change_replay_identity(tmp_path):
    fields = copy.deepcopy(load_inputs(RECIPE)[0].fields)
    state, questions, assets = helpers.build_request(fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    state["description"] += " More legitimate context."
    assert replay_key(state, questions, assets=assets) != original
    path = tmp_path / fields["screenshot"]
    path.parent.mkdir()
    with Image.open(RECIPE / fields["screenshot"]) as source:
        altered = source.copy()
        altered.putpixel((0, 0), (123, 87, 99))
        altered.save(path)
    new_state, new_questions, new_assets = helpers.build_request(fields, tmp_path)
    assert replay_key(new_state, new_questions, assets=new_assets) != original


def test_request_ignores_gold_drawing_and_split_metadata():
    original = load_inputs(RECIPE)[0].fields
    fields = {**original, "gold": "not_supported", "split": "test", "rendering": "success"}
    assert helpers.build_request(fields, RECIPE) == helpers.build_request(original, RECIPE)
    state, _questions, _assets = helpers.build_request(fields, RECIPE)
    assert not {"gold", "split", "rendering", "screenshot_path"} & state.keys()


@pytest.mark.parametrize("values", list(itertools.product((0.0, 0.5, 1.0), repeat=4)))
def test_artifact_mismatch_cannot_be_overridden_by_any_answer(values):
    fields = copy.deepcopy(load_inputs(RECIPE)[0].fields)
    fields["capture_manifest"]["build"] = "another-build"
    route = helpers.route("r", fields, answers(values), 0.6, "evidence")
    assert route.outcome == helpers.REVIEW


@pytest.mark.parametrize("value", (None, float("nan"), float("inf"), -0.01, 1.01, True, "yes"))
def test_invalid_probability_always_goes_to_review(value):
    fields = load_inputs(RECIPE)[0].fields
    assert (
        helpers.route("r", fields, answers((value, 0.99, 0.99, 0.99)), 0.6, "ref").outcome
        == "review"
    )


def test_missing_answer_and_exact_tie_are_reviews():
    fields = load_inputs(RECIPE)[0].fields
    assert helpers.route("r", fields, {}, 0.6, "ref").outcome == "review"
    assert helpers.route("r", fields, answers((0.5, 1, 1, 1)), 0, "ref").outcome == "review"


@pytest.mark.parametrize("bits", ((1, 0, 1, 1), (0, 0, 1, 1), (0, 1, 0, 1), (1, 1, 1, 0)))
def test_conflicting_log_only_missing_only_and_wrong_view_evidence_need_review(bits):
    fields = load_inputs(RECIPE)[0].fields
    assert helpers.route("r", fields, answers(bits), 0.6, "ref").outcome == "review"


@pytest.mark.parametrize("variation", ("build", "run", "stale", "future", "log_build"))
def test_metadata_mismatch_fixture_is_forced_review(variation):
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("bug93_builder", RECIPE / "build_fixtures.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    row = next(row for row in module.ROWS if row[3] == variation)
    assert helpers.artifact_problem(module.fields_for(row)) is not None


def test_budget_cache_and_failed_attempt_accounting():
    request = helpers.build_request(load_inputs(RECIPE)[0].fields, RECIPE)
    backend = get_backend(fixtures=RECIPE / "fixtures" / "responses.json")
    session = helpers.RequestSession(backend, max_requests=1)
    assert session.decide(request) is session.decide(request)
    assert session.attempts == 1
    other = helpers.build_request(load_inputs(RECIPE)[1].fields, RECIPE)
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(other)
    assert session.attempts == 1
    broken = SimpleNamespace(
        decide=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("broken"))
    )
    failed = helpers.RequestSession(broken, max_requests=1)
    with pytest.raises(ValueError, match="broken"):
        failed.decide(request)
    assert failed.attempts == 1
    with pytest.raises(RuntimeError, match="budget"):
        failed.decide(request)


def test_baseline_reads_pixels_and_log_text_not_labels_or_path_names(tmp_path):
    examples = load_inputs(RECIPE)
    positive = next(e for e in examples if e.id == "v01")
    negative = next(e for e in examples if e.id == "v02")
    fields = copy.deepcopy(positive.fields)
    assert helpers.baseline(fields, RECIPE)[0] == "supported"
    (tmp_path / "assets").mkdir()
    destination = tmp_path / fields["screenshot"]
    destination.write_bytes((RECIPE / negative.fields["screenshot"]).read_bytes())
    assert helpers.baseline(fields, tmp_path)[0] == "review"
    for log in fields["log_events"]:
        log["code"] = "SAVE_OK"
        log["message"] = "Draft saved successfully."
    assert helpers.baseline(fields, tmp_path)[0] == "not_supported"
    fields.update(gold="supported", split="validation", rendering="failure")
    assert helpers.baseline(fields, tmp_path)[0] == "not_supported"
    renamed = {**fields, "screenshot": "assets/renamed.png"}
    (tmp_path / renamed["screenshot"]).write_bytes(destination.read_bytes())
    assert helpers.baseline(renamed, tmp_path) == helpers.baseline(fields, tmp_path)


def test_dispatch_preserves_evidence_and_never_executes():
    examples, _labels, results = data()
    queue, log = ReviewQueue(), ActionLog()
    for ident in ("d01", "d02"):
        e = next(e for e in examples if e.id == ident)
        state, _q, _assets = helpers.build_request(e.fields, RECIPE)
        routing = helpers.route(e.id, e.fields, results[e.id].answers, 0.68, state["screenshot"])
        helpers.dispatch(routing, results[e.id], queue, log)
    assert len(queue) == len(log) == 1
    assert all(entry["executed"] is False for entry in log.to_dicts())
    assert queue.to_dicts()[0]["item"]["screenshot"].startswith("image:sha256:")
    assert set(queue.to_dicts()[0]["answer"]["answers"]) == set(helpers.CLAIMS)


def test_stored_answers_are_not_all_right():
    examples, labels, results = data()
    validation = [e for e in examples if e.split == "validation"]
    correct, certainty = helpers.claim_pool(validation, labels, results)
    threshold = select_confidence_threshold(correct, certainty, target_accuracy=0.95)
    assert threshold == helpers.select_policy(validation, labels, results)
    wrong_accepted = []
    for e in examples:
        if e.split != "test":
            continue
        routing = helpers.route(e.id, e.fields, results[e.id].answers, threshold, "ref")
        if routing.certainty is not None and routing.certainty >= threshold:
            if routing.accepted and routing.outcome != labels[e.id]["outcome"]:
                wrong_accepted.append(e.id)
    assert wrong_accepted == ["t11"]


def test_threshold_objective_is_pinned_to_real_source():
    source = inspect.getsource(helpers.select_policy)
    assert "target_accuracy=0.95" in source
    assert "min_coverage=" not in source
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    assert "helpers.select_policy(validation, labels, results)" in cells["evaluation-validation"]


def test_policy_rejects_test_split():
    examples, labels, results = data()
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy([e for e in examples if e.split == "test"], labels, results)


def test_rebuild_refuses_recorded_without_force(tmp_path):
    """Extra guard supplements the unchanged scaffold guard with malformed-file protection."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("bug93_guard", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "responses.json"
    target.write_text("{broken", encoding="utf-8")
    assert module._is_recorded(target)
