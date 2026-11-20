"""Exercise the notebook's evidence branches with replay answers and invented provenance."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from jev_cookbook import DecisionResult, Provenance, ReplayBackend

RECIPE = Path(__file__).resolve().parent.parent


class FixtureBackend:
    """Reuse the stored choices and attach test-only provenance without making live calls."""

    def __init__(self, mode):
        self.mode = mode
        self.model = "test-requested-alias" if mode == "live" else "test-returned-model"
        self.recorded_dates = ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04")
        self.replay = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
        self.calls = 0

    def decide(self, state, questions, *, assets=None):
        result = self.replay.decide(state, questions, assets=assets)
        self.calls += 1
        if self.calls == 1:
            date = "2026-01-01"  # demo
        elif self.calls <= 15:
            date = "2026-01-02"  # validation
        else:
            date = "2026-01-03" if self.calls % 2 == 0 else "2026-01-04"
        model = "test-returned-model"
        choice = replace(result["sku"], provenance=Provenance.recorded(model, date))
        return DecisionResult({"sku": choice}, model=model)


@pytest.mark.parametrize("mode", ["live", "recorded"])
def test_notebook_only_reports_recorded_test_evidence(monkeypatch, capsys, mode):
    monkeypatch.chdir(RECIPE)
    monkeypatch.setattr("IPython.display.display", lambda *_args: None)
    plots = []
    monkeypatch.setattr(
        "jev_cookbook.style.plot_confusion_matrix",
        lambda _matrix, *, title: plots.append(title),
    )
    monkeypatch.setattr("jev_cookbook.get_backend", lambda **_kwargs: FixtureBackend(mode))
    cells = json.loads((RECIPE / "notebook.ipynb").read_text(encoding="utf-8"))["cells"]
    namespace = {}
    streams = {}
    for cell in cells:
        if cell["cell_type"] == "code":
            exec(compile("".join(cell["source"]), cell["id"], "exec"), namespace)
            streams[cell["id"]] = capsys.readouterr().out

    assert namespace["backend"].audit()["decide_calls"] == 31
    assert len(namespace["review_queue"].pending()) == 6
    measured = streams["measured"]
    assert (
        "Held-out test N=16: returned model(s) test-returned-model, "
        "captured 2026-01-03, 2026-01-04."
    ) in measured
    assert "2026-01-01" not in measured
    assert "Validation N=14: returned model(s) test-returned-model, captured 2026-01-02" in measured

    if mode == "live":
        assert "test-requested-alias" in streams["setup"]
        assert "test-requested-alias" not in measured
        assert "metrics withheld pending recorded evaluation" in streams["evaluation"]
        for cell_id in (
            "answer",
            "python-rule",
            "validation-table",
            "evaluation-rows",
            "gate",
            "evaluation-matrix",
            "queue",
        ):
            assert streams[cell_id] == ""
        assert plots == []
    else:
        label = "(recorded test-returned-model, captured 2026-01-03, 2026-01-04)"
        assert label in streams["evaluation"]
        assert label in streams["gate"]
        assert label in streams["evaluation-matrix"]
        assert label in streams["queue"]
        assert plots == [f"Test split, 16 examples {label}"]
