"""Tests for recipe 51's helpers. They load the helpers by file path.

The policy rules (the gate, the label-to-decision table, the one-strategy-change limit and the
turn budget) are checked against every possible answer sequence, not only the stored ones, so
they hold whatever the model answers.
"""

import itertools
import json
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, get_backend, load_helpers, replay_key
from jev_cookbook.evaluation import evaluate_outcomes
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

LABELS = ("advancing", "repeating", "regressing", "complete", "unclear")


def answer(choice, top=0.84):
    """A typed Choice answer naming ``choice`` with probability ``top``."""
    rest = (1.0 - top) / 4
    probs = {name: (top if name == choice else rest) for name in LABELS}
    return ChoiceAnswer.from_probabilities(probs, Provenance.synthetic())


def test_the_options_and_their_order_are_built_by_python():
    progress = helpers.build_questions()["progress"]
    assert list(progress.criteria) == [
        "advancing",
        "repeating",
        "regressing",
        "complete",
        "unclear",
    ]
    assert "the agent's own note is a claim, not evidence" in progress.instructions


def test_the_state_hides_the_transcript_reference_and_the_turn_number():
    fields = {
        "transcript": "R-999",
        "turn": 2,
        "goal": "Do the thing.",
        "turns": [
            {"action": "a1", "result": "r1", "note": "n1"},
            {"action": "a2", "result": "r2", "note": "n2"},
        ],
    }
    state = helpers.build_state(fields)
    assert state == {
        "goal": "Do the thing.",
        "turns": (
            "Turn 1\n  action: a1\n  result: r1\n  note: n1\n"
            "Turn 2 (latest)\n  action: a2\n  result: r2\n  note: n2"
        ),
    }
    assert "R-999" not in json.dumps(state)


@pytest.mark.parametrize(
    ("choice", "confidence", "changes", "expected"),
    [
        ("advancing", 0.5, 0, ("continue", "confident advancing")),
        ("complete", 0.5, 0, ("stop", "task complete")),
        ("regressing", 0.5, 0, ("stop", "regressing: progress was lost")),
        ("repeating", 0.5, 0, ("change_strategy", "repeating: change strategy")),
        ("repeating", 0.5, 1, ("stop", "still repeating after a strategy change")),
        ("unclear", 0.5, 0, ("review", "progress unclear from the turns shown")),
        ("advancing", 0.49, 0, ("review", "confidence below the threshold")),
        ("complete", 0.49, 0, ("review", "confidence below the threshold")),
        ("repeating", 0.49, 1, ("review", "confidence below the threshold")),
        ("unclear", 0.49, 0, ("review", "confidence below the threshold")),
    ],
)
def test_the_decision_table(choice, confidence, changes, expected):
    assert helpers.transition(choice, confidence, 0.5, changes, 3) == expected


@pytest.mark.parametrize(
    ("choice", "confidence", "changes", "expected"),
    [
        ("advancing", 0.9, 0, ("stop", "turn budget reached")),
        ("advancing", 0.1, 0, ("stop", "turn budget reached")),
        ("unclear", 0.9, 0, ("stop", "turn budget reached")),
        ("repeating", 0.9, 0, ("stop", "repeating at the turn budget")),
        ("repeating", 0.1, 0, ("stop", "turn budget reached")),
        ("complete", 0.1, 0, ("stop", "turn budget reached")),
        ("complete", 0.9, 0, ("stop", "task complete")),
        ("regressing", 0.9, 0, ("stop", "regressing: progress was lost")),
        ("repeating", 0.9, 1, ("stop", "still repeating after a strategy change")),
    ],
)
@pytest.mark.parametrize("turn", [8, 9])
def test_the_budget_turn_is_part_of_the_table(choice, confidence, changes, expected, turn):
    """At the budget turn the run stops whatever the answer, below-threshold answers included."""
    assert helpers.MAX_TURNS == 8
    assert helpers.transition(choice, confidence, 0.5, changes, turn) == expected


def test_an_unknown_label_is_an_error():
    with pytest.raises(ValueError, match="unknown progress label"):
        helpers.transition("stuck", 1.0, 0.5, 0, 3)


def test_the_gate_is_inclusive_and_bounded():
    assert helpers.transition("advancing", 0.5, 0.5, 0, 3)[0] == "continue"
    assert helpers.transition("advancing", 0.5 - 1e-9, 0.5, 0, 3)[0] == "review"
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="between 0 and 1"):
            helpers.transition("advancing", 0.5, bad, 0, 3)


def test_a_confident_unclear_is_never_answered():
    assert not helpers.checkpoint_answered(answer("unclear", 0.96), 0.0, 3)
    assert helpers.checkpoint_answered(answer("advancing", 0.96), 0.0, 3)


@pytest.mark.parametrize("choice", LABELS)
@pytest.mark.parametrize("top", [0.3, 0.84])
@pytest.mark.parametrize("turn", [3, 7, 8])
def test_checkpoint_answered_agrees_with_what_the_run_does(choice, top, turn):
    """A checkpoint counts as answered exactly when the run neither queues it nor stops it for
    the budget alone: at the budget turn the budget decides unless the label stops the run for
    its own reason."""
    a = answer(choice, top)
    queue, actions = ReviewQueue(), ActionLog()
    helpers.supervise("R", [(turn, a)], 0.5, queue=queue, actions=actions)
    rules = [e["rule"] for e in actions.to_dicts()]
    assert helpers.checkpoint_answered(a, 0.5, turn) == (
        len(queue) == 0 and "turn budget reached" not in rules
    )
    if turn == helpers.MAX_TURNS:
        assert len(queue) == 0
        assert len(actions) == 1


def test_a_checkpoint_the_turn_budget_decides_is_not_answered():
    """Below the gate, or a confident advancing, at the budget turn: stopped by the budget, so
    the model's label decided nothing. A confident stop of its own is answered."""
    for choice, top in (
        ("advancing", 0.84),
        ("advancing", 0.3),
        ("unclear", 0.84),
        ("complete", 0.3),
    ):
        assert not helpers.checkpoint_answered(answer(choice, top), 0.5, helpers.MAX_TURNS)
    for choice in ("complete", "regressing", "repeating"):
        assert helpers.checkpoint_answered(answer(choice, 0.84), 0.5, helpers.MAX_TURNS)


@pytest.mark.parametrize(
    "turns",
    [(2,), (2, 3), (2, 3, 4), (2, 3, 4, 5), (5, 6, 7, 8), (7, 9), (8, 9), (6, 8, 10), (7, 8, 9)],
)
def test_the_policy_holds_for_every_answer_sequence(turns):
    """Every sequence of labels and gate results over the given checkpoint turns, including
    turns past the budget: the run never takes a checkpoint after the budget turn, changes strategy at most once,
    never queues or acts on an answer except by the table, stops at the first stop and nowhere
    else, and at the budget turn stops whatever the answer and the gate said."""
    for labels in itertools.product(LABELS, repeat=len(turns)):
        for gates in itertools.product((True, False), repeat=len(turns)):
            confidences = [0.9 if cleared else 0.1 for cleared in gates]
            run = helpers._run("R", list(zip(turns, labels, confidences, strict=True)), 0.5)
            decisions = [s.decision for s in run.steps]
            # The first checkpoint at or past the budget turn is the last one the run takes (a
            # sequence may skip the budget turn itself, as (7, 9) does), and it is a stop.
            assert all(s.turn < helpers.MAX_TURNS for s in run.steps[:-1])
            assert decisions.count("change_strategy") <= helpers.MAX_STRATEGY_CHANGES
            assert decisions.count("stop") <= 1
            if "stop" in decisions:
                assert decisions[-1] == "stop"
                assert run.stopped_at == run.steps[-1].turn
            if any(t >= helpers.MAX_TURNS for t in turns):
                assert run.stopped_at is not None  # the budget always ends the run
            for step, cleared in zip(run.steps, gates, strict=False):
                if step.turn >= helpers.MAX_TURNS:
                    assert step.decision == "stop"
                elif not cleared:
                    assert step.decision == "review"
                    assert step.reason == "confidence below the threshold"


def test_the_turn_budget_stops_whatever_the_answer():
    turns = list(range(2, helpers.MAX_TURNS + 1))
    for last in LABELS:
        for cleared in (True, False):
            labels = ["advancing"] * (len(turns) - 1) + [last]
            confidences = [0.9] * (len(turns) - 1) + [0.9 if cleared else 0.1]
            run = helpers._run("R", list(zip(turns, labels, confidences, strict=True)), 0.5)
            assert run.stopped_at == helpers.MAX_TURNS
            if last in ("complete", "regressing") and cleared:
                assert run.stop_reason not in (
                    "turn budget reached",
                    "repeating at the turn budget",
                )
            elif last == "repeating" and cleared:
                assert run.stop_reason == "repeating at the turn budget"
            else:
                assert run.stop_reason == "turn budget reached"


def test_a_below_threshold_answer_at_the_budget_turn_is_stopped_not_queued():
    queue, actions = ReviewQueue(), ActionLog()
    answers = [(7, answer("advancing", 0.84)), (8, answer("complete", 0.30))]
    run = helpers.supervise("R", answers, 0.5, queue=queue, actions=actions)
    assert (run.stopped_at, run.stop_reason) == (8, "turn budget reached")
    assert len(queue) == 0
    assert [(e["kind"], e["step"], e["rule"]) for e in actions.to_dicts()] == [
        ("stop", 8, "turn budget reached")
    ]


@pytest.mark.parametrize("label", ["repeating", "regressing"])
def test_a_gold_stall_at_the_budget_turn_is_detected_with_delay_zero(label):
    gold = [(7, "advancing"), (8, label)]
    onset = helpers.stall_onset(gold)
    assert onset == helpers.MAX_TURNS
    found = helpers.detection(helpers.label_run("R", gold), onset)
    assert (found.outcome, found.delay) == ("detected", 0)


def test_a_confident_stall_answer_at_the_budget_turn_counts_for_detection():
    queue, actions = ReviewQueue(), ActionLog()
    answers = [(7, answer("advancing", 0.84)), (8, answer("repeating", 0.84))]
    run = helpers.supervise("R", answers, 0.5, queue=queue, actions=actions)
    assert (run.stopped_at, run.stop_reason) == (8, "repeating at the turn budget")
    assert [(e["kind"], e["step"], e["rule"]) for e in actions.to_dicts()] == [
        ("stop", 8, "repeating at the turn budget")
    ]
    assert run.first_stall_intervention == 8
    assert helpers.detection(run, 8).outcome == "detected"
    # A confident regressing keeps its own stall reason; an advancing one is only the budget.
    regress = helpers.supervise(
        "R",
        [(7, answer("advancing")), (8, answer("regressing", 0.84))],
        0.5,
        queue=ReviewQueue(),
        actions=ActionLog(),
    )
    assert (regress.stop_reason, regress.first_stall_intervention) == (
        "regressing: progress was lost",
        8,
    )
    calm = helpers.supervise(
        "R",
        [(7, answer("advancing")), (8, answer("advancing", 0.84))],
        0.5,
        queue=ReviewQueue(),
        actions=ActionLog(),
    )
    assert (calm.stop_reason, calm.first_stall_intervention) == ("turn budget reached", None)
    # A below-threshold repeat at the budget turn is stopped but is not a stall intervention.
    weak = helpers.supervise(
        "R",
        [(7, answer("advancing")), (8, answer("repeating", 0.3))],
        0.5,
        queue=ReviewQueue(),
        actions=ActionLog(),
    )
    assert weak.first_stall_intervention is None
    assert helpers.detection(weak, 8).outcome == "missed"


def test_checkpoints_must_come_in_turn_order():
    with pytest.raises(ValueError, match="increasing turn order"):
        helpers.label_run("R", [(3, "advancing"), (2, "advancing")])


def test_supervise_writes_exactly_what_the_policy_did():
    """Literals typed from a hand-built sequence, not derived from the function."""
    queue, actions = ReviewQueue(), ActionLog()
    answers = [
        (2, answer("advancing", 0.84)),
        (3, answer("repeating", 0.36)),
        (4, answer("unclear", 0.84)),
        (5, answer("repeating", 0.84)),
        (6, answer("repeating", 0.84)),
        (7, answer("complete", 0.84)),
    ]
    run = helpers.supervise("R-1", answers, 0.5, queue=queue, actions=actions)
    assert [(s.turn, s.decision) for s in run.steps] == [
        (2, "continue"),
        (3, "review"),
        (4, "review"),
        (5, "change_strategy"),
        (6, "stop"),
    ]
    assert run.stopped_at == 6
    assert run.stop_reason == "still repeating after a strategy change"
    assert run.first_stall_intervention == 5
    assert [(i["id"], i["item"]["turn"], i["reason"]) for i in queue.to_dicts()] == [
        (0, 3, "confidence below the threshold"),
        (1, 4, "progress unclear from the turns shown"),
    ]
    assert [(e["kind"], e["step"], e["rule"], e["executed"]) for e in actions.to_dicts()] == [
        ("change_strategy", 5, "repeating: change strategy", False),
        ("stop", 6, "still repeating after a strategy change", False),
    ]


def _action_rows(actions):
    return [
        (e["kind"], e["payload"]["transcript"], e["step"], e["payload"]["choice"], e["rule"])
        for e in actions.to_dicts()
    ]


def _queue_rows(queue):
    return [
        (i["item"]["transcript"], i["item"]["turn"], i["item"]["choice"], i["reason"])
        for i in queue.to_dicts()
    ]


def _fixture_runs(split, threshold):
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    by_ref = {}
    for example in load_inputs(RECIPE):
        if example.split == split:
            by_ref.setdefault(example.fields["transcript"], []).append(example)
    queue, actions = ReviewQueue(), ActionLog()
    runs = {}
    for ref, group in by_ref.items():
        group.sort(key=lambda e: e.fields["turn"])
        answers = [
            (e.fields["turn"], backend.decide(helpers.build_state(e.fields), questions)["progress"])
            for e in group
        ]
        runs[ref] = helpers.supervise(ref, answers, threshold, queue=queue, actions=actions)
    return by_ref, runs, queue, actions


def test_the_test_split_supervision_on_the_committed_fixtures():
    """What the notebook's test split produces at the frozen threshold, typed from the fixtures."""
    by_ref, runs, queue, actions = _fixture_runs("test", frozen_threshold())
    assert {ref: (r.stopped_at, r.stop_reason) for ref, r in runs.items()} == {
        "R-201": (4, "task complete"),
        "R-202": (3, "still repeating after a strategy change"),
        "R-203": (6, "task complete"),
        "R-204": (3, "regressing: progress was lost"),
        "R-205": (5, "task complete"),
        "R-206": (5, "task complete"),
    }
    labels = load_labels(RECIPE)
    found = {
        ref: helpers.detection(
            runs[ref], helpers.stall_onset([(e.fields["turn"], labels[e.id]) for e in group])
        )
        for ref, group in by_ref.items()
    }
    assert {ref: (d.outcome, d.delay) for ref, d in found.items()} == {
        "R-201": ("no stall", None),
        "R-202": ("detected", 0),
        "R-203": ("detected", 1),
        "R-204": ("detected", 0),
        "R-205": ("no stall", None),
        "R-206": ("missed", None),
    }
    assert _action_rows(actions) == [
        ("stop", "R-201", 4, "complete", "task complete"),
        ("change_strategy", "R-202", 2, "repeating", "repeating: change strategy"),
        ("stop", "R-202", 3, "repeating", "still repeating after a strategy change"),
        ("change_strategy", "R-203", 5, "repeating", "repeating: change strategy"),
        ("stop", "R-203", 6, "complete", "task complete"),
        ("stop", "R-204", 3, "regressing", "regressing: progress was lost"),
        ("stop", "R-205", 5, "complete", "task complete"),
        ("stop", "R-206", 5, "complete", "task complete"),
    ]
    assert _queue_rows(queue) == [
        ("R-205", 3, "complete", "confidence below the threshold"),
        ("R-206", 2, "unclear", "progress unclear from the turns shown"),
        ("R-206", 3, "repeating", "confidence below the threshold"),
        ("R-206", 4, "repeating", "confidence below the threshold"),
    ]
    assert all(not e["executed"] for e in actions.to_dicts())


def test_the_validation_split_supervision_on_the_committed_fixtures():
    """The validation split, the only fixture path through the turn budget stop."""
    _, runs, queue, actions = _fixture_runs("validation", frozen_threshold())
    assert {ref: (r.stopped_at, r.stop_reason) for ref, r in runs.items()} == {
        "R-101": (7, "task complete"),
        "R-102": (3, "still repeating after a strategy change"),
        "R-103": (6, "task complete"),
        "R-104": (5, "regressing: progress was lost"),
        "R-105": (5, "task complete"),
        "R-106": (8, "turn budget reached"),
    }
    assert _action_rows(actions) == [
        ("stop", "R-101", 7, "complete", "task complete"),
        ("change_strategy", "R-102", 2, "repeating", "repeating: change strategy"),
        ("stop", "R-102", 3, "repeating", "still repeating after a strategy change"),
        ("change_strategy", "R-103", 5, "repeating", "repeating: change strategy"),
        ("stop", "R-103", 6, "complete", "task complete"),
        ("stop", "R-104", 5, "regressing", "regressing: progress was lost"),
        ("change_strategy", "R-105", 2, "repeating", "repeating: change strategy"),
        ("stop", "R-105", 5, "complete", "task complete"),
        ("stop", "R-106", 8, "complete", "turn budget reached"),
    ]
    assert _queue_rows(queue) == [
        ("R-103", 4, "advancing", "confidence below the threshold"),
        ("R-104", 4, "complete", "confidence below the threshold"),
        ("R-106", 4, "repeating", "confidence below the threshold"),
        ("R-106", 5, "unclear", "progress unclear from the turns shown"),
    ]


def test_detection_outcomes():
    run = helpers.label_run("R", [(2, "advancing"), (3, "repeating"), (4, "repeating")])
    assert helpers.detection(run, 3).outcome == "detected"
    assert helpers.detection(run, 3).delay == 0
    assert helpers.detection(run, 4).outcome == "early"
    assert helpers.detection(run, None).outcome == "early"
    quiet = helpers.label_run("R", [(2, "advancing"), (3, "complete")])
    assert helpers.detection(quiet, 2).outcome == "missed"
    assert helpers.detection(quiet, None).outcome == "no stall"


def test_the_stall_onset_is_the_first_stall_label():
    assert helpers.stall_onset([(2, "advancing"), (3, "regressing"), (4, "repeating")]) == 3
    assert helpers.stall_onset([(2, "advancing"), (3, "unclear")]) is None


def test_the_exact_repeat_baseline_needs_action_and_result_identical():
    a = {"action": "x", "result": "y", "note": "first"}
    same = {"action": "x", "result": "y", "note": "different note"}
    reworded = {"action": "x --again", "result": "y", "note": ""}
    assert helpers.exact_repeat_baseline([a, same]) == "repeating"
    assert helpers.exact_repeat_baseline([a, reworded]) == "advancing"


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)


def test_every_checkpoint_shows_exactly_the_turns_up_to_it():
    for example in load_inputs(RECIPE):
        assert len(example.fields["turns"]) == example.fields["turn"] >= 2


def _validation_pool():
    """``(correct, confidence, turn)`` lists for the validation answers that name an actionable
    label (``helpers.choose_threshold`` drops the ones at or after the budget turn)."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    pool = []
    for e in load_inputs(RECIPE):
        if e.split != "validation":
            continue
        a = backend.decide(helpers.build_state(e.fields), questions)["progress"]
        if a.choice != "unclear":
            pool.append((a.choice == labels[e.id], a.confidence, e.fields["turn"]))
    return [ok for ok, _, _ in pool], [c for _, c, _ in pool], [t for _, _, t in pool]


def frozen_threshold():
    """The frozen gate, derived through the one helper (``helpers.choose_threshold``)."""
    return helpers.choose_threshold(*_validation_pool())


def test_the_threshold_selection_ignores_checkpoints_at_the_budget_turn():
    """The gate has no effect at the budget turn, so a confident wrong answer there cannot raise
    it; the same answer before the budget turn does."""
    correct, confidences = [True, False, True], [0.9, 0.3, 0.6]
    assert helpers.choose_threshold(correct, confidences, [2, 3, 4]) == pytest.approx(0.6)
    low = helpers.choose_threshold([True, True, False], [0.9, 0.6, 0.8], [2, 3, helpers.MAX_TURNS])
    assert low == pytest.approx(0.6)
    high = helpers.choose_threshold([True, True, False], [0.9, 0.6, 0.8], [2, 3, 4])
    assert high > 0.8
    with pytest.raises(ValueError, match="same length"):
        helpers.choose_threshold([True], [0.9], [2, 3])


def test_the_validation_answered_counts_and_the_forced_values():
    """What the notebook prints for ``validation``: 24 of 29 checkpoints answered (coverage
    0.8276). The one checkpoint at the budget turn (v-table-migration-t8, stored answer
    ``complete`` at 0.30, gold ``advancing``) is decided by the budget, so the model did not
    answer it; every other answered checkpoint is before the budget turn and cleared the
    frozen gate, which was chosen so that each such answer is right. So accuracy among the
    answered is 1.0 and risk 0.0 on validation, forced by that selection."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    threshold = frozen_threshold()
    examples = [e for e in load_inputs(RECIPE) if e.split == "validation"]
    answers = [
        backend.decide(helpers.build_state(e.fields), questions)["progress"] for e in examples
    ]
    took = [
        helpers.checkpoint_answered(a, threshold, e.fields["turn"])
        for a, e in zip(answers, examples, strict=True)
    ]
    right = [a.choice == labels[e.id] for a, e in zip(answers, examples, strict=True)]
    result = evaluate_outcomes(took, right)
    assert (result.n_answered, result.n_total) == (24, 29)
    assert f"{result.coverage:.4f}" == "0.8276"
    assert (result.accuracy, result.risk) == (1.0, 0.0)
    at_budget = [e.id for e in examples if e.fields["turn"] >= helpers.MAX_TURNS]
    assert at_budget == ["v-table-migration-t8"]
    assert not any(t for t, e in zip(took, examples, strict=True) if e.id in at_budget)


def test_stored_answers_are_not_all_right():
    """Using the frozen threshold, exactly one `test` answer is wrong and still clears the gate:
    the single mistake the notebook's prose says the gate lets through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    threshold = helpers.choose_threshold(*_validation_pool())
    wrong_and_confident = []
    for e in load_inputs(RECIPE):
        if e.split != "test":
            continue
        a = backend.decide(helpers.build_state(e.fields), questions)["progress"]
        if a.choice != labels[e.id] and a.confidence >= threshold:
            wrong_and_confident.append(e.id)
    assert wrong_and_confident == ["t-retry-search-t4"]


def test_the_notebooks_own_selection_agrees_with_the_helper():
    """The notebook calls select_confidence_threshold by name; its committed output must name the
    same threshold this file derives through ``frozen_threshold``."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    printed = "".join(
        "".join(o.get("text", "")) for o in cell["outputs"] if o.get("output_type") == "stream"
    )
    assert f"chosen threshold, frozen from here on: {frozen_threshold():.4f}" in printed


def test_the_notebook_selects_the_threshold_by_target_accuracy_not_min_coverage():
    """Pins the objective against the committed cell source, not only the value it lands on."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "python-rule")
    source = "".join(cell["source"])
    assert "target_accuracy=1.0" in source
    assert "min_coverage" not in source


def test_the_quantities_the_prose_states():
    """The README and notebook say one strategy change is allowed, a confident stall that
    follows it stops the run, five options exist and four of them are actionable. Pin each."""
    assert helpers.MAX_STRATEGY_CHANGES == 1
    assert len(helpers.OPTIONS) == 5
    assert [name for name in helpers.OPTIONS if name != helpers.UNCLEAR] == [
        "advancing",
        "repeating",
        "regressing",
        "complete",
    ]
