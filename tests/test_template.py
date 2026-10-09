"""The template recipe is a recipe: its fixtures validate, its notebook keeps the contract.

The generic build_fixtures.py guard tests (refusal without --force, inputs/labels regenerated
from ROWS even on a refused run, and the writer byte-identical to jev_cookbook.live's recorder)
live in recipes/_template/tests/test_build_fixtures.py, the same file every scaffolded replay
recipe gets a copy of, not here: this file is for behaviour specific to the template as a
worked example (re-execution, the minimal-diff recording check, the scaffolder's own sections)."""

import ast
import difflib
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

from jev_cookbook.fixtures import validate_recipe
from jev_cookbook.live import merge_responses

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "recipes" / "_template"
NOTEBOOK = json.loads((TEMPLATE / "notebook.ipynb").read_text("utf-8"))


def load_tool(name):
    spec = importlib.util.spec_from_file_location(
        f"{name}_for_template_test", REPO / "tools" / name
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source(cell):
    return "".join(cell["source"])


def test_the_template_fixtures_validate():
    report = validate_recipe(TEMPLATE)
    assert list(report) == []
    assert report.mode == "replay"


def test_the_template_has_the_documented_files():
    expected = {
        "notebook.ipynb",
        "README.md",
        "helpers.py",
        "build_fixtures.py",
        "fixtures/inputs.jsonl",
        "fixtures/labels.jsonl",
        "fixtures/responses.json",
        "tests/test_helpers.py",
        "tests/test_build_fixtures.py",
    }
    found = {
        p.relative_to(TEMPLATE).as_posix()
        for p in TEMPLATE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert found == expected


def test_the_notebook_sections_are_the_scaffolders_sections():
    scaffolder = load_tool("new_recipe.py")
    headings = [
        line[3:]
        for cell in NOTEBOOK["cells"]
        if cell["cell_type"] == "markdown"
        for line in source(cell).splitlines()
        if line.startswith("## ")
    ]
    assert headings == scaffolder.SECTIONS


def test_the_scaffolded_build_fixtures_test_stays_in_step_with_the_template(tmp_path):
    """recipes/_template/tests/test_build_fixtures.py's own docstring promises that every
    scaffolded replay recipe gets a copy of it, kept in step with
    tools/new_recipe.py's build_fixtures_test_text. Prove it rather than assert it: substitute
    the template's own placeholders ("_template" the folder name, "template_build_fixtures_for_
    test" the module name) for a recipe's slug and module name, then swap in the scaffolder's own
    module docstring last (the one intentional difference this test allows: the template's talks
    about every recipe getting a copy of it, which a scaffolded copy does not need to say about
    itself) — order matters here, see the comment below. The result must equal what the
    scaffolder actually emits for that recipe, byte for byte."""
    new_recipe = load_tool("new_recipe.py")
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    recipe = next(r for r in catalog["recipes"] if r["rank"] == 9)
    template_text = (TEMPLATE / "tests" / "test_build_fixtures.py").read_text("utf-8")
    scaffolded = new_recipe.build_fixtures_test_text(recipe)

    template_docstring = template_text.split('"""', 2)[1]
    scaffolded_docstring = scaffolded.split('"""', 2)[1]
    assert template_docstring != scaffolded_docstring  # the one difference this test allows

    # The docstring swap must run last, after the slug/module-name substitutions below, not
    # before: the scaffolded docstring itself says "the recipes/_template/build_fixtures.py
    # pattern" (a deliberate, unsubstituted reference to the template as the canonical source),
    # so swapping the docstring in first would let the slug substitution corrupt that reference.
    # Swapping last has its own trap in the other direction: if the template's docstring ever
    # came to contain "_template" or the module-name placeholder itself, the substitutions below
    # would already have mutated that occurrence, and this exact-match replace would then silently
    # no-op instead of swapping in the scaffolded docstring — failing on an opaque byte diff rather
    # than naming the cause. Guard it explicitly: the original docstring text must survive the
    # substitutions below unchanged before this test relies on finding and replacing it.
    module_name = f"recipe{recipe['rank']:02d}_build_fixtures_for_test"
    substituted = template_text.replace("_template", recipe["slug"]).replace(
        "template_build_fixtures_for_test", module_name
    )
    assert template_docstring in substituted
    expected = substituted.replace(template_docstring, scaffolded_docstring)
    assert scaffolded == expected


def test_the_notebook_is_executed_and_has_no_error_output():
    code = [c for c in NOTEBOOK["cells"] if c["cell_type"] == "code"]
    assert code and all(c["execution_count"] for c in code)
    assert not [o for c in code for o in c["outputs"] if o["output_type"] == "error"]


def test_the_notebook_imports_only_the_standard_library_and_jev_cookbook():
    roots = set()
    for cell in NOTEBOOK["cells"]:
        if cell["cell_type"] != "code":
            continue
        text = "\n".join(line for line in source(cell).splitlines() if not line.startswith("%"))
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots.add(node.module.split(".")[0])
    assert "jev_cookbook" in roots
    assert roots <= {"jev_cookbook", "json"}
    assert roots <= set(sys.stdlib_module_names) | {"jev_cookbook"}


def test_the_notebook_states_the_run_mode_and_not_measured_live():
    text = json.dumps(NOTEBOOK["cells"])
    assert "offline replay of synthetic fixtures" in text
    assert "Not measured live" in text
    assert "pipeline check" in text


@pytest.mark.parametrize("path", ["README.md", "notebook.ipynb", "helpers.py"])
def test_nothing_in_the_template_claims_how_well_jev_performs(path):
    text = (TEMPLATE / path).read_text("utf-8").lower()
    for phrase in ("accurate", "outperform", "state of the art", "faster than", "cheaper"):
        assert phrase not in text


def test_re_executing_the_notebook_changes_nothing(tmp_path):
    copy = tmp_path / "_template"
    copy.mkdir()
    for p in TEMPLATE.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            target = copy / p.relative_to(TEMPLATE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
    executor = load_tool("execute_notebook.py")
    executor.execute(copy)
    before = json.loads((TEMPLATE / "notebook.ipynb").read_text("utf-8"))
    after = json.loads((copy / "notebook.ipynb").read_text("utf-8"))

    def text_outputs(nb):
        return [
            [
                {k: v for k, v in o.items() if k != "data"}
                | {"text/plain": o.get("data", {}).get("text/plain")}
                for o in c.get("outputs", [])
            ]
            for c in nb["cells"]
        ]

    assert text_outputs(after) == text_outputs(before)
    assert [c["source"] for c in after["cells"]] == [c["source"] for c in before["cells"]]
    assert re.search(r"(?m)^\s*\"image/png\"", (copy / "notebook.ipynb").read_text("utf-8"))


def copy_template(tmp_path):
    copy = tmp_path / "_template"
    for p in TEMPLATE.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            target = copy / p.relative_to(TEMPLATE)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(p.read_bytes())
    return copy


def test_two_executions_of_the_template_give_byte_identical_files(tmp_path):
    copy = copy_template(tmp_path)
    executor = load_tool("execute_notebook.py")
    executor.execute(copy)
    first = (copy / "notebook.ipynb").read_bytes()
    executor.execute(copy)
    second = (copy / "notebook.ipynb").read_bytes()
    assert first == second
    assert b"\r" not in first


def stream_lines(cell_id):
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == cell_id)
    return "".join(
        "".join(o["text"]) for o in cell["outputs"] if o["output_type"] == "stream"
    ).splitlines()


def test_every_metric_line_of_the_evaluation_carries_the_pipeline_check_label():
    """CONTRIBUTING.md section 2: "In a synthetic run, any metric is a check that the pipeline
    works, and the notebook says so next to the number." That includes validation numbers: in
    this (synthetic) run, a validation line is both a selection step and a pipeline check, not
    one or the other."""
    threshold_lines = [
        line for line in stream_lines("python-rule") if line.startswith(("answers that", "chosen"))
    ]
    assert len(threshold_lines) == 2
    lines = (
        threshold_lines + stream_lines("evaluation-validation") + stream_lines("evaluation-test")
    )
    assert lines
    for line in lines:
        assert "(a pipeline check, not a Jev result)" in line, line


def test_every_validation_number_carries_the_mode_independent_selection_label():
    """CONTRIBUTING.md section 2: a number from the validation split is a selection step, not
    a result. Unlike `check`, this label must not depend on `backend.mode`: it is printed in
    the offline (synthetic) run tested here, and it must stay printed in a `recorded` or
    `live` run too, where `check` goes empty but `selection` must not."""
    threshold_lines = [
        line for line in stream_lines("python-rule") if line.startswith(("answers that", "chosen"))
    ]
    assert len(threshold_lines) == 2
    validation_lines = stream_lines("evaluation-validation")
    assert validation_lines
    for line in threshold_lines + validation_lines:
        assert "(a selection step, not a reported result)" in line, line


def test_the_evaluation_reports_what_the_routing_rule_does():
    from jev_cookbook import get_backend, load_helpers
    from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, select_split

    helpers = load_helpers(TEMPLATE)
    questions = helpers.build_questions()
    backend = get_backend(fixtures=responses_path(TEMPLATE))
    examples, labels = load_inputs(TEMPLATE), load_labels(TEMPLATE)

    def answers_for(split):
        chosen = select_split(examples, split)
        return chosen, [
            backend.decide(helpers.build_state(e.fields), questions)["route"] for e in chosen
        ]

    # The threshold, derived independently: the lowest confidence among validation answers
    # that name a queue such that every named-queue answer at or above it is right. A
    # confident `none` never sets it.
    validation, answers = answers_for("validation")
    named = [
        (a.confidence, a.choice == labels[e.id])
        for a, e in zip(answers, validation, strict=True)
        if a.choice in helpers.QUEUES
    ]
    threshold = min(c for c, _ in named if all(ok for c2, ok in named if c2 >= c))
    printed = " ".join(stream_lines("evaluation-test"))
    assert f"threshold {threshold:.2f} frozen" in printed

    test, test_answers = answers_for("test")
    auto = right = review = 0
    for example, answer in zip(test, test_answers, strict=True):
        routing = helpers.route(example.fields["ticket"], answer, threshold)
        if routing.outcome == helpers.REVIEW:
            review += 1
        else:
            auto += 1
            right += answer.choice == labels[example.id]
    assert f"routed automatically: {auto} of 10" in printed
    assert f"right among those routed automatically: {right} of {auto}" in printed
    assert f"sent to review: {review} of 10" in printed


def test_the_template_readme_discloses_mode_model_date_and_n():
    readme = (TEMPLATE / "README.md").read_text("utf-8")
    section = readme.split("## What was and was not measured")[1].split("## What is in")[0]
    for field in ("**Mode:**", "**Model, capture date:**", "**N:**"):
        assert field in section
    assert "synthetic" in section and "10 `validation` and 10 `test`" in section
    assert "model version the API returned" in readme and "sample size N" in readme
    assert "answers_for" in readme and "TYPESAFE_API_KEY" in readme and '".[live]"' in readme


def test_the_header_counts_the_scored_examples_not_the_demo_ones():
    setup = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "setup"))
    assert "%matplotlib" not in setup
    assert "n_examples=len(scored)" in setup and "None if offline" not in setup
    assert "header = " not in setup and "sample size" not in setup
    assert 'scored = [e for e in examples if e.split != "demo"]' in setup
    assert "len(scored)" in setup and "len(examples)" not in setup


def test_the_confusion_matrix_title_follows_the_mode_and_states_n():
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "evaluation-matrix")
    assert 'title=f"Test split, {len(test_examples)} examples{check}"' in source(cell)


def test_the_first_next_step_names_the_tools_that_show_key_drift():
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "next-md")
    first = source(cell).split("\n- ")[1]
    assert "pytest recipes/_template" in first and "git checkout" in first
    assert "validator" not in first


def test_the_next_steps_settle_the_neighbour_link_convention():
    """A neighbour link is a folder link (the renderer gives no per-recipe anchor to link to
    instead: tools/render_catalog.py builds the catalog table from bare titles), and it must
    point to a recipe that already exists on `main`: a forward link to one that is not yet
    published is not allowed."""
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "next-md")
    text = source(cell)
    assert "](../" in text  # the neighbour links themselves are unchanged
    assert "no per-row anchor" in text
    assert "already committed on `main`" in text and "not allowed" in text


def test_the_rule_demo_uses_the_threshold_chosen_on_validation_not_a_hardcoded_value():
    """Issue #124 / PR #123 comment 6059256403: the up-close rule demo should use the frozen
    threshold chosen on validation, not an arbitrary starting value, and the threshold must be
    selected before that demo runs."""
    python_md = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "python-md"))
    assert "0.5" not in python_md
    assert "chosen here, on `validation`, and then frozen" in python_md
    python_rule = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "python-rule"))
    assert "min_confidence=0.5" not in python_rule
    assert "min_confidence=threshold" in python_rule
    assert python_rule.index("threshold = select_confidence_threshold") < python_rule.index(
        "min_confidence=threshold"
    )


def test_report_has_a_comment_about_dropping_the_reasons_tally():
    """PR #123 comment 6059256403 (suggestion): report()'s reasons tally is dead weight for a
    rule with a single review reason; the template should say so for copies with a richer
    rule."""
    cell = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "evaluation-validation"))
    assert "exactly one review reason" in cell
    assert "Drop `reasons`" in cell


def test_the_measured_markdown_does_not_hardcode_a_mode_specific_claim():
    """Issue #124, item 5: the 'What was and was not measured' markdown must not assert a
    specific mode (so it cannot go stale once fixtures/responses.json is swapped for a recorded
    run); the mode-specific claim belongs in the code cell below, which reads backend.mode."""
    measured_md = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "measured-md"))
    assert "backend.mode" in measured_md
    # The markdown may name every possible mode in general terms, but it must not assert that
    # *this* run is synthetic or that the stored answers were written by hand: that claim is
    # mode-specific and belongs in the code cell below, derived from backend.mode at run time.
    for stale in ("written by hand", "invented messages", "hand-written"):
        assert stale not in measured_md.lower()
    assert "demo" in measured_md


def test_the_confusion_matrix_cell_prints_what_it_plots():
    """ "Print what you plot": the figure comparison in CI is loose, so the printed numbers are
    what actually pins the matrix byte for byte. Every printed line is a `test` number in an
    offline run, so it carries `check` like every other metric line in this cell."""
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "evaluation-matrix")
    text = source(cell)
    assert "print(" in text and "matrix.matrix.tolist()" in text
    lines = stream_lines("evaluation-matrix")
    assert len(lines) >= 1 + len(["billing", "bug", "account", "none"])
    for line in lines:
        assert "(a pipeline check, not a Jev result)" in line, line


def test_the_measured_cell_prints_n_in_every_mode_the_markdown_promises_it():
    """docs/recipe-template.md: the "What was and was not measured" markdown must not promise an
    N its code does not print, in any mode. The offline branch prints N too, not only the
    recorded/live branch."""
    cell = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "measured"))
    offline_branch = cell.split("else:")[0]
    assert "N:" in offline_branch
    lines = stream_lines("measured")
    assert any(line.startswith("N:") for line in lines)


def test_gold_label_is_defined_in_prose_not_in_a_code_comment_and_links_the_glossary():
    """CONTRIBUTING.md section 6: prose in markdown cells, not in code comments. The setup cell
    may still point at the term (so a reader of the code alone is not left wondering why `scored`
    excludes the demo examples), but the definition itself lives in markdown."""
    setup = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "setup"))
    assert "recorded correct answer" not in setup
    evaluation_md = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "evaluation-md"))
    assert "gold label" in evaluation_md.lower()
    assert "recorded correct answer" in evaluation_md
    assert "../../docs/glossary.md#gold-label" in evaluation_md


def test_the_fallback_exemption_states_the_two_part_test():
    python_md = source(next(c for c in NOTEBOOK["cells"] if c.get("id") == "python-md"))
    assert "writes nothing anywhere" in python_md and "leaves no harm standing" in python_md


def test_a_simulated_recording_produces_a_minimal_diff():
    """Proves issue #124 item 4's actual purpose: recording over this file should change only
    the values a real call would change, not reformat every response. Simulate a recording
    that keeps every answer's content but flips its provenance to recorded (what the
    recording wave does), merge it the way jev_cookbook.live.record does, and check the diff
    is confined to the lines that actually changed (provenance and, for the top-level entry,
    its model) rather than a wholesale reordering."""
    responses_path = TEMPLATE / "fixtures" / "responses.json"
    before_text = responses_path.read_text("utf-8")
    before_lines = before_text.splitlines()
    data = json.loads(before_text)

    recorded = {}
    for key, response in data.items():
        new_answers = {}
        for name, answer in response["answers"].items():
            new_answer = dict(answer)
            new_answer["provenance"] = {
                "source": "recorded",
                "model": "jev-1.13.0",
                "date": "2026-10-09",
            }
            new_answers[name] = new_answer
        recorded[key] = {"model": "jev-1.13.0", "usage": response["usage"], "answers": new_answers}

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "responses.json"
        scratch.write_text(before_text, encoding="utf-8")
        merge_responses(scratch, recorded, overwrite=True)
        after_lines = scratch.read_text("utf-8").splitlines()

    diff = list(difflib.unified_diff(before_lines, after_lines, lineterm=""))
    changed = [line for line in diff if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    # Every response's provenance block is 3 lines (source, model, date) on each side, and the
    # top-level model line changes too: for N responses that is at most 4N changed lines on
    # each side, well under reformatting the whole 500+ line file.
    assert 0 < len(changed) <= 8 * len(data), len(changed)
