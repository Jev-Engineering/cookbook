"""Policy, image identity, input isolation and deliberately imperfect held-out behavior."""

import ast
import copy
import importlib.util
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, BudgetExceeded, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def example(ident):
    return next(e for e in load_inputs(RECIPE) if e.id == ident)


def answer(choice, top=0.9):
    return ChoiceAnswer.from_probabilities(
        {name: top if name == choice else (1 - top) / 5 for name in helpers.OPTIONS},
        Provenance.synthetic(),
    )


@pytest.mark.parametrize("choice", ["selected", "disabled", "active", "hovered", "error"])
def test_every_concrete_state_is_gated_and_is_only_an_observation(choice):
    value = answer(choice)
    actions, queue = ActionLog(), ReviewQueue()
    accepted = helpers.apply_policy("x", value, value.confidence, queue)
    assert accepted.outcome == helpers.ACCEPTED
    assert not hasattr(accepted, "may_click")
    assert helpers.classify("x", value, value.confidence + 1e-8).outcome == helpers.REVIEW
    assert len(queue) == 0 and actions.to_dicts() == []


@pytest.mark.parametrize("threshold", [0, 0.5, 1.0])
def test_unknown_is_review_even_when_certain(threshold):
    queue = ReviewQueue()
    outcome = helpers.apply_policy("x", answer("unknown", 1.0), threshold, queue)
    assert outcome.outcome == helpers.REVIEW
    assert len(queue) == 1
    assert queue.to_dicts()[0]["item"]["example_id"] == "x"
    metrics = evaluate_outcomes([outcome.outcome == helpers.ACCEPTED], [True])
    assert metrics.n_answered == 0 and metrics.coverage == 0


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -0.1, 1.1, True])
def test_missing_and_invalid_confidence_cannot_pass(confidence):
    result = helpers.classify("x", SimpleNamespace(choice="active", confidence=confidence), 0)
    assert result.outcome == helpers.REVIEW


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan"), float("inf"), True, None])
def test_invalid_threshold_fails_closed(threshold):
    with pytest.raises(ValueError, match="finite number between 0 and 1"):
        helpers.classify("x", answer("active"), threshold)


def test_unrecognized_option_cannot_create_an_action():
    result = helpers.classify("x", SimpleNamespace(choice="click", confidence=1.0), 0)
    assert result.outcome == helpers.REVIEW


def test_low_confidence_reason_uses_the_shared_wording():
    result = helpers.classify("x", answer("error", 0.4), 0.8)
    assert result.reason == "confidence below the threshold"


def test_request_contains_one_image_question_and_no_authoring_fields():
    fields = copy.deepcopy(example("d01").fields)
    expected = helpers.build_request(fields)
    fields.update(label="disabled", split="test", rendered_state="error", theme="secret")
    state, questions, assets = helpers.build_request(fields)
    assert (state, questions, assets) == expected
    assert set(state) == {"component", "appearance_contract", "query_image"}
    assert list(questions) == ["visual_state"]
    assert list(questions["visual_state"].criteria) == [
        "selected",
        "disabled",
        "active",
        "hovered",
        "error",
        "unknown",
    ]
    for criterion in questions["visual_state"].criteria.values():
        assert "image:sha256:" in criterion
    assert "assets/" not in json.dumps(state)
    assert "assets/" not in str(questions["visual_state"].criteria)


def test_every_replay_key_matches_images_state_and_questions():
    for item in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(item.fields)
        assert item.replay_keys == (replay_key(state, questions, assets=assets),)
        assert state["query_image"] not in {
            image_reference(image_asset(RECIPE / path))
            for path in item.fields["references"].values()
        }


@pytest.mark.parametrize("target", ["query", "reference"])
def test_changing_image_bytes_changes_replay_identity(tmp_path, target):
    fields = copy.deepcopy(example("d01").fields)
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    before = helpers.build_request(fields, tmp_path)
    relative = fields["image"] if target == "query" else fields["references"]["selected"]
    with Image.open(tmp_path / relative) as original:
        changed = original.convert("RGB")
    changed.putpixel((0, 0), (12, 34, 56))
    changed.save(tmp_path / relative)
    after = helpers.build_request(fields, tmp_path)
    assert replay_key(*before[:2], assets=before[2]) != replay_key(*after[:2], assets=after[2])


def test_changing_component_context_changes_key():
    fields = copy.deepcopy(example("d01").fields)
    before = helpers.build_request(fields)
    fields["component"] = "A different component"
    after = helpers.build_request(fields)
    assert replay_key(*before[:2], assets=before[2]) != replay_key(*after[:2], assets=after[2])


def test_session_caches_and_stops_before_an_extra_request():
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.Session(backend, max_requests=1)
    one = session.decide(example("d01").fields)
    assert session.decide(example("d01").fields) is one
    assert session.budget.used("requests") == 1
    with pytest.raises(BudgetExceeded):
        session.decide(example("d02").fields)
    assert session.budget.used("requests") == 1


def test_failed_request_consumes_budget_without_retry():
    class Broken:
        calls = 0

        def decide(self, *args, **kwargs):
            self.calls += 1
            raise RuntimeError("failure")

    backend = Broken()
    session = helpers.Session(backend, max_requests=1)
    with pytest.raises(RuntimeError, match="failure"):
        session.decide(example("d01").fields)
    with pytest.raises(BudgetExceeded):
        session.decide(example("d01").fields)
    assert backend.calls == 1


def test_baseline_reads_pixels_not_names_or_gold(tmp_path):
    fields = copy.deepcopy(example("d01").fields)
    expected = helpers.template_baseline(fields)
    paths = [fields["image"], *fields["references"].values()]
    renamed = {}
    for index, path in enumerate(paths):
        name = f"unrelated-{index}.png"
        shutil.copyfile(RECIPE / path, tmp_path / name)
        renamed[path] = name
    fields["image"] = renamed[fields["image"]]
    fields["references"] = {k: renamed[v] for k, v in fields["references"].items()}
    fields.update(label="error", rendered_state="disabled", split="test")
    assert helpers.template_baseline(fields, tmp_path) == expected
    assert expected[0] == "selected"
    fields["image"] = fields["references"]["error"]
    assert helpers.template_baseline(fields, tmp_path)[0] == "error"


def test_identical_active_hover_focus_appearance_requires_unknown():
    item = example("d02")
    paths = item.fields["references"]
    assert (RECIPE / paths["active"]).read_bytes() == (RECIPE / paths["hovered"]).read_bytes()
    assert helpers.template_baseline(item.fields)[0] == "unknown"
    spec = importlib.util.spec_from_file_location("recipe73_renderer", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    appearances = [
        module.render("button", "light", state, shared=True).tobytes()
        for state in ("active", "hovered", "focused")
    ]
    assert appearances[0] == appearances[1] == appearances[2]
    state, questions, _ = helpers.build_request(item.fields)
    assert "indistinguishable" in state["appearance_contract"]
    assert "unknown" in questions["visual_state"].instructions


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.Session(backend)
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(item):
        return session.decide(item.fields)["visual_state"]

    validation = [e for e in examples if e.split == "validation"]
    named = [(decide(e), labels[e.id]) for e in validation if decide(e).choice in helpers.CONCRETE]
    threshold = select_confidence_threshold(
        [a.choice == gold for a, gold in named],
        [a.confidence for a, gold in named],
        target_accuracy=1.0,
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if decide(e).choice != labels[e.id]
        and decide(e).confidence >= threshold
        and helpers.classify(e.id, decide(e), threshold).outcome == helpers.ACCEPTED
    ]
    assert wrong_and_confident == ["t07"]
    assert threshold == pytest.approx(0.58)


def test_notebook_selects_target_accuracy_from_actual_call():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    keywords = {keyword.arg: ast.literal_eval(keyword.value) for keyword in calls[0].keywords}
    assert keywords == {"target_accuracy": 1.0}
    assert "answer.choice in helpers.CONCRETE" in source
