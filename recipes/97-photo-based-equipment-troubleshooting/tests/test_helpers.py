"""Pin scope, policy, fixture identity, meaningful baselines and honest evaluation."""

import ast
import hashlib
import inspect
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(candidate, p=0.96):
    return ChoiceAnswer.from_probabilities(
        {key: p if key == candidate else (1 - p) / 4 for key in helpers.OPTIONS},
        Provenance.synthetic(),
    )


def fields():
    return {"model": "PG-2", "revision": "R2", "review_approved": True, "artifact_only": True}


@pytest.mark.parametrize("choice", helpers.OPTIONS + ("open_enclosure",))
@pytest.mark.parametrize("flag", ("review_approved", "artifact_only"))
@pytest.mark.parametrize("value", (False, None, "true", 1))
def test_trusted_interlocks_hold_for_arbitrary_answers(choice, flag, value):
    context = fields() | {flag: value}
    assert not helpers.route(context, SimpleNamespace(choice=choice, confidence=1), 0).accepted


@pytest.mark.parametrize("profile", (("PG-2", "R1"), ("PG-1", "R0")))
def test_filter_check_cannot_cross_revision_boundary(profile):
    context = fields() | dict(zip(("model", "revision"), profile, strict=True))
    assert "incompatible" in helpers.route(context, answer("check_filter"), 0).reason


def test_r2_rejects_card_and_unknown_revision_rejects_every_answer():
    assert not helpers.route(fields(), answer("check_card"), 0).accepted
    for choice in helpers.OPTIONS:
        assert not helpers.route(fields() | {"revision": "R9"}, answer(choice), 0).accepted


@pytest.mark.parametrize("confidence", (None, float("nan"), float("inf"), -1, 2, "0.99", True))
def test_invalid_or_missing_confidence_cannot_pass(confidence):
    assert not helpers.route(
        fields(), SimpleNamespace(choice="check_filter", confidence=confidence), 0.5
    ).accepted


@pytest.mark.parametrize("threshold", (None, float("nan"), float("inf"), -0.1, 1.1, True))
def test_invalid_threshold_is_rejected(threshold):
    with pytest.raises(ValueError):
        helpers.route(fields(), answer("check_filter"), threshold)


def test_inclusive_gate_and_explicit_uncertain_review():
    a = answer("check_filter")
    assert helpers.route(fields(), a, a.confidence).accepted
    assert not helpers.route(fields(), a, a.confidence + 1e-9).accepted
    assert helpers.route(fields(), answer("uncertain"), 0).outcome == "review"


def test_dispatch_drafts_only_fixed_text_and_never_executes():
    actions, reviews = ActionLog(), ReviewQueue()
    helpers.dispatch("demo", fields(), answer("check_filter"), 0.5, actions, reviews)
    helpers.dispatch("ambiguous", fields(), answer("uncertain"), 0, actions, reviews)
    helpers.dispatch("normal", fields(), answer("none_suitable"), 0.5, actions, reviews)
    assert len(actions) == 1 and len(reviews) == 1
    entry = actions.to_dicts()[0]
    assert entry["executed"] is False
    assert (
        entry["payload"]["text"]
        == "Compare the photographed filter tab mark with the R2 reference legend."
    )
    assert reviews.pending()[0].item["case"] == "ambiguous"


def test_options_and_request_exclude_labels_policy_flags_and_drawing_metadata():
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(
        example.fields | {"gold": "secret", "split": "test", "cue": "amber"}, RECIPE
    )
    assert set(state) == {"image", "inventory", "operator_note", "manual"}
    assert tuple(questions["candidate"].criteria) == (
        "check_window",
        "check_card",
        "check_filter",
        "none_suitable",
        "uncertain",
    )
    assert state["image"].startswith("image:sha256:")
    assert set(assets) == {state["image"]}
    assert "secret" not in json.dumps(state)


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_image_bytes_inventory_manual_and_questions_change_identity(tmp_path):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    e = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(e.fields, tmp_path)
    original = replay_key(state, questions, assets=assets)
    assert (
        replay_key(
            state | {"inventory": {"model": "PG-2", "revision": "R2"}}, questions, assets=assets
        )
        != original
    )
    assert (
        replay_key(
            state | {"manual": state["manual"] + "Revision correction."}, questions, assets=assets
        )
        != original
    )
    with Image.open(tmp_path / e.fields["image"]) as source:
        image = source.copy()
    image.putpixel((342, 126), (1, 2, 3))
    image.save(tmp_path / e.fields["image"])
    changed, questions, changed_assets = helpers.build_request(e.fields, tmp_path)
    assert replay_key(changed, questions, assets=changed_assets) != original
    from jev_cookbook import Choice

    other_questions = {
        "candidate": Choice(
            criteria=questions["candidate"].criteria, instructions="Different question."
        )
    }
    assert replay_key(state, other_questions, assets=assets) != original


def test_image_content_does_not_duplicate_across_splits():
    seen = {}
    for example in load_inputs(RECIPE):
        with Image.open(RECIPE / example.fields["image"]) as image:
            assert image.size == (480, 360)
            digest = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
        assert digest not in seen, (example.id, seen.get(digest))
        seen[digest] = example.id


def test_pixel_baseline_uses_changed_pixels_and_ignores_filenames(tmp_path):
    examples = load_inputs(RECIPE)
    amber = examples[0]
    blue = next(e for e in examples if e.id == "v04")
    target = tmp_path / "same-name.png"
    shutil.copyfile(RECIPE / amber.fields["image"], target)
    assert helpers.pixel_cue(target) == "amber"
    shutil.copyfile(RECIPE / blue.fields["image"], target)
    assert helpers.pixel_cue(target) == "blue"
    base = helpers.baseline(amber.fields, RECIPE, retrieval=True).choice
    assert (
        helpers.baseline(
            amber.fields | {"label": "garbage", "id": "t01", "split": "test"},
            RECIPE,
            retrieval=True,
        ).choice
        == base
    )


def test_retrieval_is_sensitive_to_model_and_surfaces_obsolete_conflict():
    examples = {e.id: e for e in load_inputs(RECIPE)}
    assert helpers.baseline(examples["v01"].fields, RECIPE, retrieval=True).choice == "check_card"
    clean = examples["v01"].fields | {"revision": "R2"}
    assert helpers.baseline(clean, RECIPE, retrieval=True).choice == "check_filter"
    ranked = helpers.retrieve_sections(examples["t02"].fields, "amber")
    assert ranked[0][1] == "H21"
    assert any(row[1] == "P31" for row in ranked)
    assert len(helpers.manual_text().split()) > 4000
    assert len(helpers.manual_sections()) == 28


def test_request_budget_cache_and_changed_evidence():
    backend = get_backend(fixtures=RECIPE / "fixtures/responses.json")
    session = helpers.RequestSession(backend, RECIPE, max_requests=1)
    examples = load_inputs(RECIPE)
    result = session.decide(examples[0])
    assert session.decide(examples[0]) is result
    assert session.attempts == 1
    with pytest.raises(RuntimeError, match="budget"):
        session.decide(examples[1])
    changed = replace(examples[0], fields=examples[0].fields | {"note": "changed"})
    with pytest.raises(ValueError, match="changed evidence"):
        session.decide(changed)


def test_stored_answers_are_not_all_right():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    session = helpers.RequestSession(
        get_backend(fixtures=RECIPE / "fixtures/responses.json"), RECIPE
    )
    answers = {e.id: session.decide(e)["candidate"] for e in examples}
    validation = [e for e in examples if e.split == "validation"]
    eligible = [e for e in validation if helpers.route(e.fields, answers[e.id], 0).accepted]
    threshold = select_confidence_threshold(
        [answers[e.id].choice == labels[e.id]["candidate"] for e in eligible],
        [answers[e.id].confidence for e in eligible],
        target_accuracy=1.0,
    )
    assert threshold == helpers.select_gate(validation, answers, labels)
    wrong_and_confident = [
        e.id
        for e in examples
        if e.split == "test"
        and answers[e.id].choice != labels[e.id]["candidate"]
        and answers[e.id].confidence >= threshold
        and helpers.route(e.fields, answers[e.id], threshold).accepted
    ]
    assert wrong_and_confident == ["t08"]


def test_the_selection_objective_is_pinned_to_the_actual_helper_source():
    source = inspect.getsource(helpers.select_gate)
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source
    tree = ast.parse(source)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "select_confidence_threshold"
    ]
    assert len(calls) == 1
    assert [(k.arg, ast.literal_eval(k.value)) for k in calls[0].keywords] == [
        ("target_accuracy", 1.0)
    ]
    with pytest.raises(ValueError, match="validation"):
        helpers.select_gate([e for e in load_inputs(RECIPE) if e.split == "test"], {}, {})
