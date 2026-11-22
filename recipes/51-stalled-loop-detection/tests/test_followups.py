"""Regression cases for ended stalls, budget review and pre-write validation."""

import ast
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers
from jev_cookbook.evaluation import accuracy
from jev_cookbook.fixtures import load_inputs
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def answer(choice, confident=True):
    top = 0.84 if confident else 0.36
    probabilities = {
        label: (top if label == choice else (1 - top) / 4) for label in helpers.OPTIONS
    }
    return ChoiceAnswer.from_probabilities(probabilities, Provenance.synthetic())


@pytest.mark.parametrize("stall", ["repeating", "regressing"])
def test_an_intervention_after_a_stall_ended_is_a_miss_and_false_alarm(stall):
    gold = [(2, stall)] + [(turn, "advancing") for turn in range(3, 8)]
    run = helpers.label_run("late", [(turn, "advancing") for turn in range(2, 7)] + [(7, stall)])
    found = helpers.detection(run, gold)
    assert (found.onset, found.intervened, found.outcome, found.delay, found.false_alarm) == (
        2,
        None,
        "missed",
        None,
        7,
    )


def test_a_false_alarm_between_stalls_does_not_hide_a_later_detection():
    gold = [(2, "repeating"), (3, "advancing"), (4, "regressing")]
    run = helpers.label_run("resumed", [(2, "advancing"), (3, "repeating"), (4, "regressing")])
    found = helpers.detection(run, gold)
    assert (found.onset, found.intervened, found.outcome, found.delay, found.false_alarm) == (
        2,
        4,
        "detected",
        2,
        3,
    )


@pytest.mark.parametrize("turn", [helpers.MAX_TURNS, helpers.MAX_TURNS + 1])
@pytest.mark.parametrize("choice", helpers.OPTIONS)
@pytest.mark.parametrize("confident", [False, True])
def test_budget_stop_keeps_review_and_never_consumes_later_checkpoint(turn, choice, confident):
    queue, actions = ReviewQueue(), ActionLog()
    last = answer(choice, confident)
    answers = [(t, answer("advancing")) for t in range(2, helpers.MAX_TURNS)]
    answers += [(turn, last), (turn + 1, answer("repeating"))]
    run = helpers.supervise("budget", answers, 0.5, queue=queue, actions=actions)
    assert run.stopped_at == turn
    assert [step.turn for step in run.steps] == list(range(2, helpers.MAX_TURNS)) + [turn]
    needs_review = not confident or choice == "unclear"
    assert len(queue) == int(needs_review)
    assert len(actions) == 1
    entry = actions.to_dicts()[0]
    assert (entry["kind"], entry["step"], entry["executed"]) == ("stop", turn, False)
    if needs_review:
        review = queue.to_dicts()[0]
        assert review["reason"] == (
            "progress unclear from the turns shown"
            if confident
            else "confidence below the threshold"
        )
        assert (review["step"], review["item"]["choice"]) == (turn, choice)
        assert review["answer"] == entry["answer"] == last.to_dict()
        assert entry["rule"] == "turn budget reached"


@pytest.mark.parametrize(
    "bad",
    [
        SimpleNamespace(choice="invalid", confidence=0.8),
        SimpleNamespace(choice="advancing", confidence=None),
    ],
)
def test_a_later_checkpoint_failure_leaves_existing_sinks_unchanged(bad):
    queue, actions = ReviewQueue(), ActionLog()
    queue.submit({"existing": True}, "already pending")
    actions.record("existing", {"saved": True})
    before = queue.to_dicts(), actions.to_dicts()
    answers = [(2, answer("unclear")), (3, answer("repeating")), (4, bad)]
    with pytest.raises((ValueError, TypeError)):
        helpers.supervise("invalid", answers, 0.5, queue=queue, actions=actions)
    assert (queue.to_dicts(), actions.to_dicts()) == before


def test_the_test_fixture_has_a_full_transcript_at_the_budget():
    checkpoints = [e for e in load_inputs(RECIPE) if e.fields["transcript"] == "R-207"]
    assert all(e.split == "test" for e in checkpoints)
    assert [e.fields["turn"] for e in checkpoints] == list(range(2, helpers.MAX_TURNS + 1))
    assert len(checkpoints[-1].fields["turns"]) == helpers.MAX_TURNS


def test_baseline_report_uses_its_gold_parameter_even_when_global_labels_disagree(capsys):
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text())
    cell = next(c for c in notebook["cells"] if c["id"] == "evaluation-baseline")
    function = next(
        n for n in ast.parse("".join(cell["source"])).body if isinstance(n, ast.FunctionDef)
    )
    scope = {
        "helpers": helpers,
        "accuracy": accuracy,
        "Counter": Counter,
        "labels": {"c2": "advancing"},
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), "baseline_report", "exec"), scope)
    turn = {"action": "inspect", "result": "no matches", "note": ""}
    example = SimpleNamespace(id="c2", fields={"turn": 2, "turns": [turn, turn]})
    found = scope["baseline_report"]("probe", [example], {"R": [example]}, ["repeating"], "")
    assert (found[0].onset, found[0].outcome, found[0].delay) == (2, "detected", 0)
    assert "baseline label accuracy 1.0000" in capsys.readouterr().out


@pytest.mark.parametrize("lengths", [(1, 0, 1), (1, 2, 1), (1, 1, 0), (1, 1, 2)])
def test_threshold_pool_strict_zip_rejects_each_misaligned_input(lengths):
    n_answers, n_gold, n_turns = lengths
    with pytest.raises(ValueError, match="zip"):
        helpers.threshold_pool(
            [answer("advancing")] * n_answers, ["advancing"] * n_gold, [2] * n_turns
        )
