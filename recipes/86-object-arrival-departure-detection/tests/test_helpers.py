"""Test chronology, pixel checks, budget stops, replay identity and actual accepted errors."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, BudgetExceeded, ReviewQueue
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
EXAMPLES = {e.id: e for e in load_inputs(RECIPE)}


def observation(choice="arrival", confidence=0.9, issues=()):
    return SimpleNamespace(
        prepared=SimpleNamespace(issues=issues),
        answer=SimpleNamespace(choice=choice, confidence=confidence),
    )


@pytest.mark.parametrize("choice", ["arrival", "departure", "unchanged"])
def test_gate_inclusive_and_every_resolved_option_is_gated(choice):
    assert helpers.route(observation(choice), 0.9).accepted
    assert helpers.route(observation(choice), 0.90001).label == "review"


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -1, 2, True, "0.9"])
def test_invalid_confidence_cannot_authorize_a_note(confidence):
    assert not helpers.route(observation(confidence=confidence), 0.5).accepted


@pytest.mark.parametrize("choice", ["uncertain", "delivered", "stolen", "other"])
def test_uncertain_and_unallowed_choices_always_defer(choice):
    assert not helpers.route(observation(choice, 1.0), 0.0).accepted


@pytest.mark.parametrize("threshold", [None, float("nan"), float("inf"), -1, 2, True])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        helpers.route(observation(), threshold)


def test_quality_veto_beats_arbitrarily_confident_answer():
    outcome = helpers.route(observation(confidence=1, issues=("camera changed",)), 0)
    assert not outcome.accepted and outcome.reason == "camera changed"


@pytest.mark.parametrize(
    "times",
    [(0, 0, 2), (2, 1, 0), (-1, 1, 2), (0, 1, float("nan")), (0, 1, float("inf")), (0, 1, True)],
)
def test_invalid_timestamps_rejected_before_backend(times):
    fields = copy.deepcopy(EXAMPLES["v01"].fields)
    for row, time in zip(fields["frames"], times, strict=True):
        row["timestamp_seconds"] = time
    with pytest.raises(ValueError):
        helpers.ClipRunner(None).observe(fields, RECIPE)


@pytest.mark.parametrize(
    "ident,reason", [("v08", "camera"), ("v09", "sampling"), ("v10", "lighting")]
)
def test_unusable_clips_never_spend_a_request(ident, reason):
    runner = helpers.ClipRunner(None, max_requests=0)
    observed = runner.observe(EXAMPLES[ident].fields, RECIPE)
    assert observed.answer is None
    assert reason in "; ".join(observed.prepared.issues)
    assert runner.requests == 0


def test_budget_cache_and_stop_hold_without_model_cooperation():
    runner = helpers.ClipRunner(get_backend(fixtures=responses_path(RECIPE)), max_requests=1)
    first = runner.observe(EXAMPLES["v01"].fields, RECIPE)
    assert runner.observe(EXAMPLES["v01"].fields, RECIPE).result is first.result
    with pytest.raises(BudgetExceeded):
        runner.observe(EXAMPLES["v02"].fields, RECIPE)
    assert runner.requests == 1


def test_state_and_options_have_no_authoring_metadata():
    fields = dict(EXAMPLES["t11"].fields, gold="departure", split="test", drawing="CCE")
    prepared = helpers.prepare(fields, RECIPE)
    assert set(prepared.state) == {"target", "frames"}
    assert all(set(f) == {"timestamp_seconds", "image"} for f in prepared.state["frames"])
    assert all(f["image"].startswith("image:sha256:") for f in prepared.state["frames"])
    assert list(helpers.build_questions()["event"].criteria) == [
        "arrival",
        "departure",
        "unchanged",
        "uncertain",
    ]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in EXAMPLES.values():
        p = helpers.prepare(example.fields, RECIPE)
        expected = (
            () if p.issues else (replay_key(p.state, helpers.build_questions(), assets=p.assets),)
        )
        assert example.replay_keys == expected


def test_timestamps_order_and_actual_bytes_participate_in_replay(tmp_path):
    p = helpers.prepare(EXAMPLES["v01"].fields, RECIPE)
    q = helpers.build_questions()
    key = replay_key(p.state, q, assets=p.assets)
    changed = copy.deepcopy(p.state)
    changed["frames"][1]["timestamp_seconds"] = 1.5
    assert replay_key(changed, q, assets=p.assets) != key
    changed["frames"].reverse()
    assert replay_key(changed, q, assets=p.assets) != key
    with Image.open(RECIPE / EXAMPLES["v01"].fields["frames"][0]["path"]) as im:
        im.putpixel((10, 10), (1, 2, 3))
        im.save(tmp_path / "different.png")
    assets = dict(p.assets)
    assets[p.state["frames"][0]["image"]] = image_asset(tmp_path / "different.png")
    assert replay_key(p.state, q, assets=assets) != key


def test_pixel_baseline_uses_all_frames_and_can_be_wrong():
    labels = load_labels(RECIPE)
    assert helpers.pixel_baseline(helpers.prepare(EXAMPLES["v01"].fields, RECIPE)) == "arrival"
    assert helpers.pixel_baseline(helpers.prepare(EXAMPLES["v02"].fields, RECIPE)) == "departure"
    assert helpers.pixel_baseline(helpers.prepare(EXAMPLES["v06"].fields, RECIPE)) == "uncertain"
    assert helpers.pixel_baseline(helpers.prepare(EXAMPLES["t05"].fields, RECIPE)) == "uncertain"
    p = helpers.prepare(EXAMPLES["t11"].fields, RECIPE)
    assert helpers.pixel_baseline(p) == "departure" != labels["t11"]
    copied = dict(EXAMPLES["t11"].fields, id="different", gold="arrival", split="train")
    assert helpers.pixel_baseline(helpers.prepare(copied, RECIPE)) == "departure"


def test_stored_answers_are_not_all_right():
    labels = load_labels(RECIPE)
    runner = helpers.ClipRunner(get_backend(fixtures=responses_path(RECIPE)))
    validation = [
        (e, runner.observe(e.fields, RECIPE)) for e in EXAMPLES.values() if e.split == "validation"
    ]
    eligible = [
        (e, o.answer)
        for e, o in validation
        if o.answer is not None and o.answer.choice != "uncertain"
    ]
    threshold = select_confidence_threshold(
        [a.choice == labels[e.id] for e, a in eligible],
        [a.confidence for _, a in eligible],
        target_accuracy=1.0,
    )
    test = [(e, runner.observe(e.fields, RECIPE)) for e in EXAMPLES.values() if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e, o in test
        if o.answer is not None
        and o.answer.choice != labels[e.id]
        and o.answer.confidence >= threshold
        and helpers.route(o, threshold).accepted
    ]
    assert wrong_and_confident == ["t11"]


def test_the_notebook_pins_the_selection_objective():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


def test_simulated_logs_and_reviews_follow_actual_outcomes():
    runner = helpers.ClipRunner(get_backend(fixtures=responses_path(RECIPE)))
    actions, reviews = ActionLog(), ReviewQueue()
    for ident in ("d01", "d02", "v08"):
        observed = runner.observe(EXAMPLES[ident].fields, RECIPE)
        helpers.log_outcome(ident, observed, 0.6, actions, reviews)
    assert len(actions) == 1 and len(reviews) == 2
    assert actions.to_dicts()[0]["executed"] is False
    assert actions.to_dicts()[0]["payload"]["physical_event"] == "not established"


def test_typed_distribution_remains_a_probability_distribution():
    answer = ChoiceAnswer.from_probabilities(
        {"arrival": 0.91, "departure": 0.03, "unchanged": 0.03, "uncertain": 0.03},
        Provenance.synthetic(),
    )
    assert answer.choice == "arrival" and 0 < answer.confidence < 1


def test_evaluation_completes_when_all_test_clips_go_to_review(capsys):
    """A legitimately empty action log must not prevent the measured disclosure."""
    from jev_cookbook.evaluation import accuracy, evaluate_outcomes

    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "evaluation-test")
    backend = get_backend(fixtures=responses_path(RECIPE))
    scope = {
        "examples": list(EXAMPLES.values()),
        "labels": load_labels(RECIPE),
        "helpers": helpers,
        "ROOT": RECIPE,
        "runner": helpers.ClipRunner(backend),
        "backend": backend,
        "threshold": 1.0,
        "ActionLog": ActionLog,
        "ReviewQueue": ReviewQueue,
        "evaluate_outcomes": evaluate_outcomes,
        "accuracy": accuracy,
        "check": " -- a pipeline check, not a Jev result",
    }
    exec("".join(cell["source"]), scope)
    assert len(scope["actions"]) == 0
    assert len(scope["reviews"]) == 12
    assert "Simulated action sample: []" in capsys.readouterr().out


@pytest.mark.parametrize("count", [2, 5])
def test_frame_count_limits_stop_before_request(count):
    rows = EXAMPLES["v01"].fields["frames"]
    fields = {
        "frames": [dict(rows[i % len(rows)], timestamp_seconds=float(i)) for i in range(count)]
    }
    with pytest.raises(ValueError, match="three or four"):
        helpers.ClipRunner(None).observe(fields, RECIPE)


def test_span_limit_is_independent_of_each_gap_limit():
    rows = EXAMPLES["v01"].fields["frames"]
    fields = {"frames": [dict(rows[i % 3], timestamp_seconds=1.5 * i) for i in range(4)]}
    observed = helpers.ClipRunner(None, max_requests=0).observe(fields, RECIPE)
    assert observed.prepared.issues == ("sample span exceeds four seconds",)
    assert observed.answer is None


def test_changed_dimensions_block_before_a_request(tmp_path):
    fields = copy.deepcopy(EXAMPLES["v01"].fields)
    for i, row in enumerate(fields["frames"]):
        with Image.open(RECIPE / row["path"]) as image:
            if i == 2:
                image = image.resize((512, 360))
            image.save(tmp_path / f"frame-{i}.png")
        row["path"] = f"frame-{i}.png"
    observed = helpers.ClipRunner(None, max_requests=0).observe(fields, tmp_path)
    assert observed.prepared.issues == ("frame dimensions changed",)
    assert not helpers.route(observed, 0).accepted
