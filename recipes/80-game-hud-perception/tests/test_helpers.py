import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    BoxAnswer,
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    ReplayBackend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import confusion_matrix
from jev_cookbook.fixtures import load_inputs, load_labels, select_split, validate_recipe
from jev_cookbook.vision import normalized_to_pixels

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
PROV = Provenance.synthetic()


def choice(value, criteria, peak=0.97):
    probabilities = {key: (1 - peak) / (len(criteria) - 1) for key in criteria}
    probabilities[value] = peak
    return ChoiceAnswer.from_probabilities(probabilities, PROV)


def first(phase="combat", presence="visible", enabled="enabled", peak=0.97):
    return DecisionResult(
        {
            "phase": choice(phase, helpers.PHASES, peak),
            "presence": choice(presence, helpers.PRESENCE, peak),
            "enabled": choice(enabled, helpers.ENABLED, peak),
        },
        "synthetic",
    )


def second(target="card", confidence=0.97, energy="2"):
    answers = {
        "target_box": BoxAnswer(helpers.pixel_box(helpers.FIXED_PIXELS[target]), confidence, PROV)
    }
    if target == "energy_meter":
        answers["energy"] = choice(energy, helpers.ENERGY)
    return DecisionResult(answers, "synthetic")


class Answers:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    def decide(self, state, questions, *, assets):
        self.calls += 1
        assert set(assets) == {state["screenshot"]}
        return self.results.pop(0)


def example(target="card"):
    return SimpleNamespace(
        id="boundary", split="demo", fields={"image": "assets/panel-01.png", "target": target}
    )


@pytest.mark.parametrize(
    "phase,presence,enabled,event",
    [
        ("menu", "visible", "enabled", "no_action"),
        ("reward", "visible", "enabled", "no_action"),
        ("combat", "absent", "not_applicable", "no_action"),
        ("combat", "visible", "disabled", "no_action"),
        ("ambiguous", "visible", "enabled", "review"),
        ("combat", "uncertain", "enabled", "review"),
        ("combat", "visible", "uncertain", "review"),
        ("combat", "visible", "not_applicable", "review"),
    ],
)
def test_phase_presence_and_enabled_gates_prevent_box_and_action(phase, presence, enabled, event):
    backend = Answers(first(phase, presence, enabled), second())
    obs = helpers.perceive(example(), backend, helpers.Policy(0.75), RECIPE)
    assert obs.event == event
    assert obs.requests == backend.calls == 1
    assert obs.actions == []
    assert bool(obs.reviews) == (event == "review")
    assert len(backend.results) == 1


def test_read_only_target_rejects_inconsistent_enabled_answer():
    backend = Answers(first(enabled="enabled"))
    obs = helpers.perceive(example("energy_meter"), backend, helpers.Policy(0.75), RECIPE)
    assert obs.event == "review" and not obs.actions


@pytest.mark.parametrize("phase,presence", [("combat", "visible"), ("menu", "absent")])
def test_low_confidence_applies_to_no_action_fallbacks_too(phase, presence):
    backend = Answers(first(phase, presence, peak=0.60))
    obs = helpers.perceive(example(), backend, helpers.Policy(0.75), RECIPE)
    assert obs.event == "review"
    assert obs.reason == "confidence below the threshold"
    assert not obs.actions


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_request_budget_is_checked_before_sending(limit):
    backend = Answers(first(), second())
    obs = helpers.perceive(example(), backend, helpers.Policy(0.75, max_requests=limit), RECIPE)
    assert backend.calls == obs.requests == limit
    assert obs.event == ("select_card" if limit == 2 else "review")
    if limit < 2:
        assert obs.reason == "request budget exhausted" and not obs.actions
    else:
        assert len(obs.actions) == 1 and obs.actions[0]["executed"] is False
        x, y = obs.actions[0]["payload"]["center_pixel"]
        assert 180 <= x < 300 and 248 <= y < 370


@pytest.mark.parametrize(
    "confidence,reason",
    [
        (None, "box confidence missing"),
        (0.70, "confidence below the threshold"),
    ],
)
def test_missing_and_low_box_confidence_abstain(confidence, reason):
    obs = helpers.perceive(
        example(), Answers(first(), second(confidence=confidence)), helpers.Policy(0.75), RECIPE
    )
    assert obs.event == "review" and obs.reason == reason
    assert obs.raw_box is not None and obs.box is None and not obs.actions


def test_unreadable_energy_never_produces_an_intent():
    obs = helpers.perceive(
        example("energy_meter"),
        Answers(first(enabled="not_applicable"), second("energy_meter", energy="unreadable")),
        helpers.Policy(0.75),
        RECIPE,
    )
    assert obs.event == "review" and obs.reason == "energy unreadable"
    assert obs.energy is None and not obs.actions


def test_low_confidence_energy_does_not_become_an_exact_resource_value():
    localization = second("energy_meter")
    low_energy = DecisionResult(
        {
            "target_box": localization["target_box"],
            "energy": choice("2", helpers.ENERGY, peak=0.60),
        },
        "synthetic",
    )
    obs = helpers.perceive(
        example("energy_meter"),
        Answers(first(enabled="not_applicable"), low_energy),
        helpers.Policy(0.75),
        RECIPE,
    )
    assert obs.event == "review" and obs.reason == "confidence below the threshold"
    assert obs.energy is None and obs.box is None and not obs.actions


@pytest.mark.parametrize(
    "edge,value",
    [
        ("left", -0.01),
        ("right", 1.01),
        ("top", float("nan")),
        ("bottom", float("inf")),
        ("left", 0.9),
        ("bottom", 0.1),
    ],
)
def test_bad_geometry_is_rejected_without_clipping(edge, value):
    box = dict(left=0.2, top=0.2, right=0.8, bottom=0.8)
    box[edge] = value
    answer = SimpleNamespace(box=box, confidence=0.99)
    assert helpers.gate_box(answer, (640, 400), helpers.Policy(0.75)) == (
        None,
        "invalid bounding box",
    )


def test_tiny_box_does_not_pass_a_high_confidence():
    answer = SimpleNamespace(
        box=dict(left=0.1, top=0.1, right=0.101, bottom=0.101), confidence=0.99
    )
    assert helpers.gate_box(answer, (640, 400), helpers.Policy(0.75))[1] == (
        "box too small for this policy"
    )


def test_exact_coordinate_conventions():
    assert normalized_to_pixels(helpers.pixel_box((0, 0, 640, 400)), 640, 400) == (0, 0, 640, 400)
    assert normalized_to_pixels(
        dict(left=0.251, top=0.101, right=0.749, bottom=0.499), 640, 400
    ) == (160, 40, 480, 200)
    for pixels in helpers.FIXED_PIXELS.values():
        assert normalized_to_pixels(helpers.pixel_box(pixels), 640, 400) == pixels
    with pytest.raises(ValueError, match="inside"):
        helpers.pixel_box((-1, 0, 640, 400))


@pytest.mark.parametrize("confidence,budget", [(True, 2), (float("nan"), 2), (0.7, 3), (0.7, True)])
def test_policy_rejects_invalid_values(confidence, budget):
    with pytest.raises(ValueError):
        helpers.Policy(confidence, max_requests=budget)


def test_model_state_has_no_labels_paths_or_layout_metadata():
    for item in load_inputs(RECIPE):
        state, assets, size = helpers.prepare(item.fields, RECIPE)
        assert set(state) == {"screenshot", "requested_target"}
        assert item.fields["image"] not in json.dumps(state)
        assert state["screenshot"].startswith("image:sha256:")
        assert set(assets) == {state["screenshot"]}
        assert size == (640, 400)
        assert set(item.fields) == {"image", "target"}
    with pytest.raises(ValueError, match="inside"):
        helpers.prepare({"image": "../outside.png", "target": "card"}, RECIPE)


def test_fixtures_have_strict_layout_unique_content_and_exact_request_keys():
    assert not validate_recipe(RECIPE)
    assert {p.name for p in (RECIPE / "fixtures").iterdir()} == {
        "inputs.jsonl",
        "labels.jsonl",
        "responses.json",
    }
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    seen_images = set()
    for item in load_inputs(RECIPE):
        state, assets, _ = helpers.prepare(item.fields, RECIPE)
        assert state["screenshot"] not in seen_images
        seen_images.add(state["screenshot"])
        obs = helpers.perceive(item, backend, helpers.Policy(0.55), RECIPE)
        assert tuple(obs.keys) == item.replay_keys
        assert obs.keys[0] == replay_key(state, helpers.build_questions(), assets=assets)
        with Image.open(RECIPE / item.fields["image"]) as image:
            assert image.format == "PNG" and image.size == (640, 400)
    assert "data_base64" not in (RECIPE / "fixtures" / "inputs.jsonl").read_text()


def test_validation_selection_is_frozen_and_confident_test_mistakes_remain():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    validation = select_split(examples, "validation")
    policy, rows, results = helpers.select_policy(validation, labels, backend, RECIPE)
    assert policy.confidence == 0.75
    assert len(results) == sum(len(item.replay_keys) for item in validation)
    assert len(rows) == 3
    test = select_split(examples, "test")
    observations = [helpers.perceive(item, backend, policy, RECIPE) for item in test]
    mistakes = [
        obs
        for obs in observations
        if obs.actions and not helpers.event_correct(obs, labels[obs.ident])
    ]
    assert {obs.ident for obs in mistakes} == {"t04", "t11"}
    assert all(obs.results[-1]["target_box"].confidence >= policy.confidence for obs in mistakes)
    assert helpers.summarize(observations, labels)["wrong_simulated_intents"] == 2
    with pytest.raises(ValueError, match="validation split"):
        helpers.select_policy(test, labels, backend, RECIPE)


def test_summary_exposes_missed_required_and_absent_denominators():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    test = select_split(examples, "test")
    required_ids = {"t01", "t02", "t03", "t04", "t10", "t12"}
    assert {ident for ident in required_ids if labels[ident]["box"] is None} == set()
    perception = [helpers.perceive(item, backend, helpers.Policy(0.75), RECIPE) for item in test]
    baseline = [helpers.fixed_layout(item, RECIPE) for item in test]
    for observations, missing_ids in ((perception, {"t10"}), (baseline, {"t01", "t03"})):
        assert {
            obs.ident for obs in observations if obs.ident in required_ids and obs.box is None
        } == missing_ids
        metrics = helpers.summarize(observations, labels)
        assert metrics["required_targets"] == 6
        assert metrics["missed_required"] == len(missing_ids)
        assert metrics["absent_targets"] == 1
        assert metrics["false_localizations_on_absent"] == 0
    rejected = next(obs for obs in perception if obs.ident == "t10")
    assert rejected.raw_box is not None and rejected.box is None
    wrong_box = next(obs for obs in perception if obs.ident == "t04")
    assert wrong_box.box is not None and not helpers.event_correct(wrong_box, labels["t04"])
    assert {item.id for item in test if labels[item.id]["presence"] == "absent"} == {"t05"}


def test_notebook_live_metrics_and_chart_are_adjacent_unrecorded_diagnostics(capsys, monkeypatch):
    """Exercise production reporting with replay answers; never construct a live backend."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    assignments = [
        node
        for node in ast.parse(cells["setup"]).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id in {"check", "selection"}
            for target in node.targets
        )
    ]
    namespace = {"backend": SimpleNamespace(mode="live")}
    exec(
        compile(ast.Module(body=assignments, type_ignores=[]), "reporting-labels", "exec"),
        namespace,
    )
    notice = " (unrecorded live diagnostic; not reportable)"
    assert namespace["check"] == notice
    titles = []
    namespace.update(
        helpers=helpers,
        examples=load_inputs(RECIPE),
        labels=load_labels(RECIPE),
        backend=ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json"),
        select_split=select_split,
        confusion_matrix=confusion_matrix,
        plot_confusion_matrix=lambda matrix, *, title: titles.append(title),
    )
    monkeypatch.chdir(RECIPE)
    for ident in (
        "evaluation-validation",
        "evaluation-test",
        "evaluation-matrix",
        "evaluation-wrong",
    ):
        exec(cells[ident], namespace)
    metric_lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(("Validation", "Frozen policy", "Test"))
    ]
    assert any(line.startswith("Test perception") for line in metric_lines)
    assert any(line.startswith("Test fixed-layout baseline") for line in metric_lines)
    assert any(line.startswith("Test phase matrix") for line in metric_lines)
    assert any(line.startswith("Validation") for line in metric_lines)
    assert all(line.endswith(notice) for line in metric_lines)
    assert titles and all(title.endswith(notice) for title in titles)


def test_selection_objective_and_minimum_coverage_are_pinned_in_executed_sources():
    source = ast.parse(inspect.getsource(helpers.select_policy))
    objective = next(node for node in ast.walk(source) if isinstance(node, ast.Lambda))
    assert ast.unparse(objective.body) == (
        "(1 - row['resolved_accuracy'], row['abstention'], row['threshold'])"
    )
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    code = "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )
    calls = [
        node
        for node in ast.walk(ast.parse(code))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "select_policy"
    ]
    assert len(calls) == 1
    assert next(kw.value.value for kw in calls[0].keywords if kw.arg == "min_coverage") == 0.5


def test_baseline_uses_only_the_same_pixels_and_target_and_zero_requests():
    item = next(item for item in load_inputs(RECIPE) if item.id == "t01")
    obs = helpers.fixed_layout(item, RECIPE)
    renamed = SimpleNamespace(id="different-bookkeeping-id", fields=item.fields)
    other = helpers.fixed_layout(renamed, RECIPE)
    assert (obs.phase, obs.presence, obs.event) == (other.phase, other.presence, other.event)
    assert obs.requests == 0
    assert obs.event == "no_action"  # shifted energy panel is outside its frozen crop


def test_notebook_preview_handles_a_valid_abstaining_live_answer(capsys):
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    source = next(cell["source"] for cell in notebook["cells"] if cell["id"] == "answer-overlay")
    shown = []
    namespace = {
        "demo_observation": SimpleNamespace(
            box=None, event="review", reason="box confidence missing"
        ),
        "demo": SimpleNamespace(fields={"image": RECIPE / "assets" / "panel-01.png"}),
        "Image": Image,
        "display": shown.append,
    }
    exec("".join(source), namespace)
    assert "No approved box: review - box confidence missing" in capsys.readouterr().out
    assert len(shown) == 1 and shown[0].size == (640, 400)
