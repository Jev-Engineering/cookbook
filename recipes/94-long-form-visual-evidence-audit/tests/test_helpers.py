"""Audit invariants, independent baselines, provenance, and held-out imperfection."""

import ast
import copy
import hashlib
import inspect
import itertools
import json
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import Noul, NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue
from jev_cookbook.vision import image_asset, image_reference, run_record

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
EXAMPLES = load_inputs(RECIPE)
LABELS = load_labels(RECIPE)


def answers(*probabilities):
    return {
        name: NoulAnswer(value, Provenance.synthetic())
        for name, value in zip(helpers.QUESTION_NAMES, probabilities, strict=True)
    }


def results_for(examples):
    backend = get_backend(fixtures=responses_path(RECIPE))
    return {e.id: helpers.AuditSession(backend, RECIPE).decide(e) for e in examples}


def test_questions_are_four_independent_bounded_propositions():
    questions = helpers.build_questions()
    assert list(questions) == [
        "visual_support",
        "visual_contradiction",
        "report_support",
        "report_contradiction",
    ]
    assert all(isinstance(q, Noul) for q in questions.values())
    assert "directly shows the claim to be true" in questions["visual_support"].instructions
    assert "explicitly contradicts the claim" in questions["report_contradiction"].instructions


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    for example in EXAMPLES:
        state, questions, assets = helpers.build_request(example.fields, RECIPE)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)
        assert len(assets) == 2
        serialized = json.dumps(state)
        for forbidden in (
            "rationale",
            "probabilities",
            "gold",
            "split",
            "history_path",
            "data_base64",
        ):
            assert forbidden not in serialized
        assert all(p["image"].startswith("image:sha256:") for p in state["photos"])


def test_full_documents_have_distant_dated_evidence_and_other_asset_record():
    for example in EXAMPLES:
        history = helpers.load_history(example.fields, RECIPE)
        assert len(history) == 44
        assert sum(len(r["body"].split()) for r in history) > 3500
        assert history[2]["title"] == "Archived condition sign-off"
        assert history[-1]["title"] == "Audit-date signed addendum"
        assert history[2]["observed_at"] < history[-1]["observed_at"]
        assert len(history[3:43]) == 40
        eligible = helpers.eligible_records(example.fields, history)
        assert history[2] not in eligible and history[24] not in eligible
        assert history[-1] in eligible


@pytest.mark.parametrize("bits", list(itertools.product((0.01, 0.99), repeat=4)))
def test_composition_and_review_under_arbitrary_answers(bits):
    outcome = helpers.audit(EXAMPLES[0].fields, answers(*bits), 0.8, RECIPE)
    vs, vc, rs, rc = (p > 0.5 for p in bits)
    if (vs and vc) or (rs and rc) or not any((vs, vc, rs, rc)):
        assert outcome.outcome == "review"
        assert not outcome.accepted
    elif vc or rc:
        assert outcome.accepted and outcome.category == "contradicted"
    elif vs:
        assert outcome.accepted and outcome.category == "image_supported"
    else:
        assert outcome.accepted and outcome.category == "report_only"


def test_threshold_boundary_missing_answers_and_invalid_thresholds():
    fields = EXAMPLES[0].fields
    strong = answers(0.9, 0.1, 0.9, 0.1)
    threshold = helpers.certainty(strong)
    assert helpers.audit(fields, strong, threshold, RECIPE).accepted
    rejected = helpers.audit(fields, strong, threshold + 0.001, RECIPE)
    assert rejected.reason == "confidence below the threshold"
    assert helpers.audit(fields, {}, 0, RECIPE).outcome == "review"
    for bad in (float("nan"), float("inf"), -1, 1.01, None):
        with pytest.raises(ValueError):
            helpers.audit(fields, strong, bad, RECIPE)


@pytest.mark.parametrize(
    "mutation", ["stale", "future", "unknown", "wrong_asset", "duplicate", "date", "no_current"]
)
def test_photo_provenance_interlock_overrides_confident_answers(mutation):
    fields = copy.deepcopy(EXAMPLES[0].fields)
    current = fields["photos"][1]
    if mutation == "stale":
        current["captured_at"] = "2020-01-01"
        fields["source_manifest"][current["source_id"]]["captured_at"] = "2020-01-01"
    elif mutation == "future":
        current["published_at"] = "2027-01-01"
    elif mutation == "unknown":
        current["source_id"] = "NOT-REGISTERED"
    elif mutation == "wrong_asset":
        current["asset_id"] = "OTHER-PUMP"
    elif mutation == "duplicate":
        current["source_id"] = fields["photos"][0]["source_id"]
    elif mutation == "date":
        current["captured_at"] = "invalid"
    else:
        current["role"] = "historical"
    outcome = helpers.audit(fields, answers(0.999, 0.001, 0.999, 0.001), 0.5, RECIPE)
    assert outcome.outcome == "review"
    assert outcome.category == "unknown"


def test_report_dates_source_uniqueness_and_cutoff_are_exact():
    fields = EXAMPLES[0].fields
    history = helpers.load_history(fields, RECIPE)
    assert not helpers.report_checks(fields, history)
    duplicate = copy.deepcopy(history)
    duplicate[0]["source_id"] = duplicate[1]["source_id"]
    assert helpers.report_checks(fields, duplicate) == ["duplicate report source identity"]
    malformed = copy.deepcopy(history)
    malformed[0]["published_at"] = "2010-01-01"
    assert "invalid report chronology" in helpers.report_checks(fields, malformed)
    future = copy.deepcopy(history)
    future[-1]["published_at"] = "2027-01-01"
    assert not helpers.eligible_records(fields, future)


def test_report_and_pixels_and_source_identity_bind_replay_key(tmp_path):
    fields = copy.deepcopy(EXAMPLES[0].fields)
    state, questions, assets = helpers.build_request(fields, RECIPE)
    original = replay_key(state, questions, assets=assets)
    changed = copy.deepcopy(state)
    changed["history"][-1]["body"] += " The earlier sign-off was withdrawn."
    assert replay_key(changed, questions, assets=assets) != original
    changed = copy.deepcopy(state)
    changed["photos"][1]["source_id"] = "IMG-OTHER"
    assert replay_key(changed, questions, assets=assets) != original
    with Image.open(RECIPE / fields["photos"][1]["path"]) as opened:
        image = opened.convert("RGB")
        image.putpixel((240, 160), (0, 0, 0))
        image.save(tmp_path / "changed.png")
    changed_asset = image_asset(tmp_path / "changed.png")
    changed_reference = image_reference(changed_asset)
    changed = copy.deepcopy(state)
    old_reference = changed["photos"][1]["image"]
    changed["photos"][1]["image"] = changed_reference
    changed_assets = dict(assets)
    changed_assets.pop(old_reference)
    changed_assets[changed_reference] = changed_asset
    assert replay_key(changed, questions, assets=changed_assets) != original


@pytest.mark.parametrize("change", ["future_publication", "other_asset"])
def test_report_claim_without_eligible_sources_cannot_be_accepted(tmp_path, change):
    fields = copy.deepcopy(next(e for e in EXAMPLES if e.id == "t03").fields)
    history = helpers.load_history(fields, RECIPE)
    if change == "future_publication":
        history[-1]["published_at"] = "2027-01-01"
    else:
        history[-1]["asset_id"] = "ANOTHER-PUMP"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(history))
    fields["history_path"] = str(path)
    for result in (answers(.01, .01, .99, .01), answers(.01, .01, .01, .99)):
        outcome = helpers.audit(fields, result, .8, RECIPE)
        assert outcome.outcome == "review"
        assert outcome.category == "unknown"
        assert outcome.report_sources == ()


def test_image_lineages_do_not_cross_splits():
    hashes = {}
    asset_ids = {}
    for example in EXAMPLES:
        assert example.fields["asset_id"] not in asset_ids
        asset_ids[example.fields["asset_id"]] = example.split
        for photo in example.fields["photos"]:
            path = RECIPE / photo["path"]
            with Image.open(path) as image:
                assert image.size == (480, 360)
                digest = hashlib.sha256(image.tobytes()).hexdigest()
            assert digest not in hashes
            hashes[digest] = example.split


def test_baseline_uses_pixels_and_retrieved_report_without_labels(tmp_path):
    fields = copy.deepcopy(EXAMPLES[0].fields)
    assert helpers.retrieval_pixel_baseline(fields, RECIPE) == "image_supported"
    # Same dates and report, pixels replaced by the independently supplied historical view.
    fields["photos"][1]["path"] = fields["photos"][0]["path"]
    assert helpers.retrieval_pixel_baseline(fields, RECIPE) == "report_only"
    bearing = copy.deepcopy(next(e for e in EXAMPLES if e.id == "t03").fields)
    assert helpers.retrieval_pixel_baseline(bearing, RECIPE) == "report_only"
    history = helpers.load_history(bearing, RECIPE)
    history[-1]["body"] = "The exterior paint was inspected."
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history))
    bearing["history_path"] = str(path)
    assert helpers.retrieval_pixel_baseline(bearing, RECIPE) == "unknown"
    source = inspect.getsource(helpers.retrieval_pixel_baseline)
    assert "load_labels" not in source and "responses" not in source


def test_the_threshold_objective_is_pinned_to_committed_wrapper_source():
    source = inspect.getsource(helpers.choose_threshold)
    assert "min_coverage=0.75" in source
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
        ("min_coverage", 0.75)
    ]


def test_stored_answers_are_not_all_right():
    validation = [e for e in EXAMPLES if e.split == "validation"]
    results = results_for(validation)
    eligible = [
        e for e in validation if helpers.audit(e.fields, results[e.id].answers, 0, RECIPE).accepted
    ]
    correct = [
        helpers.category(results[e.id].answers) == LABELS[e.id]["category"] for e in eligible
    ]
    confidence = [helpers.certainty(results[e.id].answers) for e in eligible]
    threshold = select_confidence_threshold(correct, confidence, min_coverage=0.75)
    assert threshold == helpers.choose_threshold(validation, results, LABELS, RECIPE)
    test = [e for e in EXAMPLES if e.split == "test"]
    results = results_for(test)
    wrong_and_confident = [
        e.id
        for e in test
        if helpers.category(results[e.id].answers) != LABELS[e.id]["category"]
        and helpers.certainty(results[e.id].answers) >= threshold
        and helpers.audit(e.fields, results[e.id].answers, threshold, RECIPE).accepted
    ]
    assert wrong_and_confident == ["t11"]


def test_request_budget_stops_and_duplicate_cases_are_not_decided_twice():
    backend = get_backend(fixtures=responses_path(RECIPE))
    session = helpers.AuditSession(backend, RECIPE, max_requests=1)
    session.decide(EXAMPLES[0])
    with pytest.raises(ValueError, match="already audited"):
        session.decide(EXAMPLES[0])
    with pytest.raises(RuntimeError, match="budget exhausted"):
        session.decide(EXAMPLES[1])
    assert session.requests == 1
    for invalid in (-1, 27, 1.5, True):
        with pytest.raises(ValueError):
            helpers.AuditSession(backend, RECIPE, max_requests=invalid)


def test_reviews_do_not_count_as_coverage_or_simulated_actions():
    examples = [EXAMPLES[0], next(e for e in EXAMPLES if e.id == "v07")]
    results = results_for(examples)
    actions, reviews = ActionLog(), ReviewQueue()
    outcomes = [helpers.audit(e.fields, results[e.id].answers, 0.8, RECIPE) for e in examples]
    for example, outcome in zip(examples, outcomes, strict=True):
        helpers.record_outcome(example, results[example.id], outcome, actions, reviews)
    assert len(actions) == 1 and len(reviews) == 1
    assert not actions.to_dicts()[0]["executed"]
    assert actions.to_dicts()[0]["payload"]["photo_sources"] == ["IMG-101-A", "IMG-101-B"]
    summary = evaluate_outcomes([o.accepted for o in outcomes], [True, True])
    assert summary.coverage == 0.5 and summary.n_answered == 1


def test_unknown_accounting_stays_none_and_long_context_opt_in_is_distinct():
    result = results_for(EXAMPLES[:1])[EXAMPLES[0].id]
    row = run_record(result, mode="synthetic")
    assert all(
        row[k] is None for k in ("input_tokens", "output_tokens", "latency_seconds", "cost_usd")
    )
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    setup = next(c for c in notebook["cells"] if c["id"] == "setup")
    source = "".join(setup["source"])
    assert "images=True" in source and "long_context=True" in source
    assert 'model="jev-1.14.0"' in source
