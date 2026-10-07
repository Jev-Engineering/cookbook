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
