"""tools/notebook_ci.py: which notebooks to run, and the every-recipe-needs-fixtures gate."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "notebook_ci.py"
TEMPLATE_FIXTURES = REPO / "recipes" / "_template" / "fixtures"

spec = importlib.util.spec_from_file_location("notebook_ci_for_test", TOOL)
notebook_ci = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = notebook_ci
spec.loader.exec_module(notebook_ci)

NB = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n'


def git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def write(root, relative, text=NB):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def tree(tmp_path):
    """A repository whose main has three recipe folders (one without a notebook)."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid")):
        git(root, "config", key, value)
    git(root, "config", "commit.gpgsign", "false")
    write(root, "README.md", "readme\n")
    write(root, "docs/guide.md", "guide\n")
    write(root, "recipes/_template/notebook.ipynb")
    write(root, "recipes/01-first/notebook.ipynb")
    write(root, "recipes/02-second/notebook.ipynb")
    write(root, "recipes/03-no-notebook/README.md", "x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "work")
    return root


def selected(root, change=None):
    if change:
        change(root)
        git(root, "add", "-A")
        git(root, "commit", "-q", "--allow-empty", "-m", "change")
        return notebook_ci.select(root, "main", "work")
    return notebook_ci.select(root, None, None)


# -- the matrix ----------------------------------------------------------------------------------


def test_main_selects_every_notebook_including_the_template(tree):
    assert selected(tree) == ["01-first", "02-second", "_template"]


def test_recipe_pull_request_selects_only_its_recipe(tree):
    assert selected(tree, lambda r: write(r, "recipes/01-first/helpers.py", "x = 1\n")) == [
        "01-first"
    ]


def test_recipe_pull_request_with_the_generated_readme_still_selects_only_its_recipe(tree):
    def change(root):
        write(root, "recipes/02-second/notebook.ipynb", NB.replace("5}", "5} "))
        write(root, "README.md", "readme, regenerated\n")

    assert selected(tree, change) == ["02-second"]


def test_pull_request_touching_two_recipes_selects_both(tree):
    def change(root):
        write(root, "recipes/01-first/a.py", "x\n")
        write(root, "recipes/02-second/a.py", "x\n")

    assert selected(tree, change) == ["01-first", "02-second"]


@pytest.mark.parametrize(
    "path", ["docs/guide.md", "tools/execute_notebook.py", "src/jev_cookbook/x.py", "LICENSE"]
)
def test_any_other_changed_path_selects_everything(tree, path):
    def change(root):
        write(root, "recipes/01-first/a.py", "x\n")
        write(root, path, "changed\n")

    assert selected(tree, change) == ["01-first", "02-second", "_template"]


def test_a_pull_request_changing_only_the_readme_selects_nothing(tree):
    assert selected(tree, lambda r: write(r, "README.md", "new\n")) == []


def test_deleting_a_recipe_notebook_selects_nothing_to_run(tree):
    assert selected(tree, lambda r: (r / "recipes/01-first/notebook.ipynb").unlink()) == []


def test_template_only_change_selects_the_template(tree):
    assert selected(tree, lambda r: write(r, "recipes/_template/x.py", "x\n")) == ["_template"]


def test_a_file_directly_under_recipes_selects_everything(tree):
    assert selected(tree, lambda r: write(r, "recipes/notes.md", "x\n")) == [
        "01-first",
        "02-second",
        "_template",
    ]


def test_recipe_folder_names_are_validated_before_they_reach_a_workflow(tree):
    write(tree, "recipes/$(echo x)/notebook.ipynb")
    with pytest.raises(SystemExit, match="not NN-slug"):
        notebook_ci.select(tree, None, None)


def test_missing_base_is_an_error(tree):
    with pytest.raises(SystemExit, match="git diff"):
        notebook_ci.select(tree, "no-such-ref", "work")


def test_matrix_command_writes_github_output(tree, tmp_path):
    out = tmp_path / "out.txt"
    result = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--root",
            str(tree),
            "matrix",
            "--github-output",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"recipe": ["01-first", "02-second", "_template"]}
    assert out.read_text(encoding="utf-8") == (
        'matrix={"recipe":["01-first","02-second","_template"]}\ncount=3\n'
    )


def test_base_and_head_go_together(tree):
    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(tree), "matrix", "--base", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


def push_matrix(root, base, head="work", *extra):
    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), "matrix", "--base", base, "--head", head]
        + list(extra),
        capture_output=True,
        text=True,
        check=False,
    )
    return result, (json.loads(result.stdout)["recipe"] if result.returncode == 0 else None)


def test_push_with_a_missing_or_zero_before_is_an_error_unless_lenient(tree):
    for before in ("0" * 40, "f" * 40):
        result, _ = push_matrix(tree, before)
        assert result.returncode != 0, before


def test_lenient_push_with_an_unusable_before_selects_everything(tree):
    for before in ("0" * 40, "f" * 40, "no-such-ref"):
        result, names = push_matrix(tree, before, "work", "--lenient")
        assert result.returncode == 0, result.stderr
        assert names == ["01-first", "02-second", "_template"], before
        assert "selecting every notebook" in result.stderr


def test_lenient_push_with_a_real_before_selects_only_the_changed_recipe(tree):
    write(tree, "recipes/02-second/helpers.py", "x = 1\n")
    write(tree, "README.md", "regenerated\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "recipe")
    result, names = push_matrix(tree, "main", "work", "--lenient")
    assert result.returncode == 0 and names == ["02-second"], result.stderr


def test_lenient_push_that_touches_shared_code_selects_everything(tree):
    write(tree, "recipes/02-second/helpers.py", "x = 1\n")
    write(tree, "docs/guide.md", "changed\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "shared")
    _, names = push_matrix(tree, "main", "work", "--lenient")
    assert names == ["01-first", "02-second", "_template"]


def test_the_real_repository_matrix_has_the_template():
    assert "_template" in notebook_ci.with_notebooks(REPO)


# -- the fixtures gate ---------------------------------------------------------------------------


@pytest.fixture
def recipes_root(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(
        REPO / "recipes" / "_template" / "fixtures", root / "recipes" / "_template" / "fixtures"
    )
    return root


def run_gate(root):
    return subprocess.run(
        [sys.executable, str(TOOL), "--root", str(root), "fixtures"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_fixtures_pass_and_report_the_mode(recipes_root):
    result = run_gate(recipes_root)
    assert result.returncode == 0, result.stdout
    assert "_template: valid" in result.stdout
    assert "(mode replay)" in result.stdout


def test_recipe_without_a_fixtures_folder_fails(recipes_root):
    (recipes_root / "recipes" / "01-first").mkdir()
    result = run_gate(recipes_root)
    assert result.returncode == 1
    assert "01-first: no fixtures/ folder" in result.stdout


def test_invalid_fixtures_fail_with_the_validator_message(recipes_root):
    labels = recipes_root / "recipes" / "_template" / "fixtures" / "labels.jsonl"
    labels.write_text(labels.read_text(encoding="utf-8") + '{"id": "ghost", "label": "x"}\n')
    result = run_gate(recipes_root)
    assert result.returncode == 1
    assert "_template: INVALID" in result.stdout


def test_drifted_responses_fail(recipes_root):
    inputs = recipes_root / "recipes" / "_template" / "fixtures" / "inputs.jsonl"
    lines = inputs.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["replay_keys"] = ["0" * 64]
    lines[0] = json.dumps(first)
    inputs.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = run_gate(recipes_root)
    assert result.returncode == 1 and "INVALID" in result.stdout


def test_no_recipes_directory_is_an_error(tmp_path):
    result = run_gate(tmp_path)
    assert result.returncode != 0


def test_empty_recipes_directory_fails(tmp_path):
    (tmp_path / "recipes").mkdir()
    result = run_gate(tmp_path)
    assert result.returncode == 1


def test_the_real_repository_passes_the_gate():
    result = run_gate(REPO)
    assert result.returncode == 0, result.stdout
