"""#233: the run-mode paragraph in a notebook's ``setup-md`` is pinned to what the notebooks print.

The paragraph that used to say "every number below carries that mode with it" was false: demo
answers and per-example lines are numbers that carry no such label. Its replacement makes only
claims a script can check against the committed outputs, and this test is that script:

* the template and every published notebook that carries the paragraph carry it verbatim (so a
  later template edit cannot silently drop or reword it, and the copies cannot drift);
* the notebooks that do not carry it are exactly the ones that never had the old sentence;
* the only parenthetical labels of the form ``(a ..., not a ...)`` in any carrying notebook's
  committed output are the two the paragraph names;
* the pipeline-check label appears only in a run whose committed header says ``synthetic`` or
  ``scripted``, and every such run prints it at least once.

What it deliberately does NOT claim, because it is not true of the published set: that every
metric line carries a label. Some validation lines in recipes 06-10, 18 and 37 carry only the
selection label, and recipes 39, 47 and 49 print a metric line with no label at all. Those are
pre-existing labelling gaps (CONTRIBUTING.md section 2), tracked outside this test; the paragraph
says "may follow" for that reason.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted(REPO.glob("recipes/*/notebook.ipynb"))

PARAGRAPH = (
    "Two labels may follow a number below. `(a pipeline check, not a Jev result)` marks a "
    "synthetic or scripted run; a recorded or live run does not print it, and its header says "
    "which mode ran. `(a selection step, not a reported result)` marks a number used to choose "
    "a setting on `validation`. A line with neither label, such as an individual answer or a "
    "per-example line, still comes from the mode the header names."
)
CHECK = "a pipeline check, not a Jev result"
SELECTION = "a selection step, not a reported result"
# Never carried the old "every number below carries that mode" sentence, so never needed the swap.
NEVER_HAD_THE_OLD_SENTENCE = {
    "36-card-game-action-selection",
    "41-approval-scope-review",
    "43-failure-recovery-selection",
    "44-plan-constraint-assessment",
    "45-memory-reconciliation",
    "48-document-revision-consistency",
    "50-model-comparison-and-calibration",
}
LABEL = re.compile(r"\((a [^()]*, not a [^()]*)\)")
PROVENANCE = re.compile(r"Mode: offline(?: replay of (\w+) fixtures|, (scripted) backend)")


def load(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def setup_markdown(nb: dict) -> str:
    cells = [c for c in nb["cells"] if c["cell_type"] == "markdown"]
    text = [("".join(c["source"])) for c in cells]
    return next((t for t in text if "which mode ran" in t), "")


def output_lines(nb: dict):
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        for out in cell.get("outputs", []):
            if out.get("output_type") == "stream":
                yield from "".join(out["text"]).splitlines()


def carries(nb: dict) -> bool:
    return "Two labels may follow a number below" in setup_markdown(nb)


def squash(text: str) -> str:
    return " ".join(text.split())


def test_the_old_false_sentence_is_gone_everywhere():
    for path in NOTEBOOKS:
        raw = path.read_text("utf-8")
        assert "carries that mode" not in raw, path
        assert "labelled a selection step instead" not in raw, path


def test_exactly_the_expected_notebooks_carry_the_paragraph():
    without = {p.parent.name for p in NOTEBOOKS if not carries(load(p))}
    assert without == NEVER_HAD_THE_OLD_SENTENCE


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.parent.name)
def test_the_paragraph_is_verbatim_and_its_claims_hold_in_the_committed_output(path):
    nb = load(path)
    if not carries(nb):
        pytest.skip("never carried the sentence")
    assert PARAGRAPH in squash(setup_markdown(nb))

    lines = list(output_lines(nb))
    labels = {m for line in lines for m in LABEL.findall(line)}
    assert labels <= {CHECK, SELECTION}, labels - {CHECK, SELECTION}

    modes = {m for line in lines for g in PROVENANCE.findall(line) for m in g if m}
    printed_check = any(CHECK in line for line in lines)
    if printed_check:
        assert modes & {"synthetic", "scripted"}, (
            "pipeline-check label in a run not marked synthetic"
        )
    if modes & {"synthetic", "scripted"}:
        assert printed_check, (
            "a synthetic or scripted run that never prints the pipeline-check label"
        )
    assert not (modes & {"recorded", "live"} and printed_check)


def test_the_template_prints_both_labels_on_a_validation_metric():
    """The paragraph says the two labels may follow a number; the template is where a reader sees
    them stacked, so pin that its validation metric lines carry both."""
    nb = load(REPO / "recipes" / "_template" / "notebook.ipynb")
    validation = [
        line for line in output_lines(nb) if "right among those routed automatically" in line
    ]
    assert any(SELECTION in line and CHECK in line for line in validation)


def test_the_scaffolder_evaluation_stub_keeps_the_forced_metric_prompt():
    """#222 gap 3: the scaffold's evaluation TODO still asks the builder to say which validation
    numbers their selection forces, and the template still says the line it forces."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("nr_sentence", REPO / "tools" / "new_recipe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    recipe = next(r for r in catalog["recipes"] if r["rank"] == 1)
    stub = next(c for c in module.notebook_cells(catalog, recipe) if c["id"] == "evaluation-md")
    source = stub["source"]
    assert "which `validation` numbers your selection forces" in "".join(source)
    template = load(REPO / "recipes" / "_template" / "notebook.ipynb")
    evaluation = next(c for c in template["cells"] if c["id"] == "evaluation-md")
    assert "by construction" in "".join(evaluation["source"])
