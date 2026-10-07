"""The template recipe is a recipe: its fixtures validate, its notebook keeps the contract."""

import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from jev_cookbook.fixtures import validate_recipe

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
    for cell_id in ("evaluation-validation", "evaluation-test"):
        lines = stream_lines(cell_id)
        assert lines
        for line in lines:
            assert "(a pipeline check, not a Jev result)" in line, line


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
