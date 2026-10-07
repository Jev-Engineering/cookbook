"""Command line: ``python -m jev_cookbook.fixtures validate recipes/NN-slug``."""

from __future__ import annotations

import argparse
import sys

from . import FIXTURES_DIR, validate_all, validate_recipe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jev_cookbook.fixtures", description="Check recipe fixtures."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate", help="validate a recipe's fixtures folder")
    val.add_argument("recipe_dir", nargs="?", help="a recipe directory, such as recipes/01-slug")
    val.add_argument(
        "--all", action="store_true", help=f"validate every recipes/*/{FIXTURES_DIR} that exists"
    )
    val.add_argument("--recipes-dir", default="recipes", help="with --all (default: recipes)")
    args = parser.parse_args(argv)

    if args.all == (args.recipe_dir is not None):
        parser.error("give either a recipe directory or --all")
    if args.all:
        results = validate_all(args.recipes_dir)
        if not results:
            print(f"no {args.recipes_dir}/*/{FIXTURES_DIR} folders found; nothing to validate")
    else:
        results = {args.recipe_dir: validate_recipe(args.recipe_dir)}
    failed = 0
    for recipe, problems in results.items():
        if problems and problems.mode:
            print(f"{recipe}: mode {problems.mode}")
        if problems:
            failed += 1
            for problem in problems:
                print(problem, file=sys.stderr)
        else:
            print(f"{recipe}: fixtures valid (mode {problems.mode})")
    if failed:
        total = sum(len(p) for p in results.values())
        print(f"{total} problem(s) in {failed} recipe(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
