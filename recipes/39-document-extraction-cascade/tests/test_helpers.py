"""Tests for recipe 39's helpers. They load helpers.py and build_fixtures.py by file path."""

import importlib.util
import json
import random
from pathlib import Path

import pytest

from jev_cookbook import get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import (
    evaluate_outcomes,
    noul_confidence,
    select_confidence_threshold,
    select_threshold,
)
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def _load_build_fixtures():
    """``build_fixtures.py``, loaded by file path (its own ``ROWS`` and ``_resolve_row``, not a
    re-derivation of them): the same mechanism ``tests/test_build_fixtures.py`` uses."""
    spec = importlib.util.spec_from_file_location(
        "recipe39_build_fixtures_for_helper_tests", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD_FIXTURES = _load_build_fixtures()


def _all_field_results(backend, examples, t, gate):
    """``{doc_id: {field: FieldResult}}`` for every example in ``examples``, via the shared
    ``helpers.decide_document``/``helpers.field_result`` the notebook itself calls."""
    results = {}
    for example in examples:
        _s1, a1, _s2, a2 = helpers.decide_document(backend, example.fields)
        results[example.id] = {
            field: helpers.field_result(example.id, field, example.fields, a1, a2, t, gate)
            for field in helpers.FIELDS
        }
    return results


def _frozen_thresholds(backend, examples, labels):
    """The business threshold and confidence gate, chosen on ``validation`` exactly as the
    notebook chooses them. Shared by several tests below so that none of them has to
    re-describe the selection procedure -- but see ``test_stored_answers_are_not_all_right``,
    which deliberately does NOT call this: an independent strong-form check must not re-derive
    through the same path it is meant to audit."""
    validation = select_split(examples, "validation")
    truth, noul = [], []
    for example in validation:
        _s1, a1, s2, a2 = helpers.decide_document(backend, example.fields)
        gold = labels[example.id]
        for field in s2:
            spans = helpers.spans_by_id(example.fields, field)
            is_right = gold[field] != helpers.NOT_FOUND and gold[field] in spans[a1[field].choice]
            truth.append(is_right)
            noul.append(a2[field].noul)
    t = select_threshold(truth, noul, "f1")
    correct = [(n >= t) == truth_i for n, truth_i in zip(noul, truth, strict=True)]
    gate = select_confidence_threshold(correct, noul_confidence(noul), min_coverage=0.85)
    return t, gate


# --------------------------------------------------------------------------------------------
# The questions Python builds
# --------------------------------------------------------------------------------------------


def test_stage1_builds_one_choice_per_field_with_candidates():
    fields = {"doc_id": "X", "document": "Invoice #4420 for your records. Total due: $540.00."}
    which = helpers.stage1_fields(fields)
    assert which == ["invoice_number", "total_amount"]
    questions = helpers.build_stage1_questions(fields, which)
    assert set(questions) == {"invoice_number", "total_amount"}
    assert list(questions["invoice_number"].criteria) == ["s1", helpers.NOT_FOUND]
    assert list(questions["total_amount"].criteria) == ["s1", helpers.NOT_FOUND]
    state = helpers.build_stage1_state(fields, which)
    assert state == {
        "invoice_number": {"s1": "Invoice #4420 for your records. "},
        "total_amount": {"s1": "Total due: $540.00."},
    }


def test_stage1_fields_excludes_a_field_with_no_candidate():
    fields = {"doc_id": "X", "document": "Bill To: Keystone Retail Group, 400 Commerce Ave."}
    assert helpers.stage1_fields(fields) == []


def test_stage2_asks_only_about_fields_stage1_named_a_real_candidate_for():
    assert helpers.stage2_fields({"invoice_number": "s1", "total_amount": helpers.NOT_FOUND}) == [
        "invoice_number"
    ]
    assert helpers.stage2_fields({}) == []
    questions = helpers.build_stage2_questions(["total_amount"])
    assert set(questions) == {"total_amount"}
    assert questions["total_amount"].criteria is None


def test_stage2_state_carries_the_exact_selected_span_text():
    fields = {"doc_id": "X", "document": "Invoice #4420 for your records. Total due: $540.00."}
    state = helpers.build_stage2_state(fields, {"invoice_number": "s1"}, ["invoice_number"])
    assert state == {"invoice_number": "Invoice #4420 for your records. "}


# --------------------------------------------------------------------------------------------
# The request boundary: independent questions share a request; a dependent one waits
# --------------------------------------------------------------------------------------------


def test_plan_requests_shapes():
    assert helpers.plan_requests([], []) == []
    assert helpers.plan_requests(["invoice_number"], []) == [
        helpers.RequestPlan(1, ("invoice_number",), ())
    ]
    assert helpers.plan_requests(
        ["invoice_number", "total_amount"], ["invoice_number", "total_amount"]
    ) == [
        helpers.RequestPlan(1, ("invoice_number", "total_amount"), ()),
        helpers.RequestPlan(
            2, ("invoice_number", "total_amount"), ("invoice_number", "total_amount")
        ),
    ]
    # A field stage 1 resolved to not_found never reaches stage 2, so a document where only one
    # of its two stage-1 fields named a real candidate makes a one-field stage-2 request, not a
    # two-field one.
    assert helpers.plan_requests(["invoice_number", "total_amount"], ["invoice_number"]) == [
        helpers.RequestPlan(1, ("invoice_number", "total_amount"), ()),
        helpers.RequestPlan(2, ("invoice_number",), ("invoice_number",)),
    ]


def test_every_replay_key_in_the_fixtures_matches_the_current_request_sequence():
    """The fixture validator cannot see question drift; this test can. Each example's
    ``replay_keys`` must equal the stage-1 key (if a stage-1 request is made) followed by the
    stage-2 key (if a stage-2 request is made), recomputed fresh from the current
    ``helpers.py`` -- not copied from ``build_fixtures.py``, so a change to either file that
    silently stops agreeing with the other is caught here."""
    for example in load_inputs(RECIPE):
        fields = example.fields
        s1 = helpers.stage1_fields(fields)
        expected = []
        stage1_choices = {}
        if s1:
            q1 = helpers.build_stage1_questions(fields, s1)
            state1 = helpers.build_stage1_state(fields, s1)
            expected.append(replay_key(state1, q1))
            # The example's own stage-1 answer decides which fields stage 2 asks about; read it
            # from the committed response rather than the row spec, so this test exercises the
            # same fixtures the notebook replays.
            backend = get_backend(fixtures=responses_path(RECIPE))
            stage1_choices = {f: a.choice for f, a in backend.decide(state1, q1).answers.items()}
        s2 = helpers.stage2_fields(stage1_choices)
        if s2:
            q2 = helpers.build_stage2_questions(s2)
            state2 = helpers.build_stage2_state(fields, stage1_choices, s2)
            expected.append(replay_key(state2, q2))
        assert tuple(example.replay_keys) == tuple(expected), example.id


def test_deciding_every_document_once_each_makes_one_backend_decide_call_per_stored_response():
    """Count every attempt the backend actually makes, not how many documents get cached -- a
    counter that only reported cache size would not catch a document being decided twice, which
    is exactly the bug this guards against. Deciding every document in ``fixtures/`` once each,
    through the shared ``helpers.decide_document_cached`` the notebook also uses, must call
    ``backend.decide`` exactly once per request ``fixtures/responses.json`` stores an answer
    for -- the same count the README's live-mode budget note promises."""
    examples = load_inputs(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    calls = 0
    real_decide = backend.decide

    def counting_decide(state, questions):
        nonlocal calls
        calls += 1
        return real_decide(state, questions)

    backend.decide = counting_decide
    cache: dict = {}
    for example in examples:
        helpers.decide_document_cached(backend, cache, example.id, example.fields)

    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    assert calls == len(responses) == 52


def test_decide_document_cached_decides_each_document_at_most_once():
    """``decide_document_cached`` must not merely return the right answer -- it must not call
    ``backend.decide`` again for a document already in its cache. Calling it twice for the same
    document (``v01``, which makes one stage-1 and one stage-2 request) must make exactly 2
    ``backend.decide`` calls in total, not 4."""
    fields = _document_fields("v01")
    backend = get_backend(fixtures=responses_path(RECIPE))
    calls = 0
    real_decide = backend.decide

    def counting_decide(state, questions):
        nonlocal calls
        calls += 1
        return real_decide(state, questions)

    backend.decide = counting_decide
    cache: dict = {}
    first = helpers.decide_document_cached(backend, cache, "v01", fields)
    second = helpers.decide_document_cached(backend, cache, "v01", fields)
    assert first == second
    assert calls == 2


# --------------------------------------------------------------------------------------------
# Rule: a fixture-spec shorthand must never default the label-bearing field. Assert every
# committed stored answer's top choice (Choice) or exact value (Noul) matches its own row's
# spec, computed independently of build_responses (a plain argmax over the row's own
# probabilities, not a call to ChoiceAnswer.from_probabilities or build_responses itself).
# --------------------------------------------------------------------------------------------


def _argmax(options, probs):
    best = 0
    for i in range(1, len(probs)):
        if probs[i] > probs[best]:
            best = i
    return options[best]


def test_every_stored_choice_answers_top_choice_matches_its_row_spec():
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    checked = 0
    for row in BUILD_FIXTURES.ROWS:
        fields = BUILD_FIXTURES._fields(row)
        s1_fields = helpers.stage1_fields(fields)
        for field in s1_fields:
            spans = helpers.spans_by_id(fields, field)
            options = [*spans, helpers.NOT_FOUND]
            expected_top = _argmax(options, row["stage1"][field])
            q1 = helpers.build_stage1_questions(fields, s1_fields)
            state1 = helpers.build_stage1_state(fields, s1_fields)
            key1 = replay_key(state1, q1)
            stored_choice = responses[key1]["answers"][field]["choice"]
            assert stored_choice == expected_top, (
                f"{row['id']}/{field}: stored choice {stored_choice!r} != spec top {expected_top!r}"
            )
            checked += 1
    assert checked > 0


def test_every_stored_noul_answer_matches_its_row_spec_exactly():
    responses = json.loads((RECIPE / "fixtures" / "responses.json").read_text("utf-8"))
    checked = 0
    for row in BUILD_FIXTURES.ROWS:
        _s1, _a1, _key1, s2_fields, _a2, key2 = BUILD_FIXTURES._resolve_row(row)
        for field in s2_fields:
            stored_noul = responses[key2]["answers"][field]["noul"]
            assert stored_noul == row["stage2"][field], (
                f"{row['id']}/{field}: stored noul {stored_noul!r} != spec {row['stage2'][field]!r}"
            )
            checked += 1
    assert checked > 0


# --------------------------------------------------------------------------------------------
# Composing a field's result: the rule Python enforces
# --------------------------------------------------------------------------------------------


def test_no_candidates_is_not_found_and_never_gated():
    result = helpers.no_candidates("D99", "invoice_number")
    assert result.outcome == helpers.NOT_FOUND
    assert result.choice is None
    assert result.value is None


def test_resolve_not_found_is_final_whatever_its_confidence():
    result = helpers.resolve_not_found("D99", "total_amount")
    assert result.outcome == helpers.NOT_FOUND
    assert result.choice == helpers.NOT_FOUND


def test_finalize_field_extracts_when_confident_and_verified():
    spans = {"s1": "Invoice #4420 for your records. "}
    result = helpers.finalize_field("D1", "invoice_number", "s1", spans, 0.9, 0.8, 0.5, 0.3)
    assert result.outcome == helpers.EXTRACTED
    assert result.value == spans["s1"]
    assert result.reason == "confident and verified"


def test_finalize_field_reviews_when_uncertain():
    spans = {"s1": "Invoice #4420 for your records. "}
    result = helpers.finalize_field("D1", "invoice_number", "s1", spans, 0.9, 0.1, 0.5, 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_CONFIDENCE


def test_finalize_field_reviews_when_inconsistent():
    spans = {"s1": "Previous invoice reference 3990 was paid in full last month. "}
    result = helpers.finalize_field("D1", "invoice_number", "s1", spans, 0.1, 0.8, 0.5, 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_INCONSISTENT


def test_finalize_field_reviews_a_foreign_choice_defensively():
    spans = {"s1": "Invoice #4420 for your records. "}
    result = helpers.finalize_field("D1", "invoice_number", "not-a-span", spans, 0.9, 0.8, 0.5, 0.3)
    assert result.outcome == helpers.REVIEW
    assert result.reason == helpers.REASON_FOREIGN


def test_matches_gold():
    extracted = helpers.FieldResult(
        "D1", "invoice_number", "s1", helpers.EXTRACTED, "Invoice #4420.", "r"
    )
    assert helpers.matches_gold(extracted, "4420")
    assert not helpers.matches_gold(extracted, "9999")
    not_found = helpers.FieldResult(
        "D1", "invoice_number", helpers.NOT_FOUND, helpers.NOT_FOUND, None, "r"
    )
    assert helpers.matches_gold(not_found, helpers.NOT_FOUND)
    assert not helpers.matches_gold(not_found, "4420")
    review = helpers.FieldResult("D1", "invoice_number", "s1", helpers.REVIEW, None, "r")
    assert not helpers.matches_gold(review, "4420")
    assert not helpers.matches_gold(review, helpers.NOT_FOUND)


def test_compose_document_outcome_is_accepted_only_when_no_field_is_in_review():
    extracted = helpers.FieldResult("D1", "invoice_number", "s1", helpers.EXTRACTED, "x", "r")
    review = helpers.FieldResult("D1", "total_amount", "s1", helpers.REVIEW, None, "r")
    both_ok = {"invoice_number": extracted, "total_amount": extracted}
    one_review = {"invoice_number": extracted, "total_amount": review}
    assert helpers.compose_document_outcome("D1", both_ok).accepted
    assert not helpers.compose_document_outcome("D1", one_review).accepted


# --------------------------------------------------------------------------------------------
# Independent consequentiality: flipping one field's stage-1 or stage-2 stored answer, on a
# real committed document, changes the composed document outcome -- demonstrated separately
# per field and per stage, so neither field and neither stage is merely along for the ride.
# --------------------------------------------------------------------------------------------


def _document_fields(doc_id):
    for example in load_inputs(RECIPE):
        if example.id == doc_id:
            return example.fields
    raise KeyError(doc_id)


def _stage2_noul_and_confidence(doc_id: str, field: str) -> tuple[float, float]:
    """The real, committed stage-2 ``noul`` for ``(doc_id, field)`` and its derived
    confidence, read from the stored fixtures through ``helpers.decide_document`` -- the same
    production path the notebook calls -- rather than a literal that merely happens to match
    today's stored answer."""
    fields = _document_fields(doc_id)
    backend = get_backend(fixtures=responses_path(RECIPE))
    _s1, _a1, _s2, a2 = helpers.decide_document(backend, fields)
    noul = a2[field].noul
    return noul, noul_confidence([noul])[0]


def test_flipping_stage1s_choice_changes_whether_the_field_is_correct():
    """``v11`` (real id ``D11``) has three invoice-number candidates: two decoys and the real
    one, which stage 1 actually names. Swapping only the stage-1 CHOICE to a decoy -- the same
    document, the same (real, committed) stage-2 noul value, nothing else touched -- flips the
    field (and so the document) from correct to wrong, because the decoy's own text never
    contains the gold invoice number. This isolates stage 1's own contribution from stage 2's."""
    fields = _document_fields("v11")
    spans = helpers.spans_by_id(fields, "invoice_number")
    gold = "5126"
    real_choice = next(sid for sid, text in spans.items() if gold in text)
    decoy_choice = next(sid for sid in spans if sid != real_choice)
    noul, confidence = _stage2_noul_and_confidence("v11", "invoice_number")

    real = helpers.finalize_field(
        "v11", "invoice_number", real_choice, spans, noul, confidence, 0.85, 0.7
    )
    decoy = helpers.finalize_field(
        "v11", "invoice_number", decoy_choice, spans, noul, confidence, 0.85, 0.7
    )
    assert helpers.matches_gold(real, gold)
    assert not helpers.matches_gold(decoy, gold)


def test_flipping_stage1s_choice_changes_the_amount_field_too():
    """The same isolation, for ``total_amount`` on ``v11``: three amount candidates, the real
    total against a subtotal and a tax line."""
    fields = _document_fields("v11")
    spans = helpers.spans_by_id(fields, "total_amount")
    gold = "97.20"
    real_choice = next(sid for sid, text in spans.items() if gold in text)
    decoy_choice = next(sid for sid in spans if sid != real_choice)
    noul, confidence = _stage2_noul_and_confidence("v11", "total_amount")

    real = helpers.finalize_field(
        "v11", "total_amount", real_choice, spans, noul, confidence, 0.85, 0.7
    )
    decoy = helpers.finalize_field(
        "v11", "total_amount", decoy_choice, spans, noul, confidence, 0.85, 0.7
    )
    assert helpers.matches_gold(real, gold)
    assert not helpers.matches_gold(decoy, gold)


def test_flipping_stage2s_verification_changes_whether_the_document_is_accepted():
    """``v01`` (real id ``D01``) is, as committed, fully accepted: both fields extracted and
    verified. Flipping only the stage-2 noul for ``invoice_number`` away from its real,
    committed value (confidently verified) to confidently-not -- the same stage-1 choice, the
    same document, ``total_amount`` built from its own real stored answer -- sends that field
    to review and so withholds the whole document. This isolates stage 2's own contribution
    from stage 1's."""
    fields = _document_fields("v01")
    spans = helpers.spans_by_id(fields, "invoice_number")
    backend = get_backend(fixtures=responses_path(RECIPE))
    _s1, a1, _s2, a2 = helpers.decide_document(backend, fields)
    choice = a1["invoice_number"].choice
    t, gate = 0.85, 0.70

    invoice_noul = a2["invoice_number"].noul
    verified = helpers.finalize_field(
        "v01",
        "invoice_number",
        choice,
        spans,
        invoice_noul,
        noul_confidence([invoice_noul])[0],
        t,
        gate,
    )
    not_verified_noul = 0.10
    not_verified = helpers.finalize_field(
        "v01",
        "invoice_number",
        choice,
        spans,
        not_verified_noul,
        noul_confidence([not_verified_noul])[0],
        t,
        gate,
    )
    amount_spans = helpers.spans_by_id(fields, "total_amount")
    amount_noul = a2["total_amount"].noul
    amount = helpers.finalize_field(
        "v01",
        "total_amount",
        a1["total_amount"].choice,
        amount_spans,
        amount_noul,
        noul_confidence([amount_noul])[0],
        t,
        gate,
    )

    accepted_before = helpers.compose_document_outcome(
        "v01", {"invoice_number": verified, "total_amount": amount}
    ).accepted
    accepted_after = helpers.compose_document_outcome(
        "v01", {"invoice_number": not_verified, "total_amount": amount}
    ).accepted
    assert accepted_before
    assert not accepted_after


def test_flipping_stage2s_verification_changes_the_amount_field_too():
    """The same isolation as above, for ``total_amount`` on ``v01``."""
    fields = _document_fields("v01")
    spans = helpers.spans_by_id(fields, "total_amount")
    backend = get_backend(fixtures=responses_path(RECIPE))
    _s1, a1, _s2, a2 = helpers.decide_document(backend, fields)
    choice = a1["total_amount"].choice
    t, gate = 0.85, 0.70

    invoice_spans = helpers.spans_by_id(fields, "invoice_number")
    invoice_noul = a2["invoice_number"].noul
    invoice = helpers.finalize_field(
        "v01",
        "invoice_number",
        a1["invoice_number"].choice,
        invoice_spans,
        invoice_noul,
        noul_confidence([invoice_noul])[0],
        t,
        gate,
    )

    amount_noul = a2["total_amount"].noul
    verified = helpers.finalize_field(
        "v01",
        "total_amount",
        choice,
        spans,
        amount_noul,
        noul_confidence([amount_noul])[0],
        t,
        gate,
    )
    not_verified_noul = 0.10
    not_verified = helpers.finalize_field(
        "v01",
        "total_amount",
        choice,
        spans,
        not_verified_noul,
        noul_confidence([not_verified_noul])[0],
        t,
        gate,
    )

    accepted_before = helpers.compose_document_outcome(
        "v01", {"invoice_number": invoice, "total_amount": verified}
    ).accepted
    accepted_after = helpers.compose_document_outcome(
        "v01", {"invoice_number": invoice, "total_amount": not_verified}
    ).accepted
    assert accepted_before
    assert not accepted_after


# --------------------------------------------------------------------------------------------
# Pooling order: two different orderings of the same (document, field) decisions must agree,
# both on the set of rows they describe and on the metrics computed from them -- the stage-
# ordering check this cascade's own evaluation depends on.
# --------------------------------------------------------------------------------------------


def test_pooling_order_does_not_change_attribution_or_metrics():
    examples = select_split(load_inputs(RECIPE), "test")
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    t, gate = _frozen_thresholds(backend, load_inputs(RECIPE), labels)
    results = _all_field_results(backend, examples, t, gate)
    gold = {e.id: labels[e.id] for e in examples}
    doc_ids = [e.id for e in examples]

    keys_a, accepted_a, correct_a = helpers.flatten_fields(doc_ids, results, gold)

    # An alternate ordering: field-major, document-minor, built independently rather than by
    # sorting keys_a (sorting would hide a genuine attribution bug if one existed).
    keys_b, accepted_b, correct_b = [], [], []
    for field in helpers.FIELDS:
        for doc_id in doc_ids:
            result = results[doc_id][field]
            keys_b.append((doc_id, field))
            accepted_b.append(result.outcome != helpers.REVIEW)
            correct_b.append(helpers.matches_gold(result, gold[doc_id][field]))

    rows_a = dict(zip(keys_a, zip(accepted_a, correct_a, strict=True), strict=True))
    rows_b = dict(zip(keys_b, zip(accepted_b, correct_b, strict=True), strict=True))
    assert rows_a == rows_b, "the two orderings disagree about some (document, field) pair"

    result_a = evaluate_outcomes(accepted_a, correct_a)
    result_b = evaluate_outcomes(accepted_b, correct_b)
    assert (
        result_a.n_total,
        result_a.n_answered,
        result_a.coverage,
        result_a.accuracy,
        result_a.risk,
    ) == (
        result_b.n_total,
        result_b.n_answered,
        result_b.coverage,
        result_b.accuracy,
        result_b.risk,
    )

    # A third, randomly shuffled order: the most convincing version of "order cannot matter",
    # since neither hand-written ordering above could coincidentally share a bug.
    rng = random.Random(12345)
    shuffled = list(zip(keys_a, accepted_a, correct_a, strict=True))
    rng.shuffle(shuffled)
    keys_c, accepted_c, correct_c = (list(x) for x in zip(*shuffled, strict=True))
    result_c = evaluate_outcomes(accepted_c, correct_c)
    assert (
        result_c.n_total,
        result_c.n_answered,
        result_c.coverage,
        result_c.accuracy,
        result_c.risk,
    ) == (
        result_a.n_total,
        result_a.n_answered,
        result_a.coverage,
        result_a.accuracy,
        result_a.risk,
    )


# --------------------------------------------------------------------------------------------
# Scored (document, field) pairs and scored documents are two different quantities -- the
# field-level and task-level metrics are each computed over one of them -- and a fixture edit
# must not be able to silently collapse the two without a test noticing.
# --------------------------------------------------------------------------------------------


def test_field_examples_outnumber_document_units():
    """A cascade asks several questions per document, so the number of scored (document,
    field) pairs -- what the field-level metrics are over -- is larger than the number of
    scored documents -- what the task-level metrics are over. Pinned here so a future fixture
    edit cannot silently collapse the two without a test noticing."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    scored = [e for e in examples if e.id in labels]
    n_units = len(scored)
    n_examples = sum(len(helpers.FIELDS) for _ in scored)
    assert n_examples == 2 * n_units
    assert n_examples > n_units


# --------------------------------------------------------------------------------------------
# Rule: each field must be falsifiable -- at least one committed row where that field's own
# outcome is wrong or sent to review, so neither field's accuracy is perfect by construction.
# --------------------------------------------------------------------------------------------


def test_each_field_has_at_least_one_fallible_committed_row():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    t, gate = _frozen_thresholds(backend, examples, labels)
    scored = [e for e in examples if e.id in labels]
    results = _all_field_results(backend, scored, t, gate)
    for field in helpers.FIELDS:
        fallible = [
            e.id
            for e in scored
            if results[e.id][field].outcome == helpers.REVIEW
            or not helpers.matches_gold(results[e.id][field], labels[e.id][field])
        ]
        assert fallible, f"{field}: every committed row is a correct, accepted answer"


# --------------------------------------------------------------------------------------------
# Pin the threshold-selection objective itself (min_coverage, not target_accuracy=1.0), not
# only the frozen values both the notebook and this test re-derive from it -- the value alone
# does not pin which objective produced it.
# --------------------------------------------------------------------------------------------


def test_business_threshold_and_confidence_gate_objectives_and_values():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    t, gate = _frozen_thresholds(backend, examples, labels)
    assert t == pytest.approx(0.85)
    assert gate == pytest.approx(0.70)


def test_the_notebook_selects_the_confidence_gate_by_min_coverage_not_target_accuracy():
    """The confidence gate's objective is chosen once, in the notebook's own ``evaluation-gate``
    cell, by calling ``select_confidence_threshold(..., min_coverage=0.85)``. Nothing ties a
    notebook cell's source to an importable constant, so an edit that swapped only that call to
    ``target_accuracy=0.90`` -- which still re-executes clean and still prints ``0.7000`` on this
    pool, with every other test in this file staying green -- would otherwise leave the notebook
    running a different selection than the one the tests above describe. Parse the committed
    notebook's own cell and pin the objective's keyword, not only the value it currently
    produces."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "evaluation-gate")
    source = "".join(cell["source"])
    assert "min_coverage=0.85" in source
    assert "target_accuracy" not in source


def test_v12_total_amount_is_the_unique_maximum_validation_confidence():
    """The notebook justifies choosing ``min_coverage`` over ``target_accuracy=1.0`` by one
    fact about this fixture pool: the validation split's sole verification error
    (``v12``/``total_amount``) carries the pool's uniquely highest confidence, so no confidence
    gate can exclude it without excluding the whole validation pool, and
    ``target_accuracy=1.0`` is infeasible. Pinned here so a fixture edit that moved that error
    away from the top of the confidence ranking -- which would make the claim false while
    leaving the two frozen values unchanged -- cannot pass silently."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))
    validation = select_split(examples, "validation")
    keys: list[tuple[str, str]] = []
    truth: list[bool] = []
    noul: list[float] = []
    for example in validation:
        _s1, a1, s2, a2 = helpers.decide_document(backend, example.fields)
        gold = labels[example.id]
        for field in s2:
            spans = helpers.spans_by_id(example.fields, field)
            is_right = gold[field] != helpers.NOT_FOUND and gold[field] in spans[a1[field].choice]
            keys.append((example.id, field))
            truth.append(is_right)
            noul.append(a2[field].noul)
    business_threshold = select_threshold(truth, noul, "f1")
    correct = [(n >= business_threshold) == t for n, t in zip(noul, truth, strict=True)]
    confidence = noul_confidence(noul)

    wrong_keys = [k for k, c in zip(keys, correct, strict=True) if not c]
    assert wrong_keys == [("v12", "total_amount")]

    max_confidence = max(confidence)
    at_max = [k for k, c in zip(keys, confidence, strict=True) if c == max_confidence]
    assert at_max == [("v12", "total_amount")]

    with pytest.raises(ValueError):
        select_confidence_threshold(correct, confidence, target_accuracy=1.0)


# --------------------------------------------------------------------------------------------
# G1(c): the strong form. Re-derives the confidence gate independently of
# ``_frozen_thresholds`` above (a strong-form check cannot re-derive through the production
# path it audits) and requires a wrong, confidently-accepted `test` answer at or above it.
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = get_backend(fixtures=responses_path(RECIPE))

    validation = select_split(examples, "validation")
    val_truth, val_noul = [], []
    for example in validation:
        _s1, a1, s2, a2 = helpers.decide_document(backend, example.fields)
        gold = labels[example.id]
        for field in s2:
            spans = helpers.spans_by_id(example.fields, field)
            is_right = gold[field] != helpers.NOT_FOUND and gold[field] in spans[a1[field].choice]
            val_truth.append(is_right)
            val_noul.append(a2[field].noul)
    business_threshold = select_threshold(val_truth, val_noul, "f1")
    val_correct = [
        (n >= business_threshold) == truth for n, truth in zip(val_noul, val_truth, strict=True)
    ]
    gate = select_confidence_threshold(val_correct, noul_confidence(val_noul), min_coverage=0.85)

    test = select_split(examples, "test")
    wrong_and_confident = []
    for example in test:
        _s1, a1, s2, a2 = helpers.decide_document(backend, example.fields)
        gold = labels[example.id]
        for field in s2:
            spans = helpers.spans_by_id(example.fields, field)
            choice = a1[field].choice
            noul_answer = a2[field]
            is_right = gold[field] != helpers.NOT_FOUND and gold[field] in spans[choice]
            if noul_confidence([noul_answer.noul])[0] >= gate and not is_right:
                wrong_and_confident.append((example.id, field))
    assert wrong_and_confident, "expected at least one confidently wrong test answer"
