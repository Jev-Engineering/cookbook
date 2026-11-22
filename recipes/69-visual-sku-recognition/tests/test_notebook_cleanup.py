"""Selected-cell unit tests; these do not execute or refresh a Jupyter notebook."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, load_helpers
from jev_cookbook.evaluation import accuracy, evaluate_outcomes
from jev_cookbook.fixtures import load_inputs, load_labels, select_split
from jev_cookbook.simulation import ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def run_cell(cell_id, namespace):
    cells = json.loads((RECIPE / "notebook.ipynb").read_text(encoding="utf-8"))["cells"]
    source = next("".join(c["source"]) for c in cells if c["id"] == cell_id)
    exec(compile(source, cell_id, "exec"), namespace)


def certain_answer(choice):
    return ChoiceAnswer.from_probabilities(
        {option: float(option == choice) for option in helpers.OPTIONS}, Provenance.synthetic()
    )


def test_profile_uses_asset_keys_and_reports_per_request_maximum_and_sum(capsys):
    examples = [SimpleNamespace(id=str(i), fields={"index": i}) for i in range(2)]
    # The values deliberately hold no base64: distinct-file identity comes from keys alone.
    assets_by_request = [{"shared": object(), "first": object()}, {"shared": object()}]
    profiles = [
        SimpleNamespace(
            copies=3,
            distinct_assets=2,
            distinct_bytes=7,
            expanded_bytes=11,
            state_copies=1,
            per_question={"sku": 2},
        ),
        SimpleNamespace(
            copies=2,
            distinct_assets=1,
            distinct_bytes=5,
            expanded_bytes=10,
            state_copies=1,
            per_question={"sku": 1},
        ),
    ]
    built, checked = [], []

    def build_request(fields):
        index = fields["index"]
        built.append(index)
        return {"index": index}, assets_by_request[index]

    def profile(state, _questions, assets):
        assert assets is assets_by_request[state["index"]]
        return profiles[state["index"]]

    namespace = {
        "examples": examples,
        "state": {"index": 0},
        "assets": assets_by_request[0],
        "questions": object(),
        "helpers": SimpleNamespace(build_request=build_request),
        "hashlib": hashlib,
        "image_request_profile": profile,
        "preflight_image_request": checked.append,
    }
    run_cell("copies", namespace)
    output = capsys.readouterr().out
    assert built == [0, 1]
    assert checked == [profiles[0], profiles[0], profiles[1]]
    assert namespace["files"] == {"shared", "first"}
    assert "5 image copies" in output
    assert "distinct images summed over the requests: 3" in output
    assert "Per-request file bytes: distinct max 7, sum 12; expanded max 11, sum 21" in output
    assert "Different image files across all requests: 2" in output


def test_hard_case_sheet_includes_every_ambiguous_query_and_accurate_captions(capsys):
    sheets = []
    namespace = {
        "examples": load_inputs(RECIPE),
        "labels": load_labels(RECIPE),
        "helpers": SimpleNamespace(
            CATALOG=helpers.CATALOG,
            contact_sheet=lambda items: sheets.append(items) or b"",
        ),
        "Image": lambda **kwargs: kwargs,
        "display": lambda _image: None,
    }
    run_cell("hard", namespace)
    output = capsys.readouterr().out
    assert [path for _label, path in sheets[2]] == [
        f"assets/query-{ident}.png" for ident in ("v12", "v13", "t13", "t14", "v14", "t15")
    ]
    assert "on DEGUM (v12, t13) and on BIVEN (v13, t14)" in output
    assert "shift-only studio query v01, followed by shelf, far and dim queries" in output


def test_queue_cell_performs_the_declared_side_effect_without_an_unused_result():
    outcome = helpers.decide_sku("Q-unit", certain_answer("DEGUM"), None)
    namespace = {
        "helpers": helpers,
        "ReviewQueue": ReviewQueue,
        "test_outcomes": [outcome],
        "reportable": False,
    }
    run_cell("queue", namespace)
    assert "routed" not in namespace
    assert [item.item for item in namespace["review_queue"].pending()] == [
        {"capture": "Q-unit", "model_choice": "DEGUM"}
    ]


@pytest.mark.parametrize("validation_choice", ["all_wrong", "uncertain"])
def test_infeasible_validation_reports_review_only_and_scores_test_without_deliveries(
    validation_choice,
    capsys,
):
    examples, labels = load_inputs(RECIPE), load_labels(RECIPE)
    builds, calls = [], []

    def build_request(fields):
        builds.append(fields["capture"])
        return {"capture": fields["capture"]}, {}

    def decide(state, _questions, *, assets):
        assert assets == {}
        capture = state["capture"]
        calls.append(capture)
        example = next(e for e in examples if e.fields["capture"] == capture)
        # Every validation prediction is wrong, including the maximum confidence boundary.
        choice = validation_choice if example.split == "validation" else "no_match"
        if choice == "all_wrong":
            choice = "BIVEN" if labels[example.id] == "DEGUM" else "DEGUM"
            assert choice != labels[example.id]
        answer = certain_answer(choice)
        assert answer.confidence == 1.0
        return {"sku": answer}

    namespace = {
        "examples": examples,
        "labels": labels,
        "select_split": select_split,
        "helpers": SimpleNamespace(
            build_request=build_request,
            choose_threshold=helpers.choose_threshold,
            decide_sku=helpers.decide_sku,
            queue_reviews=helpers.queue_reviews,
            CATALOG=helpers.CATALOG,
            ANSWERED=helpers.ANSWERED,
            REVIEW=helpers.REVIEW,
            NO_MATCH=helpers.NO_MATCH,
        ),
        "backend": SimpleNamespace(decide=decide, mode="synthetic"),
        "questions": {},
        "reportable": True,
        "selection": " (a selection step, not a reported result)",
        "check": " (a pipeline check, not a Jev result)",
        "Counter": Counter,
        "accuracy": accuracy,
        "evaluate_outcomes": evaluate_outcomes,
        "ReviewQueue": ReviewQueue,
        "example": examples[-1],
        "answer": certain_answer("DEGUM"),
    }
    run_cell("python-rule", namespace)
    calibration_output = capsys.readouterr().out
    assert namespace["threshold"] is None
    assert namespace["frozen_policy"] == "review only"
    explanation = (
        "No confidence threshold reaches the requested validation accuracy"
        if validation_choice == "all_wrong"
        else "No validation answers are eligible for delivery"
    )
    assert f"{explanation}; all answers go to review" in calibration_output
    assert namespace["shown"].label is None
    run_cell("validation-table", namespace)
    run_cell("evaluation", namespace)
    run_cell("queue", namespace)
    assert len(builds) == len(calls) == 30
    assert (
        Counter(builds)
        == Counter(calls)
        == Counter(e.fields["capture"] for e in examples if e.split != "demo")
    )
    assert namespace["val_report"].n_answered == namespace["task"].n_answered == 0
    assert all(o.label is None for o in namespace["test_outcomes"])
    assert len(namespace["review_queue"].pending()) == 16
    assert "routed" not in namespace
    assert "accuracy among delivered n/a (N=0), risk n/a (N=0)" in capsys.readouterr().out
