"""Pins the objective this recipe's threshold selection actually uses.

A printed f-string beside the call, or a test that only checks the resulting threshold VALUE,
does not pin which objective produced it: on this recipe's own pool, `select_confidence_threshold`
is piecewise constant across the whole feasible range of `min_coverage`, so a value-change
mutation of the committed notebook's keyword argument moves no number at all (see
`docs/evaluation.md` and the notebook's own sweep cell). What does pin it is comparing a string
naming the objective against a real read of the committed notebook source: swapping the
notebook's `min_coverage=` keyword to `target_accuracy=` changes the committed cell source, and
this test's own assertion is what would catch that.
"""

import json
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_the_threshold_selection_objective_is_min_coverage_in_the_committed_notebook():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c.get("id") == "threshold-code")
    source = "".join(cell["source"])
    assert "min_coverage" in source
    assert "target_accuracy" not in source
