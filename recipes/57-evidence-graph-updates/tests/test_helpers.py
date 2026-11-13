"""Tests for recipe 57's helpers. They load the helpers by file path.

The expected values below are literals typed from the fixtures, not recomputed by the helpers
under test (docs/simulation.md, shape 2: decide-and-apply)."""

import inspect
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, NoulAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split
from jev_cookbook.simulation import Budget, ReplayMismatch, replay_transactions

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)
SYN = Provenance.synthetic()


def _examples():
    return {e.id: e for e in load_inputs(RECIPE)}


def _backend():
    return get_backend(fixtures=responses_path(RECIPE))


def _first(probs, conflict):
    return {
        "entity": ChoiceAnswer.from_probabilities(probs, SYN),
        "conflict": NoulAnswer(conflict, SYN),
    }


def _second(supported, ended):
    return {"supported": NoulAnswer(supported, SYN), "ended": NoulAnswer(ended, SYN)}


SETTINGS = helpers.Settings(gate=0.5, conflict=0.8, supported=0.7, ended=0.4)


def _run(split):
    """The notebook's own sequence on one split, with the settings frozen on validation."""
    examples = load_inputs(RECIPE)
    labels = load_labels(RECIPE)
    backend = _backend()
    budget = Budget(requests=2 * len(examples))
    val = select_split(examples, "validation")
    first = helpers.ask_first(backend, budget, val)
    stage_one = helpers.freeze_stage_one([first[e.id] for e in val], [labels[e.id] for e in val])
    second = helpers.ask_second(backend, budget, val, first, stage_one)
    reached = [
        e
        for e in val
        if e.id in second
        and first[e.id]["entity"].choice == labels[e.id]["entity"]
        and "supported" in labels[e.id]
    ]
    settings = helpers.freeze_stage_two(
        stage_one, [second[e.id] for e in reached], [labels[e.id] for e in reached]
    )
    if split == "test":
        rows = select_split(examples, "test")
        first = helpers.ask_first(backend, budget, rows)
        second = helpers.ask_second(backend, budget, rows, first, settings)
    else:
        rows = val
    decisions = [helpers.decide(e, first[e.id], second.get(e.id), settings) for e in rows]
    return settings, rows, first, second, decisions, budget


# --- questions and state -----------------------------------------------------------------


def test_candidates_and_option_order_are_built_by_python():
    assert helpers.candidates("M. Okafor") == ["P01", "P02"]
    assert helpers.candidates("Gwen Tallis") == ["P21"]
    assert helpers.option_order("d01", "P. Lund") == ["P23", "P22"]
    fields = _examples()["d01"].fields
    options = list(helpers.build_first_questions("d01", fields)["entity"].criteria)
    assert options == ["P23", "P22", "no_match"]


def test_request_one_and_request_two_each_ask_two_questions():
    fields = _examples()["d01"].fields
    assert list(helpers.build_first_questions("d01", fields)) == ["entity", "conflict"]
    assert type(helpers.build_first_questions("d01", fields)["conflict"]).__name__ == "Noul"
    assert list(helpers.build_second_questions()) == ["supported", "ended"]


def test_the_states_keep_ids_in_python():
    fields = _examples()["d01"].fields
    assert helpers.build_first_state(fields) == {
        "mention": "P. Lund",
        "proposed_update": "P. Lund now works at Quillmoor Analytics",
        "excerpts": [
            "Staff newsletter: Survey designer P. Lund has left Halden Institute.",
            "Team blog: Quillmoor Analytics introduced P. Lund, who will design its customer surveys.",
        ],
    }
    second = helpers.build_second_state(fields, "P22")
    assert {k: second[k] for k in ("person", "current_employer", "proposed_employer")} == {
        "person": "Petra Lund, survey designer",
        "current_employer": "Halden Institute",
        "proposed_employer": "Quillmoor Analytics",
    }


def test_request_one_never_chooses_the_same_person_twice_among_rows_that_reach_request_two():
    """build_second_state shows the seed graph, so a person chosen twice among the proposals
    that get request 2 in one split would be shown with a stale employer the second time. The
    check is over the persons request 1 actually chose, not the gold persons: in the test split
    t08-wrong-match chooses P17, who is gold for t12-low-confidence, which the gate stops."""
    for split in ("validation", "test"):
        _, rows, first, second, _, _ = _run(split)
        chosen = [first[e.id]["entity"].choice for e in rows if e.id in second]
        assert len(chosen) == len(set(chosen)), split
    _, rows, first, second, _, _ = _run("test")
    assert [first[e.id]["entity"].choice for e in rows if e.id in ("t08-wrong-match", "t12-low-confidence")] == ["P17", "P17"]  # fmt: skip
    assert "t12-low-confidence" not in second


def test_a_mention_with_no_candidate_is_settled_in_python_without_a_request():
    class NoRequests:
        def decide(self, *_):
            raise AssertionError("a request was sent")

    assert helpers.candidates("") == [] and helpers.candidates("   ") == []
    assert helpers.candidates("Mira Okafor,") == ["P01", "P02"]
    mentions = {"u1": "Lena Smith", "u2": "", "u3": "  ", "u4": "Smith."}
    examples = [
        SimpleNamespace(id=k, fields={"mention": m, "target": "O1", "excerpts": []})
        for k, m in mentions.items()
    ]
    budget = Budget(requests=4)
    first = helpers.ask_first(NoRequests(), budget, examples)
    assert budget.used("requests") == 0
    for e in examples:
        d = helpers.decide(e, first[e.id], None, SETTINGS)
        assert (d.outcome, d.reason, d.answers) == ("no_match", "the mention matches no listed person", {})  # fmt: skip
    assert helpers.ask_second(NoRequests(), budget, examples, first, SETTINGS) == {}


def test_every_replay_key_matches_the_current_questions():
    """Request 1 for every example; request 2, built from request 1's stored choice, only for
    the examples listed here."""
    backend = _backend()
    with_second = []
    for e in load_inputs(RECIPE):
        state = helpers.build_first_state(e.fields)
        questions = helpers.build_first_questions(e.id, e.fields)
        assert e.replay_keys[0] == replay_key(state, questions)
        if len(e.replay_keys) == 2:
            with_second.append(e.id)
            person = backend.decide(state, questions)["entity"].choice
            second = helpers.build_second_state(e.fields, person)
            assert e.replay_keys[1] == replay_key(second, helpers.build_second_questions())
        else:
            assert len(e.replay_keys) == 1
    assert with_second == [
        "v01", "v02-initial", "v04-unsupported", "v05-invariant", "v06-left-only", "v08",
        "v09-initial", "v10", "v11-invariant",
        "t01", "t02-initial", "t03-left-only", "t04-invariant", "t05-unsupported",
        "t08-wrong-match", "t09", "t10-missed", "t11-conflict",
        "d01",
    ]  # fmt: skip


# --- the rule ------------------------------------------------------------------------------


def test_decide_first_stops_early_in_four_ways():
    cases = [
        (None, helpers.REVIEW, "request budget spent"),
        (_first({"P01": 0.4, "P02": 0.35, "no_match": 0.25}, 0.1), helpers.REVIEW, "confidence below the threshold"),
        (_first({"P01": 0.05, "P02": 0.05, "no_match": 0.9}, 0.1), "no_match", "the mention matches no listed person"),
        (_first({"P01": 0.9, "P02": 0.05, "no_match": 0.05}, 0.85), helpers.REVIEW, "the excerpts conflict"),
    ]  # fmt: skip
    for first, outcome, reason in cases:
        d = helpers.decide_first(first, SETTINGS, "x")
        assert (d.outcome, d.reason) == (outcome, reason)
    assert (
        helpers.decide_first(_first({"P01": 0.9, "P02": 0.05, "no_match": 0.05}, 0.1), SETTINGS)
        is None
    )


def test_the_gate_applies_to_no_match_too_and_is_inclusive():
    unsure = _first({"P01": 0.2, "P02": 0.2, "no_match": 0.6}, 0.1)
    assert unsure["entity"].confidence < SETTINGS.gate
    assert helpers.decide_first(unsure, SETTINGS).reason == "confidence below the threshold"
    sure = _first({"P01": 0.9, "P02": 0.05, "no_match": 0.05}, 0.1)
    at = helpers.Settings(sure["entity"].confidence, 0.8, 0.7, 0.4)
    assert helpers.decide_first(sure, at) is None


def test_decide_composes_the_second_request():
    e = _examples()["t01"]
    first = _first({"P12": 0.9, "P11": 0.05, "no_match": 0.05}, 0.1)
    replace = helpers.decide(e, first, _second(0.9, 0.9), SETTINGS)
    assert (replace.outcome, replace.person, replace.target, replace.replace) == (
        "propose", "P12", "O2", True,
    )  # fmt: skip
    add = helpers.decide(e, first, _second(0.9, 0.1), SETTINGS)
    assert (add.outcome, add.replace) == ("propose", False)
    rejected = helpers.decide(e, first, _second(0.5, 0.9), SETTINGS)
    assert (rejected.outcome, rejected.reason) == (
        "rejected",
        "the evidence does not support the relationship",
    )
    unpaid = helpers.decide(e, first, None, SETTINGS)
    assert (unpaid.outcome, unpaid.reason) == ("review", "request budget spent")


def test_the_budget_holds_whatever_the_model_answers():
    """With room for one request, the second example's request 1 is never sent."""
    examples = select_split(load_inputs(RECIPE), "test")[:2]
    budget = Budget(requests=1)
    first = helpers.ask_first(_backend(), budget, examples)
    assert first[examples[1].id] is None
    assert budget.used("requests") == 1
    decision = helpers.decide(examples[1], first[examples[1].id], None, SETTINGS)
    assert (decision.outcome, decision.reason) == ("review", "request budget spent")
    assert helpers.ask_second(_backend(), budget, examples[:1], first, SETTINGS) == {
        examples[0].id: None
    }


def test_freezing_handles_refused_requests_and_an_empty_second_stage():
    probs = {"P01": 0.9, "P02": 0.05, "no_match": 0.05}
    answered = [_first(probs, 0.9), _first({"P01": 0.1, "P02": 0.8, "no_match": 0.1}, 0.1)]
    gold = [
        {"entity": "P01", "conflict": True},
        {"entity": "P02", "conflict": False},
    ]
    expected = helpers.freeze_stage_one(answered, gold)
    mixed = [None, answered[0], helpers.UNMATCHED, answered[1]]
    mixed_gold = [gold[0], *gold[:1], gold[1], gold[1]]
    assert helpers.freeze_stage_one(mixed, mixed_gold) == expected
    nothing = helpers.freeze_stage_one([None, helpers.UNMATCHED], gold)
    assert (nothing.gate, nothing.conflict) == (math.inf, math.inf)
    refused = helpers.freeze_stage_two(expected, [None], [{"supported": True, "ended": False}])
    assert (refused.supported, refused.ended) == (math.inf, math.inf)
    assert helpers.freeze_stage_two(expected, [], []) == refused
    calm = _first(probs, 0.0)
    d = helpers.decide(_examples()["t01"], calm, _second(0.99, 0.99), refused)
    assert (d.outcome, d.reason) == ("rejected", "the evidence does not support the relationship")


# --- settings ------------------------------------------------------------------------------


def test_the_frozen_settings():
    settings, *_ = _run("validation")
    assert settings == helpers.Settings(0.49000000000000005, 0.81, 0.76, 0.41)


def test_the_threshold_objectives_are_pinned_in_the_committed_helpers():
    """Pin which objective each selection uses, not only the value it lands on."""
    first_source = inspect.getsource(helpers.freeze_stage_one)
    assert "select_confidence_threshold(correct, confidence, target_accuracy=1.0)" in first_source
    assert "min_coverage" not in first_source
    assert '"f1"' in first_source
    second_source = inspect.getsource(helpers.freeze_stage_two)
    assert second_source.count('"f1"') == 2


def test_stored_answers_are_not_all_right():
    """Re-derive the entity gate the way helpers.freeze_stage_one does (every validation entity
    answer counts) and require a wrong `test` entity answer at or above it: a mistake the gate
    still lets through."""
    backend = _backend()
    labels = load_labels(RECIPE)
    examples = load_inputs(RECIPE)

    def decide(example):
        state = helpers.build_first_state(example.fields)
        return backend.decide(state, helpers.build_first_questions(example.id, example.fields))[
            "entity"
        ]

    validation = [e for e in examples if e.split == "validation"]
    correct = [decide(e).choice == labels[e.id]["entity"] for e in validation]
    confidence = [decide(e).confidence for e in validation]
    threshold = select_confidence_threshold(correct, confidence, target_accuracy=1.0)
    wrong_and_confident = [
        e.id
        for e in examples
        if e.split == "test"
        and decide(e).choice != labels[e.id]["entity"]
        and decide(e).confidence >= threshold
    ]
    assert wrong_and_confident == ["t08-wrong-match"]


# --- the side effects: store, transactions, review queue -----------------------------------


def test_the_seed_graph_satisfies_the_invariant():
    tx, queue, outcomes = helpers.run_updates([], "rule:test")
    assert [r.status for r in tx.log] == ["committed"]
    assert tx.store.version == 52
    edges = [k for k in tx.store.keys() if k.startswith("edge:")]
    assert len(edges) == len(helpers.PEOPLE) == 23
    assert (len(queue), outcomes) == (0, [])


def test_run_updates_on_test_matches_the_fixtures():
    _, rows, _, _, decisions, budget = _run("test")
    assert budget.used("requests") == 42
    tx, queue, outcomes = helpers.run_updates(decisions, "rule:apply_update")
    assert [(o.example, o.outcome, o.reason) for o in outcomes] == [
        ("t01", "applied", "the transaction committed"),
        ("t02-initial", "applied", "the transaction committed"),
        ("t03-left-only", "rejected", "the evidence does not support the relationship"),
        ("t04-invariant", "review", "the transaction was rolled back"),
        ("t05-unsupported", "review", "the transaction was rolled back"),
        ("t06-conflict", "review", "the excerpts conflict"),
        ("t07-no-match", "no_match", "the mention matches no listed person"),
        ("t08-wrong-match", "applied", "the transaction committed"),
        ("t09", "applied", "the transaction committed"),
        ("t10-missed", "rejected", "the evidence does not support the relationship"),
        ("t11-conflict", "applied", "the transaction committed"),
        ("t12-low-confidence", "review", "confidence below the threshold"),
    ]
    assert [
        (r["name"], r["status"], r["version_before"], r["version_after"]) for r in tx.to_dicts()
    ] == [
        ("seed_graph", "committed", 0, 52),
        ("works_at:t01", "committed", 52, 54),
        ("works_at:t02-initial", "committed", 54, 56),
        ("works_at:t04-invariant", "rolled_back", 56, 56),
        ("works_at:t05-unsupported", "rolled_back", 56, 56),
        ("works_at:t08-wrong-match", "committed", 56, 58),
        ("works_at:t09", "committed", 58, 60),
        ("works_at:t11-conflict", "committed", 60, 62),
    ]
    assert [(i["id"], i["item"]["example"], i["reason"], i["step"]) for i in queue.to_dicts()] == [
        (0, "t04-invariant", "the transaction was rolled back", 4),
        (1, "t05-unsupported", "the transaction was rolled back", 5),
        (2, "t06-conflict", "the excerpts conflict", 6),
        (3, "t12-low-confidence", "confidence below the threshold", 12),
    ]
    assert [h.to_dict()["tombstone"] for h in tx.store.history("edge:P17|works_at|O1")] == [
        False,
        True,
    ]
    assert tx.store.get("edge:P17|works_at|O2") == {
        "person": "P17",
        "relation": "works_at",
        "org": "O2",
    }


def test_update_accuracy_against_gold():
    labels = load_labels(RECIPE)
    for split, expected in (("validation", ["v11-invariant"]), ("test", ["t08-wrong-match", "t10-missed", "t11-conflict", "t12-low-confidence"])):  # fmt: skip
        _, rows, _, _, decisions, _ = _run(split)
        _, _, outcomes = helpers.run_updates(decisions, "rule:apply_update")
        wrong = [
            e.id
            for e, o in zip(rows, outcomes, strict=True)
            if o.ops != helpers.gold_ops(labels[e.id])
        ]
        assert wrong == expected


def test_a_rolled_back_update_leaves_the_store_unchanged():
    e = _examples()["t04-invariant"]
    add = helpers.Decision(e.id, "propose", "", "P15", "O1", False, None)
    already = helpers.Decision("dup", "propose", "", "P15", "O5", False, None)
    tx, queue, outcomes = helpers.run_updates([add, already], "rule:test")
    assert [r.status for r in tx.log] == ["committed", "rolled_back", "rolled_back"]
    assert tx.store.version == 52
    assert tx.store.snapshot() == tx.store.at(52)
    assert (
        tx.log[1].error
        == "ValueError: invariant rejected: ['P15 would work at 2 organisations: O1, O5']"
    )
    assert tx.log[2].error == "ValueError: validate rejected: ['the edge is already in the graph']"
    assert [o.outcome for o in outcomes] == ["review", "review"]
    assert [i["reason"] for i in queue.to_dicts()] == ["the transaction was rolled back"] * 2


def test_a_replacement_deletes_the_edge_the_live_store_holds_for_that_person():
    """The second update of one person deletes the edge the first one wrote, not the seed edge."""
    first = helpers.Decision("a", "propose", "", "P17", "O2", True, None)
    second = helpers.Decision("b", "propose", "", "P17", "O3", True, None)
    tx, queue, outcomes = helpers.run_updates([first, second], "rule:test")
    assert [(o.outcome, o.ops) for o in outcomes] == [
        ("applied", (("delete", "edge:P17|works_at|O1"), ("put", "edge:P17|works_at|O2"))),
        ("applied", (("delete", "edge:P17|works_at|O2"), ("put", "edge:P17|works_at|O3"))),
    ]
    assert len(queue) == 0
    assert [k for k in tx.store.keys() if k.startswith("edge:P17|")] == ["edge:P17|works_at|O3"]


def test_validate_update_rejects_removing_another_persons_edge():
    tx, _, _ = helpers.run_updates([], "rule:test")
    own = {"person": "P12", "org": "O2", "replace": True, "remove": "edge:P12|works_at|O3"}
    assert helpers.validate_update(tx.store, own) is None
    other = {**own, "remove": "edge:P11|works_at|O6"}
    assert helpers.validate_update(tx.store, other) == [
        "edge:P11|works_at|O6 is not P12's current employment"
    ]
    gone = {**own, "remove": "edge:P12|works_at|O5"}
    assert helpers.validate_update(tx.store, gone) is not None
    nothing = {**own, "remove": None}
    assert helpers.validate_update(tx.store, nothing) == [
        "P12 has no current employment to replace"
    ]


def test_removing_an_employment_without_adding_one_is_not_what_the_invariant_checks():
    """The invariant is "at most one employer": a person left with none passes it."""
    tx, _, _ = helpers.run_updates([], "rule:test")
    state = {k: v for k, v in tx.store.snapshot().items() if k != "edge:P01|works_at|O1"}
    view = SimpleNamespace(snapshot=lambda: state)
    assert helpers.graph_invariant(view) is None


def test_the_log_replays_to_an_identical_graph():
    *_, decisions, _ = _run("test")
    tx, _, _ = helpers.run_updates(decisions, "rule:apply_update")
    rebuilt = replay_transactions(tx.log)
    assert rebuilt.to_dicts() == tx.store.to_dicts()
    assert rebuilt.version == 62
    tampered = [r.to_dict() for r in tx.log]
    del tampered[1]
    with pytest.raises(ReplayMismatch):
        replay_transactions(tampered)


# --- the multi-proposition Noul pair -------------------------------------------------------


def test_each_proposition_has_both_gold_values_and_every_combination_in_both_splits():
    labels = load_labels(RECIPE)
    for split in ("validation", "test"):
        pairs = {
            (labels[e.id]["supported"], labels[e.id]["ended"])
            for e in select_split(load_inputs(RECIPE), split)
            if "supported" in labels[e.id]
        }
        assert pairs == {(True, True), (True, False), (False, True), (False, False)}
        conflicts = {labels[e.id]["conflict"] for e in select_split(load_inputs(RECIPE), split)}
        assert conflicts == {True, False}


def test_each_proposition_alone_changes_the_composed_outcome_on_t01():
    settings, rows, first, second, decisions, _ = _run("test")
    row = next(e for e in rows if e.id == "t01")
    original = second["t01"]
    variants = [
        original,
        {"supported": NoulAnswer(0.0, SYN), "ended": original["ended"]},
        {"supported": original["supported"], "ended": NoulAnswer(0.0, SYN)},
    ]
    decided = [helpers.decide(row, first["t01"], v, settings) for v in variants]
    _, _, outcomes = helpers.run_updates(decided, "rule:test")
    assert [(o.outcome, o.reason) for o in outcomes] == [
        ("applied", "the transaction committed"),
        ("rejected", "the evidence does not support the relationship"),
        ("review", "the transaction was rolled back"),
    ]


# --- the baseline --------------------------------------------------------------------------


def _baseline_row(*texts):
    excerpts = [{"source": "s", "text": t} for t in texts]
    fields = {"mention": "Ruth Pell", "target": "O2", "excerpts": excerpts}
    return SimpleNamespace(id="b", fields=fields)


def test_the_baseline_ended_cue_starts_at_a_word_in_the_same_excerpt_as_the_employer():
    # Ruth Pell (P07) works at Tessaly Foundry in the seed graph; the proposed employer is Halden.
    plain = _baseline_row("Ruth Pell of Tessaly Foundry will join Halden Institute.")
    assert helpers.baseline_decide(plain).replace is False
    left = _baseline_row("Ruth Pell left Tessaly Foundry to join Halden Institute.")
    assert helpers.baseline_decide(left).replace is True
    substring = _baseline_row(
        "Ruth Pell of Tessaly Foundry mapped the cleft, then Halden Institute."
    )
    assert helpers.baseline_decide(substring).replace is False
    apart = _baseline_row(
        "Ruth Pell left the choir last spring.",
        "Ruth Pell works at Tessaly Foundry and will join Halden Institute.",
    )
    assert helpers.baseline_decide(apart).replace is False


def test_the_baseline_on_test():
    rows = select_split(load_inputs(RECIPE), "test")
    decisions = [helpers.baseline_decide(e) for e in rows]
    _, _, outcomes = helpers.run_updates(decisions, "rule:baseline")
    assert [o.outcome for o in outcomes] == [
        "applied", "no_match", "rejected", "review", "review", "review",
        "no_match", "no_match", "applied", "review", "review", "no_match",
    ]  # fmt: skip
