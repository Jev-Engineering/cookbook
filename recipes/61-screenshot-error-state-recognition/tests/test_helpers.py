"""Tests for recipe 61's helpers. They load the helpers by file path."""

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook import synthetic_images as si
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

OPTIONS = ["crash", "loading", "auth_failure", "normal", "unknown"]


def answer(choice, share=1.0):
    """A synthetic answer for ``choice`` holding ``share`` of the probability; the rest is even."""
    rest = (1.0 - share) / (len(OPTIONS) - 1)
    probabilities = {o: (share if o == choice else rest) for o in OPTIONS}
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


def test_the_option_list_is_fixed_by_python_and_ends_with_the_fallback():
    assert list(helpers.OPTIONS) == OPTIONS
    assert len(helpers.OPTIONS) == 5
    question = helpers.build_questions()["app_state"]
    assert list(question.criteria) == OPTIONS
    assert question.to_dict()["type"] == "choice"


def test_questions_are_built_by_python_from_words_only():
    questions = helpers.build_questions()
    assert list(questions) == ["app_state"]
    question = questions["app_state"]
    assert question.instructions.startswith("Which option describes the application state")
    # The look-alike pairs are named in the criteria that need them, as literal text.
    assert "A warning about a slow connection does not change" in question.criteria["loading"]
    assert "even when the rest of the form looks ordinary" in question.criteria["auth_failure"]
    assert "None of the other four options fits" in question.criteria["unknown"]
    assert all("image:sha256:" not in text for text in question.criteria.values())


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. One request per example.
    # The key covers the image's bytes, so a changed picture fails here.
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        state, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


def test_every_scene_can_be_redrawn_from_its_manifest_entry():
    # A shared scene is rebuilt from the generator and parameters its entry records and compared
    # with the committed file. A function in build_fixtures.py is covered by the emitted test
    # that reruns that script and compares every fixture, manifest and image byte. A different
    # script requires extending that regeneration test and this coverage assertion together.
    manifest = json.loads((RECIPE / "assets-manifest.json").read_text("utf-8"))
    assert manifest["assets"], "the image recipe must have manifest entries"
    for entry in manifest["assets"]:
        module, separator, function = entry["generator"].partition(":")
        assert separator and function, "each entry must name a generator function"
        if module == "jev_cookbook.synthetic_images":
            assert si.check_reproducible(RECIPE, entry) in ("unchanged", "kept-committed-bytes")
        else:
            assert module == "build_fixtures.py", "extend the regeneration test for this script"
            script = RECIPE / module
            assert script.is_file(), "the declared generator script must exist"
            definitions = ast.parse(script.read_text("utf-8")).body
            assert any(
                isinstance(node, ast.FunctionDef) and node.name == function for node in definitions
            )
            coverage = RECIPE / "tests" / "test_build_fixtures.py"
            assert coverage.is_file(), "custom scenes need the fixture/image regeneration test"
            checks = ast.parse(coverage.read_text("utf-8")).body
            assert any(
                isinstance(node, ast.FunctionDef)
                and node.name == "test_the_generator_reproduces_the_committed_fixtures_and_images"
                for node in checks
            )


def test_gold_label_is_read_from_the_kind_that_was_drawn():
    assert {
        "sign_in": "normal",
        "sign_in_rejected": "auth_failure",
        "sign_in_waiting": "loading",
        "sign_in_crashed": "crash",
        "waiting_with_warning": "loading",
        "rejected_inline": "auth_failure",
        "sign_in_with_hint": "normal",
        "dashboard": "normal",
        "dashboard_crashed": "crash",
        "page_not_found": "unknown",
        "payment_declined": "unknown",
        "maintenance": "unknown",
        "partial_render": "unknown",
    } == {kind: helpers.gold_label(kind) for kind in helpers.KINDS}
    assert len(helpers.KINDS) == 13
    with pytest.raises(ValueError, match="not_a_kind"):
        helpers.gold_label("not_a_kind")


def test_the_request_holds_one_reference_and_one_image():
    example = load_inputs(RECIPE)[0]
    state, assets = helpers.build_request(example.fields)
    assert list(state) == ["screenshot"]
    assert list(assets) == [state["screenshot"]]
    assert state["screenshot"].startswith("image:sha256:")


def test_a_path_outside_the_recipe_folder_is_refused():
    with pytest.raises(ValueError):
        helpers.build_request({"capture": "S-0", "image": "../README.md"})


def test_unknown_is_always_a_review_whatever_its_confidence():
    for threshold in (None, 0.0, 0.5, 1.0):
        outcome = helpers.decide_state("S-1", answer("unknown"), threshold)
        assert (outcome.kind, outcome.label, outcome.reason) == (
            "review",
            None,
            "the answer is unknown",
        )
        assert outcome.choice == "unknown"


def test_a_category_is_delivered_only_at_or_above_the_threshold():
    sure = answer("crash")  # confidence 1.0
    assert helpers.decide_state("S-1", sure, 1.0).label == "crash"
    middling = answer("loading", share=0.6)  # confidence (0.6 - 0.2) / 0.8, about 0.5
    assert helpers.decide_state("S-1", middling, middling.confidence).kind == "answered"
    below = helpers.decide_state("S-1", middling, math.nextafter(middling.confidence, 1.0))
    assert (below.kind, below.label, below.reason) == (
        "review",
        None,
        "confidence below the threshold",
    )
    assert below.choice == "loading"


def test_without_a_validated_threshold_every_category_is_a_review():
    outcome = helpers.decide_state("S-1", answer("normal"), None)
    assert (outcome.kind, outcome.reason) == ("review", "no validated threshold")


def test_an_option_outside_the_list_raises_and_a_threshold_outside_zero_to_one_raises():
    stray = SimpleNamespace(choice="timeout", confidence=1.0)
    with pytest.raises(ValueError, match="timeout"):
        helpers.decide_state("S-1", stray, 0.5)
    with pytest.raises(ValueError, match="threshold"):
        helpers.decide_state("S-1", answer("crash"), 1.5)
    with pytest.raises(ValueError, match="threshold"):
        helpers.decide_state("S-1", answer("crash"), -0.1)


def test_a_nan_confidence_is_a_review_not_a_delivery():
    odd = SimpleNamespace(choice="crash", confidence=math.nan)
    assert helpers.decide_state("S-1", odd, 0.0).kind == "review"


def test_the_rule_holds_over_every_option_and_a_grid_of_confidences_and_thresholds():
    # 5 options by 20 confidences by 6 thresholds. Whatever the answer, the outcome is a delivery
    # exactly when the option is not unknown and the confidence reaches the threshold. A share of
    # exactly 0.2 would be a five-way tie, so the steps start above it.
    for option in OPTIONS:
        for step in range(1, 21):
            share = 0.2 + 0.8 * step / 20
            made = answer(option, share=share)
            for threshold in (None, 0.0, 0.25, 0.5, 0.75, 1.0):
                outcome = helpers.decide_state("S-1", made, threshold)
                delivered = (
                    option != "unknown" and threshold is not None and made.confidence >= threshold
                )
                assert (outcome.kind == "answered") is delivered, (option, share, threshold)
                assert (outcome.label is not None) is delivered


def test_the_threshold_is_the_lowest_confidence_where_every_delivered_answer_is_right():
    answers = [
        answer("crash", 0.9),
        answer("normal", 0.7),
        answer("loading", 0.5),
        answer("normal", 0.4),
    ]
    gold = ["crash", "normal", "auth_failure", "normal"]
    threshold, candidates = helpers.choose_threshold(answers, gold, target_accuracy=1.0)
    assert candidates == 4
    # confidence is (share - 0.2) / 0.8: the wrong answer holds 0.375, the right ones 0.875, 0.625
    # and 0.25, and the 0.25 one is below the wrong answer, so the lowest safe bar is 0.625
    assert threshold == pytest.approx(0.625)


def test_unknown_answers_do_not_set_the_threshold():
    answers = [answer("crash", 0.9), answer("unknown", 0.9), answer("normal", 0.3)]
    gold = ["crash", "crash", "normal"]
    # the unknown answer is wrong against its gold label but is never delivered, so it is left
    # out: two candidates remain, and the lowest confidence that keeps both right is the lower.
    threshold, candidates = helpers.choose_threshold(answers, gold, target_accuracy=1.0)
    assert candidates == 2
    assert threshold == pytest.approx(0.125)


def test_a_validation_set_with_nothing_to_deliver_or_no_feasible_cutoff_freezes_review_only():
    assert helpers.choose_threshold([answer("unknown")], ["unknown"], target_accuracy=1.0) == (
        None,
        0,
    )
    assert helpers.choose_threshold([answer("crash")], ["normal"], target_accuracy=1.0) == (None, 1)


def test_queue_reviews_queues_exactly_the_reviews_and_nothing_for_a_delivery():
    outcomes = [
        helpers.decide_state("S-1", answer("crash"), 0.5),  # delivered
        helpers.decide_state("S-2", answer("unknown"), 0.5),  # review: unknown
        helpers.decide_state("S-3", answer("normal", 0.4), 0.5),  # review: below the threshold
    ]
    queue = ReviewQueue()
    helpers.queue_reviews(queue, outcomes)
    assert [(i.item, i.reason) for i in queue.pending()] == [
        ({"capture": "S-2", "model_choice": "unknown"}, "the answer is unknown"),
        ({"capture": "S-3", "model_choice": "normal"}, "confidence below the threshold"),
    ]


def test_the_fixture_set_has_the_sizes_and_hard_cases_the_notebook_states():
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    assert len(examples) == 29 and len(labels) == 28
    assert [len(select_split(examples, s)) for s in ("validation", "test", "demo")] == [12, 16, 1]
    # every hard case the notebook names, with its gold label typed from the notebook's prose
    loading = ("v06", "t07", "t08")
    assert {i: labels[i] for i in loading} == dict.fromkeys(loading, "loading")
    rejected = ("v07", "t09", "t10")
    assert {i: labels[i] for i in rejected} == dict.fromkeys(rejected, "auth_failure")
    hint = ("v11", "t11", "t12")
    assert {i: labels[i] for i in hint} == dict.fromkeys(hint, "normal")
    unknown = ("v08", "t13", "v09", "t14", "t16", "v12", "t15")
    assert {i: labels[i] for i in unknown} == dict.fromkeys(unknown, "unknown")
    test_labels = [labels[e.id] for e in select_split(examples, "test")]
    assert {o: test_labels.count(o) for o in OPTIONS} == {
        "crash": 2,
        "loading": 3,
        "auth_failure": 3,
        "normal": 4,
        "unknown": 4,
    }


def test_the_stored_answers_the_notebook_discusses_are_the_ones_in_the_replay():
    backend = get_backend(fixtures=responses_path(RECIPE), images=True)
    questions = helpers.build_questions()
    by_id = {e.id: e for e in load_inputs(RECIPE)}

    def chose(ident):
        state, assets = helpers.build_request(by_id[ident].fields)
        return backend.decide(state, questions, assets=assets)["app_state"]

    assert chose("t14").choice == "auth_failure"  # a declined payment, answered as a category
    assert chose("t16").choice == "crash"  # a maintenance notice, answered as a category


def test_stored_answers_are_not_all_right_and_a_wrong_one_clears_the_frozen_gate():
    # Mirror the notebook's threshold selection on validation, then require a wrong `test`
    # answer at or above it: a mistake the gate still lets through, which is what evaluating
    # on `test` exists to catch.
    backend = get_backend(fixtures=responses_path(RECIPE), images=True)
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def answers_of(split):
        chosen = select_split(examples, split)
        found = []
        for e in chosen:
            state, assets = helpers.build_request(e.fields)
            found.append(backend.decide(state, questions, assets=assets)["app_state"])
        return chosen, found

    validation, val_answers = answers_of("validation")
    threshold, _n = helpers.choose_threshold(
        val_answers, [labels[e.id] for e in validation], target_accuracy=1.0
    )
    assert threshold is not None
    test, test_answers = answers_of("test")
    delivered_wrong = [
        e.id
        for e, a in zip(test, test_answers, strict=True)
        if a.choice != labels[e.id] and a.choice != "unknown" and a.confidence >= threshold
    ]
    assert delivered_wrong == ["t08", "t14"]


def test_the_notebook_selects_the_threshold_by_target_accuracy_not_min_coverage():
    # The committed cell source pins the objective: the one real choose_threshold call in the
    # python-rule cell uses target_accuracy=1.0.
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert source.count("helpers.choose_threshold(") == 1
    assert source.count("target_accuracy=1.0") == 1
    assert "min_coverage" not in source
