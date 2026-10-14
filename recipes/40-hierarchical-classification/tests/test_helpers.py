"""Tests for recipe 40's helpers. They load the helpers by file path."""

import json
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import accuracy, select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(probabilities: dict) -> ChoiceAnswer:
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


# --------------------------------------------------------------------------------------------
# questions are built by Python, against literal expected values
# --------------------------------------------------------------------------------------------


def test_the_department_question_has_four_fixed_options():
    question = helpers.build_department_question()
    assert list(question.criteria) == [
        "account_billing",
        "product_technical",
        "people_policy",
        "unclassified",
    ]
    assert all(
        isinstance(description, str) and description for description in question.criteria.values()
    )


def test_every_real_department_has_at_least_two_topics():
    # CONTRIBUTING.md section 3: a Choice needs at least two options.
    for department in helpers.REAL_DEPARTMENTS:
        topics = helpers.build_topic_question(department)
        assert len(topics.criteria) >= 2


def test_the_topic_question_options_match_leaves_by_department():
    for department in helpers.REAL_DEPARTMENTS:
        topics = helpers.build_topic_question(department)
        assert list(topics.criteria) == list(helpers.LEAVES_BY_DEPARTMENT[department])


def test_the_fallback_department_has_no_topic_question():
    # The fallback is terminal: docs/backends.md "Single-option Choice" -- Python resolves it
    # directly, so no second-stage question is ever built for it.
    with pytest.raises(ValueError):
        helpers.build_topic_question(helpers.UNCLASSIFIED)
    with pytest.raises(ValueError):
        helpers.build_topic_question("not_a_department")


def test_the_flat_question_covers_every_full_path_plus_the_fallback():
    flat = helpers.build_flat_question()
    expected = [
        f"{department}.{topic}"
        for department in helpers.REAL_DEPARTMENTS
        for topic in helpers.LEAVES_BY_DEPARTMENT[department]
    ] + [helpers.UNCLASSIFIED]
    assert list(flat.criteria) == expected
    assert list(helpers.FLAT_LEAVES) == expected


def test_the_staged_policys_widest_question_is_smaller_than_the_flat_questions():
    """The structural case for staging, independent of any one measurement: for ``D``
    departments of ``T`` topics each, the flat question's option count grows as ``D * T + 1``
    (every full path plus the fallback), while the staged design never asks a single question
    wider than ``max(D + 1, T)`` -- the department question (``D`` real departments plus the
    fallback) or the largest department's own topic question, whichever has more options. On
    this taxonomy ``D = 3`` and the largest department has ``T = 3`` topics, so the staged
    design's widest question has 4 options against the flat question's 9 -- small enough on
    both sides that one combined question stays practical to write and to answer, which is
    exactly why the flat baseline ties the hierarchy rather than losing to it here. The gap
    between the two counts grows with ``T``; it does not close as ``T`` shrinks."""
    staged_widest = max(
        len(helpers.DEPARTMENTS),
        max(len(helpers.LEAVES_BY_DEPARTMENT[d]) for d in helpers.REAL_DEPARTMENTS),
    )
    flat_count = len(helpers.FLAT_LEAVES)
    assert staged_widest == 4
    assert flat_count == 9
    assert staged_widest < flat_count


# --------------------------------------------------------------------------------------------
# department_of: reads the department out of a full path, never derives one label from another
# --------------------------------------------------------------------------------------------


def test_department_of_reads_the_department_out_of_a_full_path():
    assert helpers.department_of("account_billing.invoice_question") == "account_billing"
    assert helpers.department_of("product_technical.general_question") == "product_technical"
    assert helpers.department_of("people_policy.security_policy") == "people_policy"
    assert helpers.department_of("unclassified") == "unclassified"


# --------------------------------------------------------------------------------------------
# rank_real_departments and best_topic
# --------------------------------------------------------------------------------------------


def test_rank_real_departments_orders_by_probability_descending():
    a = answer(
        {
            "account_billing": 0.1,
            "product_technical": 0.6,
            "people_policy": 0.2,
            "unclassified": 0.1,
        }
    )
    assert helpers.rank_real_departments(a) == [
        "product_technical",
        "people_policy",
        "account_billing",
    ]


def test_rank_real_departments_breaks_ties_by_name():
    # Every real department tied: deterministic for any model answer, not whatever order a
    # dict happens to iterate in.
    a = answer(
        {
            "account_billing": 0.2,
            "product_technical": 0.2,
            "people_policy": 0.2,
            "unclassified": 0.4,
        }
    )
    assert helpers.rank_real_departments(a) == [
        "account_billing",
        "people_policy",
        "product_technical",
    ]


def test_best_topic_reads_the_chosen_options_own_probability():
    a = answer({"invoice_question": 0.7, "refund_request": 0.2, "general_question": 0.1})
    topic, probability = helpers.best_topic(a)
    assert topic == "invoice_question"
    assert probability == pytest.approx(0.7)


# --------------------------------------------------------------------------------------------
# resolve_path: the composed policy, independent of any particular model answer
# --------------------------------------------------------------------------------------------


def test_resolve_path_rejects_an_out_of_range_branch_margin():
    department_answer = answer(
        {
            "account_billing": 0.4,
            "product_technical": 0.3,
            "people_policy": 0.2,
            "unclassified": 0.1,
        }
    )
    with pytest.raises(ValueError):
        helpers.resolve_path("d1", department_answer, {}, 1.5)
    with pytest.raises(ValueError):
        helpers.resolve_path("d1", department_answer, {}, -0.1)


def test_resolve_path_greedy_never_branches():
    # branch_margin = 0.0: confidence is never less than 0, so this is exactly the greedy
    # single-path baseline this use case names, not a second copy of the same logic.
    department_answer = answer(
        {
            "account_billing": 0.3,
            "product_technical": 0.3,
            "people_policy": 0.2,
            "unclassified": 0.2,
        }
    )
    topic_answers = {
        "account_billing": answer(
            {"invoice_question": 0.9, "refund_request": 0.05, "general_question": 0.05}
        ),
        "product_technical": answer(
            {"bug_report": 0.9, "how_to_question": 0.05, "general_question": 0.05}
        ),
    }
    resolved = helpers.resolve_path("d1", department_answer, topic_answers, 0.0)
    assert resolved.branched is False
    assert resolved.requests == 2


def test_resolve_path_branches_when_department_confidence_is_below_the_margin():
    department_answer = answer(
        {
            "account_billing": 0.3,
            "product_technical": 0.28,
            "people_policy": 0.22,
            "unclassified": 0.2,
        }
    )
    topic_answers = {
        "account_billing": answer(
            {"invoice_question": 0.9, "refund_request": 0.05, "general_question": 0.05}
        ),
        "product_technical": answer(
            {"bug_report": 0.9, "how_to_question": 0.05, "general_question": 0.05}
        ),
    }
    resolved = helpers.resolve_path("d1", department_answer, topic_answers, 0.9)
    assert resolved.branched is True
    assert resolved.requests == 3


def test_resolve_path_does_not_branch_when_department_confidence_clears_the_margin():
    department_answer = answer(
        {
            "account_billing": 0.85,
            "product_technical": 0.06,
            "people_policy": 0.05,
            "unclassified": 0.04,
        }
    )
    topic_answers = {
        "account_billing": answer(
            {"invoice_question": 0.9, "refund_request": 0.05, "general_question": 0.05}
        )
    }
    resolved = helpers.resolve_path("d1", department_answer, topic_answers, 0.5)
    assert resolved.branched is False
    assert resolved.department == "account_billing"
    assert resolved.leaf == "account_billing.invoice_question"


def test_resolve_path_raises_for_an_explored_department_with_no_topic_answer():
    department_answer = answer(
        {
            "account_billing": 0.3,
            "product_technical": 0.28,
            "people_policy": 0.22,
            "unclassified": 0.2,
        }
    )
    with pytest.raises(KeyError):
        helpers.resolve_path("d1", department_answer, {}, 0.9)


def test_resolve_path_picks_the_fallback_when_its_own_probability_dominates():
    # A real department's candidate score is its own probability times a topic probability
    # that can never exceed 1, so it can never exceed its own department probability -- the
    # fallback's raw probability, always a candidate, wins outright when it is higher than
    # every explored real department's own probability, whatever the topic answers say.
    department_answer = answer(
        {
            "account_billing": 0.3,
            "product_technical": 0.2,
            "people_policy": 0.1,
            "unclassified": 0.4,
        }
    )
    topic_answers = {
        "account_billing": answer(
            {"invoice_question": 1.0, "refund_request": 0.0, "general_question": 0.0}
        ),
        "product_technical": answer(
            {"bug_report": 1.0, "how_to_question": 0.0, "general_question": 0.0}
        ),
    }
    resolved = helpers.resolve_path("d1", department_answer, topic_answers, 0.9)
    assert resolved.department == helpers.UNCLASSIFIED
    assert resolved.leaf == helpers.UNCLASSIFIED
    assert resolved.path_confidence == pytest.approx(0.4)


def test_resolve_path_path_confidence_is_the_product_of_both_stages():
    department_answer = answer(
        {
            "account_billing": 0.6,
            "product_technical": 0.2,
            "people_policy": 0.1,
            "unclassified": 0.1,
        }
    )
    topic_answers = {
        "account_billing": answer(
            {"invoice_question": 0.5, "refund_request": 0.3, "general_question": 0.2}
        )
    }
    resolved = helpers.resolve_path("d1", department_answer, topic_answers, 0.0)
    assert resolved.path_confidence == pytest.approx(0.6 * 0.5)


# --------------------------------------------------------------------------------------------
# gate_path: the review gate, and the fixed lexicon
# --------------------------------------------------------------------------------------------


def test_gate_path_rejects_an_out_of_range_review_gate():
    resolved = helpers.ResolvedPath(
        "d1", "account_billing", "account_billing.invoice_question", 0.5, False, 2
    )
    with pytest.raises(ValueError):
        helpers.gate_path(resolved, 1.5)
    with pytest.raises(ValueError):
        helpers.gate_path(resolved, -0.1)


def test_gate_path_answers_at_or_above_the_gate_and_reviews_below_it():
    resolved = helpers.ResolvedPath(
        "d1", "account_billing", "account_billing.invoice_question", 0.5, False, 2
    )
    assert helpers.gate_path(resolved, 0.5).outcome == helpers.ANSWERED
    assert helpers.gate_path(resolved, 0.51).outcome == helpers.REVIEW


def test_review_outcome_is_the_fixed_lexicon_value():
    assert helpers.REVIEW == "review"
    assert helpers.ANSWERED == "answered"
    resolved = helpers.ResolvedPath(
        "d1", "account_billing", "account_billing.invoice_question", 0.1, False, 2
    )
    routing = helpers.gate_path(resolved, 0.9)
    assert routing.outcome == helpers.REVIEW
    assert routing.reason == "confidence below the threshold"


# --------------------------------------------------------------------------------------------
# classify_flat: one request, no stages
# --------------------------------------------------------------------------------------------


def test_classify_flat_always_spends_exactly_one_request():
    flat_answer = answer(
        {path: 1.0 if i == 0 else 0.0 for i, path in enumerate(helpers.FLAT_LEAVES)}
    )
    doc_id, leaf, requests = helpers.classify_flat("d1", flat_answer)
    assert requests == 1
    assert leaf == flat_answer.choice
    assert doc_id == "d1"


# --------------------------------------------------------------------------------------------
# every replay key in the fixtures matches the current questions -- four per example (the
# department question; a topic question for each of the two real departments the department
# probabilities themselves rank highest; the flat baseline's question), in that order, since
# this recipe asks one dependent request after another rather than one request per example
# (CONTRIBUTING.md section 3).
# --------------------------------------------------------------------------------------------


def _expected_keys(example, responses: dict) -> list[str]:
    state = helpers.build_state(example.fields)
    department_question = helpers.build_department_question()
    department_key = replay_key(state, {"department": department_question})
    department_probabilities = responses[department_key]["answers"]["department"]["probabilities"]
    ranked = sorted(helpers.REAL_DEPARTMENTS, key=lambda d: (-department_probabilities[d], d))[:2]
    topic_keys = [
        replay_key(state, {"topic": helpers.build_topic_question(department)})
        for department in ranked
    ]
    flat_key = replay_key(state, {"flat_topic": helpers.build_flat_question()})
    return [department_key, *topic_keys, flat_key]


def test_every_replay_key_in_the_fixtures_matches_the_current_questions():
    # The fixture validator cannot see question drift; this test can. Each example lists four
    # keys, in request order: department; a topic question for each of the two real departments
    # the DEPARTMENT ANSWER ITSELF (read from the stored response, not re-derived by this test)
    # ranks highest; flat_topic.
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    for example in load_inputs(RECIPE):
        assert list(example.replay_keys) == _expected_keys(example, responses)


# --------------------------------------------------------------------------------------------
# independently consequential: flipping what branching sees, or how a full path is compared,
# changes the composed outcome, on real committed fixtures
# --------------------------------------------------------------------------------------------


def _decide(backend, questions, name, example):
    return backend.decide(helpers.build_state(example.fields), questions)[name]


def _resolve(backend, example, branch_margin, department_answer=None):
    department_question = helpers.build_department_question()
    if department_answer is None:
        department_answer = _decide(
            backend, {"department": department_question}, "department", example
        )
    ranked = helpers.rank_real_departments(department_answer)
    topic_answers = {
        department: _decide(
            backend, {"topic": helpers.build_topic_question(department)}, "topic", example
        )
        for department in ranked[:2]
    }
    return helpers.resolve_path(example.id, department_answer, topic_answers, branch_margin)


FROZEN_BRANCH_MARGIN = 0.7866666666666666  # see test_the_threshold_objectives_are_pinned


@pytest.mark.parametrize(
    "example_id,gold",
    [
        ("t11-branch-rescue-shared-name", "account_billing.general_question"),
        ("t12-branch-rescue-second-department", "people_policy.security_policy"),
    ],
)
def test_branching_rescues_a_real_fixture_greedy_gets_wrong(example_id, gold):
    """Demonstrated on real committed fixtures, not a synthetic row built inside the test: for
    both ``t11`` and ``t12``, the greedy baseline (``branch_margin=0.0``) names a different,
    wrong department outright, while carrying the top two real departments forward (the frozen
    ``branch_margin``, pinned below) finds the gold full path. Flipping the branch decision
    changes the composed outcome -- proof that branching is independently consequential, not
    merely present."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    examples = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    example = examples[example_id]
    assert labels[example_id] == gold

    greedy = _resolve(backend, example, 0.0)
    branched = _resolve(backend, example, FROZEN_BRANCH_MARGIN)

    assert greedy.leaf != gold, "expected the greedy baseline to miss this fixture"
    assert branched.leaf == gold, "expected branching to recover the gold full path"
    assert branched.branched is True


def test_the_shared_topic_name_would_be_a_false_match_on_a_real_fixture():
    """``t13-shared-name-trap``'s gold label is ``product_technical.general_question``; the
    policy's own resolved path is ``account_billing.general_question`` -- wrong by full path,
    but its BARE topic name, ``general_question``, is identical to the gold bare topic name,
    because two departments in this taxonomy deliberately share that name. Comparing bare
    topic names alone would call this example correct; comparing the full path (what
    ``accuracy`` in the notebook actually does) correctly calls it wrong. The two comparisons
    disagree about this one real fixture, which is what proves the full-path rule is
    consequential here, not merely stated."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    examples = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    example = examples["t13-shared-name-trap"]
    gold = labels[example.id]

    resolved = _resolve(backend, example, FROZEN_BRANCH_MARGIN)

    bare_gold = gold.rsplit(".", 1)[-1]
    bare_predicted = resolved.leaf.rsplit(".", 1)[-1]
    assert bare_predicted == bare_gold, "expected the bare topic names to coincide"
    assert resolved.leaf != gold, "expected the full path to disagree with gold"
    assert accuracy([gold], [resolved.leaf]) == 0.0
    assert accuracy([bare_gold], [bare_predicted]) == 1.0


def test_a_department_correct_fixture_can_still_have_the_wrong_full_path():
    """``t15-wrong-topic-right-department``: the policy names the right department and the
    wrong topic inside it, so department-level accuracy and full-path leaf accuracy disagree
    about this one real fixture -- exactly the per-level-versus-end-to-end gap a department-
    only metric cannot see."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    examples = {e.id: e for e in load_inputs(RECIPE)}
    labels = load_labels(RECIPE)
    example = examples["t15-wrong-topic-right-department"]
    gold = labels[example.id]

    resolved = _resolve(backend, example, FROZEN_BRANCH_MARGIN)

    assert resolved.department == helpers.department_of(gold)
    assert resolved.leaf != gold


# --------------------------------------------------------------------------------------------
# the notebook pools several lists built from the same test_examples list (gold, resolved
# paths, greedy paths, flat answers) with plain list comprehensions and zip(..., strict=True),
# never a dict keyed by id -- so the claim that index i of every list describes the same
# document needs checking against the committed notebook cell itself, not against a
# reconstruction that uses the very comprehensions it is supposed to distrust (a rebuild in
# this file would hold any resolve_path's own doc_id-passthrough by construction, whatever the
# notebook's cell actually does -- it is a property of resolve_path, not of the notebook).
# --------------------------------------------------------------------------------------------


def test_the_notebooks_pooled_evaluation_lists_share_one_unreordered_source():
    """The notebook's ``evaluation-test`` cell pools four lists over the test split --
    ``test_gold``, ``test_resolved``, ``test_greedy`` and ``test_flat`` -- and the rest of the
    evaluation section indexes all four in parallel, trusting that index i of each describes
    the same document. The committed cell makes that true by construction, and this test
    checks the committed cell's own source for exactly that construction: ``test_fetched`` is
    built directly from ``test_examples``, in order; ``test_gold`` is built directly from
    ``test_examples``, in the same order; ``test_resolved`` and ``test_greedy`` are each built
    from ``zip(test_examples, test_fetched, strict=True)``, pairing them index-for-index with
    those same two already-aligned lists; and ``test_flat`` is built directly from
    ``test_fetched``, in its order. None of the four comprehensions reorders its source.

    A reorder actually committed to this cell is what turns this red: mutating the committed
    ``test_gold`` line to iterate ``reversed(test_examples)`` instead of ``test_examples`` --
    a real misalignment between gold and the other three pooled lists -- removes the exact
    substring this test asserts and fails only this assertion."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cells = {c.get("id"): "".join(c["source"]) for c in notebook["cells"]}
    source = cells["evaluation-test"]
    normalized = " ".join(source.split())

    assert "reversed(" not in source

    assert "test_fetched = [fetch(e) for e in test_examples]" in normalized
    assert "test_gold = [labels[e.id] for e in test_examples]" in normalized
    assert normalized.count("in zip( test_examples, test_fetched, strict=True )") == 2
    assert (
        "test_flat = [flat_answer.choice for _department_answer, _topic_answers, "
        "flat_answer in test_fetched]"
    ) in normalized


# --------------------------------------------------------------------------------------------
# stored answers are not all right -- the strong form (G1(c)): re-derive both frozen
# thresholds the way the notebook does and require a wrong test decision at or above each one.
# ``branch_margin`` (the department-level threshold) is re-derived FIRST: the mechanical guard
# (tests/test_recipe_guard.py::test_stored_answers_are_not_all_right_is_the_strong_form) finds
# the first ``name = select_confidence_threshold(...)`` assignment in this function and
# requires an assert bound to a ``>= name`` comparison for exactly that name. ``review_gate``
# (the leaf-level threshold) is re-derived second, for this recipe's own extra rigor, with its
# own independent wrong-and-confident check.
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    backend = get_backend(fixtures=responses_path(RECIPE))
    department_question = helpers.build_department_question()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def department_answer(example):
        return _decide(backend, {"department": department_question}, "department", example)

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_department_correct = [
        department_answer(e).choice == helpers.department_of(labels[e.id]) for e in validation
    ]
    val_department_confidence = [department_answer(e).confidence for e in validation]
    branch_margin = select_confidence_threshold(
        val_department_correct, val_department_confidence, min_coverage=0.65
    )

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_department_at_or_above_margin = [
        e.id
        for e in test
        if department_answer(e).choice != helpers.department_of(labels[e.id])
        and department_answer(e).confidence >= branch_margin
    ]
    assert wrong_department_at_or_above_margin, (
        "expected at least one confidently wrong department on test, at or above the margin "
        "that would still keep it on the single-request greedy path"
    )

    # The leaf-level (full-path) check: re-resolve every validation path with branch_margin
    # frozen above, pick the review gate from those, and require a wrong TEST full path the
    # gate would still answer rather than send to review.
    val_resolved = [_resolve(backend, e, branch_margin) for e in validation]
    val_leaf_correct = [
        r.leaf == labels[e.id] for e, r in zip(validation, val_resolved, strict=True)
    ]
    val_path_confidence = [r.path_confidence for r in val_resolved]
    review_gate = select_confidence_threshold(
        val_leaf_correct, val_path_confidence, min_coverage=0.75
    )

    test_resolved = {e.id: _resolve(backend, e, branch_margin) for e in test}
    wrong_leaf_at_or_above_gate = [
        e.id
        for e in test
        if test_resolved[e.id].leaf != labels[e.id]
        and test_resolved[e.id].path_confidence >= review_gate
    ]
    assert wrong_leaf_at_or_above_gate, (
        "expected at least one confidently wrong full path on test, at or above the review "
        "gate that would still answer it rather than send it to review"
    )


# --------------------------------------------------------------------------------------------
# the threshold objectives are pinned: both the value each produces on real fixtures, and the
# exact keyword the committed notebook cell uses to produce it. Neither alone is a pin (see
# tests/test_recipe_guard.py's own docstring and docs/evaluation.md, "the whole arrangement is
# inert" -- swapping the keyword while leaving a hand-written value unchanged, or rebinding the
# value while leaving the keyword's spelling intact, each leaves the OTHER half of this pin
# green).
# --------------------------------------------------------------------------------------------


def test_the_threshold_objectives_are_pinned():
    backend = get_backend(fixtures=responses_path(RECIPE))
    department_question = helpers.build_department_question()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def department_answer(example):
        return _decide(backend, {"department": department_question}, "department", example)

    validation = [e for e in examples if e.split == "validation"]
    val_department_correct = [
        department_answer(e).choice == helpers.department_of(labels[e.id]) for e in validation
    ]
    val_department_confidence = [department_answer(e).confidence for e in validation]
    branch_margin = select_confidence_threshold(
        val_department_correct, val_department_confidence, min_coverage=0.65
    )
    assert branch_margin == pytest.approx(0.7866666666666666)

    val_resolved = [_resolve(backend, e, branch_margin) for e in validation]
    val_leaf_correct = [
        r.leaf == labels[e.id] for e, r in zip(validation, val_resolved, strict=True)
    ]
    val_path_confidence = [r.path_confidence for r in val_resolved]
    review_gate = select_confidence_threshold(
        val_leaf_correct, val_path_confidence, min_coverage=0.75
    )
    assert review_gate == pytest.approx(0.256)


def test_the_notebooks_threshold_objectives_match_this_files_pinned_keywords():
    """Nothing ties a notebook cell's source to an importable value: an edit that changed only
    the notebook's own objective or min_coverage parameter (swapping `min_coverage=0.65` for a
    different value, or the keyword itself for `target_accuracy=`) would otherwise leave every
    test in this file green while the notebook ran a different selection than the one they
    describe. Parse the committed notebook's own cells and pin the exact keyword text, not only
    the value it produces."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cells = {c.get("id"): "".join(c["source"]) for c in notebook["cells"]}
    assert "min_coverage=branch_min_coverage" in cells["python-rule"]
    assert "branch_min_coverage = 0.65" in cells["python-rule"]
    assert "min_coverage=review_min_coverage" in cells["python-rule"]
    assert "review_min_coverage = 0.75" in cells["python-rule"]


# --------------------------------------------------------------------------------------------
# select_confidence_threshold's min_coverage is a floor on coverage, not on the threshold
# itself (see its own docstring in src/jev_cookbook/evaluation.py): demanding that MORE
# validation examples clear the returned threshold can only be satisfied by a LOWER-or-equal
# threshold, never a higher one. "Next steps" sends a reader back to raise
# branch_min_coverage and watch branch_margin move -- pinned here, on this recipe's own
# validation pool, so the direction cannot go stale silently.
# --------------------------------------------------------------------------------------------


def test_a_higher_min_coverage_can_only_select_a_lower_or_equal_threshold():
    backend = get_backend(fixtures=responses_path(RECIPE))
    department_question = helpers.build_department_question()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def department_answer(example):
        return _decide(backend, {"department": department_question}, "department", example)

    validation = [e for e in examples if e.split == "validation"]
    val_department_correct = [
        department_answer(e).choice == helpers.department_of(labels[e.id]) for e in validation
    ]
    val_department_confidence = [department_answer(e).confidence for e in validation]

    lower_floor = select_confidence_threshold(
        val_department_correct, val_department_confidence, min_coverage=0.65
    )
    higher_floor = select_confidence_threshold(
        val_department_correct, val_department_confidence, min_coverage=0.85
    )
    assert higher_floor <= lower_floor
    assert higher_floor < lower_floor, "expected a real move on this pool, not a tie"
