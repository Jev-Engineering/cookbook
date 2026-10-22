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
import types
from pathlib import Path

import nbformat
import pytest
from nbclient.exceptions import DeadKernelError

from jev_cookbook import load_helpers
from jev_cookbook.fixtures import validate_recipe

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "recipes" / "_template"


def load_tool(name):
    spec = importlib.util.spec_from_file_location(f"{name}_for_test", REPO / "tools" / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_module_at(path, name):
    """Import an arbitrary .py file (a scaffolded build_fixtures.py, not under tools/) so its
    functions and module-level values (ROWS, build_responses) are plain Python objects, not
    subprocess output."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


new_recipe = load_tool("new_recipe.py")
execute_notebook = load_tool("execute_notebook.py")
readme_install = load_module_at(
    Path(__file__).with_name("readme_install.py"), "readme_install_for_test"
)
port_collisions = load_module_at(
    Path(__file__).with_name("kernel_port_collisions.py"), "kernel_port_collisions_for_test"
)

executor_budget = load_module_at(
    Path(__file__).with_name("executor_budget.py"), "executor_budget_for_test"
)

# The timeout of the subprocess tests below, so that a hang is a failure rather than a stalled
# suite. tests/executor_budget.py has the arithmetic: the tool's own permitted waits (a silent
# kernel's 180 seconds on each of its 2 starts, quick-exit starts, the warm-up), and no more than
# the CI test job leaves once the rest of the suite has run (#117, #328).
SLOW_START = executor_budget.SLOW_START
QUICK_START = executor_budget.QUICK_START
HANG_GUARD = executor_budget.hang_guard(execute_notebook)


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
        "side_effects.json",
        "tests/test_helpers.py",
        "tests/test_build_fixtures.py",
    }


@pytest.mark.parametrize("mode", new_recipe.MODES)
def test_the_scaffold_writes_a_side_effects_declaration_with_a_placeholder_reason(
    catalog, recipes, mode
):
    """#327: a new recipe starts with a ``side_effects.json`` it must edit, not with nothing to
    forget. The placeholder is a ``none`` declaration whose reason carries the scaffold's TODO
    marker, so ``grep -rn TODO`` lists it with everything else the builder still owes."""
    _, recipe = entry(catalog, 31)
    new_recipe.scaffold(31, catalog, recipes, mode)
    text = (recipes / recipe["slug"] / "side_effects.json").read_text("utf-8")
    assert text.endswith("\n") and "\r" not in text
    declaration = json.loads(text)
    assert set(declaration) == {"schema", "none"} and declaration["schema"] == 1
    assert "TODO" in declaration["none"]
    assert "TODO" in text.splitlines()[2]  # a grep for TODO lists the line to rewrite


def test_the_command_line_names_the_side_effects_file_among_the_todo_files(catalog, recipes):
    _, recipe = entry(catalog, 31)
    assert run(31, catalog, recipes) == 0
    todo_files = {
        p.name
        for p in (recipes / recipe["slug"]).rglob("*")
        if p.is_file() and "TODO" in p.read_text("utf-8")
    }
    assert "side_effects.json" in todo_files


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
            # tests/test_build_fixtures.py is emitted complete: it already works against a
            # correct build_fixtures.py, with nothing left for the builder to fill in, so unlike
            # every other scaffolded file it carries no TODO.
            if path.name != "test_build_fixtures.py":
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


@pytest.mark.parametrize("bad", ["0", "101", "-1", "abc", "1.5", "", "٣"])
def test_a_number_outside_1_to_100_is_a_usage_error(bad, catalog, recipes):
    with pytest.raises(SystemExit) as stop:
        run(bad, catalog, recipes)
    assert stop.value.code == 2
    assert not recipes.exists()


def test_recipe_100_scaffolds_without_inventing_an_issue(catalog, recipes, capsys):
    _, recipe = entry(catalog, 100)
    assert recipe["issue"] is None
    assert run(100, catalog, recipes) == 0
    assert "No assigned recipe issue" in capsys.readouterr().out
    folder = recipes / "100-multimodal-agent-handoff-verification"
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    nbformat.validate(nb)
    assert "Recipe 100" in nb.cells[0].source
    assert "run_header(\n    100," in nb.cells[2].source
    readme = (folder / "README.md").read_text("utf-8")
    assert f"recipes/{recipe['slug']}" in readme
    assert "issues/100" not in readme
    assert "Closes #100" not in readme
    assert all(not c.outputs for c in nb.cells if c.cell_type == "code")


@pytest.mark.parametrize("slug", ["../escape", "0100-test", "101-test", "99-wrong-rank"])
def test_invalid_catalog_slug_writes_nothing(catalog, recipes, slug, capsys):
    data, recipe = entry(catalog, 100)
    recipe["slug"] = slug
    catalog.write_text(json.dumps(data), encoding="utf-8")
    assert run(100, catalog, recipes) == 1
    assert "invalid catalog slug" in capsys.readouterr().err
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
    assert len(list(recipes.iterdir())) == 100
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


SCRIPTED_HELPERS = """
from jev_cookbook import Choice

SEED = 7


def build_state(fields):
    return {"text": fields["text"]}


def build_questions():
    return {"pick": Choice(instructions="Which one?", criteria={"a": "first", "b": "second"})}


def script(state, questions, rng):
    return {"pick": {"a": 0.2 + rng.random(), "b": 1.0}}
"""

SCRIPTED_ROWS = (
    'ROWS = [("v1", "validation", {"text": "x"}, "a"), ("t1", "test", {"text": "y"}, "b"), '
    '("d1", "demo", {"text": "z"}, None)]'
)


def scaffold_scripted(catalog, recipes, number=36):
    _, recipe = entry(catalog, number)
    assert (
        new_recipe.main(
            [
                str(number),
                "--mode",
                "scripted",
                "--catalog",
                str(catalog),
                "--recipes-dir",
                str(recipes),
            ]
        )
        == 0
    )
    folder = recipes / recipe["slug"]
    (folder / "helpers.py").write_text(SCRIPTED_HELPERS.lstrip(), encoding="utf-8", newline="\n")
    build = (folder / "build_fixtures.py").read_text("utf-8")
    start = build.index("ROWS = []")
    end = build.index("\n", start)
    build = build[:start] + SCRIPTED_ROWS + build[end:]
    (folder / "build_fixtures.py").write_text(build, encoding="utf-8", newline="\n")
    return folder


def run_generated_tests(folder):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(folder)]
        + [str(folder / "tests")],
        cwd=folder,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_a_scripted_scaffold_runs_from_the_scaffold_to_a_byte_identical_notebook(catalog, recipes):
    folder = scaffold_scripted(catalog, recipes)
    scaffold_only = {p.name for p in folder.iterdir()}
    assert "fixtures" not in scaffold_only or not any((folder / "fixtures").iterdir())
    # A scripted recipe has no responses.json and no --force/refusal logic for the guard tests
    # to exercise, so the scaffolder does not emit tests/test_build_fixtures.py for it.
    assert {p.name for p in (folder / "tests").iterdir()} == {"test_helpers.py"}
    subprocess.run([sys.executable, str(folder / "build_fixtures.py")], check=True, cwd=recipes)
    fixtures = folder / "fixtures"
    assert {p.name for p in fixtures.iterdir()} == {"inputs.jsonl", "labels.jsonl"}
    for line in (fixtures / "inputs.jsonl").read_text("utf-8").splitlines():
        assert json.loads(line)["replay_keys"] == []
    report = validate_recipe(folder)
    assert not report and report.mode == "scripted"

    execute_notebook.execute(folder)
    first = (folder / "notebook.ipynb").read_bytes()
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    streams = "".join(
        o.get("text", "") for c in nb.cells if c.cell_type == "code" for o in c.outputs
    )
    assert "scripted backend" in streams
    assert "Provenance: scripted. Not measured live: a pipeline check" in streams
    execute_notebook.execute(folder)
    assert (folder / "notebook.ipynb").read_bytes() == first

    result = run_generated_tests(folder)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_scripted_scaffold_has_the_script_hook_and_no_replay_machinery(catalog, recipes):
    _, recipe = entry(catalog, 36)
    new_recipe.main(
        ["36", "--mode", "scripted", "--catalog", str(catalog), "--recipes-dir", str(recipes)]
    )
    folder = recipes / recipe["slug"]
    helpers_source = (folder / "helpers.py").read_text("utf-8")
    assert "def script(state, questions, rng):" in helpers_source and "SEED = 0" in helpers_source
    build = (folder / "build_fixtures.py").read_text("utf-8")
    for name in ("answers_for", "replay_key(", "DecisionResult", "Provenance"):
        assert name not in build
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    setup = next(c for c in nb.cells if c.get("id") == "setup").source
    assert "get_backend(script=helpers.script, seed=helpers.SEED)" in setup
    assert "responses_path" not in setup and "backend=backend" in setup
    # The replay scaffold is unchanged by the option.
    other = recipes / "other"
    new_recipe.main(["36", "--catalog", str(catalog), "--recipes-dir", str(other)])
    replay_setup = next(
        c
        for c in nbformat.read(other / recipe["slug"] / "notebook.ipynb", as_version=4).cells
        if c.get("id") == "setup"
    ).source
    assert "get_backend(fixtures=responses_path())" in replay_setup
    assert "def script" not in (other / recipe["slug"] / "helpers.py").read_text("utf-8")


def test_the_generated_test_fails_when_the_script_is_not_deterministic(catalog, recipes):
    folder = scaffold_scripted(catalog, recipes)
    subprocess.run([sys.executable, str(folder / "build_fixtures.py")], check=True, cwd=recipes)
    assert run_generated_tests(folder).returncode == 0
    mutated = SCRIPTED_HELPERS.replace(
        "from jev_cookbook import Choice", "import random\n\nfrom jev_cookbook import Choice"
    ).replace("0.2 + rng.random()", "0.2 + random.random()")
    assert mutated != SCRIPTED_HELPERS
    (folder / "helpers.py").write_text(mutated.lstrip(), encoding="utf-8", newline="\n")
    result = run_generated_tests(folder)
    assert result.returncode != 0, result.stdout
    assert "test_every_replay_key_in_the_fixtures_matches_the_current_question" in result.stdout


def test_an_unknown_scaffold_mode_is_rejected(catalog, recipes):
    with pytest.raises(SystemExit):
        new_recipe.main(["1", "--mode", "live", "--catalog", str(catalog)])
    with pytest.raises(new_recipe.ScaffoldError):
        new_recipe.scaffold(1, catalog, recipes, mode="live")
    assert not recipes.exists()


@pytest.mark.parametrize("value", ["0", "-5", "x"])
def test_a_timeout_below_one_is_a_usage_error(tmp_path, value, capsys):
    folder = tmp_path / "t"
    write_notebook(folder, "pass")
    with pytest.raises(SystemExit) as exit_info:
        execute_notebook.main([str(folder), "--timeout", value])
    assert exit_info.value.code == 2
    assert "--timeout" in capsys.readouterr().err


def test_the_state_cell_says_what_to_do_when_there_is_no_demo_example(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    nb = nbformat.read(recipes / recipe["slug"] / "notebook.ipynb", as_version=4)
    state = next(c for c in nb.cells if c.get("id") == "state").source
    assert "StopIteration" not in state and "next(" not in state
    assert "add at least one demo example" in state
    namespace = {"examples": [], "helpers": None}
    with pytest.raises(ValueError, match="add at least one demo example"):
        exec(state, namespace)  # noqa: S102 - runs the scaffold's own cell on an empty list


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
    assert os.environ["JEV_COOKBOOK_LIVE"] == "1"  # the parent's environment is untouched
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


def test_the_stderr_failure_message_shows_what_was_written_redacted_and_bounded(tmp_path, capsys):
    """#287: the log used to say a cell wrote to stderr and not what, so a flake could not be
    diagnosed. The text is shown, with paths and long unbroken runs replaced and a size cap."""
    secret = "A" * 40
    code = (
        "import sys\n"
        "print('Matplotlib is building the font cache; this may take a moment.', file=sys.stderr)\n"
        "print('opened /home/runner/work/secret-project/file.txt and C:\\\\Users\\\\me\\\\x.py',\n"
        "      file=sys.stderr)\n"
        f"print('key {secret}', file=sys.stderr)\n" + "print('filler', file=sys.stderr)\n" * 20
    )
    folder = tmp_path / "noisy"
    write_notebook(folder, code)
    assert execute_notebook.main([str(folder)]) == 1
    err = capsys.readouterr().err
    assert "Matplotlib is building the font cache; this may take a moment." in err
    assert "<path>" in err
    for leaked in ("/home/runner", "secret-project", "C:\\Users", secret):
        assert leaked not in err
    assert "<redacted>" in err
    assert "[... truncated]" in err
    assert err.count("filler") <= execute_notebook.STDERR_EXCERPT_LINES


def test_stderr_excerpt_is_bounded_in_lines_and_characters():
    many_lines = "\n".join(f"line {i}" for i in range(50))
    out = execute_notebook.stderr_excerpt(many_lines)
    assert out.count("\n") <= execute_notebook.STDERR_EXCERPT_LINES
    assert out.endswith("[... truncated]")
    long_line = "word " * 500
    out = execute_notebook.stderr_excerpt(long_line)
    marker = f"\n{execute_notebook.STDERR_LINE_PREFIX}{execute_notebook.STDERR_TRUNCATED}"
    assert len(out) <= execute_notebook.STDERR_EXCERPT_CHARS + len(marker)
    assert out.endswith("[... truncated]")
    assert (
        execute_notebook.stderr_excerpt("\x1b[31mred\x1b[0m\x07 text")
        == execute_notebook.STDERR_LINE_PREFIX + "red text"
    )


WORKFLOW_COMMANDS = (
    "::error::boom",
    "   ::warning::indented with spaces",
    "\t::notice::indented with a tab",
    "::stop-commands::token",
    "::add-mask::value",
)


def test_no_line_of_the_stderr_excerpt_can_be_read_as_a_workflow_command():
    """#316: the excerpt is a cell's text in a log that GitHub Actions scans for ``::command::``
    lines. The runner trims leading whitespace before it looks, so indenting is not enough: each
    line must start with something that is not whitespace and not ``::``."""
    out = execute_notebook.stderr_excerpt("\n".join(WORKFLOW_COMMANDS))
    assert out.count("\n") == len(WORKFLOW_COMMANDS) - 1
    for line in out.splitlines():
        assert line.startswith(execute_notebook.STDERR_LINE_PREFIX), line
        assert not line.lstrip().startswith("::"), line
    assert "boom" in out  # the text is still shown, only inert


def test_the_stderr_failure_message_has_no_workflow_command_line(tmp_path, capsys):
    code = "import sys\n" + "".join(
        f"print({command!r}, file=sys.stderr)\n" for command in WORKFLOW_COMMANDS
    )
    folder = tmp_path / "commands"
    write_notebook(folder, code)
    assert execute_notebook.main([str(folder)]) == 1
    err = capsys.readouterr().err
    assert "boom" in err and "wrote to stderr" in err
    for line in err.splitlines():
        assert not line.lstrip().startswith("::"), line


@pytest.mark.parametrize(
    "text, hidden",
    [
        (r"C:\Program Files\Python314\Lib\secretproj\x.py", ["Files", "secretproj", "Python314"]),
        ("C:/Program Files/secretproj/x.py", ["Files", "secretproj"]),
        (r"c:\Users\Jane Doe", ["Jane", "Doe"]),
        (r"\\fileserver\share\secretproj\x.py", ["fileserver", "share", "secretproj"]),
        (r"\\?\C:\Users\Jane Doe\My Folder\x.py", ["Jane", "Doe", "Folder"]),
        (r"\\wsl$\Ubuntu\home\me\secretproj", ["Ubuntu", "secretproj"]),
        (r"opened D:\Work Files\secretproj\a.py now", ["Work", "Files", "secretproj"]),
    ],
)
def test_windows_and_unc_paths_are_redacted_whole_even_with_spaces(text, hidden):
    out = execute_notebook.stderr_excerpt(text)
    assert "<path>" in out, out
    for word in hidden:
        assert word not in out, (word, out)


def test_a_quoted_windows_path_leaves_the_rest_of_the_line_readable():
    out = execute_notebook.stderr_excerpt(
        'File "C:\\Users\\Jane Doe\\x.py", line 3, in <module>\nOSError: bad'
    )
    assert "Jane" not in out and "Doe" not in out
    assert '"<path>", line 3, in <module>' in out
    assert "OSError: bad" in out


def test_text_that_only_looks_like_a_drive_is_not_redacted():
    """A letter and a colon at the end of a word (``NOTE:/``) is not a drive."""
    assert "NOTE:" in execute_notebook.stderr_excerpt("see NOTE: this, and NOTE:/x")


# A sitecustomize that makes matplotlib's "building the font cache" timer (5 seconds on a slow
# runner) fire immediately, so a build that happens inside a cell is reproduced on any machine.
IMMEDIATE_FONT_CACHE_NOTICE = """\
import threading

_Timer = threading.Timer


def _timer(interval, *args, **kwargs):
    return _Timer(0 if interval == 5 else interval, *args, **kwargs)


threading.Timer = _timer
"""

FONT_CACHE_CELL = "import matplotlib.font_manager"


def font_cache_environment(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "sitecustomize.py").write_text(IMMEDIATE_FONT_CACHE_NOTICE, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(hooks))
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mplconfig"))


def test_a_font_cache_built_inside_a_cell_is_the_stderr_write_of_287(tmp_path, monkeypatch, capsys):
    """The reproduction, and the negative control for the next test: with no warm-up and an empty
    cache, the cell builds the cache, matplotlib logs its notice to stderr and the run fails."""
    pytest.importorskip("matplotlib")
    font_cache_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(execute_notebook, "warm_font_cache", lambda environment: None)
    folder = tmp_path / "cold"
    write_notebook(folder, FONT_CACHE_CELL)
    assert execute_notebook.main([str(folder)]) == 1
    assert "building the font cache" in capsys.readouterr().err


def test_the_font_cache_is_built_before_the_kernel_so_no_cell_writes_the_notice(
    tmp_path, monkeypatch, capsys
):
    """#287's fix: the same cold cache, the same cell, the same timer, and the run passes because
    the executor built the cache first. The stderr rule itself is not involved."""
    pytest.importorskip("matplotlib")
    font_cache_environment(tmp_path, monkeypatch)
    folder = tmp_path / "warm"
    write_notebook(folder, FONT_CACHE_CELL)
    assert execute_notebook.main([str(folder)]) == 0, capsys.readouterr().err
    assert list((tmp_path / "mplconfig").glob("fontlist-*.json"))


def test_the_warm_up_uses_the_kernels_environment_and_never_fails_the_run(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs, command=command)
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(execute_notebook.subprocess, "run", fake_run)
    environment = {"HOME": "/kernel/home", "MPLCONFIGDIR": "/kernel/mpl"}
    execute_notebook.warm_font_cache(environment)  # a timeout is absorbed
    assert seen["env"] == environment
    assert seen["command"][-1] == execute_notebook.FONT_CACHE_WARMUP

    def missing(command, **kwargs):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(execute_notebook.subprocess, "run", missing)
    execute_notebook.warm_font_cache(environment)  # an unrunnable interpreter is absorbed


def run_warm_up_with(monkeypatch, outcome):
    """``warm_font_cache`` with ``subprocess.run`` replaced: ``outcome`` is an exception to raise
    or a CompletedProcess to return. What it printed is read by the caller from capsys."""

    def fake_run(command, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(execute_notebook.subprocess, "run", fake_run)
    execute_notebook.warm_font_cache({})


def completed(returncode, stderr=b""):
    return subprocess.CompletedProcess(["python"], returncode, b"", stderr)


def test_a_timed_out_warm_up_leaves_one_line_in_the_log(monkeypatch, capsys):
    run_warm_up_with(monkeypatch, subprocess.TimeoutExpired(["python"], 1))
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and err.startswith("font-cache warm-up timed out after ")


def test_a_failed_warm_up_leaves_one_line_with_its_status_and_last_message(monkeypatch, capsys):
    stderr = b'Traceback (most recent call last):\n  File "/srv/secret/x.py"\nImportError: boom\n'
    run_warm_up_with(monkeypatch, completed(3, stderr))
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert err.startswith("font-cache warm-up exited with status 3: ImportError: boom")
    assert "secret" not in err


def test_a_warm_up_that_cannot_run_leaves_one_line_naming_the_error_not_its_text(
    monkeypatch, capsys
):
    run_warm_up_with(monkeypatch, FileNotFoundError("/home/someone/python"))
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "could not run (FileNotFoundError)" in err
    assert "someone" not in err


def test_a_warm_up_note_is_bounded_and_redacted(monkeypatch, capsys):
    run_warm_up_with(monkeypatch, completed(1, b"error /home/x/y " + b"word " * 200 + b"\n"))
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    frame = execute_notebook.font_cache_warmup_note("exited with status 1: ")
    assert len(err) == len(frame) + execute_notebook.WARM_NOTE_CHARS + len("\n")
    assert "/home" not in err and "error <path> word" in err


def test_a_clean_warm_up_prints_nothing(monkeypatch, capsys):
    run_warm_up_with(monkeypatch, completed(0, b"harmless chatter"))
    assert capsys.readouterr().err == ""


def test_the_warm_up_interpreter_runs_without_the_user_site(monkeypatch, capsys):
    """#316: ``-s``, like the CI sandbox's own interpreter. Checked on a real process that fails
    (and so says so) unless the user site directory is off."""
    monkeypatch.setattr(
        execute_notebook,
        "FONT_CACHE_WARMUP",
        "import sys; sys.exit(0 if sys.flags.no_user_site else 7)",
    )
    monkeypatch.delenv("PYTHONNOUSERSITE", raising=False)
    execute_notebook.warm_font_cache(dict(os.environ))
    assert capsys.readouterr().err == ""

    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return completed(0)

    monkeypatch.setattr(execute_notebook.subprocess, "run", fake_run)
    execute_notebook.warm_font_cache({})
    assert seen["command"][1] == "-s"


def test_execute_warms_the_cache_with_the_scrubbed_kernel_environment(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(execute_notebook, "warm_font_cache", seen.append)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "placeholder")
    folder = tmp_path / "plain"
    write_notebook(folder, "x = 1")
    assert execute_notebook.main([str(folder)]) == 0
    assert len(seen) == 1
    assert "JEV_COOKBOOK_LIVE" not in seen[0] and "TYPESAFE_API_KEY" not in seen[0]
    assert seen[0].get("PATH") == os.environ.get("PATH")


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


# A kernel is a child process that inherits this process's stderr, so what it prints when it
# fails to start (a ZMQError traceback for a port it could not bind, say) lands in the stderr of
# the tool that started it. The tool absorbs that failure by starting another kernel, but its
# stderr still holds the dead one's traceback, and a test asserting on the tool's own output (no
# traceback, no exit-time noise) then fails for a reason that is not the tool's (#328). The tests
# that run the tool in a subprocess therefore give its kernels a log file of their own, so
# ``result.stderr`` is the tool's alone; the kernels' output is kept and shown when a test fails.
RUN_APART_FROM_ITS_KERNELS = """
import jupyter_client.provisioning.local_provisioner as provisioner
kernel_log = open({log!r}, "w", encoding="utf-8")
launch = provisioner.launch_kernel
def launch_with_a_stderr_of_its_own(cmd, **kwargs):
    return launch(cmd, stderr=kernel_log, **kwargs)
provisioner.launch_kernel = launch_with_a_stderr_of_its_own
"""

RUN_THE_TOOL_AS_A_SCRIPT = """
import runpy, sys
sys.argv = [{tool!r}, *{arguments!r}]
runpy.run_path({tool!r}, run_name="__main__")
"""

LOSE_PORTS_FIRST = """
import sys
sys.path.insert(0, {tests!r})
import kernel_port_collisions
kernel_port_collisions.PortCollisions({collisions}).install()
"""


def run_script(tmp_path, body, **fields):
    """Run ``body`` as a script in a subprocess, with its kernels' stderr in a file. Returns the
    completed process (its ``stderr`` is the script's own) and the kernels' stderr."""
    log = tmp_path / "kernels.log"
    script = tmp_path / "script.py"
    source = (RUN_APART_FROM_ITS_KERNELS + body).format(log=str(log), **fields)
    script.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=HANG_GUARD
    )
    return result, log.read_text("utf-8") if log.exists() else ""


def run_tool(tmp_path, *arguments, collisions=0):
    """``python tools/execute_notebook.py <arguments>`` in a subprocess, apart from its kernels,
    the first ``collisions`` of which lose the race for their port (kernel_port_collisions.py)."""
    body = (LOSE_PORTS_FIRST if collisions else "") + RUN_THE_TOOL_AS_A_SCRIPT
    return run_script(
        tmp_path,
        body,
        tool=str(REPO / "tools" / "execute_notebook.py"),
        arguments=[str(argument) for argument in arguments],
        tests=str(Path(__file__).resolve().parent),
        collisions=collisions,
    )


# Run with and without a start that loses its port: the second kernel's run must read the same.
THE_FIRST_START_MAY_LOSE_ITS_PORT = pytest.mark.parametrize(
    "collisions", [pytest.param(0, id="clean-start"), pytest.param(1, id="lost-port")]
)


@THE_FIRST_START_MAY_LOSE_ITS_PORT
def test_a_dead_kernel_fails_the_run_quickly_and_leaves_the_file(tmp_path, collisions):
    """A cell that kills the kernel used to hang the executor forever, the cell timeout
    notwithstanding. It runs in a subprocess so that a regression is a failure, not a hang."""
    folder = tmp_path / "dead"
    write_notebook(folder, "import os\nos._exit(1)")
    before = (folder / "notebook.ipynb").read_bytes()
    result, kernels = run_tool(tmp_path, folder, collisions=collisions)
    assert result.returncode == 1, (result.stderr, kernels)
    assert "the kernel died" in result.stderr, (result.stderr, kernels)
    assert (folder / "notebook.ipynb").read_bytes() == before


@THE_FIRST_START_MAY_LOSE_ITS_PORT
def test_a_looping_cell_hits_the_timeout_with_one_line_and_leaves_the_file(tmp_path, collisions):
    folder = tmp_path / "loop"
    write_notebook(folder, "while True:\n    pass")
    before = (folder / "notebook.ipynb").read_bytes()
    result, kernels = run_tool(tmp_path, folder, "--timeout", 3, collisions=collisions)
    assert result.returncode == 1, (result.stderr, kernels)
    assert "ran longer than 3 s" in result.stderr, (result.stderr, kernels)
    assert "Traceback" not in result.stderr, (result.stderr, kernels)
    if collisions:  # the first kernel did fail on its port, and said so in its own stderr
        assert "in use" in kernels, kernels
        assert "starting a fresh one" in result.stderr, result.stderr
    assert (folder / "notebook.ipynb").read_bytes() == before


def test_a_kernel_that_never_starts_exits_1_with_one_line(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "nostart"
    write_notebook(folder, "1 + 1")
    before = (folder / "notebook.ipynb").read_bytes()

    def refuse(self, *args, **kwargs):
        raise RuntimeError("Kernel didn't respond in 60 seconds")

    monkeypatch.setattr(execute_notebook.NotebookClient, "execute", refuse)
    assert execute_notebook.main([str(folder)]) == 1
    assert "the kernel did not start" in capsys.readouterr().err
    assert (folder / "notebook.ipynb").read_bytes() == before


# Each way a kernel fails to start, with how many starts the tool makes before it gives up. These
# are written out here, not read from the tool, so that raising a budget is a decision made twice.
START_MESSAGES = [
    pytest.param("Kernel didn't respond in 60 seconds", 2, id="alive-but-silent"),
    pytest.param("Kernel died before replying to kernel_info", 4, id="exited-at-once"),
]


def test_the_start_budgets_are_the_documented_ones():
    assert execute_notebook.START_ATTEMPTS == {SLOW_START: 2, QUICK_START: 4}
    assert set(execute_notebook.START_FAILURES) == {SLOW_START, QUICK_START}


def test_every_hang_guard_fits_in_the_ci_test_job():
    """A hang guard longer than the CI job that runs it never fires: the job is killed first and
    the hang is not a named failure. Each guard, and the room the rest of the suite leaves, is read
    from the tool's constants and from .github/workflows/ci.yml, not copied."""
    job = executor_budget.ci_test_job_seconds()
    guards = executor_budget.every_guard(execute_notebook)
    assert HANG_GUARD == guards["tests/test_new_recipe.py"]
    for user, guard in guards.items():
        assert executor_budget.fits_in_the_ci_test_job(guard), (user, guard, job)
        # and it still covers what the tool may legitimately take on a silent kernel
        assert guard > execute_notebook.START_WAIT * execute_notebook.START_ATTEMPTS[SLOW_START]
        if user != "tests/test_new_recipe.py":  # the other users wait with the same derivation
            source = (REPO / user).read_text(encoding="utf-8")
            assert "timeout=EXECUTE_TIMEOUT" in source and "hang_guard(" in source, user


def test_the_ci_fit_check_fails_for_a_guard_that_is_too_long():
    """The check above is not vacuous: the guard this PR started from (1020 s) does not fit."""
    assert not executor_budget.fits_in_the_ci_test_job(1020)
    assert not executor_budget.fits_in_the_ci_test_job(
        executor_budget.hang_guard(
            types.SimpleNamespace(START_WAIT=400, START_ATTEMPTS=execute_notebook.START_ATTEMPTS)
        )
    )
    assert executor_budget.fits_in_the_ci_test_job(HANG_GUARD)


def lose_starts(monkeypatch, *failures):
    """Make the kernel start fail with each of ``failures`` in turn (a message, or an exception),
    then run for real. Returns the list that counts the starts."""
    real = execute_notebook.NotebookClient.execute
    starts = []

    def execute(self, *args, **kwargs):
        index = len(starts)
        starts.append(index)
        if index < len(failures):
            failure = failures[index]
            raise failure if isinstance(failure, BaseException) else RuntimeError(failure)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(execute_notebook.NotebookClient, "execute", execute)
    return starts


@pytest.mark.parametrize(("message", "attempts"), START_MESSAGES)
def test_a_kernel_start_failure_is_retried_and_then_the_notebook_runs(
    tmp_path, monkeypatch, capsys, message, attempts
):
    """Every start but the last fails and the run still succeeds: the budget is spent in full."""
    folder = tmp_path / "flaky"
    write_notebook(folder, "print('ran')")
    starts = lose_starts(monkeypatch, *[message] * (attempts - 1))
    assert execute_notebook.main([str(folder)]) == 0
    assert len(starts) == attempts
    err = capsys.readouterr().err
    assert err.count("starting a fresh one") == attempts - 1  # a retry is never silent
    assert f"(attempt {attempts} of {attempts})" in err
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    assert nb.cells[0].outputs[0].text == "ran\n"


@pytest.mark.parametrize(("message", "attempts"), START_MESSAGES)
def test_a_kernel_that_never_starts_is_tried_exactly_as_often_as_its_failure_allows(
    tmp_path, monkeypatch, capsys, message, attempts
):
    folder = tmp_path / "nostart2"
    write_notebook(folder, "1 + 1")
    before = (folder / "notebook.ipynb").read_bytes()
    starts = lose_starts(monkeypatch, *[message] * (attempts + 3))
    assert execute_notebook.main([str(folder)]) == 1
    assert len(starts) == attempts
    err = capsys.readouterr().err
    assert "the kernel did not start" in err
    assert message in err  # the kernel's own last message is not replaced
    assert f"{attempts} start attempts failed" in err
    assert (folder / "notebook.ipynb").read_bytes() == before


@pytest.mark.parametrize(
    ("failures", "status"),
    [
        pytest.param([SLOW_START, QUICK_START, QUICK_START, QUICK_START], 0, id="one-silent"),
        pytest.param([QUICK_START] * 3 + [SLOW_START, SLOW_START], 1, id="two-silent"),
    ],
)
def test_the_two_budgets_are_counted_separately(tmp_path, monkeypatch, failures, status):
    """A silent kernel costs START_WAIT seconds a time and is tried twice; a kernel that exits at
    once is tried four times. One kind's failures do not use up the other's budget, so a silent
    start after three quick exits is still tried again, and a second silent one ends the run
    though a quick exit would have had one start left."""
    folder = tmp_path / "mixed"
    write_notebook(folder, "print('ran')")
    starts = lose_starts(monkeypatch, *failures)
    assert execute_notebook.main([str(folder)]) == status
    # one-silent: four starts fail and the fifth runs; two-silent: all five fail
    assert len(starts) == 5


def test_a_kernel_that_died_after_starting_is_never_retried(tmp_path, monkeypatch, capsys):
    """``DeadKernelError`` is a ``RuntimeError`` and may carry the start-up wording; it means a
    running kernel died, perhaps in a cell, so it ends the run at once."""
    folder = tmp_path / "died"
    write_notebook(folder, "1 + 1")
    starts = lose_starts(monkeypatch, DeadKernelError(f"{QUICK_START} to kernel_info"))
    assert execute_notebook.main([str(folder)]) == 1
    assert len(starts) == 1
    assert "the kernel died" in capsys.readouterr().err


def test_an_unrecognised_start_up_error_is_never_retried(tmp_path, monkeypatch):
    folder = tmp_path / "unknown"
    write_notebook(folder, "1 + 1")
    starts = lose_starts(monkeypatch, "the disk is on fire")
    with pytest.raises(RuntimeError, match="the disk is on fire"):
        execute_notebook.main([str(folder)])
    assert len(starts) == 1


@pytest.fixture
def lost_ports():
    """Make kernel starts lose the race for a port, for real: set ``lost_ports.left`` to the number
    of the next starts that get their shell port taken between jupyter_client choosing it and the
    kernel binding it, which is what happens on Windows under load (``ZMQError: Address in use``).
    See tests/kernel_port_collisions.py."""
    collisions = port_collisions.PortCollisions(0).install()
    yield collisions
    collisions.uninstall()


@pytest.mark.parametrize("collisions", [1, 3])
def test_a_port_lost_to_another_process_is_absorbed_by_starting_a_fresh_kernel(
    tmp_path, lost_ports, capsys, collisions
):
    """With one collision the second start works; with three in a row the fourth does, which the
    two starts the tool used to make could not."""
    folder = tmp_path / "taken"
    write_notebook(folder, "print('ran')")
    lost_ports.left = collisions
    assert execute_notebook.main([str(folder)]) == 0
    err = capsys.readouterr().err
    assert err.count("Kernel died before replying") == collisions  # each taken port killed a kernel
    assert err.count("starting a fresh one") == collisions
    assert len(lost_ports.starts) == collisions + 1
    assert len(set(lost_ports.starts)) == collisions + 1  # each start drew new ports
    nb = nbformat.read(folder / "notebook.ipynb", as_version=4)
    assert nb.cells[0].outputs[0].text == "ran\n"


def test_a_port_that_is_never_free_still_fails_after_the_last_attempt(tmp_path, lost_ports, capsys):
    """The retry does not hide a kernel that cannot start: when every attempt loses its port the
    run fails, with the kernel's own error, a count, and the notebook untouched."""
    folder = tmp_path / "never"
    write_notebook(folder, "print('ran')")
    before = (folder / "notebook.ipynb").read_bytes()
    lost_ports.left = 99
    assert execute_notebook.main([str(folder)]) == 1
    err = capsys.readouterr().err
    attempts = execute_notebook.START_ATTEMPTS[QUICK_START]
    assert len(lost_ports.starts) == attempts
    assert "the kernel did not start" in err
    assert f"{attempts} start attempts failed" in err
    assert (folder / "notebook.ipynb").read_bytes() == before


PROBE = """
import sys
sys.path.insert(0, {tools!r})
import execute_notebook as tool
from jupyter_client.asynchronous.client import AsyncKernelClient
real = AsyncKernelClient.wait_for_ready
calls = []
async def lose_the_first(self, *args, **kwargs):
    calls.append(1)
    if len(calls) == 1:
        raise RuntimeError("Kernel died before replying to kernel_info")
    return await real(self, *args, **kwargs)
AsyncKernelClient.wait_for_ready = lose_the_first
sys.exit(tool.main([{folder!r}]))
"""


def test_a_failed_start_leaves_no_exit_time_noise(tmp_path):
    """After a failed first start and a successful retry, the process exits silently: nbclient's
    exit-time cleanup hook for the failed client (an AssertionError at exit) is unregistered.

    The probe fails its first start on purpose, so only the retries are left to absorb a real
    failure; the kernels' own stderr is kept apart from the probe's (``run_script``), because a
    kernel that lost a port prints a traceback that is not this process's exit noise."""
    folder = tmp_path / "quiet"
    write_notebook(folder, "1 + 1")
    result, kernels = run_script(tmp_path, PROBE, tools=str(REPO / "tools"), folder=str(folder))
    assert result.returncode == 0, (result.stderr, kernels)
    assert "AssertionError" not in result.stderr, (result.stderr, kernels)
    assert "atexit" not in result.stderr, (result.stderr, kernels)


def test_a_failing_cell_is_never_retried(tmp_path, monkeypatch):
    folder = tmp_path / "failsonce"
    write_notebook(folder, "raise ValueError('nope')")
    real = execute_notebook.NotebookClient.execute
    calls = []

    def count(self, *args, **kwargs):
        calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(execute_notebook.NotebookClient, "execute", count)
    assert execute_notebook.main([str(folder)]) == 1
    assert len(calls) == 1


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
    assert 'scored = [e for e in examples if e.split not in ("train", "demo")]' in setup
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
    assert "recorded_dates" in measured and "backend.model" in measured
    # "N:" must be checked against the OFFLINE branch specifically (the same split
    # tests/test_template.py's own measured-cell check uses on the template): the live (else)
    # branch always prints "N:", so asserting "N:" in measured as a whole is satisfied by the
    # live branch regardless of what the offline branch does -- exactly the defect #215 found,
    # where the offline branch printed no N at all and this assertion still passed.
    offline_branch = measured.split("else:")[0]
    assert "N:" in offline_branch, "the offline branch must print N too, not only the live branch"
    # The sentence follows the backend mode: scripted says pipeline check too, never "synthetic".
    assert "Provenance: synthetic" not in measured and "{backend.mode}. Not measured" in measured
    state = next(c for c in nb.cells if c.get("id") == "state").source
    assert 'e.split == "demo"' in state and "examples[0]" not in state


def test_the_fixture_size_hint_follows_the_contract_at_every_level():
    assert "tens of examples" in new_recipe.rows_hint(1)
    assert "tens of examples" in new_recipe.rows_hint(2)
    for level in (3, 4, 5):
        hint = new_recipe.rows_hint(level)
        assert "more than at levels" not in hint and "state the size" in hint


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


def test_the_scaffold_emits_a_stored_answers_guard_for_replay(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    tests = (recipes / recipe["slug"] / "tests" / "test_helpers.py").read_text("utf-8")
    assert "def test_stored_answers_are_not_all_right" in tests
    assert "select_confidence_threshold" in tests
    assert (
        "TODO"
        not in tests.split("def test_stored_answers_are_not_all_right")[1].split("\ndef ", 1)[0]
    )


def test_the_scripted_scaffold_has_no_stored_answers_guard(catalog, recipes):
    # A scripted recipe has no responses.json, so there is nothing for this guard to check.
    _, recipe = entry(catalog, 36)
    new_recipe.main(
        ["36", "--mode", "scripted", "--catalog", str(catalog), "--recipes-dir", str(recipes)]
    )
    tests = (recipes / recipe["slug"] / "tests" / "test_helpers.py").read_text("utf-8")
    assert "test_stored_answers_are_not_all_right" not in tests


def test_the_scaffolded_stored_answers_guard_passes_against_a_filled_in_recipe(catalog, recipes):
    """The emitted test_stored_answers_are_not_all_right must not just exist: once a builder has
    filled in helpers.py, build_fixtures.py and run it, the emitted test actually passes against
    MINIMAL_REPLAY_ROWS (t1 is wrong and, at the frozen threshold, confidently so)."""
    folder = scaffold_replay_with_build_script(catalog, recipes, number=9)
    subprocess.run([sys.executable, str(folder / "build_fixtures.py")], check=True, cwd=recipes)
    result = run_generated_tests(folder)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_scaffolded_stored_answers_guard_fails_when_no_wrong_answer_is_confident(
    catalog, recipes
):
    """The guard must actually discriminate, not pass regardless of the fixtures: lower t1's
    spec so it is still wrong but below the frozen threshold, and confirm the generated test
    fails rather than passing vacuously."""
    folder = scaffold_replay_with_build_script(catalog, recipes, number=10)
    build = (folder / "build_fixtures.py").read_text("utf-8")
    weakened = build.replace(
        MINIMAL_REPLAY_ROWS, MINIMAL_REPLAY_ROWS.replace('"b", 0.95)', '"b", 0.6)')
    )
    assert weakened != build, "MINIMAL_REPLAY_ROWS no longer matches; update the replacement above"
    (folder / "build_fixtures.py").write_text(weakened, encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(folder / "build_fixtures.py")], check=True, cwd=recipes)
    failed = run_generated_tests(folder)
    assert failed.returncode != 0
    assert "test_stored_answers_are_not_all_right" in failed.stdout


def test_the_replay_scaffold_tests_have_no_scripted_machinery(catalog, recipes):
    """A replay recipe never defines helpers.script or helpers.SEED; the scaffolder knows the
    mode up front, so the generated test file for --mode replay (the default) must not carry
    the scripted branch (or the runtime mode check that used to select it)."""
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    tests = (recipes / recipe["slug"] / "tests" / "test_helpers.py").read_text("utf-8")
    for dead in ("ScriptedBackend", "helpers.script", "helpers.SEED", "validate_recipe"):
        assert dead not in tests, dead


def test_the_scripted_scaffold_tests_have_no_replay_machinery(catalog, recipes):
    _, recipe = entry(catalog, 36)
    new_recipe.main(
        ["36", "--mode", "scripted", "--catalog", str(catalog), "--recipes-dir", str(recipes)]
    )
    tests = (recipes / recipe["slug"] / "tests" / "test_helpers.py").read_text("utf-8")
    for dead in ("replay_key(", "responses_path", "validate_recipe"):
        assert dead not in tests, dead
    assert "ScriptedBackend" in tests and "helpers.SEED" in tests


def test_the_scaffold_readme_live_section_states_the_budget_and_env_var(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    readme = (recipes / recipe["slug"] / "README.md").read_text("utf-8")
    section = readme.split("## Switch to live")[1].split("## What was and was not measured")[0]
    assert "JEV_COOKBOOK_LIVE_MAX_REQUESTS" in section
    assert "25" in section
    assert "TODO" in section


MINIMAL_REPLAY_HELPERS = """
from jev_cookbook import Choice


def build_state(fields):
    return {"text": fields["text"]}


def build_questions():
    return {"pick": Choice(instructions="Which one?", criteria={"a": "first", "b": "second"})}
"""

MINIMAL_REPLAY_ROWS = (
    'ROWS = [("v1", "validation", {"text": "x"}, "a", 0.9), '
    '("v2", "validation", {"text": "x2"}, "b", 0.1), '
    '("t1", "test", {"text": "y"}, "b", 0.95), '
    '("d1", "demo", {"text": "z"}, None, 0.5)]'
)


def scaffold_replay_with_build_script(catalog, recipes, number=2):
    """Scaffold a replay recipe and fill in just enough of helpers.py and build_fixtures.py to
    run build_fixtures.py end to end."""
    _, recipe = entry(catalog, number)
    assert run(number, catalog, recipes) == 0
    folder = recipes / recipe["slug"]
    (folder / "helpers.py").write_text(
        MINIMAL_REPLAY_HELPERS.lstrip(), encoding="utf-8", newline="\n"
    )
    build = (folder / "build_fixtures.py").read_text("utf-8")
    build = build.replace(
        "from jev_cookbook import DecisionResult, Provenance, dump_responses, load_helpers, replay_key",
        "from jev_cookbook import ChoiceAnswer, DecisionResult, Provenance, dump_responses, "
        "load_helpers, replay_key",
    )
    build = build.replace(
        '    raise NotImplementedError("TODO: build the typed answers from the row\'s spec")',
        '    return {"pick": ChoiceAnswer.from_probabilities('
        '{"a": spec, "b": 1 - spec}, provenance)}',
    )
    start = build.index("ROWS = []")
    end = build.index("\n", start)
    build = build[:start] + MINIMAL_REPLAY_ROWS + build[end:]
    (folder / "build_fixtures.py").write_text(build, encoding="utf-8", newline="\n")
    return folder


def test_build_fixtures_refuses_to_overwrite_a_recorded_responses_file(catalog, recipes):
    folder = scaffold_replay_with_build_script(catalog, recipes)
    script = folder / "build_fixtures.py"
    first = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=recipes
    )
    assert first.returncode == 0, first.stderr

    responses = folder / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    assert data, "the fixtures should hold at least one response"
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    before = responses.read_bytes()

    refused = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=recipes
    )
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True, cwd=recipes
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_build_fixtures_refusal_warns_when_rows_desynchronised_the_fixtures(catalog, recipes):
    """Rewriting inputs.jsonl/labels.jsonl while refusing to touch responses.json (the split
    this issue asks for) can leave the three files out of sync: if a ROWS field changed, the
    freshly computed replay keys may no longer be in the kept responses.json. The refusal
    message should say so."""
    folder = scaffold_replay_with_build_script(catalog, recipes, number=6)
    script = folder / "build_fixtures.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=recipes)

    responses = folder / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    # Change a ROWS field (the text), which changes the replay key it computes.
    build = script.read_text("utf-8")
    build = build.replace('{"text": "x"}', '{"text": "x changed"}')
    script.write_text(build, encoding="utf-8", newline="\n")

    refused = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=recipes
    )
    assert refused.returncode != 0
    assert "desynchronised" in refused.stderr
    assert "--force" in refused.stderr and "record" in refused.stderr


def test_is_recorded_does_not_crash_on_a_non_object_responses_file(catalog, recipes):
    folder = scaffold_replay_with_build_script(catalog, recipes, number=7)
    script = folder / "build_fixtures.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=recipes)

    responses = folder / "fixtures" / "responses.json"
    for bad in ("[]", "null", '"not an object"', "[1, 2, 3]"):
        responses.write_text(bad, encoding="utf-8", newline="\n")
        result = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, cwd=recipes
        )
        assert "Traceback" not in result.stderr, (bad, result.stderr)


def test_build_fixtures_rewrites_inputs_and_labels_even_when_responses_is_refused(catalog, recipes):
    folder = scaffold_replay_with_build_script(catalog, recipes, number=3)
    script = folder / "build_fixtures.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=recipes)

    responses = folder / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    inputs = folder / "fixtures" / "inputs.jsonl"
    inputs.unlink()
    refused = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=recipes
    )
    assert refused.returncode != 0
    assert inputs.exists(), "inputs.jsonl is regenerated even when responses.json is refused"


def test_build_fixtures_writes_responses_byte_identical_to_the_recorders_writer(catalog, recipes):
    """jev_cookbook.dump_responses (what the live recorder writes with) is
    json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\\n": only the
    top-level keys are sorted, every nested dict keeps DecisionResult.to_dict()'s own field
    order. json.dumps(..., sort_keys=True) sorts every nested dict too, which disagrees with
    the recorder on every response and roughly quadruples the diff a recording produces. The
    builder must match the recorder exactly, not just agree with it on top-level order.

    Comparing the written file against dump_responses(json.loads(raw)) (re-dumping the file's own
    parsed content) cannot catch a sort_keys=True regression: json.loads preserves whatever
    nested order the file already has, and dump_responses only re-sorts the top level, so that
    round trip passes regardless of which writer produced the file. Instead, import the
    freshly scaffolded build_fixtures.py and compare against dump_responses of what build_responses
    computes directly from ROWS, independent of what main() actually wrote."""
    from jev_cookbook import dump_responses

    folder = scaffold_replay_with_build_script(catalog, recipes, number=4)
    script = folder / "build_fixtures.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=recipes)
    raw = (folder / "fixtures" / "responses.json").read_text("utf-8")

    module = load_module_at(script, "scaffolded_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == dump_responses(module.build_responses(module.ROWS))


# The install command the `Notebook (<recipe>)` job in .github/workflows/notebooks.yml runs, and
# the one docs/recipe-template.md step 6 documents as reproducing committed outputs byte for
# byte: one wording everywhere (issue #137). ".[dev,ml]" is the old, no longer accurate wording
# for that paragraph; since #238 it is the right one for the tests' install line.
INSTALL_LINE = 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt'


def test_the_scaffold_install_line_matches_ci_and_the_docs(catalog, recipes):
    workflow = (REPO / ".github" / "workflows" / "notebooks.yml").read_text("utf-8")
    assert INSTALL_LINE in workflow, "the Notebook job's install line moved; update INSTALL_LINE"
    docs = (REPO / "docs" / "recipe-template.md").read_text("utf-8")
    assert INSTALL_LINE in docs
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    readme = (recipes / recipe["slug"] / "README.md").read_text("utf-8")
    assert INSTALL_LINE in readme
    assert readme_install.combined_reproduction_installs(readme) == []


def test_the_scaffold_readme_install_rule_accepts_the_tests_install_and_refuses_the_old_one(
    catalog, recipes
):
    """#238: ``.[dev,ml]`` in the scaffold's output is fine as the install for the tests and still
    refused in the paragraph that reproduces committed outputs (what ``".[dev,ml]" not in readme``
    used to forbid everywhere)."""
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    readme = (recipes / recipe["slug"] / "README.md").read_text("utf-8")
    documented = readme_install.with_documented_test_install(readme)
    assert readme_install.combined_reproduction_installs(documented) == []
    old = readme_install.with_pre_162_reproduction_install(readme)
    assert len(readme_install.combined_reproduction_installs(old)) == 1


def test_the_scaffold_readme_has_pull_request_rules_matching_contributing(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    readme = (recipes / recipe["slug"] / "README.md").read_text("utf-8")
    assert "## Pull request rules" in readme
    section = readme.split("## Pull request rules")[1].split("## Sources")[0]
    # The generated-README exception (CONTRIBUTING.md): the integration worker regenerates the
    # root README inside the same recipe pull request, not in a separate one and not "never".
    assert "inside this same pull request" in section
    assert "never by this recipe's own pull request" not in section
    assert f"recipes/{recipe['slug']}/" in section
    assert "CONTRIBUTING.md" in section


def test_the_scaffold_readme_states_the_catalog_check_conditionally(catalog, recipes):
    """PR #193 review (comment 6085949784): the generated sentence must describe the
    pre-publication state conditionally, so it stays true once the recipe is merged and the
    catalog has actually been regenerated for it -- not a bare, unconditional "is expected to
    be red" that would still read as current on a published recipe's README."""
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    readme = (recipes / recipe["slug"] / "README.md").read_text("utf-8")
    section = readme.split("## Pull request rules")[1].split("## Sources")[0]
    flat = " ".join(section.split())
    assert "While this recipe remains unpublished" in flat
    assert "is expected to be red on its pull request" in flat
    assert "once the catalog is regenerated for it, the check turns green" in flat


def test_the_scaffold_emits_the_build_fixtures_guard_tests_for_replay(catalog, recipes):
    _, recipe = entry(catalog, 1)
    run(1, catalog, recipes)
    tests = (recipes / recipe["slug"] / "tests" / "test_build_fixtures.py").read_text("utf-8")
    for name in (
        "def test_the_committed_responses_are_byte_identical_to_the_recorders_writer",
        "def test_build_fixtures_separates_inputs_labels_from_responses",
        "def test_the_generator_reproduces_the_committed_fixtures",
    ):
        assert name in tests
    # The refusal test also proves inputs.jsonl/labels.jsonl are regenerated from ROWS during a
    # refused run, not merely left untouched (#137 comment 6071431315).
    assert 'inputs_path.write_bytes(b"corrupted")' in tests
    assert "build_inputs_and_labels(module.ROWS)" in tests


def test_the_scaffolded_build_fixtures_test_file_passes_against_a_filled_in_recipe(
    catalog, recipes
):
    """The emitted tests/test_build_fixtures.py must not just exist: once a builder has filled
    in helpers.py and build_fixtures.py and run it, the emitted file actually passes."""
    folder = scaffold_replay_with_build_script(catalog, recipes, number=8)
    subprocess.run([sys.executable, str(folder / "build_fixtures.py")], check=True, cwd=recipes)
    result = run_generated_tests(folder)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout and "failed" not in result.stdout
