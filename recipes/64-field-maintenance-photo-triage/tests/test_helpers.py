"""Visual evidence, interlocks, isolation and evaluation protocol checks."""

import ast
import inspect
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, Budget, BudgetExceeded, ReviewQueue
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def response(label="normal", visible=0.96, flags=(), certainty=0.96, top=0.96):
    probs = {name: top if name == label else (1 - top) / 4 for name in helpers.OPTIONS}
    values = {
        "condition": ChoiceAnswer.from_probabilities(probs, Provenance.synthetic()),
        "visible": NoulAnswer(visible, Provenance.synthetic()),
    }
    values.update(
        {
            name: NoulAnswer(certainty if name in flags else 1 - certainty, Provenance.synthetic())
            for name in helpers.CONDITIONS
        }
    )
    return values


def recorded_results(examples):
    backend = get_backend(fixtures=RECIPE / "fixtures/responses.json")
    results = []
    for e in examples:
        state, questions, assets = helpers.build_request(e.fields)
        results.append(backend.decide(state, questions, assets=assets))
    return results


def test_questions_are_independent_fixed_and_state_is_annotation_free():
    q = helpers.build_questions()
    assert set(q) == {"condition", "visible", *helpers.CONDITIONS}
    assert tuple(q["condition"].criteria) == helpers.OPTIONS
    for name in ("visible", *helpers.CONDITIONS):
        assert q[name].instructions.endswith(".")
        assert "?" not in q[name].instructions
    fields = {"image": "assets/v01.png", "gold": "leak", "split": "test", "scene": "rust"}
    state, _, assets = helpers.build_request(fields)
    assert set(state) == {"image", "scope"}
    assert state["image"].startswith("image:sha256:")
    assert list(assets) == [state["image"]]
    assert "v01" not in str(state)


def test_every_replay_key_matches_images_and_questions():
    for e in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(e.fields)
        assert e.replay_keys == (replay_key(state, questions, assets=assets),)


def test_image_bytes_and_state_affect_replay(tmp_path):
    e = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(e.fields)
    original = replay_key(state, questions, assets=assets)
    assert (
        replay_key({**state, "scope": "different visible region"}, questions, assets=assets)
        != original
    )
    with Image.open(RECIPE / e.fields["image"]) as image:
        image.putpixel((100, 100), (1, 2, 3))
        image.save(tmp_path / "changed.png")
    replaced = {state["image"]: image_asset(tmp_path / "changed.png")}
    assert replay_key(state, questions, assets=replaced) != original


def test_pixels_are_distinct_across_splits():
    seen = {}
    for e in load_inputs(RECIPE):
        with Image.open(RECIPE / e.fields["image"]) as image:
            pixels = image.convert("RGB").tobytes()
        assert pixels not in seen
        seen[pixels] = e.split


def test_arbitrary_answers_cannot_skip_visibility_consistency_or_mixed_review():
    for label, visible, bits in itertools.product(
        helpers.OPTIONS, (0.1, 0.5, 0.96), itertools.product((0, 1), repeat=3)
    ):
        flags = tuple(name for name, bit in zip(helpers.CONDITIONS, bits, strict=True) if bit)
        result = response(label, visible, flags)
        out = helpers.triage("unit", result, 0.5)
        expected = flags[0] if len(flags) == 1 else "normal"
        allowed = visible > 0.5 and len(flags) <= 1 and label == expected
        assert (out.outcome == helpers.ACCEPTED) == allowed
        if not allowed:
            assert out.recommendation is None
            assert out.flags == flags


@pytest.mark.parametrize("label", helpers.OPTIONS)
def test_low_confidence_and_proposal_interlock_apply_to_every_option(label):
    flags = (label,) if label in helpers.CONDITIONS else ()
    assert (
        helpers.triage("unit", response(label, flags=flags, top=0.3), 0.54).outcome
        == helpers.REVIEW
    )
    for permission in (False, None, "yes", 1):
        out = helpers.triage("unit", response(label, flags=flags), 0.54, allow_proposal=permission)
        assert out.outcome == helpers.REVIEW


def test_ambiguous_independent_evidence_cannot_be_overridden_by_confident_choice():
    result = response("corrosion", flags=("corrosion",), certainty=0.51)
    assert helpers.triage("unit", result, 0.54).reason == "confidence below the threshold"
    result = response("normal")
    threshold = helpers.strength(result)
    assert helpers.triage("unit", result, threshold).outcome == helpers.ACCEPTED
    assert helpers.triage("unit", result, threshold + 1e-9).outcome == helpers.REVIEW


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1, True, None])
def test_malformed_probabilities_and_thresholds_fail_closed(bad):
    result = response()
    result["visible"] = SimpleNamespace(noul=bad)
    assert helpers.triage("unit", result, 0.54).outcome == helpers.REVIEW
    with pytest.raises(ValueError, match="threshold"):
        helpers.triage("unit", response(), bad)


def test_logs_only_fixed_proposals_and_review_is_never_an_action():
    actions, reviews = ActionLog(), ReviewQueue()
    for result in (response(), response("unclear", flags=("corrosion", "leak"))):
        out = helpers.triage("unit", result, 0.54)
        helpers.log_outcome(out, result, actions, reviews)
    assert len(actions) == len(reviews) == 1
    assert actions.to_dicts()[0]["kind"] == "propose_visual_followup"
    assert actions.to_dicts()[0]["executed"] is False
    assert reviews.to_dicts()[0]["item"]["flags"] == ["corrosion", "leak"]
    forged = helpers.Outcome("unit", "normal", (), helpers.ACCEPTED, "invented", "Repair now")
    with pytest.raises(ValueError, match="fixed visual"):
        helpers.log_outcome(forged, response(), actions, reviews)


def test_request_budget_stops_before_backend_call():
    class Backend:
        calls = 0

        def decide(self, *args, **kwargs):
            self.calls += 1
            return response()

    backend = Backend()
    budget = Budget(calls=1)
    fields = {"image": "assets/v01.png"}
    helpers.ask(backend, fields, budget)
    with pytest.raises(BudgetExceeded):
        helpers.ask(backend, fields, budget)
    assert backend.calls == 1


def test_pixel_baseline_reads_pixels_not_annotations_or_filename(tmp_path):
    examples = load_inputs(RECIPE)
    for e in examples:
        fields = {**e.fields, "gold": "invented", "split": "other", "scene": "clean"}
        assert helpers.pixel_baseline(fields) == helpers.pixel_baseline(e.fields)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/renamed.png").write_bytes((RECIPE / "assets/v02.png").read_bytes())
    assert helpers.pixel_baseline(
        {"image": "assets/renamed.png"}, tmp_path
    ) == helpers.pixel_baseline({"image": "assets/v02.png"})
    assert helpers.pixel_baseline({"image": "assets/v01.png"})[0] == "normal"
    assert helpers.pixel_baseline({"image": "assets/v05.png"})[0] == "corrosion"
    assert helpers.pixel_baseline({"image": "assets/v06.png"})[0] == "normal"


def test_stored_answers_are_not_all_right():
    examples = load_inputs(RECIPE)
    gold = load_labels(RECIPE)
    val = [e for e in examples if e.split == "validation"]
    val_results = recorded_results(val)
    eligible = [
        (r, gold[e.id])
        for e, r in zip(val, val_results, strict=True)
        if helpers.eligibility(r) is None
    ]
    threshold = select_confidence_threshold(
        [r["condition"].choice == g["condition"] for r, g in eligible],
        [helpers.strength(r) for r, _ in eligible],
        target_accuracy=1.0,
    )
    assert threshold == helpers.select_policy(val_results, [gold[e.id] for e in val])
    test = [e for e in examples if e.split == "test"]
    failures = [
        e.id
        for e, r in zip(test, recorded_results(test), strict=True)
        if r["condition"].choice != gold[e.id]["condition"]
        and helpers.strength(r) >= threshold
        and helpers.triage(e.id, r, threshold).outcome == helpers.ACCEPTED
    ]
    assert failures == ["t05"]


def test_policy_objective_is_pinned_to_committed_selection_source():
    source = inspect.getsource(helpers.select_policy)
    calls = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
    assert keywords == {"target_accuracy": 1.0}
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    code = {c["id"]: "".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"}
    assert "helpers.select_policy(val_results, val_gold)" in code["python-rule"]
    assert "test" not in code["python-rule"]
