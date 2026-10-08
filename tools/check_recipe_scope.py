"""Scope check for recipe pull requests (#69): the allowlist in CONTRIBUTING.md, enforced.

    python tools/check_recipe_scope.py --base origin/main --head HEAD \\
        --branch recipe/01-sentiment-classification --body-file pr-body.txt

``--base`` is the current tip of ``main`` the branch was updated against, ``--head`` the pull
request head, ``--branch`` the head branch name, ``--body-file`` a file holding the pull request
description. ``--repo`` is a git directory (default: the current one) and ``--github-repo`` the
``owner/name`` that issue references are matched against (default ``Jev-Engineering/cookbook``).
Nothing is read from the working tree except the renderer next to this file: every other fact
comes from git objects of ``--base`` and ``--head``.

Exit status: 0 accepted (a recipe pull request inside the allowlist, or a foundation pull
request, to which the allowlist does not apply), 1 rejected (one ``REJECT:`` line per problem),
2 the check could not run. It fails closed: anything it cannot decide is a rejection.

Which kind of pull request is it? A recipe pull request has BOTH markers: the branch is
``recipe/<slug>`` and the description has a closing reference (``Closes``, ``Fixes``,
``Resolves`` and their other forms; one inside a fenced code block, an inline code span (even one
that spans several lines) or an HTML comment does not count, as GitHub renders and links nothing
written in any of the three) to an issue of this repository numbered 1 to 60. A pull request with
neither marker is a foundation pull request. One marker without the other is rejected, as is a
``<slug>`` that is not the catalog slug of the issue, a pull request that closes more than one
issue of this repository, and a closing reference to an issue of this repository outside 1 to 60
next to a recipe one.

The allowlist, on ``git diff --raw -M -z base...head`` (``--name-status`` hides modes and types):

* every path of every entry (both the old and the new path of a rename) is under
  ``recipes/<slug>/`` or is exactly ``README.md``;
* inside ``recipes/<slug>/``: a deletion is allowed (it has no resulting mode); an addition must
  be mode 100644; a modification must be 100644 to 100644; a rename must be 100644 on both
  sides; a type change, a symlink (120000), a submodule (160000), any mode change and any other
  status (copy, unmerged, unknown) is rejected;
* ``README.md`` may only be modified, 100644 to 100644, and must equal
  ``render(<base README.md>, <head catalog/recipes.json>)`` byte for byte, with the head's
  ``recipes/`` tree deciding which recipes are published. The README is rendered from the BASE
  README, never from the head's own, so a prose or marker edit outside the generated regions is
  a rejection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = "Jev-Engineering/cookbook"
RECIPE_ISSUES = range(1, 61)
REGULAR = "100644"
MISSING = "000000"
BRANCH_PREFIX = "recipe/"

# As GitHub reads a closing reference: an ASCII keyword (so Unicode case folding cannot make
# "Cloſes" one), ASCII digits, and the reference on the same line as the keyword.
KEYWORD = r"(?a:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
REFERENCE = (
    r"(?:https?://github\.com/(?P<url_repo>[\w.-]+/[\w.-]+)/issues/(?P<url_n>[0-9]+)(?!\w)"
    r"|(?P<repo>[\w.-]+/[\w.-]+)?#(?P<n>[0-9]+)(?!\w))"
)
CLOSING = re.compile(rf"(?<![\w-]){KEYWORD}(?![\w-])[ \t]*:?[ \t]+{REFERENCE}", re.IGNORECASE)


FENCE = re.compile(r"[ ]{0,3}(?P<mark>`{3,}|~{3,})(?P<info>.*)")


def without_code_fences(body: str) -> str:
    """``body`` with fenced code blocks removed, as GitHub links nothing written inside one.

    A fence is three or more backticks or tildes, indented by at most three spaces; it closes at a
    line of the same character, at least as long, with nothing but spaces after it, and a fence
    that never closes runs to the end of the text (CommonMark).
    """
    kept = []
    fence = None  # (character, length) while inside a fenced block
    for line in body.splitlines():
        match = FENCE.fullmatch(line)
        if fence is None:
            if match and not (match.group("mark")[0] == "`" and "`" in match.group("info")):
                fence = (match.group("mark")[0], len(match.group("mark")))
                continue
            kept.append(line)
        elif match and match.group("mark")[0] == fence[0]:
            if len(match.group("mark")) >= fence[1] and not match.group("info").strip():
                fence = None
    return "\n".join(kept)


INLINE_CODE = re.compile(r"(?P<ticks>`+)(?:(?!(?P=ticks)).)*?(?P=ticks)", re.DOTALL)


def without_inline_code(body: str) -> str:
    """``body`` with inline code spans removed, as GitHub links nothing written inside one.

    An inline code span is a run of one or more backticks, content containing no same-length
    backtick run, then a closing run of the same length (CommonMark) — and, unlike a fence, it is
    not anchored to the start of a line, but it still can cross one: GitHub renders ``See `code``
    on one line and `` Closes #1` here`` on the next as a single code span wrapping both. The
    removal therefore runs over the whole body (``re.DOTALL``), not line by line; ``CLOSING``
    still requires the keyword and its reference to share one line on what is left.
    """
    return INLINE_CODE.sub("", body)


HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def without_html_comments(body: str) -> str:
    """``body`` with HTML comments removed, as GitHub renders (and so links) nothing inside one."""
    return HTML_COMMENT.sub("", body)


class CannotRun(Exception):
    """The check could not be evaluated (git failed, an input is unreadable)."""


def git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()[:300]
        raise CannotRun(f"git {' '.join(args[:3])} failed: {message}")
    return result.stdout


def resolve(repo: Path, ref: str) -> str:
    return (
        git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
    )


def closing_issues(body: str, github_repo: str) -> set[int]:
    """Numbers of the issues of ``github_repo`` that ``body`` closes (every GitHub keyword form)."""
    wanted = github_repo.lower()
    numbers = set()
    text = without_inline_code(without_html_comments(without_code_fences(body)))
    for match in CLOSING.finditer(text):
        repo = match.group("url_repo") or match.group("repo")
        if repo is not None and repo.lower() != wanted:
            continue
        numbers.add(int(match.group("url_n") or match.group("n")))
    return numbers


@dataclass(frozen=True)
class Entry:
    """One line of ``git diff --raw -M -z``."""

    old_mode: str
    new_mode: str
    status: str
    paths: tuple[str, ...]

    @property
    def path(self) -> str:
        return self.paths[-1]


def raw_diff(repo: Path, base: str, head: str) -> list[Entry]:
    out = git(
        repo,
        "diff",
        "--raw",
        "-M",
        "-z",
        "--no-ext-diff",
        "--no-textconv",
        "--ignore-submodules=none",
        f"{base}...{head}",
    )
    tokens = out.split(b"\0")
    if tokens and tokens[-1] == b"":
        tokens.pop()
    entries = []
    i = 0
    while i < len(tokens):
        meta = tokens[i].decode("ascii", "replace")
        match = re.fullmatch(r":(\d{6}) (\d{6}) [0-9a-f]+ [0-9a-f]+ ([A-Z])\d*", meta)
        if not match:
            raise CannotRun(f"unreadable raw diff entry {meta[:60]!r}")
        status = match.group(3)
        count = 2 if status in "RC" else 1
        raw_paths = tokens[i + 1 : i + 1 + count]
        if len(raw_paths) != count:
            raise CannotRun("truncated raw diff")
        paths = tuple(p.decode("utf-8", "surrogateescape") for p in raw_paths)
        entries.append(Entry(match.group(1), match.group(2), status, paths))
        i += 1 + count
    return entries


def in_scope(path: str, slug: str) -> bool:
    return path == "README.md" or path.startswith(f"recipes/{slug}/")


_LABEL_SAFE = frozenset(string.printable) - frozenset("\t\n\r\x0b\x0c")


def _escaped_char(char: str) -> str:
    """One non-safe character, escaped the way ``str.encode("ascii", "backslashreplace")`` would
    escape a non-ASCII one: ``\\xHH``, ``\\uHHHH`` or ``\\UHHHHHHHH`` by code point size."""
    code = ord(char)
    if code <= 0xFF:
        return f"\\x{code:02x}"
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    return f"\\U{code:08x}"


def label(path: str) -> str:
    """A path for a message: only printable, visible ASCII characters, bounded.

    Round 3 escaped non-ASCII bytes but left every ASCII control character alone, so
    ``label("a\\nb")`` kept its newline and ``label("a\\x1b[31mred")`` kept its escape — either
    could split a ``REJECT:`` line into two or colour the Actions log from a crafted path. Every
    character outside ``string.printable``, and every control character still inside it (tab,
    newline, carriage return, vertical tab, form feed), is escaped instead of passed through.
    """
    text = "".join(c if c in _LABEL_SAFE else _escaped_char(c) for c in path)
    return text if len(text) <= 100 else text[:97] + "..."


def judge_entry(entry: Entry, slug: str) -> list[str]:
    """Rejections for one diff entry (paths, types, modes). README content is judged apart."""
    where = " -> ".join(label(p) for p in entry.paths)
    problems = [
        f"{where}: {label(p)} is outside recipes/{slug}/ and is not README.md"
        for p in entry.paths
        if not in_scope(p, slug)
    ]
    if problems:
        return problems
    modes = f"{entry.old_mode} -> {entry.new_mode}"
    if "README.md" in entry.paths:
        ok = entry.status == "M" and entry.old_mode == REGULAR and entry.new_mode == REGULAR
        if ok:
            return []
        return [
            f"README.md: status {entry.status}, modes {modes}; it may only be modified as a "
            f"regular file ({REGULAR} to {REGULAR}), never deleted, renamed, retyped or re-moded"
        ]
    status = entry.status
    if status == "D":
        return []  # a deletion has no resulting mode
    if status == "A":
        ok = entry.new_mode == REGULAR
    elif status == "M":
        ok = entry.old_mode == REGULAR and entry.new_mode == REGULAR
    elif status == "R":
        ok = entry.old_mode == REGULAR and entry.new_mode == REGULAR
    else:
        return [f"{where}: status {status} ({modes}) is not allowed (type change or unknown)"]
    if ok:
        return []
    return [
        f"{where}: status {status}, modes {modes}; every new or resulting mode must be {REGULAR}"
    ]


def load_renderer() -> ModuleType:
    """A private copy of ``tools/render_catalog.py`` (so its ``is_published`` can be replaced)."""
    spec = importlib.util.spec_from_file_location(
        "_scope_render_catalog", HERE / "render_catalog.py"
    )
    if spec is None or spec.loader is None:
        raise CannotRun("cannot load tools/render_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def readme_problems(repo: Path, base: str, head: str) -> list[str]:
    """``README.md`` at ``head`` must equal the renderer's output for the BASE README."""
    renderer = load_renderer()

    def is_published(recipe: dict[str, Any]) -> bool:
        path = f"recipes/{recipe['slug']}/notebook.ipynb"
        listing = git(repo, "ls-tree", "-z", head, "--", path)
        fields = listing.split(b"\t", 1)[0].split()
        return len(fields) == 3 and fields[1] == b"blob"

    renderer.is_published = is_published
    try:
        base_readme = git(repo, "show", f"{base}:README.md").decode("utf-8")
        head_readme = git(repo, "show", f"{head}:README.md")
        catalog = json.loads(git(repo, "show", f"{head}:catalog/recipes.json").decode("utf-8"))
        expected = renderer.render(base_readme, catalog).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        return [f"README.md: cannot compute the expected README ({type(error).__name__})"]
    except SystemExit as error:
        return [f"README.md: cannot compute the expected README ({error})"]
    if head_readme != expected:
        return [
            "README.md: does not equal the renderer's output for the base README and the head "
            "catalog (only the generated regions may change, exactly as rendered)"
        ]
    return []


def catalog_slug(repo: Path, base: str, number: int) -> str | None:
    catalog = json.loads(git(repo, "show", f"{base}:catalog/recipes.json").decode("utf-8"))
    for recipe in catalog["recipes"]:
        if recipe.get("issue") == number:
            return recipe.get("slug")
    return None


def check(
    repo: Path, base_ref: str, head_ref: str, branch: str, body: str, github_repo: str
) -> tuple[list[str], str]:
    """(rejections, note). A note says which kind of pull request this was."""
    closed = closing_issues(body, github_repo)
    recipe_numbers = sorted(n for n in closed if n in RECIPE_ISSUES)
    branch_marker = branch.startswith(BRANCH_PREFIX)
    ref_marker = bool(recipe_numbers)
    if not branch_marker and not ref_marker:
        return [], "foundation pull request: the recipe allowlist does not apply"
    problems = []
    if branch_marker != ref_marker:
        have = "the branch is recipe/<slug>" if branch_marker else "a closing reference is #1-#60"
        lack = (
            "no closing reference to an issue 1 to 60"
            if branch_marker
            else "the branch is not recipe/<slug>"
        )
        return [f"only one recipe marker holds ({have}; {lack}); both are required"], ""
    if len(closed) != 1:
        listing = ", ".join(f"#{n}" for n in sorted(closed))
        return [
            f"a recipe pull request must close exactly one issue, this one closes {listing}"
        ], ""
    number = recipe_numbers[0]
    base, head = resolve(repo, base_ref), resolve(repo, head_ref)
    slug = catalog_slug(repo, base, number)
    if slug is None:
        return [f"issue #{number} has no recipe in the catalog"], ""
    if branch != BRANCH_PREFIX + slug:
        return [f"branch {label(branch)} is not recipe/{slug}, the recipe closed by #{number}"], ""
    entries = raw_diff(repo, base, head)
    for entry in entries:
        problems.extend(judge_entry(entry, slug))
    outside = any(not in_scope(p, slug) for e in entries for p in e.paths)
    # The README comparison reads the head catalog; do not parse it after a path rejection, which
    # already explains a catalog edit.
    if not outside and any("README.md" in e.paths and e.status == "M" for e in entries):
        problems.extend(readme_problems(repo, base, head))
    note = f"recipe pull request for #{number} ({slug}): {len(entries)} changed paths"
    return problems, note


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that a recipe pull request stays inside the CONTRIBUTING.md allowlist."
    )
    parser.add_argument("--base", required=True, help="current tip of main the branch is based on")
    parser.add_argument("--head", required=True, help="head commit of the pull request")
    parser.add_argument("--branch", required=True, help="head branch name")
    parser.add_argument("--body-file", required=True, type=Path, help="the description, as text")
    parser.add_argument("--repo", type=Path, default=Path("."), help="git directory")
    parser.add_argument("--github-repo", default=DEFAULT_REPO, help="owner/name of this repository")
    args = parser.parse_args(argv)
    try:
        body = args.body_file.read_text(encoding="utf-8")
        problems, note = check(args.repo, args.base, args.head, args.branch, body, args.github_repo)
    except (OSError, UnicodeDecodeError) as error:
        print(f"scope check could not run: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    except CannotRun as error:
        print(f"scope check could not run: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"REJECT: {problem}")
    if problems:
        print(
            f"{len(problems)} problem(s): the pull request is outside the allowlist",
            file=sys.stderr,
        )
        return 1
    print(f"scope ok: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
