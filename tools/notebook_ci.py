"""Helpers for the notebook workflow (#69): which notebooks to run, and the fixtures gate.

    python tools/notebook_ci.py matrix [--base REF --head REF] [--github-output FILE]
    python tools/notebook_ci.py fixtures

``matrix`` prints the recipe folders whose notebook must be executed, as JSON
(``{"recipe": [...]}``), and with ``--github-output`` writes ``matrix=`` and ``count=`` lines for
GitHub Actions. Without ``--base`` and ``--head`` it selects every ``recipes/*/notebook.ipynb``,
``_template`` included. With them (a pull request) it selects only the recipe folders that the
pull request changes (a three-dot diff, from the merge base), and only when every changed path is
inside a recipe folder or is exactly ``README.md``; any other changed path selects every notebook.

``--merge-ref --pr-head SHA`` is for a pull request's own checkout (``refs/pull/N/merge``, a merge
commit): the diff is taken against that commit's first parent, not against ``--base``, which is the
base branch's tip from when the pull request was opened and goes stale (#248). ``--pr-head`` is the
pull request's head commit (``github.event.pull_request.head.sha``): the first parent is trusted
only when the second parent is that commit, so a branch whose own tip happens to be a merge cannot
pass for the merge ref. ``--base`` is the fallback for any ``--head`` that is not that merge
commit. See ``merge_ref_base``.

``--push`` is for a push to ``main``, where ``--base`` is the previous tip (``before``). The diff
is then two-dot (``before..head``, the trees themselves), and the selection falls back to every
notebook unless ``before`` is a commit that is an ancestor of ``head``: a first push (all zeros),
a ``before`` missing from the clone, a rewound ``main`` (``before`` is ahead of ``head``) and a
rewritten history (``before`` is on another line) all run everything. A three-dot diff would
start from the merge base and could select nothing, or the wrong folders, after a forced push.
The workflow also runs everything whenever ``github.event.forced`` is true.

``--lenient`` (a manual run of the latest commit) makes a base or head that is not a commit select
every notebook instead of failing; a pull request does not use it, so there an unreadable diff
stays an error.

``fixtures`` validates every folder directly under ``recipes/`` with
``python -m jev_cookbook.fixtures validate`` and fails a recipe with no ``fixtures/`` folder,
which ``validate --all`` would skip without a word.

Exit status: 0 success, 1 a gate failed, 2 a usage or environment error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = "notebook.ipynb"
# A recipe folder name ends up in a workflow matrix and a command line: refuse anything else.
RECIPE_NAME = re.compile(r"(?:_template|(?:[0-9]{2}|100)-[a-z0-9]+(?:-[a-z0-9]+)*)")


def recipe_dirs(root: Path) -> list[Path]:
    recipes = root / "recipes"
    if not recipes.is_dir():
        raise SystemExit(f"no recipes/ directory in {root}")
    return sorted(p for p in recipes.iterdir() if p.is_dir())


def with_notebooks(root: Path) -> list[str]:
    names = [p.name for p in recipe_dirs(root) if (p / NOTEBOOK).is_file()]
    for name in names:
        if not RECIPE_NAME.fullmatch(name):
            raise SystemExit(
                f"recipe folder name {name!r} is not NN-slug (01–99), 100-slug or _template"
            )
    return names


def changed_paths(root: Path, base: str, head: str, dots: str = "...") -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            f"{base}{dots}{head}",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git diff {base}{dots}{head} failed: {result.stderr.decode()[:300]}")
    return [p.decode("utf-8", "surrogateescape") for p in result.stdout.split(b"\0") if p]


def is_commit(root: Path, ref: str) -> bool:
    if not ref or set(ref) == {"0"}:
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", "--end-of-options", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def parents(root: Path, ref: str) -> list[str] | None:
    """The full parent SHAs of the commit ``ref`` names, or ``None`` if it is not a commit."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--parents", "-n", "1", "--end-of-options", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.split()[1:]


def resolve_commit(root: Path, ref: str) -> str | None:
    """The full SHA of the commit ``ref`` names, or ``None`` if it names none here."""
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def merge_ref_base(root: Path, base: str, head: str, pr_head: str) -> str:
    """The base to diff a pull request against when ``head`` is the checked-out merge ref.

    ``actions/checkout`` on ``pull_request`` checks out ``refs/pull/N/merge``: a merge commit
    whose first parent is the base branch as it was when that commit was made, and whose second is
    the pull request's head. ``pull_request.base.sha`` is the base branch's tip when the pull
    request was *opened*, so after any later commit to the base it is an ancestor of the merge
    commit and the diff ``base.sha...merge`` also reports everything the base branch gained since
    (#248): unrelated recipes were re-executed, and one commit to ``src/`` or ``tools/`` selected
    every notebook on every open pull request. The first parent is the base the tree on disk was
    actually built on, so ``first-parent...merge`` is exactly what the pull request changes.

    Only a commit with exactly two parents *whose second parent is ``pr_head``* is trusted to be
    that merge commit (#316). Two parents alone are not proof: a pull request branch whose tip
    merged ``main`` into it also has two, and its first parent is the branch's own previous commit,
    which would hide most of the change and select too few notebooks. For any other ``head`` the
    ``base`` given is kept, and the reason is printed: that can select more than needed, never
    less.
    """
    found = parents(root, head)
    expected = resolve_commit(root, pr_head)
    if found is not None and len(found) == 2 and expected is not None and found[1] == expected:
        return found[0]
    if found is None or len(found) != 2:
        why = "is not a merge commit"
    else:
        why = f"is a merge commit whose second parent is not the pull request head {pr_head!r}"
    print(f"head {head!r} {why}: diffing against the given base {base!r}", file=sys.stderr)
    return base


def select(root: Path, base: str | None, head: str | None, dots: str = "...") -> list[str]:
    """The recipe folders to execute (see the module docstring)."""
    everything = with_notebooks(root)
    if base is None or head is None:
        return everything
    chosen: set[str] = set()
    for path in changed_paths(root, base, head, dots):
        if path == "README.md":
            continue
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "recipes":
            chosen.add(parts[1])
        else:
            return everything
    return [name for name in everything if name in chosen]


def command_matrix(args: argparse.Namespace) -> int:
    if (args.base is None) != (args.head is None):
        print("--base and --head go together", file=sys.stderr)
        return 2
    base, head = args.base, args.head
    dots = "..."
    if args.merge_ref != (args.pr_head is not None):
        print("--merge-ref and --pr-head go together", file=sys.stderr)
        return 2
    if args.merge_ref:
        if args.push or base is None:
            print("--merge-ref needs --base and --head, and is for a pull request", file=sys.stderr)
            return 2
        base = merge_ref_base(args.root, base, head, args.pr_head)
    if args.push:
        if base is None:
            print("--push needs --base and --head", file=sys.stderr)
            return 2
        dots = ".."
        if not (is_commit(args.root, base) and is_commit(args.root, head)):
            print(f"base {base!r} is not a commit here: selecting every notebook", file=sys.stderr)
            base = head = None
        elif not is_ancestor(args.root, base, head):
            print(
                f"base {base!r} is not an ancestor of the head (rewound or rewritten history): "
                "selecting every notebook",
                file=sys.stderr,
            )
            base = head = None
    elif (
        args.lenient
        and base is not None
        and not (is_commit(args.root, base) and is_commit(args.root, head))
    ):
        print(f"base {base!r} is not a commit here: selecting every notebook", file=sys.stderr)
        base = head = None
    names = select(args.root, base, head, dots)
    matrix = json.dumps({"recipe": names}, separators=(",", ":"))
    print(matrix)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"matrix={matrix}\ncount={len(names)}\n")
    return 0


def command_fixtures(args: argparse.Namespace) -> int:
    failures = 0
    folders = recipe_dirs(args.root)
    if not folders:
        print("no recipe folder under recipes/: nothing to validate", file=sys.stderr)
        return 1
    for folder in folders:
        if not (folder / "fixtures").is_dir():
            print(f"{folder.name}: no fixtures/ folder (every recipe needs one)")
            failures += 1
            continue
        result = subprocess.run(
            [sys.executable, "-m", "jev_cookbook.fixtures", "validate", f"recipes/{folder.name}"],
            capture_output=True,
            text=True,
            check=False,
            cwd=args.root,
        )
        output = (result.stdout + result.stderr).strip()
        print(f"{folder.name}: {'valid' if result.returncode == 0 else 'INVALID'}")
        if output:
            print("\n".join(f"    {line}" for line in output.splitlines()))
        if result.returncode != 0:
            failures += 1
    print(f"{len(folders)} recipe folders, {failures} failed")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: here)")
    sub = parser.add_subparsers(dest="command", required=True)
    matrix = sub.add_parser("matrix", help="the recipe folders whose notebook to execute")
    matrix.add_argument("--base", help="base commit of a pull request")
    matrix.add_argument("--head", help="head commit of a pull request")
    matrix.add_argument(
        "--lenient",
        action="store_true",
        help="a base or head that is not a commit selects every notebook (push to main)",
    )
    matrix.add_argument(
        "--push",
        action="store_true",
        help="--base is the previous tip of main: two-dot diff, every notebook unless it is an "
        "ancestor of --head",
    )
    matrix.add_argument(
        "--merge-ref",
        action="store_true",
        help="--head is a pull request's merge commit: diff against its first parent (the base "
        "branch as that merge commit saw it) instead of --base, which may be stale; needs "
        "--pr-head",
    )
    matrix.add_argument(
        "--pr-head",
        help="the pull request's head commit; with --merge-ref, --head is trusted to be the merge "
        "commit only if this is its second parent",
    )
    matrix.add_argument("--github-output", help="append matrix= and count= lines to this file")
    matrix.set_defaults(run=command_matrix)
    fixtures = sub.add_parser("fixtures", help="validate every recipe's fixtures/ folder")
    fixtures.set_defaults(run=command_fixtures)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
