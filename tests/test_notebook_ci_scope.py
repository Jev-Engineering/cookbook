"""tools/check_recipe_scope.py against temporary git repositories.

Each test builds a small repository whose ``main`` holds the real README and catalog, then a
branch with the change under test, and runs the check on ``main...branch``. Modes and types that
Windows cannot create on disk (symlinks, executables, submodules) are written straight into the
index with ``git update-index --cacheinfo``.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "check_recipe_scope.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # a dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


scope = load("check_recipe_scope_for_test", TOOL)
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text(encoding="utf-8"))
README = (REPO / "README.md").read_text(encoding="utf-8")
SLUG1 = CATALOG["recipes"][0]["slug"]
SLUG2 = CATALOG["recipes"][1]["slug"]
BODY1 = "Closes #1\n\nThe checklist."
BRANCH1 = f"recipe/{SLUG1}"
NOTEBOOK = '{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n'


class Repo:
    """A throwaway repository driven by plumbing commands."""

    def __init__(self, path):
        self.path = path
        path.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args, data=None):
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            input=data,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode()
        return result.stdout.decode().strip()

    def put(self, path, content, mode="100644"):
        data = content.encode("utf-8") if isinstance(content, str) else content
        sha = self.git("hash-object", "-w", "--stdin", data=data)
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{path}")

    def remove(self, path):
        self.git("update-index", "--force-remove", "--", path)

    def move(self, old, new):
        listing = self.git("ls-files", "-s", "--", old).split()
        mode, sha = listing[0], listing[1]
        self.remove(old)
        self.git("update-index", "--add", "--cacheinfo", f"{mode},{sha},{new}")

    def commit(self, message="change"):
        self.git("commit", "-q", "--allow-empty", "-m", message)

    def branch(self, name):
        self.git("checkout", "-q", "-b", name)

    def head_text(self, path):
        return self.git("show", f"HEAD:{path}")


def rendered_readme(published, catalog=CATALOG, base=README):
    """The renderer's output, computed independently of the tool under test."""
    module = load("render_catalog_expected", REPO / "tools" / "render_catalog.py")
    module.is_published = lambda recipe: recipe["slug"] in published
    return module.render(base, catalog)


@pytest.fixture(scope="module")
def base_repo(tmp_path_factory):
    """The base commit on ``main`` and a ``work`` branch checked out; copied for every test."""
    r = Repo(tmp_path_factory.mktemp("scope") / "repo")
    r.put("README.md", README)
    r.put("catalog/recipes.json", json.dumps(CATALOG, indent=2) + "\n")
    r.put("LICENSE", "license\n")
    r.put("pyproject.toml", "[project]\n")
    r.put("src/jev_cookbook/__init__.py", "")
    r.put("tools/render_catalog.py", "# stub\n")
    r.put("tests/test_x.py", "def test_x(): pass\n")
    r.put("docs/guide.md", "guide\n")
    r.put("orchestration/PROMPT.md", "prompt\n")
    r.put(".github/workflows/ci.yml", "name: CI\n")
    r.put(f"recipes/{SLUG1}/README.md", "recipe one\n")
    r.put(f"recipes/{SLUG1}/fixtures/inputs.jsonl", "{}\n")
    r.put(f"recipes/{SLUG1}/helpers.py", "VALUE = 1\n" * 20)
    r.put(f"recipes/{SLUG2}/notebook.ipynb", NOTEBOOK)
    r.put(f"recipes/{SLUG2}/README.md", "recipe two\n")
    r.put("recipes/_template/README.md", "template\n")
    r.commit("base")
    r.branch("work")
    return r


@pytest.fixture
def repo(base_repo, tmp_path):
    """A private copy of the base repository (a repository does not depend on its location)."""
    copy = tmp_path / "repo"
    shutil.copytree(base_repo.path, copy)
    r = Repo.__new__(Repo)
    r.path = copy
    return r


def run_check(repo, branch=BRANCH1, body=BODY1, base="main", head="HEAD"):
    repo.commit()
    return scope.check(repo.path, base, head, branch, body, scope.DEFAULT_REPO)


def reasons(result):
    return "\n".join(result[0])


def accepted(result):
    assert result[0] == [], result[0]
    assert result[1].startswith("recipe pull request for #1")


def rejected(result, *fragments):
    assert result[0], "expected a rejection"
    text = reasons(result)
    for fragment in fragments:
        assert fragment in text, text


# -- accepted -------------------------------------------------------------------------------


def test_new_notebook_with_the_exact_rendered_readme_is_accepted(repo):
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)
    repo.put("README.md", rendered_readme({SLUG1, SLUG2}))
    accepted(run_check(repo))


def test_edits_additions_and_deletions_inside_the_folder_are_accepted(repo):
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)
    repo.put(f"recipes/{SLUG1}/README.md", "recipe one, edited\n")
    repo.put(f"recipes/{SLUG1}/tests/test_helpers.py", "def test(): pass\n")
    repo.remove(f"recipes/{SLUG1}/fixtures/inputs.jsonl")
    accepted(run_check(repo))


def test_deleting_a_symlink_or_executable_inside_the_folder_has_no_resulting_mode(repo):
    # S5: a deletion shows as `:100644 000000 ... D` and is not rejected under the mode rule;
    # whatever the deleted entry was, it leaves no resulting mode.
    repo.put(f"recipes/{SLUG1}/link", "target", mode="120000")
    repo.put(f"recipes/{SLUG1}/run.sh", "x\n", mode="100755")
    repo.commit("base2")
    repo.git("branch", "-f", "main", "HEAD")
    repo.remove(f"recipes/{SLUG1}/link")
    repo.remove(f"recipes/{SLUG1}/run.sh")
    repo.remove(f"recipes/{SLUG1}/helpers.py")
    accepted(run_check(repo))


def test_rename_inside_the_folder_is_accepted(repo):
    repo.move(f"recipes/{SLUG1}/helpers.py", f"recipes/{SLUG1}/tools_helpers.py")
    accepted(run_check(repo))


def test_readme_untouched_is_accepted_even_when_stale(repo):
    # Staleness is the Catalog check's job; the allowlist only constrains what changes.
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)
    accepted(run_check(repo))


def test_foundation_pull_request_is_not_subject_to_the_allowlist(repo):
    repo.put("docs/guide.md", "changed\n")
    repo.put("tools/new.py", "x = 1\n", mode="100755")
    problems, note = run_check(repo, branch="foundation/notebook-ci", body="Closes #69\n")
    assert problems == []
    assert note.startswith("foundation pull request")


def test_foundation_pull_request_mentioning_no_issue_is_accepted(repo):
    repo.put("docs/guide.md", "changed\n")
    problems, note = run_check(repo, branch="foundation/x", body="no closing reference")
    assert problems == [] and note.startswith("foundation")


# -- the five classes of path, and the others -------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        f"recipes/{SLUG2}/README.md",  # another recipe's folder (modify)
        f"recipes/{SLUG2}/new_file.py",  # another recipe's folder (new file)
        "recipes/_template/README.md",
        "recipes/notes.md",  # directly under recipes/
        f"recipes/{SLUG1}x/README.md",  # a folder whose name only starts like the slug
        "LICENSE",  # a root file
        "NEWROOT.txt",  # a new root file
        "docs/guide.md",
        "tests/test_x.py",
        "src/jev_cookbook/__init__.py",
        "tools/render_catalog.py",
        "catalog/recipes.json",
        ".github/workflows/ci.yml",
        "orchestration/PROMPT.md",
        "pyproject.toml",
    ],
)
def test_changes_outside_the_allowlist_are_rejected(repo, path):
    repo.put(path, "changed\n")
    result = run_check(repo)
    rejected(result, "is outside recipes/")
    assert path.replace("\\", "/") in reasons(result)


def test_malformed_catalog_edit_gets_the_path_diagnostic_not_a_crash(repo):
    repo.put("catalog/recipes.json", "{ not json")
    repo.put("README.md", rendered_readme({SLUG1}))
    rejected(run_check(repo), "catalog/recipes.json", "is outside recipes/")


def test_new_file_outside_the_allowed_paths_is_rejected(repo):
    repo.put("recipes/notes/extra.md", "x\n")
    rejected(run_check(repo), "recipes/notes/extra.md")


def test_second_recipe_folder_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)
    repo.put("recipes/03-other/notebook.ipynb", NOTEBOOK)
    rejected(run_check(repo), "recipes/03-other/notebook.ipynb")


def test_deletion_outside_the_folder_is_rejected(repo):
    repo.remove("docs/guide.md")
    rejected(run_check(repo), "docs/guide.md")


def test_deleting_another_recipe_is_rejected(repo):
    repo.remove(f"recipes/{SLUG2}/notebook.ipynb")
    rejected(run_check(repo), f"recipes/{SLUG2}/notebook.ipynb")


def test_rename_out_of_the_folder_is_rejected_on_the_new_path(repo):
    repo.move(f"recipes/{SLUG1}/helpers.py", "docs/helpers.py")
    rejected(run_check(repo), "docs/helpers.py")


def test_rename_into_the_folder_from_outside_is_rejected_on_the_old_path(repo):
    repo.move("docs/guide.md", f"recipes/{SLUG1}/guide.md")
    rejected(run_check(repo), "docs/guide.md")


def test_rename_between_recipe_folders_is_rejected(repo):
    repo.move(f"recipes/{SLUG2}/notebook.ipynb", f"recipes/{SLUG1}/notebook.ipynb")
    rejected(run_check(repo), f"recipes/{SLUG2}/notebook.ipynb")


# -- modes and types inside the folder ---------------------------------------------------------


def test_symlink_inside_the_folder_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/link.md", "../../LICENSE", mode="120000")
    rejected(run_check(repo), "link.md", "120000")


def test_submodule_inside_the_folder_is_rejected(repo):
    sha = repo.git("rev-parse", "HEAD")
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{sha},recipes/{SLUG1}/sub")
    rejected(run_check(repo), "recipes/" + SLUG1 + "/sub", "160000")


def test_new_executable_file_inside_the_folder_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/run.sh", "x\n", mode="100755")
    rejected(run_check(repo), "run.sh", "000000 -> 100755")


def test_mode_change_inside_the_folder_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/helpers.py", "VALUE = 1\n" * 20, mode="100755")
    rejected(run_check(repo), "helpers.py", "100644 -> 100755")


def test_type_change_inside_the_folder_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/helpers.py", "docs/guide.md", mode="120000")
    rejected(run_check(repo), "helpers.py", "status T")


def test_rename_that_changes_the_mode_is_rejected(repo):
    repo.move(f"recipes/{SLUG1}/helpers.py", f"recipes/{SLUG1}/helpers2.py")
    repo.put(f"recipes/{SLUG1}/helpers2.py", "VALUE = 1\n" * 20, mode="100755")
    rejected(run_check(repo), "helpers2.py")


def test_modifying_an_existing_executable_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/run.sh", "x\n", mode="100755")
    repo.commit("base2")
    repo.git("branch", "-f", "main", "HEAD")
    repo.put(f"recipes/{SLUG1}/run.sh", "y\n", mode="100755")
    rejected(run_check(repo), "run.sh", "100755 -> 100755")


# -- README ------------------------------------------------------------------------------------


def published_readme():
    return rendered_readme({SLUG1, SLUG2})


def with_notebook(repo):
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)


def test_readme_prose_edit_is_rejected_even_when_the_regions_are_rendered(repo):
    with_notebook(repo)
    repo.put("README.md", "An unauthorised first line.\n" + published_readme())
    rejected(run_check(repo), "README.md", "does not equal the renderer's output")


def test_readme_marker_edit_is_rejected(repo):
    with_notebook(repo)
    text = published_readme().replace(
        "<!-- catalog:levels:start -->", "<!-- catalog:levels:start --> "
    )
    repo.put("README.md", text)
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_generated_row_edit_is_rejected(repo):
    with_notebook(repo)
    text = published_readme().replace("Open notebook", "Open the notebook", 1)
    repo.put("README.md", text)
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_extra_trailing_newline_is_rejected(repo):
    with_notebook(repo)
    repo.put("README.md", published_readme() + "\n")
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_not_rendered_for_the_new_recipe_is_rejected(repo):
    with_notebook(repo)
    repo.put("README.md", README.replace("coming soon", "complete", 1))
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_rendered_against_the_head_readme_does_not_launder_prose(repo):
    # The head README is edited by hand first, then the regions are rendered over that edit: a
    # self-render check would pass; the base-README comparison must not.
    with_notebook(repo)
    edited = "Hand-written change.\n" + README
    repo.put("README.md", rendered_readme({SLUG1, SLUG2}, base=edited))
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_that_does_not_mark_the_new_recipe_published_is_rejected(repo):
    with_notebook(repo)
    repo.put("README.md", rendered_readme({SLUG2}))  # forgets the head's new notebook
    rejected(run_check(repo), "does not equal the renderer's output")


def test_readme_mode_only_change_with_correct_content_is_rejected(repo):
    with_notebook(repo)
    repo.put("README.md", published_readme(), mode="100755")
    rejected(run_check(repo), "README.md", "100644 -> 100755")


def test_readme_type_change_to_a_symlink_is_rejected(repo):
    repo.put("README.md", "docs/guide.md", mode="120000")
    rejected(run_check(repo), "README.md", "status T")


def test_readme_deletion_is_rejected(repo):
    repo.remove("README.md")
    rejected(run_check(repo), "README.md", "never deleted")


def test_readme_rename_is_rejected(repo):
    repo.move("README.md", f"recipes/{SLUG1}/README.old.md")
    rejected(run_check(repo), "README.md")


def test_readme_content_is_judged_against_base_after_main_moved_on(repo):
    # `base` is the tip of main the branch was updated against: a stale base README fails.
    with_notebook(repo)
    repo.put("README.md", rendered_readme({SLUG1, SLUG2}))
    repo.commit("head")
    repo.git("checkout", "-q", "-f", "main")
    repo.put("README.md", "A new line on main.\n" + README)
    repo.commit("main moved")
    repo.git("checkout", "-q", "-f", "work")
    result = scope.check(repo.path, "main", "work", BRANCH1, BODY1, scope.DEFAULT_REPO)
    rejected(result, "does not equal the renderer's output")


# -- which kind of pull request ----------------------------------------------------------------


def test_recipe_branch_without_a_closing_reference_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo, body="no reference"), "only one recipe marker holds")


def test_closing_reference_without_a_recipe_branch_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo, branch="foundation/sneaky"), "only one recipe marker holds")
    rejected(run_check(repo, branch="fix/recipe-01"), "only one recipe marker holds")


def test_recipe_branch_closing_only_a_non_recipe_issue_is_rejected(repo):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo, body="Closes #61"), "only one recipe marker holds")
    rejected(run_check(repo, body="Closes #0"), "only one recipe marker holds")
    rejected(run_check(repo, body="Closes #69"), "only one recipe marker holds")


def test_branch_slug_must_match_the_catalog_slug_for_the_issue(repo):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo, branch=f"recipe/{SLUG2}"), f"is not recipe/{SLUG1}")
    rejected(run_check(repo, branch="recipe/made-up"), f"is not recipe/{SLUG1}")
    rejected(run_check(repo, branch="recipe/"), f"is not recipe/{SLUG1}")
    rejected(run_check(repo, branch=BRANCH1 + "-2"), f"is not recipe/{SLUG1}")


def test_slug_is_resolved_from_the_issue_not_the_branch(repo):
    # Branch and body agree on recipe 2, but the diff edits recipe 1's folder.
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(
        run_check(repo, branch=f"recipe/{SLUG2}", body="Closes #2"),
        f"recipes/{SLUG1}/README.md",
        "is outside recipes/",
    )


@pytest.mark.parametrize(
    "body",
    [
        "Closes #1 and Closes #2",
        "Closes #1\nFixes #2",
        "closes #1, resolves #3",
        "Closes #1\nResolves #69",
        "Closes #1\nCloses #69",
    ],
)
def test_pull_request_closing_more_than_one_issue_is_rejected(repo, body):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo, body=body), "exactly one issue")


@pytest.mark.parametrize(
    "body",
    [
        "Closes #1",
        "closes #1",
        "CLOSE #1",
        "Closed #1",
        "Fix #1",
        "fixes #1",
        "Fixed: #1",
        "Resolve #1",
        "Resolves #1.",
        "resolved #1",
        "Closes Jev-Engineering/cookbook#1",
        "Closes https://github.com/Jev-Engineering/cookbook/issues/1",
        "Closes #1\nCloses #1",
        "Closes #1\nCloses other-org/other-repo#2",
        "see #2 for context\nCloses #1",
    ],
)
def test_every_closing_keyword_form_marks_a_recipe_pull_request(repo, body):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    accepted(run_check(repo, body=body))


@pytest.mark.parametrize(
    "body",
    ["Closes #1x", "Reopens #1", "disclose #1", "Closes #10", "Closes#1", "Part of #1"],
)
def test_text_that_is_not_a_closing_reference_to_issue_1(repo, body):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    result = run_check(repo, body=body)
    # Either no marker (rejected: the branch alone) or a different recipe, never a pass for #1.
    assert result[0], result


def test_closing_issues_helper():
    closing = scope.closing_issues
    assert closing("Closes #1, closes #2", "o/r") == {1, 2}
    assert closing("Closes #1\nFixes o/r#3\nFixes x/y#4", "o/r") == {1, 3}
    assert closing("Resolves https://github.com/O/R/issues/7", "o/r") == {7}
    assert closing("closes", "o/r") == set()


@pytest.mark.parametrize(
    "text",
    [
        "Closes #１",  # a full-width digit: GitHub closes nothing
        "Closes\n#1",  # the reference is on the next line: GitHub closes nothing
        "Closes:\n#1",
        "Cloſes #1",  # a long s, which Unicode case folding would match to "s"
        "Closes https://github.com/o/r/issues/１",
    ],
)
def test_closing_issues_ignores_what_github_ignores(text):
    assert scope.closing_issues(text, "o/r") == set()
    assert scope.closing_issues("Closes #1", "o/r") == {1}


@pytest.mark.parametrize(
    "text",
    [
        "```\nCloses #1\n```",
        "Intro\n\n```text\nFixes #1\n```\n",
        "~~~\nCloses #1\n~~~",
        "  ```\nCloses #1\n  ```",
        "````\n```\nCloses #1\n```\n````",  # a shorter fence does not close a longer one
        "```\nCloses #1",  # a fence that never closes runs to the end
    ],
)
def test_closing_issues_ignores_a_reference_inside_a_code_fence(text):
    assert scope.closing_issues(text, "o/r") == set()


@pytest.mark.parametrize(
    "text",
    [
        "```\nnote\n```\nCloses #1",  # after the block
        "Closes #1\n```\nFixes #2\n```",  # before it; the one inside does not count
        "    Closes #1",  # an indented block is not a fence
    ],
)
def test_closing_issues_still_counts_a_reference_outside_a_code_fence(text):
    assert scope.closing_issues(text, "o/r") == {1}


@pytest.mark.parametrize(
    "text",
    [
        "`Closes #1`",  # the whole reference inside a single-backtick inline code span
        "``` Closes #1 ```",  # a single line: matching backtick runs make this inline code,
        # not a fence (a fence needs the backtick run alone, at line start, on its own line)
        "Closes `#1`",  # only the reference is inside the span
        "`Closes` #1",  # only the keyword is inside the span
        "See `code\nCloses #1` here",  # a single-backtick span can cross a line (CommonMark);
        # round 4 fixed this (round 3 only stripped a span within one line)
    ],
)
def test_closing_issues_ignores_a_reference_inside_an_inline_code_span(text):
    assert scope.closing_issues(text, "o/r") == set()
    assert scope.closing_issues("Closes #1", "o/r") == {1}


@pytest.mark.parametrize(
    "text",
    [
        "<!-- Closes #1 -->",
        "<!--\nCloses #1\n-->",  # a comment can cross lines too
        "Intro <!-- Closes #1 --> more text",
    ],
)
def test_closing_issues_ignores_a_reference_inside_an_html_comment(text):
    assert scope.closing_issues(text, "o/r") == set()
    assert scope.closing_issues("Closes #1", "o/r") == {1}


def test_a_fenced_reference_alone_does_not_make_a_recipe_pull_request(repo):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    problems, _ = run_check(repo, body="```\nCloses #1\n```\n")
    assert problems and "only one recipe marker holds" in problems[0]


def test_label_escapes_control_characters_and_ansi_escapes():
    # Round 3 escaped non-ASCII bytes but left ASCII control characters untouched, so a crafted
    # path could split a `REJECT:` line into two (a newline) or colour the Actions log (an ANSI
    # escape); both must now come back escaped like a non-ASCII byte would.
    assert scope.label("a\nb") == "a\\x0ab"
    assert scope.label("a\x1b[31mred") == "a\\x1b[31mred"
    assert scope.label("a\tb\rc") == "a\\x09b\\x0dc"
    assert scope.label("plain/recipes/01-slug") == "plain/recipes/01-slug"  # unaffected
    assert scope.label("café") == "caf\\xe9"  # unchanged from round 3's non-ASCII behaviour


def test_label_bounds_long_text():
    long_text = "x" * 150
    result = scope.label(long_text)
    assert len(result) == 100
    assert result.endswith("...")


# -- command line and failure modes ------------------------------------------------------------


def cli(repo, tmp_path, body=BODY1, branch=BRANCH1, base="main", head="HEAD"):
    body_file = tmp_path / "body.txt"
    body_file.write_text(body, encoding="utf-8")
    repo.commit()
    return subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repo",
            str(repo.path),
            "--base",
            base,
            "--head",
            head,
            "--branch",
            branch,
            "--body-file",
            str(body_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes(repo, tmp_path):
    repo.put(f"recipes/{SLUG1}/notebook.ipynb", NOTEBOOK)
    ok = cli(repo, tmp_path)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout.startswith("scope ok: recipe pull request for #1")
    repo.put("docs/guide.md", "changed\n")
    bad = cli(repo, tmp_path)
    assert bad.returncode == 1
    assert "REJECT:" in bad.stdout and "docs/guide.md" in bad.stdout
    foundation = cli(repo, tmp_path, branch="foundation/x", body="")
    assert foundation.returncode == 0
    assert "foundation pull request" in foundation.stdout


def test_cli_cannot_run_exit_status_2(repo, tmp_path):
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    unknown_ref = cli(repo, tmp_path, base="no-such-ref")
    assert unknown_ref.returncode == 2
    assert "could not run" in unknown_ref.stderr
    missing = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--repo",
            str(repo.path),
            "--base",
            "main",
            "--head",
            "HEAD",
            "--branch",
            BRANCH1,
            "--body-file",
            str(tmp_path / "absent.txt"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2


def test_check_fails_closed_when_the_catalog_has_no_entry_for_the_issue(repo):
    catalog = json.loads(json.dumps(CATALOG))
    catalog["recipes"][0].pop("issue")
    repo.put("catalog/recipes.json", json.dumps(catalog))
    repo.commit("catalog without issue 1")
    repo.git("branch", "-f", "main", "HEAD")
    repo.put(f"recipes/{SLUG1}/README.md", "x\n")
    rejected(run_check(repo), "has no recipe in the catalog")


def test_raw_diff_reports_modes_that_name_status_hides(repo):
    repo.put(f"recipes/{SLUG1}/link.md", "t", mode="120000")
    repo.put(f"recipes/{SLUG1}/run.sh", "x\n", mode="100755")
    repo.commit()
    entries = {e.path: e for e in scope.raw_diff(repo.path, "main", "HEAD")}
    assert entries[f"recipes/{SLUG1}/link.md"].new_mode == "120000"
    assert entries[f"recipes/{SLUG1}/run.sh"].new_mode == "100755"
    assert {e.status for e in entries.values()} == {"A"}


def test_raw_diff_lists_both_sides_of_a_rename(repo):
    repo.move(f"recipes/{SLUG1}/helpers.py", "docs/helpers.py")
    repo.commit()
    (entry,) = scope.raw_diff(repo.path, "main", "HEAD")
    assert entry.status == "R"
    assert entry.paths == (f"recipes/{SLUG1}/helpers.py", "docs/helpers.py")


def test_the_real_catalog_numbers_recipes_one_to_sixty_by_issue():
    assert [r["issue"] for r in CATALOG["recipes"]] == list(range(1, 61))
