"""The committed notebook's cells on paths the offline run does not take.

A live answer can send a named example (d01, t01) down another path, and a frozen threshold can
fail closed to an infinite sentinel. These tests run the committed code cells in order, offline,
in one namespace, override the state a live run could produce, and require the cells under test
to print what happened instead of stopping."""

import dataclasses
import json
import math
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent
_CELLS = [
    c for c in json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))["cells"]
    if c["cell_type"] == "code"
]  # fmt: skip
SOURCE = {c["id"]: "".join(c["source"]) for c in _CELLS}
ORDER = [c["id"] for c in _CELLS]


def _exec(cell, ns):
    exec(compile(SOURCE[cell], f"<cell {cell}>", "exec"), ns)


@pytest.fixture
def notebook(monkeypatch):
    """Run the committed code cells in order, offline, from the recipe folder. ``run(last,
    before={cell: fn})`` stops after ``last`` and calls ``fn(ns)`` just before ``cell`` runs."""
    monkeypatch.chdir(RECIPE)
    monkeypatch.setenv("MPLBACKEND", "Agg")
    for name in ("JEV_COOKBOOK_LIVE", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    ns = {"__name__": "__notebook__"}

    def run(last, before=None):
        for cell in ORDER:
            if cell == "answer-plot":
                continue
            if before and cell in before:
                before[cell](ns)
            _exec(cell, ns)
            if cell == last:
                return ns
        raise AssertionError(f"no code cell {last}")

    return run


def _set_settings(**changes):
    """Replace frozen settings, and the notebook's ``frozen`` view of them, as a run whose
    validation answers froze these values would have them."""

    def apply(ns):
        ns["settings"] = dataclasses.replace(ns["settings"], **changes)
        if "frozen" in ns:
            ns["frozen"] = {name: getattr(ns["settings"], name) for name in ns["frozen"]}

    return apply


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


# --- the scoring cells on fail-closed thresholds and empty populations ---------------------


def test_the_validation_scoring_cell_prints_unfitted_thresholds_instead_of_stopping(
    notebook, capsys
):
    """freeze_stage_one fails closed to gate=inf and conflict=-inf, and freeze_stage_two to
    supported=ended=inf with no row reached; evaluate_threshold raises on both."""

    def fail_closed(ns):
        ns["settings"] = ns["helpers"].Settings(math.inf, -math.inf, math.inf, math.inf)
        ns["val_second"], ns["reached"] = {}, []

    notebook("evaluation-validation", before={"evaluation-validation": fail_closed})
    out = [line for line in _lines(capsys) if " F1 at its frozen threshold" in line]
    assert [line.split(" F1")[0] for line in out] == ["conflict", "supported", "ended"]
    assert all("not fitted" in line for line in out), out


def test_the_validation_scoring_cell_prints_an_empty_population(notebook, capsys):
    """A finite threshold over no rows: evaluate_threshold raises on empty input."""

    def nobody_reached(ns):
        ns["reached"] = []

    notebook("evaluation-validation", before={"evaluation-validation": nobody_reached})
    out = [line for line in _lines(capsys) if " F1 at its frozen threshold" in line]
    assert [("no rows" in line) for line in out] == [False, True, True], out


def test_the_test_noul_cell_prints_unfitted_thresholds_instead_of_stopping(notebook, capsys):
    """The same fail-closed settings, frozen before test is read: every test proposal goes to
    review, no test row gets request 2, and no t01 counterfactual exists."""
    fail_closed = _set_settings(gate=math.inf, conflict=-math.inf, supported=math.inf, ended=math.inf)  # fmt: skip
    notebook("evaluation-nouls", before={"evaluation-test-first": fail_closed})
    out = _lines(capsys)
    noul = [line for line in out if " test rows " in line]
    assert [line.split(" ")[0] for line in noul] == ["conflict", "supported", "ended"], noul
    assert len(noul) == 3 and all("not fitted" in line for line in noul), noul
    assert any(line.startswith("t01 ") and "no request 2" in line for line in out), out


# --- the conflict check is reported on the population it is fitted on ----------------------


def test_conflict_is_reported_on_the_rows_that_reach_the_conflict_check(notebook, capsys):
    ns = notebook("evaluation-nouls")
    helpers = ns["helpers"]
    val = helpers.conflict_rows(ns["val_examples"], ns["val_first"], ns["settings"].gate)
    test = helpers.conflict_rows(ns["test_examples"], ns["test_first"], ns["settings"].gate)
    assert [e.id for e in val] == [
        "v01", "v02-initial", "v04-unsupported", "v05-invariant", "v06-left-only",
        "v07-conflict", "v08", "v09-initial", "v10", "v11-invariant",
    ]  # fmt: skip
    assert [e.id for e in test] == [
        "t01", "t02-initial", "t03-left-only", "t04-invariant", "t05-unsupported",
        "t06-conflict", "t08-wrong-match", "t09", "t10-missed", "t11-conflict",
    ]  # fmt: skip
    out = _lines(capsys)
    assert any(
        line.startswith(
            "conflict F1 at its frozen threshold, 10 rows that reach the conflict check"
        )
        for line in out
    ), out
    assert any(
        line.startswith("conflict on 10 test rows that reach the conflict check") for line in out
    ), out


# --- the named-example cells on another path ------------------------------------------------


def test_the_demo_cell_prints_d01_below_the_gate_instead_of_stopping(notebook, capsys):
    """d01's entity confidence is 0.70: a gate above it sends d01 to review, with no request 2."""
    notebook("python-demo", before={"python-demo": _set_settings(gate=0.75)})
    out = _lines(capsys)
    assert any(line.startswith("d01: review (confidence below the threshold)") for line in out)
    assert any("d01 got no request 2" in line for line in out), out
    assert any("d01 has no transaction" in line for line in out), out


def test_the_demo_cell_prints_a_rejected_d01_instead_of_stopping(notebook, capsys):
    """d01 reaches request 2, but its supported probability 0.88 is below a threshold of 0.9, so
    it is rejected and has no transaction in the log."""
    notebook("python-demo", before={"python-demo": _set_settings(supported=0.9)})
    out = _lines(capsys)
    assert any(line.startswith("  supported: Noul: 0.88") for line in out), out
    assert any(line.startswith("d01: rejected") for line in out), out
    assert any("d01 has no transaction" in line for line in out), out


def test_the_counterfactual_cell_prints_t01_without_request_two(notebook, capsys):
    """t01's entity confidence is 0.85: a gate above it sends t01 to review, with no request 2,
    while every other threshold stays fitted."""
    notebook("evaluation-nouls", before={"evaluation-test-first": _set_settings(gate=0.86)})
    out = _lines(capsys)
    assert any(line.startswith("t01 as committed: review") for line in out), out
    assert any(line.startswith("t01 ") and "no request 2" in line for line in out), out


def test_the_replay_cell_prints_a_run_with_no_committed_update(notebook, capsys):
    """When no test update commits, the store's last write is the seed graph's, with no answer."""

    def nothing_committed(ns):
        ns["test_tx"], _, _ = ns["helpers"].run_updates([], "rule:apply_update")

    notebook("evaluation-replay", before={"evaluation-replay": nothing_committed})
    out = _lines(capsys)
    assert any("no test update committed" in line for line in out), out


def test_no_notebook_function_is_rebound_after_it_is_defined():
    """A name a code cell defines as a function is not assigned anything else in that cell or a
    later one, so a later cell that calls it still gets the function."""
    import ast

    functions, rebound = set(), set()
    for cell in ORDER:
        for statement in ast.parse(SOURCE[cell]).body:
            if isinstance(statement, ast.FunctionDef):
                functions.add(statement.name)
                continue
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    rebound |= {node.id} & functions
    assert functions, "the notebook defines no function"
    assert rebound == set()
