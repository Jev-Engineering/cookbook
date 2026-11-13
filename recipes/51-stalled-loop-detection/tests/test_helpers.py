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
from jev_cookbook.evaluation import select_confidence_threshold
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
    assert helpers.transition(choice, confidence, 0.5, changes) == expected


def test_an_unknown_label_is_an_error():
    with pytest.raises(ValueError, match="unknown progress label"):
        helpers.transition("stuck", 1.0, 0.5, 0)


def test_the_gate_is_inclusive_and_bounded():
    assert helpers.transition("advancing", 0.5, 0.5, 0)[0] == "continue"
    assert helpers.transition("advancing", 0.5 - 1e-9, 0.5, 0)[0] == "review"
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="between 0 and 1"):
            helpers.transition("advancing", 0.5, bad, 0)


def test_a_confident_unclear_is_never_answered():
    assert not helpers.checkpoint_answered(answer("unclear", 0.96), 0.0)
    assert helpers.checkpoint_answered(answer("advancing", 0.96), 0.0)


@pytest.mark.parametrize(("length", "first"), [(1, 2), (2, 2), (3, 2), (4, 2), (4, 5)])
def test_the_policy_holds_for_every_answer_sequence(length, first):
    """Every sequence of labels and gate results over ``length`` checkpoints from turn
    ``first`` (the last case reaches the turn budget): the run never passes the budget,
    changes strategy at most once, never acts on an answer that did not clear the gate before
    the budget turn, and stops at the first stop and nowhere else."""
    turns = list(range(first, first + length))
    for labels in itertools.product(LABELS, repeat=length):
        for gates in itertools.product((True, False), repeat=length):
            confidences = [0.9 if cleared else 0.1 for cleared in gates]
            run = helpers._run("R", list(zip(turns, labels, confidences, strict=True)), 0.5)
            decisions = [s.decision for s in run.steps]
            assert all(s.turn <= helpers.MAX_TURNS for s in run.steps)
            assert decisions.count("change_strategy") <= helpers.MAX_STRATEGY_CHANGES
            assert decisions.count("stop") <= 1
            if "stop" in decisions:
                assert decisions[-1] == "stop"
                assert run.stopped_at == run.steps[-1].turn
            for step, cleared in zip(run.steps, gates, strict=False):
                if not cleared and step.turn < helpers.MAX_TURNS:
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
                assert run.stop_reason != "turn budget reached"
            else:
                assert run.stop_reason == "turn budget reached"


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
    assert [
        (i["item"]["transcript"], i["item"]["turn"], i["reason"]) for i in queue.to_dicts()
    ] == [
        ("R-205", 3, "confidence below the threshold"),
        ("R-206", 2, "progress unclear from the turns shown"),
        ("R-206", 3, "confidence below the threshold"),
        ("R-206", 4, "confidence below the threshold"),
    ]
    assert len(actions) == 8


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


def frozen_threshold():
    """The notebook's selection: validation answers that do not name ``unclear``."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    pool = []
    for e in load_inputs(RECIPE):
        if e.split != "validation":
            continue
        a = backend.decide(helpers.build_state(e.fields), questions)["progress"]
        if a.choice != "unclear":
            pool.append((a.choice == labels[e.id], a.confidence))
    return select_confidence_threshold(
        [ok for ok, _ in pool], [c for _, c in pool], target_accuracy=1.0
    )


def test_stored_answers_are_not_all_right():
    """Re-derive the threshold the way the notebook does and require a wrong `test` answer at
    or above it: a mistake the gate would still let through."""
    backend = get_backend(fixtures=responses_path(RECIPE))
    questions = helpers.build_questions()
    labels = load_labels(RECIPE)
    validation = [e for e in load_inputs(RECIPE) if e.split == "validation"]
    named = []
    for e in validation:
        a = backend.decide(helpers.build_state(e.fields), questions)["progress"]
        if a.choice != "unclear":
            named.append((a.choice == labels[e.id], a.confidence))
    threshold = select_confidence_threshold(
        [ok for ok, _ in named], [c for _, c in named], target_accuracy=1.0
    )
    wrong_and_confident = []
    for e in load_inputs(RECIPE):
        if e.split != "test":
            continue
        a = backend.decide(helpers.build_state(e.fields), questions)["progress"]
        if a.choice != labels[e.id] and a.confidence >= threshold:
            wrong_and_confident.append(e.id)
    assert wrong_and_confident, "expected at least one confidently wrong test answer"


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
