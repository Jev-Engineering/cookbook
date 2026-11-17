"""Interlocks, whole-sample evaluation, and the actual multimodal replay sequence."""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import BoxAnswer, NoulAnswer, Provenance, ReplayBackend, load_helpers, replay_key
from jev_cookbook.evaluation import noul_confidence
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.vision import AssetPathError, box_iou, gold_box, resolve_asset_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
POLICY = helpers.Policy(0.9, 0.9)
BOX = {"left": 0.2, "top": 0.3, "right": 0.6, "bottom": 0.5}


def observation(present=0.98, unique=0.98, enabled=0.98, confidence=0.99, box=None):
    provenance = Provenance.synthetic()
    judgments = {
        "present": NoulAnswer(present, provenance),
        "unique": NoulAnswer(unique, provenance),
        "enabled": NoulAnswer(enabled, provenance),
    }
    location = BoxAnswer(
        box=BOX if box is None else box, confidence=confidence, provenance=provenance
    )
    return helpers.Observation(judgments, location)


def validation_data():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = ReplayBackend.from_json(responses_path(RECIPE))
    validation = select_split(examples, "validation")
    observations = {
        e.id: helpers.observe(backend, e.fields, RECIPE, helpers.COLLECTION_THRESHOLD)
        for e in validation
    }
    return validation, observations, labels


def validation_policy():
    return helpers.select_policy(*validation_data())


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"present": 0.01, "unique": 0.01, "enabled": 0.01}, "absent"),
        ({"present": 0.50}, "review"),
        ({"unique": 0.02}, "review"),
        ({"unique": 0.85}, "review"),
        ({"enabled": 0.01}, "review"),
        ({"enabled": 0.82}, "review"),
        ({"confidence": 0.89}, "review"),
        ({"confidence": None}, "review"),
    ],
)
def test_refusals_cannot_create_actions_even_with_an_available_rectangle(kwargs, status):
    example = select_split(load_inputs(RECIPE), "demo")[0]
    result, actions, reviews = helpers.simulate(example, observation(**kwargs), POLICY, RECIPE)
    assert result.status == status
    assert len(actions) == 0
    assert len(reviews) == (status == "review")


@pytest.mark.parametrize(("unique", "enabled"), [(0.99, 0.99), (0.51, 0.01), (0.01, 0.51)])
def test_a_presence_no_conflicting_with_other_evidence_requires_review(unique, enabled):
    result = helpers.route(
        observation(present=0.01, unique=unique, enabled=enabled), POLICY, (512, 384)
    )
    assert result == helpers.Outcome("review", "absence conflicts with uniqueness or enabled state")


def test_missing_confidence_is_not_zero_or_implicit_permission():
    assert (
        helpers.route(observation(confidence=None), helpers.Policy(0.9, 0), (512, 384)).status
        == "review"
    )
    assert (
        helpers.route(observation(confidence=0), helpers.Policy(0.9, 0), (512, 384)).status
        == "located"
    )


@pytest.mark.parametrize(("probability", "threshold"), [(0.1, 0.9), (0.2, 0.8)])
def test_absence_boundary_is_inclusive(probability, threshold):
    assert (
        helpers.first_gate(
            observation(present=probability, unique=0.02, enabled=0.02).judgments, threshold
        ).status
        == "absent"
    )


@pytest.mark.parametrize(
    "box",
    [
        {**BOX, "left": -0.01},
        {**BOX, "right": 1.01},
        {**BOX, "right": 0.2},
        {**BOX, "top": 0.7},
        {**BOX, "bottom": float("nan")},
        {**BOX, "right": float("inf")},
        {**BOX, "left": True},
        {"top": 0.1, "bottom": 0.2},
    ],
)
def test_invalid_geometry_cannot_be_clamped_into_a_click(box):
    original = observation()
    corrupt = helpers.Observation(original.judgments, SimpleNamespace(box=box, confidence=0.99))
    result = helpers.route(corrupt, POLICY, (512, 384))
    assert result.status == "review"
    assert result.box is None and result.point is None


def test_valid_edge_box_center_is_in_image_and_log_is_simulation():
    example = select_split(load_inputs(RECIPE), "demo")[0]
    full = observation(box={"left": 0, "top": 0, "right": 1, "bottom": 1})
    result, actions, reviews = helpers.simulate(example, full, POLICY, RECIPE)
    assert result.point == (255, 191)
    assert len(actions) == 1 and len(reviews) == 0
    record = actions.to_dicts()[0]
    assert record["executed"] is False
    assert record["kind"] == "simulate_click"
    assert set(record["answer"]) == {"present", "unique", "enabled", "target_box"}


def test_focus_and_review_records_keep_the_input_and_answer_evidence():
    [example] = [e for e in load_inputs(RECIPE) if e.id == "t02"]
    seen = observation()
    located, actions, reviews = helpers.simulate(example, seen, POLICY, RECIPE)
    [action] = actions.to_dicts()
    assert located.status == "located" and len(reviews) == 0
    assert action["kind"] == "simulate_focus" and action["executed"] is False
    assert action["payload"] == {
        "example": "t02",
        "target": "Search projects",
        "point": list(located.point),
    }
    assert action["answer"]["target_box"] == seen.location.to_dict()

    seen = observation(present=0.01, unique=0.99, enabled=0.01)
    result, actions, reviews = helpers.simulate(example, seen, POLICY, RECIPE)
    [review] = reviews.to_dicts()
    assert result.status == "review" and len(actions) == 0
    assert review["item"] == {"example": "t02"} and review["status"] == "pending"
    assert review["reason"] == "absence conflicts with uniqueness or enabled state"
    assert review["answer"]["present"] == seen.judgments["present"].to_dict()


def test_iou_intersection_and_miss_contribute_to_full_denominator():
    assert box_iou(BOX, BOX) == 1.0
    assert box_iou(BOX, {"left": 0, "top": 0, "right": 0.1, "bottom": 0.1}) == 0.0
    assert box_iou(
        {"left": 0, "top": 0, "right": 0.5, "bottom": 0.5},
        {"left": 0.25, "top": 0.25, "right": 0.75, "bottom": 0.75},
    ) == pytest.approx(1 / 7)
    examples = [SimpleNamespace(id="present"), SimpleNamespace(id="absent")]
    labels = {
        "present": {"target": {"present": True, "box": BOX}, "unique": True, "enabled": True},
        "absent": {"target": {"present": False}, "unique": False, "enabled": False},
    }
    outcomes = {
        "present": helpers.Outcome("review", "missing"),
        "absent": helpers.Outcome("located", "false positive", BOX),
    }
    report, summary = helpers.summarize(examples, outcomes, labels)
    assert summary["N"] == 2 and report.n_absent == 1
    assert report.mean_iou_present == 0.0 and report.hit_rate == 0.0
    assert report.present_review == 1 and report.present_missed == 0
    assert report.false_positives == 1 and report.ious == (None, None)
    assert summary["abstention"] == 0.5 and summary["answered_risk"] == 1.0


class TrackingBackend:
    def __init__(self, backend):
        self.backend = backend
        self.keys = []
        self.question_sets = []
        self.requests = []

    def decide(self, state, questions, *, assets):
        self.keys.append(replay_key(state, questions, assets=assets))
        self.question_sets.append(set(questions))
        self.requests.append((state, questions))
        return self.backend.decide(state, questions, assets=assets)


def test_replay_keys_follow_gates_and_absent_never_requests_box():
    policy = validation_policy()
    backend = ReplayBackend.from_json(responses_path(RECIPE))
    for example in load_inputs(RECIPE):
        if example.id == "d02":
            assert not example.replay_keys
            continue
        tracking = TrackingBackend(backend)
        threshold = (
            helpers.COLLECTION_THRESHOLD if example.split == "validation" else policy.presence
        )
        seen = helpers.observe(tracking, example.fields, RECIPE, threshold)
        assert tuple(tracking.keys) == example.replay_keys
        assert tracking.question_sets[0] == {"present", "unique", "enabled"}
        if helpers.first_gate(seen.judgments, threshold) is not None:
            assert seen.location is None
            assert len(tracking.keys) == 1
        else:
            assert tracking.question_sets[1:] == [{"target_box"}]


def test_authored_absence_answers_and_the_held_out_contradiction():
    examples = {e.id: e for e in load_inputs(RECIPE)}
    replay = ReplayBackend.from_json(responses_path(RECIPE))
    threshold = validation_policy().presence
    for ident in ("v06", "t05", "t06", "t12"):
        tracking = TrackingBackend(replay)
        seen = helpers.observe(tracking, examples[ident].fields, RECIPE, threshold)
        assert seen.location is None and tracking.question_sets == [
            {"present", "unique", "enabled"}
        ]
        assert seen.judgments["present"].noul < 0.5
        assert all(answer.provenance.source == "synthetic" for answer in seen.judgments.values())
        affirmations = [seen.judgments[name].noul > 0.5 for name in ("unique", "enabled")]
        assert affirmations == [ident == "t12"] * 2


def test_synthetic_absence_witness_has_no_request_or_action():
    witness = helpers.absence_witness()
    [example] = [e for e in load_inputs(RECIPE) if e.id == "d02"]
    assert example.split == "demo" and not example.replay_keys
    assert witness.judgments["present"].provenance.source == "synthetic"
    assert witness.location.provenance.source == "synthetic"
    assert witness.location.confidence >= POLICY.box
    outcome, actions, reviews = helpers.simulate(example, witness, POLICY, RECIPE)
    assert outcome.status == "absent" and outcome.box is None
    assert len(actions) == len(reviews) == 0


def test_validation_selection_is_frozen_and_test_contains_accepted_error():
    policy = validation_policy()
    assert policy == POLICY
    backend = ReplayBackend.from_json(responses_path(RECIPE))
    labels = load_labels(RECIPE)
    test = select_split(load_inputs(RECIPE), "test")
    outcomes = {
        e.id: helpers.route(
            helpers.observe(backend, e.fields, RECIPE, policy.presence),
            policy,
            helpers.dimensions(e.fields, RECIPE),
        )
        for e in test
    }
    assert any(
        outcomes[e.id].status == "located" and not helpers.success(outcomes[e.id], labels[e.id])
        for e in test
    )
    assert any(
        gold_box(labels[e.id]["target"]) is not None and outcomes[e.id].status == "absent"
        for e in test
    )
    report, summary = helpers.summarize(test, outcomes, labels)
    assert summary["N"] == 12 and report.n_absent == 3
    assert report.false_positives == 0 and report.present_review >= 2
    assert report.absent_review == 1
    assert gold_box(labels["t03"]["target"])["right"] == 1.0
    assert outcomes["t03"].status == "located"
    assert summary["unsafe_proposals"] > 0
    assert outcomes["t12"].status == "review"
    assert outcomes["t12"].reason == "absence conflicts with uniqueness or enabled state"


def test_selector_refuses_test_data_and_pins_both_objectives():
    with pytest.raises(ValueError, match="validation"):
        helpers.select_policy(select_split(load_inputs(RECIPE), "test"), {}, {})
    presence_source = inspect.getsource(helpers.select_noul_gate)
    box_source = inspect.getsource(helpers.select_policy)
    assert "min_coverage=0.7" in presence_source
    assert "min_coverage=0.5" in box_source


def test_stored_answers_are_not_all_right():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = ReplayBackend.from_json(responses_path(RECIPE))
    validation = select_split(examples, "validation")
    observations = {
        e.id: helpers.observe(backend, e.fields, RECIPE, helpers.COLLECTION_THRESHOLD)
        for e in validation
    }
    threshold = helpers.select_noul_gate(validation, observations, labels)
    wrong_and_confident = []
    for example in select_split(examples, "test"):
        state, assets = helpers.request_data(example.fields, RECIPE)
        answer = helpers.image_decide(backend, state, helpers.build_questions(), assets)["present"]
        present = gold_box(labels[example.id]["target"]) is not None
        confidence = noul_confidence([answer.noul])[0]
        if confidence >= threshold and (answer.noul > 0.5) != present:
            wrong_and_confident.append(example.id)
    assert wrong_and_confident == ["t07"]


def test_actual_noul_gate_ablation_uses_the_committed_validation_judgments():
    validation, observations, labels = validation_data()
    policy = helpers.select_policy(validation, observations, labels)
    assert helpers.measure_noul_gates(validation, observations, policy) == {
        "present": ((0, 1), (2, 9)),
        "unique": ((0, 2), (0, 8)),
        "enabled": ((0, 2), (0, 8)),
    }
    [held_out, *_] = select_split(load_inputs(RECIPE), "test")
    with pytest.raises(ValueError, match="only validation"):
        helpers.measure_noul_gates([*validation, held_out], observations, policy)


def test_asset_paths_reject_absolute_paths_and_parent_traversal(tmp_path):
    root = tmp_path / "recipe"
    root.mkdir()
    external = tmp_path / "synthetic.png"
    Image.new("RGB", (512, 384), "white").save(external)
    absent = helpers.Outcome("absent", "target judged absent")
    for path in (external, "../synthetic.png"):
        fields = {"image": path, "target": "Save changes", "kind": "button"}
        with pytest.raises(AssetPathError):
            helpers.request_data(fields, root)
        with pytest.raises(AssetPathError):
            helpers.dimensions(fields, root)
        with pytest.raises(AssetPathError):
            helpers.show_location(fields, root, absent)


def test_actual_box_request_puts_the_target_description_in_instructions_only():
    demo = select_split(load_inputs(RECIPE), "demo")[0]
    backend = TrackingBackend(ReplayBackend.from_json(responses_path(RECIPE)))
    helpers.observe(backend, demo.fields, RECIPE, POLICY.presence)
    [(noul_state, _), (box_state, questions)] = backend.requests
    assert noul_state["target"] == demo.fields["target"]
    assert box_state == {"screenshot": noul_state["screenshot"]}
    box = questions["target_box"].to_dict()
    assert demo.fields["target"] in box["instructions"]
    assert demo.fields["kind"] in box["instructions"]
    assert "criteria" not in box


def test_state_contains_no_gold_or_coordinate_leaks_and_images_meet_limits():
    for label in load_labels(RECIPE).values():
        if gold_box(label["target"]) is None:
            assert label["boxes"] == [] and not label["unique"] and not label["enabled"]
    for example in load_inputs(RECIPE):
        state, assets = helpers.request_data(example.fields, RECIPE)
        assert set(state) == {"screenshot", "target", "kind"}
        assert list(assets) == [state["screenshot"]]
        assert example.fields["image"].split("/")[-1].endswith(".png")
        with Image.open(resolve_asset_path(example.fields["image"], root=RECIPE)) as image:
            width, height = image.size
            assert width >= 384 and height >= 320 and width * height >= 78400
        changed = dict(example.fields, boxes=[BOX], present=False, layout="secret", label="secret")
        assert helpers.request_data(changed, RECIPE) == (state, assets)


def test_known_layout_baseline_uses_no_labels_and_fails_reflow_and_absence():
    labels = load_labels(RECIPE)
    test = select_split(load_inputs(RECIPE), "test")
    outcomes = {
        e.id: helpers.baseline(e.fields, helpers.dimensions(e.fields, RECIPE)) for e in test
    }
    assert not helpers.success(outcomes["t02"], labels["t02"])
    assert not helpers.success(outcomes["t03"], labels["t03"])
    assert helpers.summarize(test, outcomes, labels)[0].false_positives == 3
