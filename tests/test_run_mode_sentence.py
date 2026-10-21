"""#233: the run-mode paragraph in a notebook's ``setup-md`` is pinned to what the notebooks print.

The paragraph that used to say "every number below carries that mode with it" was false: demo
answers and per-example lines are numbers that carry no such label. Its replacement makes only
claims a script can check against the committed outputs, and this test is that script:

* the template, the scaffolder's ``setup-md`` and every published notebook carry the paragraph
  verbatim, except the closed ``LEGACY_WITHOUT_THE_PARAGRAPH`` list below (so a later template edit
  cannot silently drop or reword it, the copies cannot drift, and a newly scaffolded recipe passes
  without anyone editing this file);
* the only parenthetical labels of the form ``(a ..., not a ...)`` in any carrying notebook's
  committed output are the two the paragraph names;
* the pipeline-check label appears only in a run whose committed header says ``synthetic`` or
  ``scripted``, and every such run prints it on at least one labelled output line (the fixed
  "Not measured live: a pipeline check, not a Jev result." prose does not count: stripping the
  label off every number must turn this red, and ``test_the_label_checks_fail_on_a_mutated_run``
  proves it does);
* no notebook, carrying or not, still says that every number it prints says so, or that every
  line of some kind carries a label (the sentence #233 was filed for, in the variants it took).

The selection label's sentence names no split: it is true of every line that carries the label,
including the queue counts and previews in recipes 02, 10, 15, 25, 26 and 31 that span ``demo``
and ``validation`` or both scored splits (review 2 of PR #317, M1).

What it deliberately does NOT claim, because it is not true of the published set: that every
metric line carries a label. Some validation lines in recipes 06-10, 18 and 37 carry only the
selection label, and recipes 39, 47 and 49 print a metric line with no label at all. Those are
pre-existing labelling gaps (CONTRIBUTING.md section 2), tracked in #326; the paragraph says
"may follow" for that reason.
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
    "which mode ran. `(a selection step, not a reported result)` marks a line that is not a "
    "result to report, such as a number from `validation`, the split settings are chosen on, or "
    "a count of the items the frozen rule queues or would queue. A line with neither label, "
    "such as an individual answer or a per-example line, still comes from the mode the header "
    "names."
)
CHECK = "a pipeline check, not a Jev result"
SELECTION = "a selection step, not a reported result"
# Published before the paragraph existed and never carried the old "carries that mode" sentence.
# Their setup text makes no claim about which lines carry a label (the forbidden-wording test
# below covers every notebook), so they were not swept. This list is CLOSED: it names only recipes
# numbered 50 or lower (`test_the_legacy_list_is_closed`), so a new recipe is never exempt and
# must carry the paragraph, which `tools/new_recipe.py` now scaffolds. Remove a name here when
# that notebook gains the paragraph (the stale-exemption test fails otherwise). 36 was on this
# list until review 1 of PR #317 (M2): its setup text made exactly the claim #233 removed.
LEGACY_WITHOUT_THE_PARAGRAPH = {
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


# Wordings that made a claim about every number or line a notebook prints, in the variants the
# claim took. #233 removed the first from 44 notebooks; recipe 36 (review 1 of PR #317, M2), 45
# and 50 had their own variants and are fixed with it. None is true of an individual answer or a
# per-example line, which carry no label, or of the headings and counts that carry only one.
FORBIDDEN_WORDINGS = (
    "carries that mode",
    "labelled a selection step instead",
    # B4: most selection-labelled lines report what the frozen rule does on validation after the
    # choice; they are not numbers that chose anything (recipe 28's own prose says so).
    "marks a number used to choose",
    # Review 2 of PR #317, M1: false for the queue counts and previews that span demo and
    # validation or both scored splits (02, 10, 15, 25, 26), so the paragraph names no split.
    "marks a number from `validation`, the split settings are chosen on; it is never",
    # Recipe 36: "every number this notebook prints ... and says so".
    "every number this notebook prints",
    "every number here, `validation` and `test` alike",
    # Recipe 45: matrix rows and per-example lines are numbers with no label.
    "every number below already being labelled",
    # Recipe 50: its leak-check and N lines name validation and carry only the pipeline check.
    "printed on every validation line",
)


def test_the_old_false_sentence_is_gone_everywhere():
    for path in NOTEBOOKS:
        nb = load(path)
        text = squash(
            " ".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
        )
        for wording in FORBIDDEN_WORDINGS:
            assert wording not in text, (path.parent.name, wording)


def test_the_legacy_list_is_closed():
    """The exemption cannot grow: it names only recipes that already existed, and each must
    still exist and still lack the paragraph (remove a name when the paragraph is added)."""
    names = {p.parent.name for p in NOTEBOOKS}
    assert LEGACY_WITHOUT_THE_PARAGRAPH <= names
    assert all(int(name[:2]) <= 50 for name in LEGACY_WITHOUT_THE_PARAGRAPH)
    stale = {
        name
        for name in LEGACY_WITHOUT_THE_PARAGRAPH
        if carries(load(REPO / "recipes" / name / "notebook.ipynb"))
    }
    assert not stale, f"carries the paragraph now; remove from the legacy list: {sorted(stale)}"


def test_every_notebook_outside_the_closed_legacy_list_carries_the_paragraph():
    """A newly scaffolded recipe passes this without anyone editing this file."""
    without = {p.parent.name for p in NOTEBOOKS if not carries(load(p))}
    assert without == LEGACY_WITHOUT_THE_PARAGRAPH


def labelled_check_lines(lines: list[str]) -> list[str]:
    """Output lines carrying the label as a trailing parenthetical, the way a number carries it.
    The fixed prose "Not measured live: a pipeline check, not a Jev result." has no parentheses,
    so it cannot stand in for a labelled number."""
    return [line for line in lines if f"({CHECK})" in line]


def check_run_mode_claims(nb: dict) -> None:
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
        assert labelled_check_lines(lines), (
            "a synthetic or scripted run that prints the pipeline-check label on no output line"
        )
    assert not (modes & {"recorded", "live"} and printed_check)


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.parent.name)
def test_the_paragraph_is_verbatim_and_its_claims_hold_in_the_committed_output(path):
    nb = load(path)
    if not carries(nb):
        assert path.parent.name in LEGACY_WITHOUT_THE_PARAGRAPH
        pytest.skip("closed legacy list: published before the paragraph, no claim of its own")
    assert PARAGRAPH in squash(setup_markdown(nb))
    check_run_mode_claims(nb)


def mutated(nb: dict, change) -> dict:
    copy = json.loads(json.dumps(nb))
    for cell in copy["cells"]:
        for out in cell.get("outputs", []):
            if out.get("output_type") == "stream":
                out["text"] = [change(line) for line in out["text"]]
    return copy


@pytest.mark.parametrize("recipe", ["_template", "47-evidence-conflict-diagnosis"])
def test_the_label_checks_fail_on_a_mutated_run(recipe):
    """Review 2 of PR #317, M3: the claim "every synthetic or scripted run prints the label"
    passed with every label stripped off every number, because the fixed provenance prose
    contains the same words. Each mutation below must turn the checks red."""
    nb = load(REPO / "recipes" / recipe / "notebook.ipynb")
    check_run_mode_claims(nb)  # the committed notebook is green

    stripped = mutated(nb, lambda t: t.replace(f" ({CHECK})", ""))
    assert any(CHECK in line for line in output_lines(stripped)), (
        "the fixed provenance prose must survive the strip, or this case proves nothing"
    )
    with pytest.raises(AssertionError, match="on no output line"):
        check_run_mode_claims(stripped)

    renamed = mutated(nb, lambda t: t.replace(f"({CHECK})", "(a pipeline probe, not a Jev result)"))
    with pytest.raises(AssertionError):
        check_run_mode_claims(renamed)

    relabelled = mutated(
        nb, lambda t: t.replace(f"({SELECTION})", "(a selection stage, not a result)")
    )
    with pytest.raises(AssertionError):
        check_run_mode_claims(relabelled)


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


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_scaffolded_setup_cell_carries_the_paragraph(mode):
    """#233 asked for the fix "in the template first so the remaining recipes are generated
    correctly" (review 2 of PR #317, M2): what the scaffolder emits carries the pinned paragraph
    (with a TODO telling the builder to define and print the selection label, which the
    scaffolded setup cell does not yet define: tests/test_template_scaffolder_agreement.py pins
    that), so a new recipe needs nothing added to this test or to the paragraph."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("nr_paragraph", REPO / "tools" / "new_recipe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert squash(module.RUN_MODE_PARAGRAPH) == PARAGRAPH
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    recipe = next(r for r in catalog["recipes"] if r["rank"] == 1)
    cells = module.notebook_cells(catalog, recipe, mode=mode)
    nb = {"cells": cells}
    assert carries(nb)
    assert PARAGRAPH in squash(setup_markdown(nb))
    code = next(c["source"] for c in cells if c["id"] == "setup")
    assert 'check = " (a pipeline check, not a Jev result)" if offline else ""' in code
    paragraph = next(
        p
        for p in "".join(next(c for c in cells if c["id"] == "setup-md")["source"]).split("\n\n")
        if "Two labels may follow" in p
    )
    assert "TODO" in paragraph  # the same \n\n block, as test_no_synthetic_claim_... requires
