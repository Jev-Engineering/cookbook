"""Temporal sampling, bounded phase judgments, policy enforcement and honest replay checks."""

import copy
import hashlib
import itertools
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    ChoiceAnswer,
    DecisionResult,
    Provenance,
    get_backend,
    load_helpers,
    replay_key,
)
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def examples():
    return load_inputs(RECIPE)


def reader(root=RECIPE, budget=24):
    return helpers.PhaseReader(
        get_backend(fixtures=RECIPE / "fixtures" / "responses.json"), root, budget
    )


def get_example(ident):
    return next(e for e in examples() if e.id == ident)


def validation_pool():
    labels = load_labels(RECIPE)
    r = reader()
    pool = []
    for example in examples():
        if example.split != "validation":
            continue
        observation = r.observe(example)
        if helpers.structural_outcome(example.fields, observation).outcome == helpers.ACCEPTED:
            pool.append((observation.event == labels[example.id]["event"], observation.confidence))
    return pool


def test_options_are_small_and_each_question_targets_exactly_one_frame():
    questions = helpers.build_questions()
    assert list(questions) == ["phase_0", "phase_1", "phase_2"]
    for i, question in enumerate(questions.values()):
        assert list(question.criteria) == ["combat", "menu", "map", "rewards", "other", "uncertain"]
        assert f"frames[{i}]" in question.instructions


def test_sampling_preserves_order_and_keeps_middle_evidence():
    fields = get_example("d01").fields
    assert helpers.sample_frames(fields) == [fields["frames"][i] for i in (0, 2, 4)]
    assert helpers.event_name(("combat", "menu", "combat")) == "combat>menu>combat"
    assert helpers.event_name(("combat", "combat", "combat")) == "steady:combat"


@pytest.mark.parametrize("ident", ["v12", "v13", "v14", "t12", "t13", "t14"])
def test_bad_capture_metadata_spends_no_requests_and_cannot_be_overridden(ident):
    r = reader()
    example = get_example(ident)
    observation = r.observe(example)
    assert r.requests == 0
    assert observation.reason
    forged = helpers.Observation(("combat", "rewards", "map"), 1.0)
    assert helpers.route(example.fields, forged, 0).outcome == helpers.REVIEW


@pytest.mark.parametrize("time", [float("nan"), float("inf"), -1, True])
def test_bad_timestamp_is_rejected(time):
    fields = copy.deepcopy(get_example("v01").fields)
    fields["frames"][1]["timestamp_seconds"] = time
    assert helpers.preflight(fields)


@pytest.mark.parametrize("problem", ["future", "too_few", "too_many", "too_close"])
def test_capture_window_limits_fail_closed(problem):
    fields = copy.deepcopy(get_example("v01").fields)
    if problem == "future":
        fields["observed_at_seconds"] = fields["frames"][-1]["timestamp_seconds"] - 0.1
    elif problem == "too_few":
        fields["frames"] = fields["frames"][:2]
    elif problem == "too_many":
        fields["frames"] = fields["frames"] * 4
    else:
        fields["frames"][1]["timestamp_seconds"] = fields["frames"][0]["timestamp_seconds"] + 0.1
    assert helpers.preflight(fields)


def test_weakest_frame_controls_the_gate():
    answers = {
        f"phase_{i}": ChoiceAnswer.from_probabilities(
            {phase: p if phase == winner else (1 - p) / 5 for phase in helpers.OPTIONS},
            Provenance.synthetic(),
        )
        for i, (winner, p) in enumerate((("combat", 0.99), ("rewards", 0.55), ("map", 0.91)))
    }

    class MixedConfidenceBackend:
        def decide(self, *_args, **_kwargs):
            return DecisionResult(answers, "synthetic")

    example = get_example("v01")
    observation = helpers.PhaseReader(MixedConfidenceBackend(), RECIPE).observe(example)
    assert observation.confidence == answers["phase_1"].confidence
    assert helpers.route(example.fields, observation, 0.8).outcome == helpers.REVIEW


def test_arbitrary_phase_answers_cannot_bypass_graph_or_unknown_interlock():
    fields = get_example("v01").fields
    expected_edges = {
        ("combat", "rewards"),
        ("rewards", "map"),
        ("map", "combat"),
        ("combat", "menu"),
        ("map", "menu"),
        ("rewards", "menu"),
        ("menu", "combat"),
        ("menu", "map"),
    }
    assert helpers.ALLOWED == expected_edges
    for phases in itertools.product([*helpers.OPTIONS, "launch_tool"], repeat=3):
        result = helpers.route(fields, helpers.Observation(phases, 1), 0.8)
        permitted = all(p in {"combat", "menu", "map", "rewards"} for p in phases) and all(
            a == b or (a, b) in expected_edges for a, b in zip(phases[:-1], phases[1:], strict=True)
        )
        assert (result.outcome == helpers.ACCEPTED) == permitted
        if not permitted:
            assert result.history == ()


@pytest.mark.parametrize("confidence", [None, float("nan"), float("inf"), -0.1, 1.1, 0.79])
def test_missing_invalid_or_low_confidence_never_changes_history(confidence):
    observation = helpers.Observation(("combat", "rewards", "map"), confidence)
    outcome = helpers.route(get_example("v01").fields, observation, 0.8)
    assert outcome.outcome == helpers.REVIEW
    assert outcome.history == ()


@pytest.mark.parametrize("threshold", [-0.1, 1.1, float("nan")])
def test_invalid_threshold_raises(threshold):
    with pytest.raises(ValueError, match="between 0 and 1"):
        helpers.route(get_example("v01").fields, helpers.Observation(("combat",) * 3, 1), threshold)


def test_threshold_is_inclusive_and_time_intervals_are_not_invented_exact_times():
    fields = get_example("v01").fields
    observation = helpers.Observation(("combat", "rewards", "map"), 0.8)
    accepted = helpers.route(fields, observation, 0.8)
    assert accepted.outcome == helpers.ACCEPTED
    assert len(accepted.history) == 2
    assert accepted.history[0]["after_seconds"] == fields["frames"][0]["timestamp_seconds"]
    assert accepted.history[0]["by_seconds"] == fields["frames"][1]["timestamp_seconds"]
    assert helpers.route(fields, observation, 0.800001).history == ()


def test_request_budget_cache_and_simulated_logs():
    r = reader(budget=1)
    first, second = get_example("d01"), get_example("d02")
    first_observation = r.observe(first)
    assert r.observe(first) is first_observation
    second_observation = r.observe(second)
    assert r.requests == 1
    assert second_observation.reason == "request budget exhausted"
    results, actions, reviews = helpers.apply_outcomes(
        [first, second], [first_observation, second_observation], 0.8
    )
    assert [x.outcome for x in results] == [helpers.ACCEPTED, helpers.REVIEW]
    assert len(actions) == len(reviews) == 1
    assert all(a["executed"] is False for a in actions.to_dicts())
    assert actions.to_dicts()[0]["payload"]["clip"] == first.id
    assert reviews.to_dicts()[0]["item"]["clip"] == second.id
    metrics = evaluate_outcomes([x.outcome == helpers.ACCEPTED for x in results], [True, True])
    assert metrics.n_answered == 1 and metrics.coverage == 0.5


def test_state_excludes_gold_split_paths_and_drawing_metadata():
    example = get_example("v01")
    fields = dict(example.fields, gold="LEAK", split="LEAK", drawing="LEAK", id="LEAK")
    state, assets = helpers.build_state(fields, RECIPE)
    assert set(state) == {"frames", "task"}
    text = json.dumps(state)
    assert "LEAK" not in text and "assets/" not in text
    assert len(assets) == 3
    assert [f["timestamp_seconds"] for f in state["frames"]] == [0, 1, 2]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in examples():
        if helpers.preflight(example.fields):
            assert not example.replay_keys
            continue
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_state_and_actual_image_bytes_change_replay_identity(tmp_path):
    example = get_example("v01")
    state, questions, assets = helpers.build_request(example.fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    changed = copy.deepcopy(state)
    changed["frames"][1]["timestamp_seconds"] = 1.2
    assert replay_key(changed, questions, assets=assets) != original
    first_ref = state["frames"][0]["image"]
    with Image.open(RECIPE / example.fields["frames"][0]["path"]) as image:
        image.putpixel((0, 0), (255, 0, 0))
        image.save(tmp_path / "changed.png")
    mutated_assets = dict(assets)
    mutated_assets[first_ref] = image_asset(tmp_path / "changed.png")
    assert replay_key(state, questions, assets=mutated_assets) != original


def test_reader_cache_does_not_reuse_answer_after_image_mutation(tmp_path):
    fields = copy.deepcopy(get_example("v01").fields)
    for frame in fields["frames"]:
        target = tmp_path / frame["path"]
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(RECIPE / frame["path"], target)
    original = reader().observe(get_example("v01")).result

    class CountingBackend:
        calls = 0

        def decide(self, *_args, **_kwargs):
            self.calls += 1
            return original

    backend = CountingBackend()
    r = helpers.PhaseReader(backend, tmp_path)
    example = SimpleNamespace(id="same", fields=fields)
    r.observe(example)
    image_path = tmp_path / fields["frames"][0]["path"]
    with Image.open(image_path) as image:
        image.putpixel((0, 0), (1, 2, 3))
        image.save(image_path)
    r.observe(example)
    assert backend.calls == 2


def test_splits_have_independent_encoded_and_decoded_pixels():
    hashes = {"validation": set(), "test": set()}
    decoded = {"validation": set(), "test": set()}
    for example in examples():
        if example.split not in hashes:
            continue
        for frame in example.fields["frames"]:
            path = RECIPE / frame["path"]
            hashes[example.split].add(hashlib.sha256(path.read_bytes()).digest())
            with Image.open(path) as image:
                decoded[example.split].add(hashlib.sha256(image.tobytes()).digest())
    assert not hashes["validation"] & hashes["test"]
    assert not decoded["validation"] & decoded["test"]


def test_pixel_baseline_uses_pixels_independent_of_filenames_and_labels(tmp_path):
    fields = copy.deepcopy(get_example("v03").fields)
    before = helpers.pixel_baseline(fields, RECIPE)
    for index, frame in enumerate(fields["frames"]):
        target = tmp_path / f"no_semantics_{index}.png"
        shutil.copyfile(RECIPE / frame["path"], target)
        frame["path"] = target.name
    fields.update(label="menu", split="invented")
    assert helpers.pixel_baseline(fields, tmp_path).phases == before.phases
    for frame in fields["frames"]:
        Image.new("RGB", (480, 360), helpers.PALETTE["rewards"]).save(tmp_path / frame["path"])
    assert helpers.pixel_baseline(fields, tmp_path).phases == ("rewards",) * 3


def test_stored_answers_are_not_all_right():
    pool = validation_pool()
    threshold = select_confidence_threshold(
        [correct for correct, _ in pool],
        [confidence for _, confidence in pool],
        target_accuracy=1.0,
    )
    assert threshold == pytest.approx(0.856)
    labels = load_labels(RECIPE)
    r = reader()
    wrong_and_confident = []
    for example in examples():
        if example.split != "test":
            continue
        observation = r.observe(example)
        if observation.confidence is not None and observation.confidence >= threshold:
            if observation.event != labels[example.id]["event"]:
                assert (
                    helpers.route(example.fields, observation, threshold).outcome
                    == helpers.ACCEPTED
                )
                wrong_and_confident.append(example.id)
    assert wrong_and_confident == ["t09"]


def test_notebook_pins_the_actual_validation_objective_and_split():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    assert 'select_split(examples, "validation")' in source
    assert 'select_split(examples, "test")' not in source


def test_full_run_has_24_requests_72_bounded_judgments_and_no_repeat_spend():
    r = reader()
    for example in examples():
        r.observe(example)
    assert r.requests == 24
    assert sum(len(o.result.answers) for o in r.cache.values()) == 72
    for example in examples():
        r.observe(example)
    assert r.requests == 24
