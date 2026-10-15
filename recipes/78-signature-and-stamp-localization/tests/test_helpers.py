"""Boundary checks for the document-localization policy and its evidence plumbing."""

import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import BoxAnswer, NoulAnswer, Provenance, ReplayBackend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.vision import crop_box, image_asset, image_reference, normalized_to_pixels

ROOT = Path(__file__).resolve().parent.parent
helpers = load_helpers(ROOT)
BOX = {"left": 0.1, "top": 0.2, "right": 0.4, "bottom": 0.3}
POLICY = helpers.Policy(0.9, 0.85)


def observation(p=0.99, u=0.99, confidence=0.99, box=BOX):
    return helpers.Observation(
        {"present": SimpleNamespace(noul=p), "unique": SimpleNamespace(noul=u)},
        SimpleNamespace(confidence=confidence, box=box),
    )


@pytest.mark.parametrize(
    "obs,status",
    [
        (observation(p=0.03, u=0.02), "absent"),
        (observation(p=0.03, u=0.99), "review"),
        (observation(p=0.75), "review"),
        (observation(u=0.1), "review"),
        (observation(confidence=None), "review"),
        (observation(confidence=0.84), "review"),
        (observation(confidence=0.85), "located"),
        (observation(p=0.9, u=0.9), "located"),
        (observation(box={**BOX, "right": -0.1}), "review"),
    ],
)
def test_policy_boundaries(obs, status):
    result = helpers.route(obs, POLICY, (600, 760))
    assert result.status == status
    assert (result.box is not None) == (status == "located")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, True, "0.99", None])
def test_invalid_arbitrary_answers_fail_closed(value):
    for obs in (observation(p=value), observation(u=value), observation(confidence=value)):
        assert helpers.route(obs, POLICY, (600, 760)).status == "review"


def test_noul_answers_are_batched_and_box_is_dependent():
    class Counting:
        mode = "synthetic"

        def __init__(self):
            self.requests = []

        def decide(self, state, questions, *, assets):
            from jev_cookbook import DecisionResult

            self.requests.append(set(questions))
            provenance = Provenance.synthetic()
            return DecisionResult(
                {"present": NoulAnswer(0.99, provenance), "unique": NoulAnswer(0.1, provenance)},
                "synthetic",
            )

    backend = Counting()
    item = load_inputs(ROOT)[0]
    obs = helpers.observe(backend, item.fields, ROOT, 0.9, helpers.RequestBudget())
    assert backend.requests == [{"present", "unique"}]
    assert obs.location is None


def test_budget_stops_before_any_backend_call():
    class FailIfCalled:
        def decide(self, *args, **kwargs):
            raise AssertionError("budget must stop before backend")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        helpers.observe(
            FailIfCalled(), load_inputs(ROOT)[0].fields, ROOT, 0.9, helpers.RequestBudget(0)
        )


def test_no_answer_can_issue_a_document_approval():
    actions, reviews = helpers.empty_logs()
    for obs in (observation(), observation(u=0), observation(p=0, u=0)):
        outcome = helpers.route(obs, POLICY, (600, 760))
        helpers.simulate("sample", outcome, actions, reviews)
    assert len(actions.to_dicts()) == 1
    assert {row["kind"] for row in actions.to_dicts()} == {"simulate_crop"}
    assert len(reviews.to_dicts()) == 1


def test_request_state_whitelists_only_evidence_and_target(tmp_path):
    fields = dict(load_inputs(ROOT)[0].fields)
    fields.update({"label": "leak", "split": "test", "boxes": [BOX], "case": "hidden"})
    state, assets = helpers.request_data(fields, ROOT)
    assert set(state) == {"document", "requested_mark"}
    assert state["document"] in assets
    assert "leak" not in json.dumps(state)
    first = replay_key(state, helpers.build_questions(), assets=assets)
    renamed = tmp_path / "renamed.png"
    renamed.write_bytes((ROOT / fields["image"]).read_bytes())
    assert image_reference(image_asset(renamed)) == state["document"]
    with Image.open(renamed) as image:
        changed = image.convert("RGB")
    changed.putpixel((0, 0), (0, 0, 0))
    changed.save(renamed)
    altered = image_asset(renamed)
    second = replay_key(state, helpers.build_questions(), assets={state["document"]: altered})
    assert first != second
    new_state = {**state, "requested_mark": helpers.TARGETS["stamp"]}
    assert replay_key(new_state, helpers.build_questions(), assets=assets) != first


def _validation():
    examples = load_inputs(ROOT)
    backend = ReplayBackend.from_json(responses_path(ROOT))
    budget = helpers.RequestBudget()
    validation = [e for e in examples if e.split == "validation"]
    observed = {
        e.id: helpers.observe(backend, e.fields, ROOT, min(helpers.PRESENCE_CANDIDATES), budget)
        for e in validation
    }
    labels = load_labels(ROOT)
    policy, _ = helpers.select_policy(
        validation, observed, labels, ROOT, objective=helpers.OBJECTIVE
    )
    return examples, backend, labels, policy, budget


def test_stored_answers_are_not_all_right():
    examples, backend, labels, policy, budget = _validation()
    assert (policy.presence, policy.box) == (0.9, 0.85)
    wrong = []
    for example in (e for e in examples if e.split == "test"):
        obs = helpers.observe(backend, example.fields, ROOT, policy.presence, budget)
        out = helpers.route(obs, policy, helpers.dimensions(example.fields, ROOT))
        if out.status == "located" and not helpers.resolved_correct(out, labels[example.id]):
            assert obs.location.confidence >= policy.box
            wrong.append(example.id)
    assert wrong == ["t04", "t07"]


def test_selection_objective_and_candidate_family_are_pinned_to_production_source():
    assert helpers.OBJECTIVE == "correct_resolutions_minus_twice_wrong_crops"
    assert helpers.PRESENCE_CANDIDATES == (0.8, 0.9, 0.95)
    assert helpers.BOX_CANDIDATES == (0.7, 0.85, 0.95)
    source = ast.parse(inspect.getsource(helpers.summarize))
    value = next(
        value
        for node in ast.walk(source)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "objective_value"
    )
    assert ast.unparse(value) == "sum(correct) - 2 * wrong_crops"
    notebook = json.loads((ROOT / "notebook.ipynb").read_text())
    code = next(c for c in notebook["cells"] if c["id"] == "evaluation-validation")
    tree = ast.parse("".join(code["source"]))
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "select_policy"
    )
    objective = next(k.value for k in call.keywords if k.arg == "objective")
    assert ast.unparse(objective) == "helpers.OBJECTIVE"


def test_selection_refuses_test_data():
    example = next(e for e in load_inputs(ROOT) if e.split == "test")
    with pytest.raises(ValueError, match="only validation"):
        helpers.select_policy([example], {}, {}, ROOT, objective=helpers.OBJECTIVE)


def test_keys_and_actual_cascade_counts():
    examples, backend, _, policy, budget = _validation()
    for example in examples:
        state, assets = helpers.request_data(example.fields, ROOT)
        first = replay_key(state, helpers.build_questions(), assets=assets)
        judgments = backend.decide(state, helpers.build_questions(), assets=assets).answers
        threshold = (
            min(helpers.PRESENCE_CANDIDATES) if example.split == "validation" else policy.presence
        )
        expected = [first]
        if helpers.first_gate(judgments, threshold) is None:
            expected.append(replay_key(state, helpers.box_questions(), assets=assets))
        assert list(example.replay_keys) == expected
        if example.split != "validation":
            helpers.observe(backend, example.fields, ROOT, threshold, budget)
    assert budget.used == 43
    assert len(json.loads(responses_path(ROOT).read_text())) == 43


def test_crops_use_actual_dimensions_and_outward_rounding():
    answer = BoxAnswer(BOX, 0.99, Provenance.synthetic())
    out = helpers.route(observation(box=answer.box), POLICY, (600, 760))
    assert out.pixels == (60, 152, 240, 228)
    image = Image.new("RGB", (600, 760))
    assert crop_box(image, out.box).size == (180, 76)
    assert normalized_to_pixels(
        {"left": 0.1001, "top": 0.2001, "right": 0.4001, "bottom": 0.3001}, 600, 760
    ) == (60, 152, 241, 229)


def test_review_is_not_coverage_and_misses_are_zero_iou():
    examples = load_inputs(ROOT)[:2]
    labels = {e.id: {"present": True, "unique": True, "boxes": [BOX]} for e in examples}
    outcomes = {
        examples[0].id: helpers.Outcome("located", "test", BOX),
        examples[1].id: helpers.Outcome("review", "uncertain"),
    }
    metrics = helpers.summarize(examples, outcomes, labels)
    assert metrics["coverage"] == 0.5
    assert metrics["mean_iou_with_misses"] == 0.5
    assert metrics["misses"] == 1


def test_baseline_uses_pixels_and_kind_only():
    item = load_inputs(ROOT)[0]
    fields = dict(item.fields)
    before = helpers.baseline(fields, ROOT)
    fields.update({"gold": None, "boxes": [], "case": "absent", "split": "test"})
    assert helpers.baseline(fields, ROOT) == before
    assert before.status == "located"


def test_asset_dimensions_and_requested_hard_cases_are_present():
    labels = load_labels(ROOT)
    assert {"blank", "printed", "seal", "duplicate", "partial", "occluded", "black"} <= {
        label["case"] for label in labels.values()
    }
    for example in load_inputs(ROOT):
        asset = image_asset(ROOT / example.fields["image"])
        assert asset["format"] == "png"
        assert helpers.dimensions(example.fields, ROOT) == (600, 760)


def test_recording_uses_returned_judgments_and_fixed_demo_gate(tmp_path, monkeypatch):
    """A changed validation policy cannot change which demo branches replay needs."""
    import jev_cookbook
    from jev_cookbook import DecisionResult

    stored = {}
    calls = []

    def fake_record(backend, requests, responses_file):
        for state, questions, assets in requests:
            calls.append(set(questions))
            assert assets and state["document"] in assets
            provenance = Provenance.synthetic()
            answers = (
                {
                    "present": NoulAnswer(0.92, provenance),
                    "unique": NoulAnswer(0.92, provenance),
                }
                if "present" in questions
                else {"mark_box": BoxAnswer(BOX, 0.92, provenance)}
            )
            stored[replay_key(state, questions, assets=assets)] = DecisionResult(
                answers, "synthetic"
            ).to_dict()
        Path(responses_file).write_text(json.dumps(stored))

    monkeypatch.setattr(jev_cookbook, "record", fake_record)
    demo = next(e for e in load_inputs(ROOT) if e.split == "demo")
    count = helpers.record_stage(object(), [demo], ROOT, tmp_path / "demo.json", 0.95)
    assert count == 2
    assert calls == [{"present", "unique"}, {"mark_box"}]
    calls.clear()
    validation = next(e for e in load_inputs(ROOT) if e.split == "validation")
    count = helpers.record_stage(object(), [validation], ROOT, tmp_path / "val.json", 0.95)
    assert count == 1
    assert calls == [{"present", "unique"}]


def test_printed_form_identifier_does_not_reveal_the_split():
    source = (ROOT / "build_fixtures.py").read_text()
    tree = ast.parse(source)
    draw_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "text"
    ]
    for call in draw_calls:
        assert not any(
            isinstance(node, ast.Name) and node.id in {"ident", "split"}
            for arg in call.args
            for node in ast.walk(arg)
        )
