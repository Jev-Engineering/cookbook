"""#217 (template part): the template's confusion-matrix print block lines its columns up even
when a count is wider than every class label.

``recipes/_template/notebook.ipynb``'s ``evaluation-matrix`` cell sizes its columns from the
labels. A format spec never truncates, so a count with more digits than the widest label made its
row shift right of the header. The cell now sizes every column as the larger of the widest label
and the widest rendered count.

This test runs the template's own cell source (not a copy of its formula) against the real
``jev_cookbook.evaluation.confusion_matrix`` and checks the printed text: every row's last
column ends at the same character as the header's, and every column's right edge is shared.
It proves itself the one way that matters, by mutation: with the cell's width fixed back to the
label width, the same harness reports the misalignment on the case that exercises it.

Scope, stated plainly: this guards the TEMPLATE'S cell only. It does not look at any published
recipe's matrix print, and recipe 23 still carries an older formulation; converging the published
recipes and guarding them is the rest of #217 and is not done here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jev_cookbook.evaluation import confusion_matrix

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_NOTEBOOK = REPO / "recipes" / "_template" / "notebook.ipynb"


def matrix_cell_source() -> str:
    cells = json.loads(TEMPLATE_NOTEBOOK.read_text("utf-8"))["cells"]
    cell = next(c for c in cells if c.get("id") == "evaluation-matrix")
    return "".join(cell["source"])


class _Helpers:
    def __init__(self, labels):
        self.QUEUES = tuple(labels[:-1])
        self.NONE = labels[-1]


def run_cell(source: str, labels: list[str], per_cell: int, capsys) -> list[str]:
    """Run the template cell with ``per_cell`` examples of each gold label predicted correctly,
    and return the printed lines (the matrix block only)."""
    gold = [label for label in labels for _ in range(per_cell)]
    namespace = {
        "confusion_matrix": confusion_matrix,
        "plot_confusion_matrix": lambda *args, **kwargs: None,
        "helpers": _Helpers(labels),
        "test_gold": gold,
        "test_answers": list(gold),
        "test_examples": gold,
        "check": "",
    }
    exec(compile(source, "<template evaluation-matrix>", "exec"), namespace)
    return capsys.readouterr().out.splitlines()


def right_edges(line: str) -> list[int]:
    """Character offset one past the end of each whitespace-separated token after the leader."""
    return [m.end() for m in re.finditer(r"\S+", line)]


def misalignments(lines: list[str], n_labels: int) -> list[str]:
    """Rows whose last ``n_labels`` token right edges differ from the header's."""
    table = lines[1:]  # the first line is the title
    header = right_edges(table[0])[-n_labels:]
    return [row for row in table[1:] if right_edges(row)[-n_labels:] != header]


CASES = {
    "count wider than every label": (["a", "b", "none"], 12345),
    "count three digits, one-character labels": (["x", "y", "z"], 120),
    "labels wider than 'predicted ->' and counts": (["insufficient_evidence", "ok", "none"], 7),
    "count one digit wider than the labels": (["billing", "bug", "account", "none"], 100000),
    "single digit counts, short labels": (["a", "b", "none"], 3),
}


@pytest.mark.parametrize("case", CASES)
def test_the_template_matrix_aligns(case, capsys):
    labels, per_cell = CASES[case]
    lines = run_cell(matrix_cell_source(), labels, per_cell, capsys)
    assert len(lines) == 2 + len(labels)
    assert misalignments(lines, len(labels)) == []
    # Every count is present in full: nothing was truncated to fit.
    assert all(str(per_cell) in row for row in lines[2:])


def test_the_harness_reports_the_old_label_width_only_sizing(capsys):
    """Mutation proof: size the columns by label width alone, as the template did before, and the
    case with a count wider than every label must be reported as misaligned. Without this the
    passing test above could be a harness that cannot fail."""
    source = matrix_cell_source()
    mutated = source.replace("column = max(width, len(str(matrix.matrix.max())))", "column = width")
    assert mutated != source
    labels, per_cell = CASES["count wider than every label"]
    lines = run_cell(mutated, labels, per_cell, capsys)
    assert misalignments(lines, len(labels)), "\n".join(lines)
    # ... and the mutation is harmless where the old formula was correct.
    labels, per_cell = CASES["single digit counts, short labels"]
    assert misalignments(run_cell(mutated, labels, per_cell, capsys), len(labels)) == []
