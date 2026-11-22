"""Unit checks of the policy-plot cell with synthetic reports, not notebook execution."""

import json
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import pytest

from jev_cookbook.style import plot_risk_coverage

RECIPE = Path(__file__).resolve().parents[1]
EXPECTED = [(0.8, 0.3), (0.5, 0.1), (1.0, 0.4)]
LABELS = ["reject_all", "mechanism (this recipe)", "approve_all"]


@pytest.fixture
def policy_figure():
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text(encoding="utf-8"))
    source = next(c["source"] for c in notebook["cells"] if c["id"] == "eval-frontier")
    scope = {
        "plot_risk_coverage": plot_risk_coverage,
        "always_review_report": SimpleNamespace(coverage=0.0, risk=0.0),
        "permission_only_report": SimpleNamespace(coverage=1.0, risk=0.4),
        "reject_all_report": SimpleNamespace(coverage=0.8, risk=0.3),
        "approve_all_report": SimpleNamespace(coverage=1.0, risk=0.4),
        "test_report": SimpleNamespace(coverage=0.5, risk=0.1),
        "test_examples": [object(), object()],
        "check": " (synthetic unit-test reports)",
    }
    try:
        exec(compile("".join(source), str(RECIPE / "notebook.ipynb"), "exec"), scope)
        yield scope["fig"]
    finally:
        plt.close("all")


def test_separate_policies_are_not_joined_into_a_curve(policy_figure):
    lines = policy_figure.axes[0].lines
    assert len(lines) == 1
    assert lines[0].get_linestyle() == "None"


def test_policy_points_and_annotations_keep_their_declared_pairing(policy_figure):
    axes = policy_figure.axes[0]
    line = axes.lines[0]
    assert list(zip(line.get_xdata(), line.get_ydata(), strict=True)) == EXPECTED
    assert [(text.get_text(), text.xy) for text in axes.texts] == list(
        zip(LABELS, EXPECTED, strict=True)
    )
