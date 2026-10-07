"""Tests for tools/new_recipe.py and tools/execute_notebook.py, against temporary trees only.

Nothing here writes into the real recipes/ folder: every call names a temporary recipes
directory and a temporary copy of the catalog.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import nbformat
import pytest

from jev_cookbook import load_helpers

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "recipes" / "_template"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(f"{name}_for_test", REPO / "tools" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


new_recipe = load_tool("new_recipe.py")
execute_notebook = load_tool("execute_notebook.py")


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "recipes.json"
    shutil.copy(REPO / "catalog" / "recipes.json", path)
    return path


@pytest.fixture
def recipes(tmp_path):
    return tmp_path / "recipes"


def run(number, catalog, recipes):
    return new_recipe.main([str(number), "--catalog", str(catalog), "--recipes-dir", str(recipes)])


def entry(catalog, number):
    data = json.loads(catalog.read_text("utf-8"))
    return data, next(r for r in data["recipes"] if r["rank"] == number)


def test_it_creates_the_folder_named_by_the_catalog(catalog, recipes):
    _, recipe = entry(catalog, 31)
    assert run(31, catalog, recipes) == 0
    folder = recipes / recipe["slug"]
    names = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert names == {
        "notebook.ipynb",
        "README.md",
        "helpers.py",
        "build_fixtures.py",
        "tests/test_helpers.py",
    }


def test_the_catalog_fields_are_filled_in_the_notebook_and_the_readme(catalog, recipes):
    data, recipe = entry(catalog, 31)
    run(31, catalog, recipes)
    folder = recipes / recipe["slug"]
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    nbformat.validate(nb)
    readme = (folder / "README.md").read_text("utf-8")
    for text in (nb.cells[0].source, readme):
        assert recipe["title"] in text
        assert recipe["use_case"] in text
        assert f"Level {recipe['level']} ({recipe['difficulty']})" in text
        assert "Recipe 31" in text
        for decision in recipe["decision_types"]:
            assert f"`{decision}`" in text
        for source in recipe["sources"]:
            reference = next(s for s in data["sources"] if s["id"] == source)
            assert reference["url"] in text
    assert f"recipes/{recipe['slug']}" in readme
    assert "run_header(\n    31," in nb.cells[2].source


def test_two_decision_types_are_both_listed(catalog, recipes):
    data, _ = entry(catalog, 1)
    multi = next(r for r in data["recipes"] if len(r["decision_types"]) > 1)
    run(multi["rank"], catalog, recipes)
    notebook = nbformat.read(recipes / multi["slug"] / "notebook.ipynb", as_version=4)
    assert " + ".join(f"`{t}`" for t in multi["decision_types"]) in notebook.cells[0].source


def test_the_example_wording_is_replaced_by_marked_placeholders(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    folder = recipes / recipe["slug"]
    for path in folder.rglob("*"):
        if path.is_file():
            text = path.read_text("utf-8")
            assert "TODO" in text, path.name
            for example_word in ("support message", "billing-team", "human_review", "T-1001"):
                assert example_word not in text, (path.name, example_word)


def test_the_notebook_has_the_templates_sections_in_order_and_no_outputs(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    nb = nbformat.read(recipes / recipe["slug"] / "notebook.ipynb", as_version=4)
    headings = [
        line[3:]
        for c in nb.cells
        if c.cell_type == "markdown"
        for line in c.source.splitlines()
        if line.startswith("## ")
    ]
    assert headings == new_recipe.SECTIONS
    code = [c for c in nb.cells if c.cell_type == "code"]
    assert all(not c.outputs and c.execution_count is None for c in code)


def test_it_refuses_to_overwrite_and_changes_nothing(catalog, recipes, capsys):
    _, recipe = entry(catalog, 2)
    existing = recipes / recipe["slug"]
    existing.mkdir(parents=True)
    (existing / "notebook.ipynb").write_text("mine", encoding="utf-8")
    assert run(2, catalog, recipes) == 1
    err = capsys.readouterr().err
    assert "already exists" in err and "refusing to overwrite" in err
    assert [p.name for p in existing.iterdir()] == ["notebook.ipynb"]
    assert (existing / "notebook.ipynb").read_text("utf-8") == "mine"


def test_running_it_twice_refuses_the_second_time(catalog, recipes):
    assert run(5, catalog, recipes) == 0
    assert run(5, catalog, recipes) == 1


@pytest.mark.parametrize("bad", ["0", "61", "-1", "abc", "1.5", "", "٣"])
def test_a_number_outside_1_to_60_is_a_usage_error(bad, catalog, recipes):
    with pytest.raises(SystemExit) as stop:
        run(bad, catalog, recipes)
    assert stop.value.code == 2
    assert not recipes.exists()


def test_a_number_missing_from_the_catalog_is_an_error(catalog, recipes, capsys):
    data = json.loads(catalog.read_text("utf-8"))
    data["recipes"] = [r for r in data["recipes"] if r["rank"] != 9]
    catalog.write_text(json.dumps(data), encoding="utf-8")
    assert run(9, catalog, recipes) == 1
    assert "not in the catalog" in capsys.readouterr().err
    assert not recipes.exists()


def test_a_missing_catalog_is_an_error(tmp_path, recipes, capsys):
    assert run(1, tmp_path / "none.json", recipes) == 1
    assert "catalog not found" in capsys.readouterr().err


def test_the_command_line_works_and_exit_status_is_visible(catalog, recipes):
    base = [sys.executable, str(REPO / "tools" / "new_recipe.py")]
    args = ["3", "--catalog", str(catalog), "--recipes-dir", str(recipes)]
    first = subprocess.run([*base, *args], capture_output=True, text=True)
    second = subprocess.run([*base, *args], capture_output=True, text=True)
    assert first.returncode == 0 and second.returncode == 1
    assert "refusing to overwrite" in second.stderr


def test_every_catalog_recipe_scaffolds_to_lint_clean_files(catalog, recipes):
    data, _ = entry(catalog, 1)
    for recipe in data["recipes"]:
        assert run(recipe["rank"], catalog, recipes) == 0
    assert len(list(recipes.iterdir())) == 60
    ruff = [sys.executable, "-m", "ruff"]
    config = ["--config", str(REPO / "pyproject.toml"), "--no-cache"]
    subprocess.run([*ruff, "check", *config, str(recipes)], check=True)
    subprocess.run([*ruff, "format", "--check", *config, str(recipes)], check=True)


def test_the_default_target_is_the_real_recipes_folder_and_this_test_never_uses_it(
    catalog, recipes
):
    """Every other test scaffolds into a temporary folder; the real ``recipes/`` listing is the
    same before and after (checked without naming any recipe, so adding one never breaks it)."""
    assert new_recipe.ROOT == REPO

    def listing():
        return sorted(p.name for p in (REPO / "recipes").iterdir() if p.name != "__pycache__")

    before = listing()
    assert run(1, catalog, recipes) == 0
    assert listing() == before


def test_a_scaffold_runs_once_the_helpers_and_fixtures_exist(catalog, recipes):
    """The walkthrough: scaffold, supply helpers and fixtures, run the notebook."""
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    folder = recipes / recipe["slug"]
    with pytest.raises(NotImplementedError, match="TODO"):
        load_helpers(folder).build_questions()
    shutil.copy(TEMPLATE / "helpers.py", folder / "helpers.py")
    shutil.copytree(TEMPLATE / "fixtures", folder / "fixtures")
    execute_notebook.execute(folder)
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    streams = "".join(
        o.get("text", "") for c in nb.cells if c.cell_type == "code" for o in c.outputs
    )
    assert "Recipe 01:" in streams and "offline replay of synthetic fixtures" in streams
    assert "Not measured live" in streams


def test_the_offline_environment_drops_the_live_switch_and_the_key():
    env = {
        "PATH": "x",
        "JEV_COOKBOOK_LIVE": "1",
        "JEV_COOKBOOK_LIVE_MODEL": "m",
        "JEV_COOKBOOK_LIVE_MAX_REQUESTS": "3",
        "TYPESAFE_API_KEY": "k",
        "HOME": "h",
    }
    assert execute_notebook.offline_environment(env) == {"PATH": "x", "HOME": "h"}


def write_notebook(folder, source):
    folder.mkdir()
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)])
    nbformat.write(nb, folder / "notebook.ipynb")


def test_a_failing_cell_leaves_the_notebook_unchanged_and_exits_1(tmp_path, capsys):
    folder = tmp_path / "bad"
    write_notebook(folder, "raise ValueError('nope')")
    before = (folder / "notebook.ipynb").read_bytes()
    assert execute_notebook.main([str(folder)]) == 1
    assert (folder / "notebook.ipynb").read_bytes() == before
    assert "a cell failed" in capsys.readouterr().err


def test_the_kernel_runs_in_the_recipe_folder_without_the_live_switch(tmp_path, monkeypatch):
    folder = tmp_path / "env"
    code = (
        "import os, pathlib\n"
        "assert pathlib.Path.cwd().name == 'env'\n"
        "assert 'JEV_COOKBOOK_LIVE' not in os.environ\n"
        "assert 'TYPESAFE_API_KEY' not in os.environ\n"
    )
    write_notebook(folder, code)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    assert execute_notebook.main([str(folder)]) == 0
    assert os.environ["JEV_COOKBOOK_LIVE"] == "1"  # the parent's environment is restored
    assert os.environ["TYPESAFE_API_KEY"] == "placeholder"


def test_a_folder_without_a_notebook_is_a_usage_error(tmp_path):
    assert execute_notebook.main([str(tmp_path)]) == 2


def test_every_typesafe_variable_is_dropped_whatever_its_case():
    env = {
        "PATH": "x",
        "TYPESAFE_API_KEY": "k",
        "TYPESAFE_BASE_URL": "u",
        "typesafe_other": "o",
        "TYPESAFEISH": "kept",
        "jev_cookbook_live": "1",
    }
    assert execute_notebook.offline_environment(env) == {"PATH": "x", "TYPESAFEISH": "kept"}


def test_the_kernel_gets_an_explicit_environment_and_the_parents_is_never_touched(
    tmp_path, monkeypatch
):
    folder = tmp_path / "isolated"
    code = (
        "import os\n"
        "assert not [k for k in os.environ if k.upper().startswith('TYPESAFE_')]\n"
        "assert 'JEV_COOKBOOK_LIVE' not in os.environ\n"
        "assert os.environ['KEEP_ME'] == 'yes'\n"
    )
    write_notebook(folder, code)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setenv("KEEP_ME", "yes")
    seen = []

    class Spy(dict):
        """Stands in for os.environ: any write or clear during the run is recorded."""

        def __setitem__(self, key, value):
            seen.append(key)
            super().__setitem__(key, value)

        def clear(self):
            seen.append("clear")
            super().clear()

    snapshot = dict(os.environ)
    monkeypatch.setattr(os, "environ", Spy(snapshot))
    assert execute_notebook.main([str(folder)]) == 0
    assert seen == []
    assert dict(os.environ) == snapshot


def test_the_kernel_is_the_interpreter_running_the_tool(tmp_path):
    folder = tmp_path / "interpreter"
    write_notebook(folder, "import sys\nprint(sys.executable)")
    assert execute_notebook.main([str(folder)]) == 0
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    printed = nb.cells[0].outputs[0]["text"].strip()
    assert Path(printed).resolve() == Path(sys.executable).resolve()


def test_a_user_level_python3_kernelspec_does_not_replace_the_interpreter(tmp_path, monkeypatch):
    specs = tmp_path / "jupyter" / "kernels" / "python3"
    specs.mkdir(parents=True)
    broken = {"argv": [sys.executable, "-c", "raise SystemExit(3)"], "display_name": "Other"}
    (specs / "kernel.json").write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path / "jupyter"))
    folder = tmp_path / "shadowed"
    write_notebook(folder, "import sys\nprint(sys.executable)")
    assert execute_notebook.main([str(folder)]) == 0


def test_a_cell_that_writes_to_stderr_fails_the_run_and_leaves_the_file(tmp_path, capsys):
    folder = tmp_path / "noisy"
    write_notebook(folder, "import sys\nprint('/some/absolute/path', file=sys.stderr)")
    before = (folder / "notebook.ipynb").read_bytes()
    assert execute_notebook.main([str(folder)]) == 1
    assert (folder / "notebook.ipynb").read_bytes() == before
    assert "wrote to stderr" in capsys.readouterr().err


def test_a_printed_line_is_one_stream_output_even_when_the_flush_lands_in_the_middle(tmp_path):
    """Without ``coalesce_streams`` the text and the newline of a ``print`` can arrive as two
    outputs whenever an IOPub flush falls between them."""
    folder = tmp_path / "split"
    code = (
        "import sys, time\nsys.stdout.write('a')\nsys.stdout.flush()\ntime.sleep(0.5)\nprint('b')"
    )
    write_notebook(folder, code)
    assert execute_notebook.main([str(folder)]) == 0
    after = nbformat.read(folder / "notebook.ipynb", as_version=4)
    outputs = after.cells[0].outputs
    assert [(o.output_type, o.name, o.text) for o in outputs] == [("stream", "stdout", "ab\n")]


def test_a_dead_kernel_fails_the_run_quickly_and_leaves_the_file(tmp_path):
    """A cell that kills the kernel used to hang the executor forever, the cell timeout
    notwithstanding. It runs in a subprocess so that a regression is a failure, not a hang."""
    folder = tmp_path / "dead"
    write_notebook(folder, "import os\nos._exit(1)")
    before = (folder / "notebook.ipynb").read_bytes()
    tool = REPO / "tools" / "execute_notebook.py"
    result = subprocess.run(
        [sys.executable, str(tool), str(folder)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 1
    assert "the kernel died" in result.stderr
    assert (folder / "notebook.ipynb").read_bytes() == before


def test_a_warning_in_a_cell_counts_as_stderr(tmp_path):
    folder = tmp_path / "warns"
    write_notebook(folder, "import warnings\nwarnings.warn('careful')")
    assert execute_notebook.main([str(folder)]) == 1


def test_the_written_file_is_lf_only(tmp_path):
    folder = tmp_path / "lf"
    write_notebook(folder, "print('a')\nprint('b')")
    assert execute_notebook.main([str(folder)]) == 0
    raw = (folder / "notebook.ipynb").read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")


def test_the_notebook_metadata_is_reset_to_the_documented_minimum(tmp_path):
    folder = tmp_path / "meta"
    folder.mkdir()
    nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("pass")])
    nb.metadata = nbformat.from_dict(
        {
            "kernelspec": {"display_name": "Mine", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.99.0"},
            "widgets": {"state": {}},
        }
    )
    nbformat.write(nb, folder / "notebook.ipynb")
    assert execute_notebook.main([str(folder)]) == 0
    after = nbformat.read(folder / "notebook.ipynb", as_version=4)
    assert after.metadata == execute_notebook.METADATA
    assert execute_notebook.METADATA == {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }


def test_no_timings_are_recorded(tmp_path):
    folder = tmp_path / "timing"
    write_notebook(folder, "pass")
    assert execute_notebook.main([str(folder)]) == 0
    after = nbformat.read(folder / "notebook.ipynb", as_version=4)
    assert all("execution" not in cell.metadata for cell in after.cells)
    assert b"iopub" not in (folder / "notebook.ipynb").read_bytes()


def test_the_scaffold_setup_cell_counts_the_scored_examples_in_every_mode(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    nb = nbformat.read(recipes / recipe["slug"] / "notebook.ipynb", as_version=4)
    setup = next(c for c in nb.cells if c.get("id") == "setup").source
    assert "%matplotlib" not in setup
    assert "n_examples=len(scored)" in setup and "None if offline" not in setup
    assert "header = " not in setup and "sample size" not in setup
    assert 'scored = [e for e in examples if e.split != "demo"]' in setup
    assert "len(scored)" in setup
    assert "len(examples)" not in setup


def test_the_scaffold_readme_and_measured_cell_leave_room_for_a_recorded_run(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    folder = recipes / recipe["slug"]
    readme = (folder / "README.md").read_text("utf-8")
    section = readme.split("## What was and was not measured")[1].split("## Sources")[0]
    for field in ("**Mode:**", "**Model, capture date:**", "**N:**"):
        assert field in section
    assert section.count("TODO") >= 3
    assert "model version the API returned" in section
    assert "Not measured live" in section
    assert "TYPESAFE_API_KEY" in readme and '".[live]"' in readme
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    measured = next(c for c in nb.cells if c.get("id") == "measured").source
    assert "recorded_dates" in measured and "backend.model" in measured and "N:" in measured


def test_no_synthetic_claim_in_the_scaffold_is_left_without_a_todo(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    folder = recipes / recipe["slug"]
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    texts = [c.source for c in nb.cells if c.cell_type == "markdown"]
    texts.append((folder / "README.md").read_text("utf-8"))
    claims = [
        paragraph
        for text in texts
        for paragraph in text.split("\n\n")
        if "synthetic" in paragraph.lower()
    ]
    assert claims, "the scaffold should still carry the synthetic wording under a TODO"
    for paragraph in claims:
        assert "TODO" in paragraph, paragraph


def test_the_scaffold_tests_include_the_replay_key_test(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    tests = (recipes / recipe["slug"] / "tests" / "test_helpers.py").read_text("utf-8")
    assert "def test_every_replay_key_in_the_fixtures_matches_the_current_question" in tests
    assert "replay_keys" in tests and "replay_key(" in tests
