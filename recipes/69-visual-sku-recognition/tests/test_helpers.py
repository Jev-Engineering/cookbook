"""Tests for recipe 69's helpers. They load the helpers by file path."""

import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook import synthetic_images as si
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ReviewQueue
from jev_cookbook.vision import image_request_profile

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

OPTIONS = ["DEGUM", "BIVEN", "NOKER", "PEBIX", "VODAR", "MAFEX", "no_match", "uncertain"]


def load_build_fixtures():
    spec = importlib.util.spec_from_file_location(
        "recipe69_build_fixtures", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answer(choice, top=0.5):
    """A Choice answer over the eight options whose top option is ``choice`` at probability
    ``top`` (at least 0.14, so it is the largest); the others share the rest equally."""
    others = (1 - top) / (len(OPTIONS) - 1)
    probabilities = {option: others for option in OPTIONS}
    probabilities[choice] = top
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def stored_answers():
    backend = get_backend(fixtures=responses_path(RECIPE), images=True)
    questions = helpers.build_questions()
    found = {}
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        found[example.id] = backend.decide(state, questions, assets=assets)["sku"]
    return found


def frozen_threshold(answers):
    """The notebook's selection, mirrored: the lowest confidence at which every validation answer
    that is not ``uncertain`` and clears it is right."""
    labels = load_labels(RECIPE)
    pool = [
        (answers[e.id].choice == labels[e.id], answers[e.id].confidence)
        for e in load_inputs(RECIPE)
        if e.split == "validation" and answers[e.id].choice != "uncertain"
    ]
    threshold = select_confidence_threshold(
        [ok for ok, _ in pool], [c for _, c in pool], target_accuracy=1.0
    )
    return threshold


# --- the catalogue and the question ------------------------------------------------------------


def test_the_catalogue_is_six_products_and_the_options_add_the_two_outcomes():
    assert [sku.name for sku in helpers.CATALOG] == OPTIONS[:6]
    assert list(helpers.OPTIONS) == OPTIONS
    assert [(s.name, s.body, s.lid, s.emblem) for s in helpers.CATALOG] == [
        ("DEGUM", "blue", "ink", "ring"),
        ("BIVEN", "blue", "ink", "bars"),
        ("NOKER", "teal", "white", "disc"),
        ("PEBIX", "green", "ink", "triangle"),
        ("VODAR", "amber", "white", "stack"),
        ("MAFEX", "purple", "white", "ring"),
    ]


def test_exactly_one_pair_of_products_differs_in_one_feature():
    pairs = []
    catalog = helpers.CATALOG
    for first in range(len(catalog)):
        for second in range(first + 1, len(catalog)):
            differing = [
                a
                for a in helpers.ATTRIBUTES
                if getattr(catalog[first], a) != getattr(catalog[second], a)
            ]
            if len(differing) == 1:
                pairs.append((catalog[first].name, catalog[second].name, differing[0]))
    assert pairs == [("DEGUM", "BIVEN", "emblem")]


def test_the_question_is_one_choice_with_a_reference_image_in_every_product_criterion():
    questions = helpers.build_questions()
    assert list(questions) == ["sku"]
    question = questions["sku"]
    assert question.to_dict()["type"] == "choice"
    assert list(question.criteria) == OPTIONS
    references = helpers.reference_assets()
    assert list(references) == OPTIONS[:6]
    for name, (reference, _asset) in references.items():
        assert question.criteria[name].count(reference) == 1
        assert reference.startswith("image:sha256:")
    # The two outcome options are words only, so they carry no copy of any image.
    for outcome in ("no_match", "uncertain"):
        assert "image:sha256:" not in question.criteria[outcome]
    assert "image:sha256:" not in question.instructions
    assert question.instructions.startswith("Which option is the tin shown in the `query` image?")
    assert question.criteria["no_match"].startswith("The tin in the query is not any product above")
    assert question.criteria["uncertain"].startswith("What the query shows fits two or more")


def test_the_state_holds_the_query_once_and_the_assets_hold_it_with_the_six_references():
    example = load_inputs(RECIPE)[0]
    state, assets = helpers.build_request(example.fields)
    assert list(state) == ["query"]
    assert state["query"] in assets
    assert len(assets) == 7
    assert [ref for ref in assets if ref != state["query"]] == [
        ref for ref, _ in helpers.reference_assets().values()
    ]


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    # The key covers every image's bytes, the six references in the criteria included, so a
    # changed picture or a changed criterion fails here.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_the_request_builder_accepts_the_catalogue_image_as_a_query():
    # A real user may submit the catalogue's own picture; only the fixtures forbid it.
    reference = helpers.CATALOG[0].reference_path
    state, assets = helpers.build_request(
        {"image": reference, "capture": "Q-0", "condition": "studio"}
    )
    assert state["query"] in assets
    assert len(assets) == 6


def test_reference_assets_returns_fresh_copies_each_call():
    first = helpers.reference_assets()
    name = helpers.CATALOG[0].name
    first[name][1]["data_base64"] = "changed"
    first.pop(helpers.CATALOG[1].name)
    again = helpers.reference_assets()
    assert again[name][1]["data_base64"] != "changed"
    assert list(again) == [sku.name for sku in helpers.CATALOG]


# --- the gold label ----------------------------------------------------------------------------


def test_candidates_are_the_products_that_agree_with_every_visible_feature():
    full = {"body": "blue", "lid": "ink", "emblem": "ring"}
    assert helpers.candidates(full) == ["DEGUM"]
    assert helpers.candidates({**full, "emblem": None}) == ["DEGUM", "BIVEN"]
    assert helpers.candidates({**full, "lid": None}) == ["DEGUM"]
    assert helpers.candidates({"body": "blue", "lid": "white", "emblem": "ring"}) == []
    assert helpers.candidates({"body": None, "lid": "white", "emblem": "ring"}) == ["MAFEX"]
    assert helpers.candidates({"body": None, "lid": "ink", "emblem": None}) == [
        "DEGUM",
        "BIVEN",
        "PEBIX",
    ]
    with pytest.raises(ValueError, match="exactly"):
        helpers.candidates({"body": "blue"})


def test_the_gold_label_is_the_product_no_match_or_uncertain():
    assert helpers.gold_label({"body": "teal", "lid": "white", "emblem": "disc"}) == "NOKER"
    assert helpers.gold_label({"body": "pink", "lid": "ink", "emblem": "disc"}) == "no_match"
    assert helpers.gold_label({"body": "blue", "lid": "white", "emblem": "ring"}) == "no_match"
    assert helpers.gold_label({"body": "blue", "lid": "ink", "emblem": None}) == "uncertain"
    assert helpers.gold_label({"body": "green", "lid": "ink", "emblem": None}) == "PEBIX"
    assert helpers.gold_label(None) == "no_match"


def test_hiding_a_feature_makes_a_product_uncertain_only_when_another_product_shares_the_rest():
    # Re-derived by counting, not by calling candidates: hide one feature of a product and count
    # the products that share the other two.
    for sku in helpers.CATALOG:
        for hidden in helpers.ATTRIBUTES:
            kept = [a for a in helpers.ATTRIBUTES if a != hidden]
            sharing = sum(
                all(getattr(other, a) == getattr(sku, a) for a in kept) for other in helpers.CATALOG
            )
            visible = {a: (None if a == hidden else getattr(sku, a)) for a in helpers.ATTRIBUTES}
            expected = sku.name if sharing == 1 else "uncertain"
            assert helpers.gold_label(visible) == expected, (sku.name, hidden)


# --- the rule ----------------------------------------------------------------------------------


def test_a_confident_product_or_no_match_is_delivered_and_a_less_confident_one_is_reviewed():
    for choice in ("DEGUM", "no_match"):
        shown = answer(choice, top=0.8)  # confidence (0.8 - 1/8) / (1 - 1/8) = 0.7714...
        assert shown.confidence == pytest.approx(0.7714285714285714)
        delivered = helpers.decide_sku("Q-1", shown, 0.77)
        assert (delivered.kind, delivered.label, delivered.reason) == (
            "answered",
            choice,
            "confident answer",
        )
        reviewed = helpers.decide_sku("Q-1", shown, 0.78)
        assert (reviewed.kind, reviewed.label, reviewed.reason) == (
            "review",
            None,
            "confidence below the threshold",
        )
        assert reviewed.choice == choice


def test_uncertain_is_a_review_at_every_confidence_and_threshold():
    for top in (0.2, 0.5, 0.9, 0.999):
        for threshold in (0.0, 0.5, 1.0):
            found = helpers.decide_sku("Q-1", answer("uncertain", top=top), threshold)
            assert (found.kind, found.label, found.reason) == (
                "review",
                None,
                "the answer is uncertain",
            )


def test_over_a_grid_the_outcome_is_a_review_exactly_below_the_threshold():
    for step in range(14, 100):
        shown = answer("VODAR", top=step / 100)
        for threshold in (0.0, 0.25, 0.5, 0.75, 1.0):
            found = helpers.decide_sku("Q-1", shown, threshold)
            if shown.confidence < threshold:
                assert (found.kind, found.reason) == ("review", "confidence below the threshold")
            else:
                assert found.kind == "answered" and found.label == "VODAR"


def test_an_option_outside_the_catalogue_list_or_a_threshold_outside_zero_to_one_raises():
    outside = ChoiceAnswer.from_probabilities({"DEGUM": 0.1, "ZZZZZ": 0.9}, Provenance.synthetic())
    with pytest.raises(ValueError, match="ZZZZZ"):
        helpers.decide_sku("Q-1", outside, 0.5)
    with pytest.raises(ValueError, match="threshold"):
        helpers.decide_sku("Q-1", answer("DEGUM", top=0.9), 1.1)
    with pytest.raises(ValueError, match="threshold"):
        helpers.decide_sku("Q-1", answer("DEGUM", top=0.9), -0.1)


def test_queue_reviews_queues_only_reviews_with_their_reasons():
    outcomes = [
        helpers.decide_sku("Q-1", answer("DEGUM", top=0.9), 0.5),  # delivered
        helpers.decide_sku("Q-2", answer("BIVEN", top=0.3), 0.5),  # below the threshold
        helpers.decide_sku("Q-3", answer("uncertain", top=0.95), 0.5),  # a deferral
        helpers.decide_sku("Q-4", answer("no_match", top=0.9), 0.5),  # delivered, nothing written
    ]
    queue = ReviewQueue()
    routed = helpers.queue_reviews(queue, outcomes)
    assert routed.review_keys == ("Q-2", "Q-3")
    assert [(i["id"], i["item"], i["reason"]) for i in queue.to_dicts()] == [
        (0, {"capture": "Q-2", "model_choice": "BIVEN"}, "confidence below the threshold"),
        (1, {"capture": "Q-3", "model_choice": "uncertain"}, "the answer is uncertain"),
    ]


def test_the_review_queue_the_notebook_fills_from_test_holds_these_captures_and_reasons():
    # Literals typed from the committed fixtures: with the threshold frozen on validation, six of
    # the sixteen test examples go to review and ten are delivered.
    answers = stored_answers()
    threshold = frozen_threshold(answers)
    test = [e for e in load_inputs(RECIPE) if e.split == "test"]
    outcomes = [helpers.decide_sku(e.fields["capture"], answers[e.id], threshold) for e in test]
    queue = ReviewQueue()
    routed = helpers.queue_reviews(queue, outcomes)
    assert routed.review_keys == ("Q-2006", "Q-2007", "Q-2010", "Q-2012", "Q-2013", "Q-2014")
    assert [i["reason"] for i in queue.to_dicts()] == [
        "confidence below the threshold",
        "confidence below the threshold",
        "confidence below the threshold",
        "confidence below the threshold",
        "the answer is uncertain",
        "confidence below the threshold",
    ]
    assert [o.label for o in outcomes if o.kind == "answered"] == [
        "DEGUM",
        "BIVEN",
        "NOKER",
        "PEBIX",
        "VODAR",
        "DEGUM",
        "VODAR",
        "no_match",
        "PEBIX",
        "MAFEX",
    ]


# --- the fixtures ------------------------------------------------------------------------------


def test_split_sizes_and_gold_labels_are_the_ones_the_notebook_reports():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    assert Counter(e.split for e in examples) == {"validation": 14, "test": 16, "demo": 1}
    assert len(examples) == 31 and len(labels) == 30
    assert Counter(labels[e.id] for e in examples if e.split == "validation") == {
        "DEGUM": 2,
        "BIVEN": 2,
        "NOKER": 2,
        "PEBIX": 2,
        "VODAR": 1,
        "MAFEX": 1,
        "no_match": 2,
        "uncertain": 2,
    }
    assert Counter(labels[e.id] for e in examples if e.split == "test") == {
        "DEGUM": 2,
        "BIVEN": 2,
        "NOKER": 1,
        "PEBIX": 2,
        "VODAR": 2,
        "MAFEX": 2,
        "no_match": 3,
        "uncertain": 2,
    }


def test_the_hard_cases_are_present_with_the_gold_labels_the_notebook_names():
    labels = load_labels(RECIPE)
    # a design the catalogue does not hold, a near miss of one product, and a frame with no tin
    assert [labels[i] for i in ("v10", "v11", "t10", "t11", "t12")] == ["no_match"] * 5
    # a hidden emblem on the pair that differs only in its emblem
    assert [labels[i] for i in ("v12", "v13", "t13", "t14")] == ["uncertain"] * 4
    # a hidden feature that does not matter: the product is still the answer
    assert [labels[i] for i in ("v14", "t15")] == ["NOKER", "PEBIX"]
    # the two products that differ in exactly one feature, each seen on its own
    assert [labels[i] for i in ("v01", "v02", "v07", "v08", "t01", "t02", "t07", "t08")] == [
        "DEGUM",
        "BIVEN",
        "DEGUM",
        "BIVEN",
        "DEGUM",
        "BIVEN",
        "DEGUM",
        "BIVEN",
    ]


def test_every_query_is_drawn_under_a_condition_and_most_differ_from_the_reference():
    conditions = {e.id: e.fields["condition"] for e in load_inputs(RECIPE)}
    assert set(conditions.values()) == {"studio", "dim", "noisy", "far", "shelf"}
    # The reference images are drawn in even light on a plain background, centred ("reference").
    # "studio" keeps those conditions and only shifts the tin in the frame.
    assert Counter(conditions.values()) == {"studio": 8, "shelf": 7, "dim": 8, "far": 5, "noisy": 3}


def test_no_query_has_the_bytes_of_a_reference_or_of_another_query():
    hashes = {}
    for path in sorted((RECIPE / "assets").glob("*.png")):
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(hashes) == 37 and len(set(hashes.values())) == 37
    assert sum(name.startswith("reference-") for name in hashes) == 6
    assert sum(name.startswith("query-") for name in hashes) == 31


def test_every_image_can_be_redrawn_from_its_manifest_entry():
    # Every entry names build_fixtures.py:draw_tin and the arguments that redraw it; the redrawn
    # pixels must be the committed pixels.
    module = load_build_fixtures()
    manifest = json.loads((RECIPE / "assets-manifest.json").read_text("utf-8"))
    assert len(manifest["assets"]) == 37
    for entry in manifest["assets"]:
        assert entry["generator"] == "build_fixtures.py:draw_tin"
        redrawn = module.draw_tin(**entry["parameters"])
        committed = (RECIPE / entry["path"]).read_bytes()
        assert si.png_pixels_equal(redrawn.png(), committed), entry["path"]


def test_every_image_is_at_least_280_pixels_on_each_side():
    manifest = json.loads((RECIPE / "assets-manifest.json").read_text("utf-8"))
    assert {(e["width"], e["height"]) for e in manifest["assets"]} == {(320, 360)}


def test_the_gold_labels_follow_from_the_drawn_designs():
    # The label of each example is derived from the design that was drawn, by gold_label; this
    # recomputes it from ROWS and compares it with the committed labels.
    module = load_build_fixtures()
    labels = load_labels(RECIPE)
    for row in module.ROWS:
        if row[1] != "demo":
            assert labels[row[0]] == helpers.gold_label(module.visible_of(row[3], row[4])), row[0]


# --- the request's images ----------------------------------------------------------------------


def test_every_request_carries_seven_copies_of_seven_distinct_images():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        profile = image_request_profile(state, questions, assets)
        assert (profile.copies, profile.distinct_assets, profile.state_copies) == (7, 7, 1)
        assert dict(profile.per_question) == {"sku": 6}


def test_the_declared_budget_is_one_request_per_example_with_seven_images_each():
    budget = json.loads((RECIPE / "request_budget.json").read_text("utf-8"))
    main = budget["backends"]["main"]
    examples = load_inputs(RECIPE)
    assert main["requests"] == len(examples) == 31
    assert main["profile"] == {"images": 7 * 31, "distinct_images": 7 * 31}


# --- the stored answers ------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    # A wrong answer anywhere is a weak guard: it would still pass even if a confidence gate caught
    # every mistake. Mirror the notebook's own threshold selection (the lowest confidence at which
    # every validation answer that is not `uncertain` and clears it is right) and require a wrong
    # `test` answer at or above it: a mistake the frozen rule delivers, which is what evaluating
    # on `test` exists to catch.
    answers = stored_answers()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)
    validation = [e for e in examples if e.split == "validation"]
    pool = [
        (answers[e.id].choice == labels[e.id], answers[e.id].confidence)
        for e in validation
        if answers[e.id].choice != "uncertain"
    ]
    threshold = select_confidence_threshold(
        [ok for ok, _ in pool], [c for _, c in pool], target_accuracy=1.0
    )
    test = [e for e in examples if e.split == "test"]
    wrong_and_confident = [
        e.id
        for e in test
        if answers[e.id].choice not in (labels[e.id], "uncertain")
        and answers[e.id].confidence >= threshold
    ]
    assert wrong_and_confident == ["t08"]
    # and a wrong answer that the gate does catch, on a gold `uncertain` example
    assert helpers.decide_sku("Q-2014", answers["t14"], threshold).kind == "review"
    assert answers["t14"].choice == "DEGUM" and labels["t14"] == "uncertain"


def test_the_notebook_selects_the_threshold_by_target_accuracy_not_min_coverage():
    # The value a test re-derives pins an objective only if no other objective reaches the same
    # value on this pool, so the committed cell source is what pins it: the one real
    # select_confidence_threshold call in the python-rule cell uses target_accuracy=1.0.
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert source.count("select_confidence_threshold(") == 1
    assert source.count("target_accuracy=1.0") == 1
    assert "min_coverage" not in source
