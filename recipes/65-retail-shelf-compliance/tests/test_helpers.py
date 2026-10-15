"""Policy, image identity, baseline independence, and held-out residual-error checks."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answers(values):
    return {g: SimpleNamespace(noul=p) for g, p in zip(helpers.GROUPS, values, strict=True)}


def fixtures():
    examples = load_inputs(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    results = {}
    for example in examples:
        state, questions, assets = helpers.request(example.fields, RECIPE)
        results[example.id] = backend.decide(state, questions, assets=assets)
    return examples, load_labels(RECIPE), results


@pytest.mark.parametrize(
    "values,expected",
    [
        ((0.99, 0.99, 0.99), "compliant"),
        ((0.01, 0.99, 0.99), "noncompliant"),
        ((0.01, 0.50, 0.99), "review"),
        ((0.50, 0.50, 0.50), "review"),
    ],
)
def test_complete_report_requires_every_group(values, expected):
    assert helpers.assess(answers(values), 0.5).outcome == expected


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), -0.1, 1.1, True, "0.99"])
def test_invalid_model_value_cannot_clear_gate(bad):
    assert helpers.assess(answers((bad, 0.99, 0.99)), 0.5).outcome == "review"


def test_missing_extra_answer_and_uncertain_negative_go_to_review():
    for invalid in ({}, {**answers((0.99, 0.99, 0.99)), "order": 0.99}):
        assert helpers.assess(invalid, 0.5).outcome == "review"
    assert helpers.assess(answers((0.49, 0.01, 0.99)), 0.5).outcome == "review"


def test_exactly_undecided_never_becomes_a_completed_answer():
    assert helpers.assess(answers((0.5, 0.99, 0.99)), 0).outcome == "review"


def test_inclusive_gate_and_invalid_threshold():
    a = answers((0.8, 0.8, 0.8))
    certainty = abs(2 * 0.8 - 1)
    assert helpers.assess(a, certainty).outcome == "compliant"
    assert helpers.assess(a, certainty + 1e-8).outcome == "review"
    for bad in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            helpers.assess(a, bad)


def test_simulation_has_only_report_actions_and_review_deferrals():
    actions, reviews = ActionLog(), ReviewQueue()
    for i, values in enumerate(((0.99, 0.99, 0.99), (0.01, 0.99, 0.99), (0.99, 0.5, 0.99))):
        helpers.report(str(i), helpers.assess(answers(values), 0.5), actions, reviews)
    assert len(actions) == 2 and len(reviews) == 1
    assert all(x["kind"] == "shelf_audit_report" and not x["executed"] for x in actions.to_dicts())
    assert reviews.pending()[0].item["groups"]["tea"] == "review"
    assert "restock" not in json.dumps(actions.to_dicts())


def test_state_contains_actual_reference_asset_without_authoring_metadata():
    example = load_inputs(RECIPE)[0]
    polluted = {**example.fields, "gold": "compliant", "split": "test", "render": "empty"}
    state, questions, assets = helpers.request(polluted, RECIPE)
    assert set(state) == {"shelf", "planogram", "scope"}
    assert state["shelf"] != state["planogram"]
    assert state["planogram"] in assets and state["shelf"] in assets
    assert set(questions) == {"oats", "tea", "soup"}
    assert all(q.type == "noul" for q in questions.values())
    assert len(assets) == 2


def test_replay_identity_binds_both_pixel_assets_and_task_context(tmp_path):
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.request(example.fields, RECIPE)
        key = replay_key(state, questions, assets=assets)
        assert example.replay_keys == (key,)
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.request(example.fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    for role in ("shelf", "planogram"):
        with Image.open(RECIPE / example.fields[role]) as image:
            image.putpixel((25, 125), (1, 2, 3))
            image.save(tmp_path / "changed.png")
        changed = image_asset(tmp_path / "changed.png")
        assert replay_key(state, questions, assets={**assets, state[role]: changed}) != original
        ref = image_reference(changed)
        replacement = {k: v for k, v in assets.items() if k != state[role]}
        replacement[ref] = changed
        assert replay_key({**state, role: ref}, questions, assets=replacement) != original
    assert replay_key({**state, "scope": "different policy"}, questions, assets=assets) != original


def test_splits_have_distinct_queries_and_one_shared_approved_reference():
    examples = load_inputs(RECIPE)
    query_refs = {}
    for e in examples:
        state, _ = helpers.build_state(e.fields, RECIPE)
        assert state["shelf"] not in query_refs
        query_refs[state["shelf"]] = e.split
    assert len({e.fields["planogram"] for e in examples}) == 1


def test_baseline_uses_pixels_not_labels_ids_or_rendering_spec(tmp_path):
    examples = load_inputs(RECIPE)
    baseline = helpers.pixel_baseline(examples[0].fields, RECIPE)
    assert baseline.outcome == "compliant"
    copied = {}
    for role in ("shelf", "planogram"):
        copied[role] = role + ".png"
        (tmp_path / copied[role]).write_bytes((RECIPE / examples[0].fields[role]).read_bytes())
    assert helpers.pixel_baseline(copied, tmp_path) == baseline
    assert (
        helpers.pixel_baseline({**examples[0].fields, "gold": "wrong", "id": "gap"}, RECIPE)
        == baseline
    )
    gap = next(e for e in examples if e.id == "t04-gap")
    assert helpers.pixel_baseline(gap.fields, RECIPE).groups["oats"] == "noncompliant"
    blocked = next(e for e in examples if e.id == "t06-occluded")
    assert helpers.pixel_baseline(blocked.fields, RECIPE).groups["soup"] == "review"
    alt = next(e for e in examples if e.id == "t07-new-pack")
    assert helpers.pixel_baseline(alt.fields, RECIPE).outcome == "noncompliant"


def test_stored_answers_are_not_all_right():
    examples, labels, results = fixtures()
    validation = [e for e in examples if e.split == "validation"]
    pairs = [
        (
            abs(2 * results[e.id][g].noul - 1),
            ("compliant" if results[e.id][g].noul >= 0.5 else "noncompliant")
            == labels[e.id]["groups"][g],
        )
        for e in validation
        for g in helpers.GROUPS
    ]
    threshold = select_confidence_threshold(
        [ok for _, ok in pairs], [c for c, _ in pairs], target_accuracy=1.0
    )
    assert threshold == helpers.freeze_policy(validation, labels, results)
    assert threshold == pytest.approx(0.56)
    wrong_and_confident = [
        e.id
        for e in examples
        if e.split == "test"
        if helpers.assess(results[e.id].answers, threshold).outcome != helpers.REVIEW
        and helpers.assess(results[e.id].answers, threshold).outcome != labels[e.id]["outcome"]
        and min(abs(2 * results[e.id][g].noul - 1) for g in helpers.GROUPS) >= threshold
    ]
    assert wrong_and_confident == ["t08-lookalike"]


def test_threshold_objective_is_pinned_to_production_function_source():
    source = inspect.getsource(helpers.freeze_policy)
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    examples, labels, results = fixtures()
    with pytest.raises(ValueError, match="validation"):
        helpers.freeze_policy([e for e in examples if e.split == "test"], labels, results)


def test_noul_answer_has_probability_not_a_confidence_field():
    value = NoulAnswer(0.8, Provenance.synthetic())
    assert not hasattr(value, "confidence")
