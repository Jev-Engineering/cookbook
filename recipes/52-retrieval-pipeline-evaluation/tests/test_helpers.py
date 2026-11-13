"""Tests for recipe 52's helpers. They load the helpers by file path."""

import json
import random
import re
from pathlib import Path

import pytest

from jev_cookbook import (
    AuditedBackend,
    ChoiceAnswer,
    Provenance,
    ScoreAnswer,
    get_backend,
    load_helpers,
)
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, load_responses, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def run_all(example, configs=None):
    """Run each configuration on one fixture example through its own audited replay backend,
    returning ``{config: (PipelineRun, audit entry)}``."""
    out = {}
    for config in configs or helpers.CONFIGS:
        backend = AuditedBackend(get_backend(fixtures=responses_path(RECIPE)))
        run = helpers.run_pipeline(backend, example.id, example.fields, config)
        out[config] = (run, backend.audit())
    return out


# --------------------------------------------------------------------------------------------
# The strong-form stored-answers check, above every parametrized test in this file so the recipe
# guard's body extraction never swallows a decorator that belongs to a later function.
# --------------------------------------------------------------------------------------------


def test_stored_answers_are_not_all_right():
    # Mirror the notebook's threshold selection: the full pipeline's verdict answers on
    # validation (a run that kept no evidence made no request, so it has no confidence to rank),
    # target_accuracy=1.0. Then require a wrong `test` verdict at or above the frozen threshold:
    # a mistake the gate would still let through.
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def verdict(example):
        run = helpers.run_pipeline(backend, example.id, example.fields, "full")
        return run.verdict

    validation = [e for e in examples if e.split == "validation" and e.id in labels]
    val_answers = {e.id: verdict(e) for e in validation}
    asked = [e for e in validation if val_answers[e.id] is not None]
    correct = [val_answers[e.id].choice == labels[e.id]["verdict"] for e in asked]
    confidence = [val_answers[e.id].confidence for e in asked]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)

    test = [e for e in examples if e.split == "test" and e.id in labels]
    wrong_and_confident = []
    for e in test:
        a = verdict(e)
        if a is not None and a.choice != labels[e.id]["verdict"] and a.confidence >= threshold:
            wrong_and_confident.append(e.id)
    assert wrong_and_confident == ["t08"]


def test_the_notebook_selects_the_threshold_by_target_accuracy_not_min_coverage():
    """The committed ``gate`` cell, read from the notebook's source rather than from a printed
    label (which an edit could change without re-executing), must still select the threshold
    with ``target_accuracy=1.0`` and not with ``min_coverage``."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "gate")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


# --------------------------------------------------------------------------------------------
# The questions, the states and the replay keys
# --------------------------------------------------------------------------------------------


def test_questions_are_built_by_python():
    questions = helpers.build_questions()
    assert list(questions) == ["keep", "relevance", "verdict"]
    assert list(questions["keep"].criteria) == ["bears_on_claim", "does_not_bear"]
    assert list(questions["verdict"].criteria) == [
        "supported",
        "contradicted",
        "not_enough_evidence",
    ]
    assert len(questions["relevance"].criteria) == 4
    assert len(set(questions["relevance"].criteria)) == 4
    # No level's text refers to another level: each is judged on its own.
    assert not any(
        re.search(r"\b(more|less|higher|lower)\b.*\bthan\b", level)
        for level in questions["relevance"].criteria
    )


def test_each_configuration_asks_exactly_the_questions_it_needs():
    names = {c: helpers.stage_one_questions(c) for c in helpers.CONFIGS}
    assert names["none"] is None
    assert list(names["filter"]) == ["keep"]
    assert list(names["rerank"]) == ["relevance"]
    assert list(names["full"]) == ["keep", "relevance"]
    assert list(helpers.verdict_questions()) == ["verdict"]


def test_the_state_carries_no_python_owned_value():
    fields = {"claim": "C", "passage": "P", "passage_id": "x-p1", "position": 3}
    assert helpers.build_state(fields) == {"claim": "C", "passage": "P"}
    assert helpers.build_state({"claim": "C", "evidence": ["A", "B"]}) == {
        "claim": "C",
        "evidence": ["A", "B"],
    }


def test_every_replay_key_in_the_fixtures_matches_what_the_pipeline_asks():
    # Each example lists, in order, the distinct keys of every request the notebook makes for
    # it: every configuration its split runs, stage one then the verdict.
    from jev_cookbook import replay_key  # noqa: PLC0415

    stored = load_responses(RECIPE)
    for example in load_inputs(RECIPE):
        keys = []
        for config in helpers.RUN_CONFIGS[example.split]:
            backend = AuditedBackend(get_backend(fixtures=responses_path(RECIPE)))
            helpers.run_pipeline(backend, example.id, example.fields, config)
            for call in backend.audit()["calls"]:
                if call["replay_key"] not in keys:
                    keys.append(call["replay_key"])
        assert list(example.replay_keys) == keys, example.id
        assert all(key in stored for key in keys)
        assert all(len(key) == 64 for key in keys)
        assert replay_key  # the key function the fixtures were written with


def test_the_fixture_sizes():
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    sizes = {s: sum(e.split == s for e in examples) for s in ("demo", "validation", "test")}
    assert sizes == {"demo": 3, "validation": 8, "test": 10}
    verdicts = {
        s: sorted(labels[e.id]["verdict"] for e in examples if e.split == s)
        for s in ("validation", "test")
    }
    assert (
        verdicts["validation"]
        == ["contradicted"] * 2 + ["not_enough_evidence"] * 2 + ["supported"] * 4
    )
    assert (
        verdicts["test"] == ["contradicted"] * 2 + ["not_enough_evidence"] * 2 + ["supported"] * 6
    )
    assert len(load_responses(RECIPE)) == 202
    assert {entry["model"] for entry in load_responses(RECIPE).values()} == {"synthetic"}


# --------------------------------------------------------------------------------------------
# Python's candidate list
# --------------------------------------------------------------------------------------------


def test_only_the_two_mirrored_passages_are_removed_as_repeats():
    examples = {e.id: e for e in load_inputs(RECIPE)}
    removed = {}
    for ident, example in examples.items():
        kept = {c.passage_id for c in helpers.candidates(example.fields)}
        listed = [p["passage_id"] for p in example.fields["passages"]]
        removed[ident] = [p for p in listed if p not in kept]
    assert {k: v for k, v in removed.items() if v} == {"v05": ["v05-p3"], "t05": ["t05-p3"]}
    assert helpers.DUPLICATE_JACCARD == 0.8
    # Whatever it removed, no gold evidence passage was lost, and no two kept passages overlap
    # at or above the cutoff.
    labels = load_labels(RECIPE)
    for ident, example in examples.items():
        cands = helpers.candidates(example.fields)
        ids = {c.passage_id for c in cands}
        if ident in labels:
            assert set(labels[ident]["evidence"]) <= ids, ident
        for i, a in enumerate(cands):
            for b in cands[i + 1 :]:
                assert helpers.word_overlap(a.text, b.text) < helpers.DUPLICATE_JACCARD


def test_positions_are_the_retrieval_order_after_removal():
    example = next(e for e in load_inputs(RECIPE) if e.id == "t05")
    assert [(c.passage_id, c.position) for c in helpers.candidates(example.fields)] == [
        ("t05-p1", 0),
        ("t05-p2", 1),
        ("t05-p4", 2),
        ("t05-p5", 3),
    ]


# --------------------------------------------------------------------------------------------
# The top-k cut holds whatever the model answers
# --------------------------------------------------------------------------------------------


def _keep_answer(rng):
    p = rng.choice([rng.uniform(0.01, 0.49), rng.uniform(0.51, 0.99)])
    return ChoiceAnswer.from_probabilities(
        {helpers.KEEP: p, helpers.DROP: 1 - p}, Provenance.synthetic()
    )


def _relevance_answer(rng):
    raw = [rng.random() + 0.01 for _ in range(4)]
    total = sum(raw)
    return ScoreAnswer.from_probabilities(
        [r / total for r in raw], helpers.RELEVANCE_LEVELS, Provenance.synthetic()
    )


@pytest.mark.parametrize("config", helpers.CONFIGS)
def test_the_evidence_is_a_short_repeat_free_sublist_whatever_the_answers(config):
    rng = random.Random(52)
    examples = load_inputs(RECIPE)
    for _ in range(40):
        for example in examples:
            cands = helpers.candidates(example.fields)
            keep = {c.passage_id: _keep_answer(rng) for c in cands}
            relevance = {c.passage_id: _relevance_answer(rng) for c in cands}
            evidence = helpers.select_evidence(cands, config, keep, relevance)
            ids = [c.passage_id for c in evidence]
            assert len(ids) <= helpers.TOP_K
            assert len(ids) == len(set(ids))
            assert set(ids) <= {c.passage_id for c in cands}
            assert all(c in cands for c in evidence)
            if "filter" in helpers.CONFIG_STAGES[config]:
                assert all(keep[i].choice == helpers.KEEP for i in ids)
                kept = [c for c in cands if keep[c.passage_id].choice == helpers.KEEP]
                assert len(ids) == min(helpers.TOP_K, len(kept))
            else:
                assert len(ids) == min(helpers.TOP_K, len(cands))
            if "rerank" in helpers.CONFIG_STAGES[config]:
                scores = [
                    (-relevance[i].score, next(c.position for c in cands if c.passage_id == i))
                    for i in ids
                ]
                assert scores == sorted(scores)
            else:
                positions = [c.position for c in evidence]
                assert positions == sorted(positions)


def test_a_filter_that_drops_everything_leaves_no_evidence_and_no_verdict_request():
    example = next(e for e in load_inputs(RECIPE) if e.id == "t04")
    cands = helpers.candidates(example.fields)
    drop_all = {
        c.passage_id: ChoiceAnswer.from_probabilities(
            {helpers.KEEP: 0.1, helpers.DROP: 0.9}, Provenance.synthetic()
        )
        for c in cands
    }
    assert helpers.select_evidence(cands, "filter", drop_all, {}) == ()

    class Refuses:
        def decide(self, state, questions):
            raise AssertionError("no request may be made without evidence")

    assert helpers.ask_verdict(Refuses(), example.fields["claim"], ()) is None


def test_the_ties_in_expected_relevance_go_to_the_earlier_retrieval_position():
    rng = random.Random(7)
    example = next(e for e in load_inputs(RECIPE) if e.id == "t01")
    cands = helpers.candidates(example.fields)
    same = _relevance_answer(rng)
    relevance = {c.passage_id: same for c in cands}
    evidence = helpers.select_evidence(cands, "rerank", {}, relevance)
    assert [c.passage_id for c in evidence] == ["t01-p1", "t01-p2"]


# --------------------------------------------------------------------------------------------
# The gate rule holds whatever the model answers
# --------------------------------------------------------------------------------------------


def _run_with(evidence_ids, answer):
    cands = tuple(helpers.Candidate(i, f"text {i}", n) for n, i in enumerate(evidence_ids))
    return helpers.PipelineRun("x", "full", cands, cands, {}, {}, answer)


def _verdict(probabilities):
    return ChoiceAnswer.from_probabilities(
        dict(zip(helpers.VERDICTS, probabilities, strict=True)), Provenance.synthetic()
    )


def test_finalize_answers_only_at_or_above_the_threshold_and_cites_the_evidence():
    rng = random.Random(3)
    for _ in range(300):
        raw = [rng.random() + 0.01 for _ in range(3)]
        probabilities = [r / sum(raw) for r in raw]
        answer = _verdict(probabilities)
        gate = rng.random()
        outcome = helpers.finalize(_run_with(["a-p1", "a-p2"], answer), gate)
        assert outcome.evidence_ids == ("a-p1", "a-p2")
        assert outcome.proposed == answer.choice
        if answer.confidence >= gate:
            assert outcome.outcome == helpers.ANSWERED
            assert outcome.verdict == answer.choice in helpers.VERDICTS
            assert outcome.reason == "confidence reaches the threshold"
        else:
            assert outcome.outcome == helpers.REVIEW
            assert outcome.verdict is None
            assert outcome.reason == "confidence below the threshold"


def test_not_enough_evidence_is_gated_like_every_other_verdict():
    low = _verdict([0.30, 0.25, 0.45])
    high = _verdict([0.05, 0.05, 0.90])
    assert helpers.finalize(_run_with(["a-p1"], low), 0.5).outcome == helpers.REVIEW
    assert helpers.finalize(_run_with(["a-p1"], high), 0.5).verdict == helpers.NOT_ENOUGH


def test_no_evidence_is_a_review_at_any_threshold_and_never_a_verdict():
    for gate in (0.0, 0.5, 1.0):
        outcome = helpers.finalize(_run_with([], None), gate)
        assert (outcome.outcome, outcome.verdict, outcome.reason) == (
            "review",
            None,
            "no passage was kept as evidence",
        )


def test_a_threshold_outside_the_unit_interval_is_refused():
    run = _run_with(["a-p1"], _verdict([0.8, 0.1, 0.1]))
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError):
            helpers.finalize(run, bad)


def test_an_outcome_cannot_state_a_verdict_without_evidence_or_a_review_with_one():
    with pytest.raises(ValueError):
        helpers.Outcome("x", "answered", "supported", (), "r", "supported")
    with pytest.raises(ValueError):
        helpers.Outcome("x", "answered", "made_up", ("a",), "r", "made_up")
    with pytest.raises(ValueError):
        helpers.Outcome("x", "review", "supported", ("a",), "r", "supported")


def test_answer_supported_needs_an_answered_outcome_with_the_gold_verdict():
    ok = helpers.Outcome("x", "answered", "supported", ("a",), "r", "supported")
    wrong = helpers.Outcome("x", "answered", "contradicted", ("a",), "r", "contradicted")
    held = helpers.Outcome("x", "review", None, ("a",), "r", "supported")
    assert helpers.answer_supported(ok, "supported")
    assert not helpers.answer_supported(wrong, "supported")
    assert not helpers.answer_supported(held, "supported")


def test_evidence_complete_needs_every_gold_passage_and_is_undefined_without_any():
    assert helpers.evidence_complete(("a", "b"), ["a", "b"]) is True
    assert helpers.evidence_complete(("a",), ["a", "b"]) is False
    assert helpers.evidence_complete(("a",), []) is None


# --------------------------------------------------------------------------------------------
# The composition: which questions share a request, and which wait for an answer
# --------------------------------------------------------------------------------------------


def test_request_counts_per_configuration_on_one_example():
    # t01 has 4 candidate passages. Stage one sends one request per passage (the filter and the
    # reranking question share it in the full pipeline); the verdict is one more request.
    example = next(e for e in load_inputs(RECIPE) if e.id == "t01")
    runs = run_all(example)
    assert {c: r[1]["decide_calls"] for c, r in runs.items()} == {
        "none": 1,
        "filter": 5,
        "rerank": 5,
        "full": 5,
    }
    assert {c: r[1]["distinct_requests"] for c, r in runs.items()} == {
        "none": 1,
        "filter": 5,
        "rerank": 5,
        "full": 5,
    }


def test_a_run_that_keeps_no_evidence_makes_only_the_stage_one_requests():
    example = next(e for e in load_inputs(RECIPE) if e.id == "t04")
    runs = run_all(example, ("filter", "full"))
    assert runs["filter"][1]["decide_calls"] == 4
    assert runs["filter"][0].verdict is None
    assert runs["full"][1]["decide_calls"] == 4
    assert runs["full"][0].evidence == ()


def test_the_evidence_each_configuration_reads_for_the_demo_hard_case():
    example = next(e for e in load_inputs(RECIPE) if e.id == "d01")
    runs = run_all(example, helpers.RUN_CONFIGS["demo"])
    evidence = {c: [x.passage_id for x in r[0].evidence] for c, r in runs.items()}
    assert evidence == {"none": ["d01-p1", "d01-p2"], "full": ["d01-p2"]}
    # The filter's stored answer for the second fact is a (mildly confident) drop.
    full = runs["full"][0]
    assert full.keep["d01-p4"].choice == helpers.DROP
    assert full.keep["d01-p4"].probabilities[helpers.KEEP] == 0.3


def test_the_audit_names_the_verdict_request_last_and_after_every_stage_one_request():
    example = next(e for e in load_inputs(RECIPE) if e.id == "t10")
    backend = AuditedBackend(get_backend(fixtures=responses_path(RECIPE)))
    helpers.run_pipeline(backend, example.id, example.fields, "full")
    audit = backend.audit()
    assert audit["decide_calls"] == 5
    stage_one_keys = [c["replay_key"] for c in audit["calls"][:4]]
    assert len(set(stage_one_keys)) == 4
    assert audit["calls"][4]["replay_key"] not in stage_one_keys


# --------------------------------------------------------------------------------------------
# What the stored answers hold, typed from the fixtures
# --------------------------------------------------------------------------------------------


def test_the_stored_answers_include_confident_mistakes_and_gated_reviews_on_test():
    backend = get_backend(fixtures=responses_path(RECIPE))
    labels = load_labels(RECIPE)
    outcomes = {}
    for example in load_inputs(RECIPE):
        if example.split != "test":
            continue
        run = helpers.run_pipeline(backend, example.id, example.fields, "full")
        outcomes[example.id] = run
    # t08: a decoy that reads as relevant makes the verifier confidently say "supported".
    assert outcomes["t08"].verdict.choice == "supported"
    assert labels["t08"]["verdict"] == "not_enough_evidence"
    # t09: the right verdict with low confidence.
    assert outcomes["t09"].verdict.choice == "supported"
    assert outcomes["t09"].verdict.confidence < 0.25
    # t04: every passage dropped, so no verdict was asked for.
    assert outcomes["t04"].verdict is None


def test_raising_the_repeat_cutoff_lets_the_near_copy_crowd_out_the_second_fact(monkeypatch):
    # The notebook's first exercise: at 0.9 the near-copy on t05 is no longer removed, and a
    # filter that keeps every passage with a fact in it hands the verifier the copy, not the
    # second fact. Re-derived here through the shared helpers, with the answers written out.
    example = next(e for e in load_inputs(RECIPE) if e.id == "t05")
    keep_ids = {"t05-p2", "t05-p3", "t05-p5"}

    def keeps(cands):
        out = {}
        for c in cands:
            p = 0.9 if c.passage_id in keep_ids else 0.1
            out[c.passage_id] = ChoiceAnswer.from_probabilities(
                {helpers.KEEP: p, helpers.DROP: round(1 - p, 4)}, Provenance.synthetic()
            )
        return out

    committed = helpers.candidates(example.fields)
    assert len(committed) == 4
    assert [
        c.passage_id for c in helpers.select_evidence(committed, "filter", keeps(committed), {})
    ] == [
        "t05-p2",
        "t05-p5",
    ]
    monkeypatch.setattr(helpers, "DUPLICATE_JACCARD", 0.9)
    raised = helpers.candidates(example.fields)
    assert len(raised) == 5
    assert [c.passage_id for c in helpers.select_evidence(raised, "filter", keeps(raised), {})] == [
        "t05-p2",
        "t05-p3",
    ]
