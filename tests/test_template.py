"""The template recipe is a recipe: its fixtures validate, its notebook keeps the contract."""

import ast
import difflib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from jev_cookbook.fixtures import validate_recipe
from jev_cookbook.live import _dump, merge_responses

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


def load_module_at(path, name):
    """Import an arbitrary .py file (the template's own build_fixtures.py, not under tools/)
    so its functions and module-level values (ROWS, build_responses) are plain Python
    objects, not subprocess output or a re-dump of the file it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
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


def test_the_generator_reproduces_the_committed_fixtures(tmp_path):
    copy = tmp_path / "_template"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((TEMPLATE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (
            TEMPLATE / "fixtures" / name
        ).read_bytes()


def test_the_first_next_step_names_the_tools_that_show_key_drift():
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "next-md")
    first = source(cell).split("\n- ")[1]
    assert "pytest recipes/_template" in first and "git checkout" in first
    assert "validator" not in first


def test_the_next_steps_settle_the_neighbour_link_convention():
    """Issue #124, item 8: a neighbour link 404s until that recipe exists. The template keeps
    the folder-link convention and says so, because the renderer gives no per-recipe anchor to
    link to instead (tools/render_catalog.py builds the catalog table from bare titles)."""
    cell = next(c for c in NOTEBOOK["cells"] if c.get("id") == "next-md")
    text = source(cell)
    assert "](../" in text  # the neighbour links themselves are unchanged
    assert "404s on GitHub" in text and "no per-row anchor" in text


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


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    copy = tmp_path / "_template"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((TEMPLATE / name).read_bytes())
    script = copy / "build_fixtures.py"
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr

    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    before = responses.read_bytes()

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.live._dump sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match _dump exactly, not just agree with it on top-level order.

    Comparing against _dump(json.loads(raw)) (re-dumping the file's own parsed content)
    cannot catch a sort_keys=True regression: json.loads preserves whatever nested order the
    file already has, and _dump only re-sorts the top level, so that round trip would pass no
    matter which writer produced the file. Instead, import build_fixtures.py and compare
    against _dump of what build_responses computes directly from ROWS, independent of what
    main() actually wrote to disk."""
    raw = (TEMPLATE / "fixtures" / "responses.json").read_text("utf-8")
    module = load_module_at(TEMPLATE / "build_fixtures.py", "template_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == _dump(module.build_responses(module.ROWS))


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
