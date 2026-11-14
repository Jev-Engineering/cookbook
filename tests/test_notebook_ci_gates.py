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


def test_recipe_100_is_discovered_and_selected_in_a_pull_request(tree):
    slug = "100-multimodal-agent-handoff-verification"
    assert selected(tree, lambda r: write(r, f"recipes/{slug}/notebook.ipynb")) == [slug]
    assert slug in selected(tree)


@pytest.mark.parametrize("slug", ["1-short", "0100-padded", "101-too-high", "100-bad_name"])
def test_invalid_numeric_recipe_folder_names_fail_closed(tree, slug):
    write(tree, f"recipes/{slug}/notebook.ipynb")
    with pytest.raises(SystemExit, match="not NN-slug"):
        selected(tree)


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


EVERYTHING = ["01-first", "02-second", "_template"]


def test_push_with_an_unusable_before_selects_everything(tree):
    for before in ("0" * 40, "f" * 40, "no-such-ref"):
        result, names = push_matrix(tree, before, "work", "--push")
        assert result.returncode == 0, result.stderr
        assert names == EVERYTHING, before
        assert "selecting every notebook" in result.stderr


def test_push_with_a_real_before_selects_only_the_changed_recipe(tree):
    write(tree, "recipes/02-second/helpers.py", "x = 1\n")
    write(tree, "README.md", "regenerated\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "recipe")
    result, names = push_matrix(tree, "main", "work", "--push")
    assert result.returncode == 0 and names == ["02-second"], result.stderr


def test_push_that_touches_shared_code_selects_everything(tree):
    write(tree, "recipes/02-second/helpers.py", "x = 1\n")
    write(tree, "docs/guide.md", "changed\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "shared")
    _, names = push_matrix(tree, "main", "work", "--push")
    assert names == EVERYTHING


def test_push_after_a_rewind_selects_everything(tree):
    """`before` is ahead of the new tip (main was reset back): the merge base is the new tip, so a
    three-dot diff is empty and would select nothing."""
    write(tree, "recipes/02-second/helpers.py", "x = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "ahead")
    ahead = git(tree, "rev-parse", "HEAD")
    result, names = push_matrix(tree, ahead, "main", "--push")
    assert result.returncode == 0, result.stderr
    assert names == EVERYTHING
    assert "not an ancestor" in result.stderr
    # What the three-dot diff alone would have said: nothing to run.
    assert notebook_ci.select(tree, ahead, "main") == []


def test_push_after_a_rewrite_selects_everything(tree):
    """`before` is on another line of history (a rewrite): the three-dot diff starts at the old
    merge base and sees only the new line's change, a README, so it would select nothing."""
    write(tree, "recipes/01-first/helpers.py", "x = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "old line")
    old = git(tree, "rev-parse", "HEAD")
    git(tree, "checkout", "-q", "-b", "rewritten", "main")
    write(tree, "README.md", "rewritten\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "new line")
    result, names = push_matrix(tree, old, "rewritten", "--push")
    assert result.returncode == 0, result.stderr
    assert names == EVERYTHING
    assert "not an ancestor" in result.stderr
    assert notebook_ci.select(tree, old, "rewritten") == []


def test_push_diff_is_between_the_two_trees(tree):
    write(tree, "recipes/01-first/helpers.py", "x = 1\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "one")
    assert notebook_ci.changed_paths(tree, "main", "work", "..") == ["recipes/01-first/helpers.py"]


def test_push_needs_a_base(tree):
    result = subprocess.run(
        [sys.executable, str(TOOL), "--root", str(tree), "matrix", "--push"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2


# -- a pull request's merge ref with a stale base.sha (#248) -------------------------------------


def commit_on(root, branch, change, message):
    git(root, "checkout", "-q", branch)
    change(root)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", message)


def pull_request_matrix(root, branch_change, main_change=None, *, merge_ref=True):
    """The matrix CI computes for a pull request that was opened at ``main``'s tip and whose base
    branch then moved on: ``work`` carries ``branch_change`` (made at the stale base), ``main``
    gains ``main_change`` afterwards, and the checkout is the merge commit GitHub builds
    (``refs/pull/N/merge``: a merge of the current ``main`` and ``work``, here a detached HEAD).
    ``stale`` is what ``pull_request.base.sha`` holds. Returns the selected recipe folders."""
    stale = git(root, "rev-parse", "main")
    commit_on(root, "work", branch_change, "the pull request")
    pr_head = git(root, "rev-parse", "work")
    if main_change:
        commit_on(root, "main", main_change, "merged meanwhile")
    git(root, "checkout", "-q", "--detach", "main")
    git(root, "merge", "-q", "--no-ff", "-m", "refs/pull/1/merge", "work")
    flags = ["--merge-ref", "--pr-head", pr_head] if merge_ref else []
    result, names = push_matrix(root, stale, "HEAD", *flags)
    assert result.returncode == 0, result.stderr
    return names


def add_recipe(number_and_slug):
    return writer(f"recipes/{number_and_slug}/notebook.ipynb", NB)


def writer(path, text="x = 1\n"):
    def change(root):
        write(root, path, text)

    return change


def shared_code(root):
    """A commit to the shared code: the three places #304 says its test covers."""
    write(root, "src/jev_cookbook/x.py", "y = 2\n")
    write(root, "tools/new_tool.py", "z = 3\n")
    write(root, "docs/guide.md", "changed\n")


def test_control_without_merge_ref_the_stale_base_selects_a_recipe_merged_since(tree):
    """The reported bug (#248), kept as a control: recipe 04-late merged to main after the pull
    request opened, and against the stale base the merge checkout reports it as changed."""
    own = writer("recipes/01-first/helpers.py")
    late = add_recipe("04-late")
    assert pull_request_matrix(tree, own, late, merge_ref=False) == ["01-first", "04-late"]


def test_merge_ref_ignores_a_recipe_merged_after_the_pull_request_opened(tree):
    own = writer("recipes/01-first/helpers.py")
    assert pull_request_matrix(tree, own, add_recipe("04-late"), merge_ref=True) == ["01-first"]


def test_control_without_merge_ref_shared_code_merged_meanwhile_selects_everything(tree):
    """The expensive case from the issue's second comment, kept as a control: one commit to src/,
    tools/ and docs/ on main after the pull request opened, against the stale base, widens the
    matrix of every open recipe pull request to every notebook."""
    own = writer("recipes/01-first/helpers.py")
    assert pull_request_matrix(tree, own, shared_code, merge_ref=False) == [
        "01-first",
        "02-second",
        "_template",
    ]


def test_merge_ref_ignores_shared_code_merged_after_the_pull_request_opened(tree):
    """The same commit to src/, tools/ and docs/, with --merge-ref: only the own recipe."""
    own = writer("recipes/01-first/helpers.py")
    assert pull_request_matrix(tree, own, shared_code) == ["01-first"]


def test_merge_ref_still_selects_the_pull_requests_own_new_recipe(tree):
    assert pull_request_matrix(tree, add_recipe("05-mine"), add_recipe("04-late")) == ["05-mine"]


def test_merge_ref_still_selects_everything_when_the_pull_request_changes_shared_code(tree):
    def own(root):
        write(root, "recipes/01-first/a.py", "x\n")
        write(root, "tools/execute_notebook.py", "changed\n")

    assert pull_request_matrix(tree, own, add_recipe("04-late")) == [
        "01-first",
        "02-second",
        "04-late",
        "_template",
    ]


def test_merge_ref_still_selects_two_recipes_the_pull_request_touches(tree):
    def own(root):
        write(root, "recipes/01-first/a.py", "x\n")
        write(root, "recipes/02-second/a.py", "x\n")

    assert pull_request_matrix(tree, own, add_recipe("04-late")) == ["01-first", "02-second"]


def test_merge_ref_deleting_a_notebook_still_selects_nothing_to_run(tree):

    def delete(root):
        (root / "recipes/01-first/notebook.ipynb").unlink()

    assert pull_request_matrix(tree, delete, add_recipe("04-late")) == []


def test_merge_ref_readme_only_pull_request_selects_nothing_even_if_main_changed_a_recipe(tree):
    readme = writer("README.md", "from the pull request\n")
    other = writer("recipes/02-second/helpers.py", "later\n")
    assert pull_request_matrix(tree, readme, other) == []


def test_merge_ref_regenerated_readme_does_not_widen_a_recipe_pull_request(tree):
    def own(root):
        write(root, "recipes/01-first/helpers.py", "x = 1\n")
        write(root, "README.md", "regenerated\n")

    def meanwhile(root):
        write(root, "docs/guide.md", "changed\n")
        write(root, "recipes/_template/x.py", "x\n")

    assert pull_request_matrix(tree, own, meanwhile) == ["01-first"]


def test_merge_ref_with_nothing_new_on_main_matches_the_old_selection(tree):
    own = writer("recipes/02-second/helpers.py")
    assert pull_request_matrix(tree, own, None) == ["02-second"]


def test_merge_ref_head_that_is_not_a_merge_commit_falls_back_to_the_given_base(tree):
    """A checkout of the branch itself has one parent. Its first parent is only its previous
    commit and would hide most of the change, so the given base is kept (over-selecting at worst)."""
    stale = git(tree, "rev-parse", "main")
    write(tree, "recipes/01-first/a.py", "x\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "one")
    write(tree, "recipes/02-second/a.py", "x\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "two")
    result, names = push_matrix(tree, stale, "HEAD", "--merge-ref", "--pr-head", "HEAD")
    assert result.returncode == 0, result.stderr
    assert names == ["01-first", "02-second"]
    assert "not a merge commit" in result.stderr


def test_merge_ref_with_an_unreadable_head_is_still_an_error(tree):
    result, _ = push_matrix(tree, "main", "no-such-ref", "--merge-ref", "--pr-head", "main")
    assert result.returncode != 0


def test_merge_ref_is_refused_for_a_push(tree):
    result, _ = push_matrix(tree, "main", "work", "--merge-ref", "--pr-head", "work", "--push")
    assert result.returncode == 2


def test_merge_ref_and_pr_head_go_together(tree):
    """A merge-ref selection that cannot check its head must not run, and a --pr-head that nothing
    uses would pass for a check (#316)."""
    for flags in (["--merge-ref"], ["--pr-head", "work"]):
        result, _ = push_matrix(tree, "main", "work", *flags)
        assert result.returncode == 2, flags
        assert "go together" in result.stderr, flags


@pytest.mark.parametrize("empty", ["", " ", "\t"])
@pytest.mark.parametrize("flags", [["--merge-ref"], []])
def test_an_empty_pr_head_is_a_usage_error_not_a_skipped_check(tree, flags, empty):
    """#316 review: ``--pr-head ""`` is not ``None``, so the pairing guard let it through and the
    check then quietly fell back to the given base. Empty means missing."""
    result, _ = push_matrix(tree, "main", "work", *flags, "--pr-head", empty)
    assert result.returncode == 2, result.stderr
    assert "--pr-head" in result.stderr and "empty" in result.stderr


def branch_that_merged_main(root):
    """What CI would check out if it checked out the pull request's branch instead of its merge
    ref, for a branch that merged ``main`` into itself: a two-parent head whose first parent is the
    branch's own previous commit. Returns (the stale base.sha, the branch tip = the PR head)."""
    stale = git(root, "rev-parse", "main")
    commit_on(root, "work", writer("tools/execute_notebook.py", "changed\n"), "shared code")
    commit_on(root, "work", writer("recipes/01-first/helpers.py"), "own recipe")
    commit_on(root, "main", add_recipe("04-late"), "merged meanwhile")
    git(root, "checkout", "-q", "work")
    git(root, "merge", "-q", "--no-ff", "-m", "merge main into the branch", "main")
    return stale, git(root, "rev-parse", "work")


def test_merge_ref_head_that_is_a_merge_of_main_into_the_branch_is_not_trusted(tree):
    """#316: two parents are not proof of the merge ref. Trusting the first parent here would diff
    only what main gained ("04-late") and miss the branch's own change, which touches shared code
    and so must select every notebook."""
    stale, pr_head = branch_that_merged_main(tree)
    result, names = push_matrix(tree, stale, "HEAD", "--merge-ref", "--pr-head", pr_head)
    assert result.returncode == 0, result.stderr
    assert names == ["01-first", "02-second", "04-late", "_template"]
    assert "second parent is not the pull request head" in result.stderr
    assert "is not a commit in this clone" not in result.stderr


def test_merge_ref_head_whose_second_parent_is_the_pull_request_head_is_trusted(tree):
    """The counterpart, same shape: an actual merge ref (main's tip first, the branch second)."""
    stale = git(tree, "rev-parse", "main")
    commit_on(tree, "work", writer("recipes/01-first/helpers.py"), "own recipe")
    pr_head = git(tree, "rev-parse", "work")
    commit_on(tree, "main", add_recipe("04-late"), "merged meanwhile")
    git(tree, "checkout", "-q", "--detach", "main")
    git(tree, "merge", "-q", "--no-ff", "-m", "refs/pull/1/merge", "work")
    result, names = push_matrix(tree, stale, "HEAD", "--merge-ref", "--pr-head", pr_head)
    assert result.returncode == 0, result.stderr
    assert names == ["01-first"]
    assert "diffing against the given base" not in result.stderr


@pytest.mark.parametrize("pr_head", ["0" * 40, "f" * 40, "no-such-ref"])
def test_merge_ref_with_an_unknown_pull_request_head_keeps_the_given_base(tree, pr_head):
    """A --pr-head this clone does not have cannot confirm anything: over-select, never less."""
    stale = git(tree, "rev-parse", "main")
    commit_on(tree, "work", writer("recipes/01-first/helpers.py"), "own recipe")
    commit_on(tree, "main", add_recipe("04-late"), "merged meanwhile")
    git(tree, "checkout", "-q", "--detach", "main")
    git(tree, "merge", "-q", "--no-ff", "-m", "refs/pull/1/merge", "work")
    result, names = push_matrix(tree, stale, "HEAD", "--merge-ref", "--pr-head", pr_head)
    assert result.returncode == 0, result.stderr
    assert names == ["01-first", "04-late"]
    # The realistic way the check silently stops applying in CI (a head this clone cannot see) must
    # not read like a real mismatch of the merge ref's shape.
    assert "is not a commit in this clone" in result.stderr
    assert "second parent is not" not in result.stderr


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
