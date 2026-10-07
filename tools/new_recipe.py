"""Create ``recipes/NN-slug/`` for recipe NN from ``catalog/recipes.json``.

    python tools/new_recipe.py 7

The folder gets a skeleton that follows ``recipes/_template/``: the notebook sections in
order, a README, ``helpers.py``, ``build_fixtures.py`` and ``tests/test_helpers.py``. The title,
level, difficulty, decision types, use case and sources come from the catalog. Everything the
builder must write is marked ``TODO``, so ``grep -rn TODO recipes/NN-slug`` lists what is left.
The command never overwrites: if the folder exists it stops with a message and exit status 1.

Standard library only. See docs/recipe-template.md for the walkthrough.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRST, LAST = 1, 60  # recipe N is issue N; the catalog has sixty recipes

# The notebook sections, in order. A test keeps this equal to the headings of the template.
SECTIONS = [
    "What you will build",
    "Setup and run mode",
    "The state",
    "The questions",
    "One answer up close",
    "Python's part",
    "Evaluation",
    "What was and was not measured",
    "Next steps",
]

TODO_MARK = "TODO"


class ScaffoldError(Exception):
    """A problem the user can fix; ``main`` prints it and exits with status 1."""


def _load_catalog(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ScaffoldError(f"catalog not found: {path}") from None
    except json.JSONDecodeError as error:
        raise ScaffoldError(f"catalog is not valid JSON ({path.name}): {error}") from None


def find_recipe(catalog: dict, number: int) -> dict:
    """The catalog entry whose ``rank`` is ``number``."""
    for recipe in catalog.get("recipes", []):
        if recipe.get("rank") == number:
            return recipe
    raise ScaffoldError(f"recipe {number} is not in the catalog")


# --------------------------------------------------------------------------- notebook


def _cell(kind: str, cell_id: str, source: str) -> dict:
    cell = {"cell_type": kind, "id": cell_id, "metadata": {}, "source": source.strip("\n")}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def _source_lines(catalog: dict, recipe: dict) -> str:
    by_id = {s["id"]: s for s in catalog.get("sources", [])}
    lines = []
    for sid in recipe.get("sources", []):
        s = by_id.get(sid)
        lines.append(f"- {sid}: [{s['reference']}]({s['url']})" if s else f"- {sid}")
    return "\n".join(lines)


def notebook_cells(catalog: dict, recipe: dict) -> list[dict]:
    """The skeleton notebook's cells, with the catalog fields filled in."""
    number = recipe["rank"]
    title = recipe["title"]
    types = " + ".join(f"`{t}`" for t in recipe["decision_types"])
    head = (
        f"# {title}\n\n"
        f"**Recipe {number:02d}** · Level {recipe['level']} ({recipe['difficulty']}) "
        f"· Decision type: {types}\n\n"
        f"{recipe['use_case']}\n\n"
        f"Sources:\n\n{_source_lines(catalog, recipe)}\n\n"
        f"## {SECTIONS[0]}\n\n"
        f"{TODO_MARK}: say in two or three sentences what the reader will have built by the end: "
        "the decision, what Jev is asked, what Python does with the answer."
    )

    def md(cell_id: str, text: str) -> dict:
        return _cell("markdown", cell_id, text)

    def code(cell_id: str, text: str) -> dict:
        return _cell("code", cell_id, text)

    return [
        md("intro", head),
        md(
            "setup-md",
            f"## {SECTIONS[1]}\n\n"
            "The notebook runs from its own folder with the standard library and `jev_cookbook` "
            "only. The header states which mode ran.\n\n"
            f"{TODO_MARK}: add the imports your later sections use (evaluation and plotting "
            "helpers), one sentence on the fixture set and its size.",
        ),
        code(
            "setup",
            f"""
from jev_cookbook import get_backend, load_helpers
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path
from jev_cookbook.style import apply_style, run_header, show_answer

apply_style()
helpers = load_helpers()  # this recipe's helpers.py, loaded by path
examples = load_inputs()
labels = load_labels()
backend = get_backend(fixtures=responses_path())
# N for the header is the number of examples the metrics are about: the ones with a gold
# label, which excludes the demo examples.
scored = [e for e in examples if e.split != "demo"]

offline = backend.mode in ("synthetic", "scripted")
check = " (a pipeline check, not a Jev result)" if offline else ""
run_header(
    {number},
    {json.dumps(title)},
    backend=backend,
    n_examples=len(scored),
)
""",
        ),
        md(
            "state-md",
            f"## {SECTIONS[2]}\n\n"
            f"{TODO_MARK}: say how Python builds the state from one input and what Jev sees. "
            "Name what Python keeps for itself (identifiers, amounts, permissions).",
        ),
        code(
            "state",
            """
example = examples[0]
state = helpers.build_state(example.fields)
print(state)
""",
        ),
        md(
            "questions-md",
            f"## {SECTIONS[3]}\n\n"
            f"{TODO_MARK}: one sentence per design choice: why this question type, who builds the "
            "options, why each outcome (`none`, `uncertain`) is there, how a multi-part judgment "
            "was split.",
        ),
        code(
            "questions",
            """
questions = helpers.build_questions()
for name, question in questions.items():
    print(name, question.to_dict())
""",
        ),
        md(
            "answer-md",
            f"## {SECTIONS[4]}\n\n"
            f"{TODO_MARK}: show one typed answer before any aggregate and say what its fields mean "
            "(choice and probabilities, noul value, score and distribution).",
        ),
        code(
            "answer",
            """
result = backend.decide(state, questions)
for answer in result.answers.values():
    show_answer(answer)
""",
        ),
        md(
            "python-md",
            f"## {SECTIONS[5]}\n\n"
            f"{TODO_MARK}: describe the rule in `helpers.py` that holds whatever the model "
            "answers, and the explicit review outcome for uncertain or inconsistent results. "
            "Then call it here.",
        ),
        code("python-rule", "# TODO: apply the rule from helpers.py to the example above"),
        md(
            "evaluation-md",
            f"## {SECTIONS[6]}\n\n"
            f"{TODO_MARK}: choose every setting on `validation`, freeze it, and report once on "
            "`test` with `jev_cookbook.evaluation`. In an offline run print each number with "
            "`check` beside it. Compare with the baseline the issue names, if there is one.",
        ),
        code("evaluation", "# TODO: evaluate on validation, then report on test"),
        md(
            "measured-md",
            f"## {SECTIONS[7]}\n\n"
            f'{TODO_MARK}: while every answer is synthetic, keep this sentence: "Not measured '
            "live: the offline run replays synthetic answers, so its numbers check the pipeline "
            'and say nothing about how Jev performs." For a recorded recipe, replace it with '
            "the model the API returned, the capture dates and N.\n\n"
            f"{TODO_MARK}: state the size of the fixture set and anything else this notebook "
            "does not show. Say nothing about Jev's quality, speed or cost.",
        ),
        code(
            "measured",
            """
if offline:
    print("Provenance: synthetic. Not measured live.")
else:
    dates = ", ".join(getattr(backend, "recorded_dates", ()) or ()) or "this run"
    print(f"Provenance: {backend.mode}, model {backend.model}")
    print(f"Captured: {dates}")
    print(f"N: {len(scored)} scored examples")  # TODO: and N for each reported metric
""",
        ),
        md(
            "next-md",
            f"## {SECTIONS[8]}\n\n"
            f"{TODO_MARK}: what to try next, and links to neighbouring recipes by slug, for "
            "example [`NN-slug`](../NN-slug/).",
        ),
    ]


def notebook_json(catalog: dict, recipe: dict) -> str:
    notebook = {
        "cells": notebook_cells(catalog, recipe),
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


# ----------------------------------------------------------------------------- other files


def readme_text(catalog: dict, recipe: dict) -> str:
    slug = recipe["slug"]
    types = " + ".join(f"`{t}`" for t in recipe["decision_types"])
    return f"""# {recipe["title"]}

**Recipe {recipe["rank"]:02d}** · Level {recipe["level"]} ({recipe["difficulty"]}) · Decision type: {types}

{recipe["use_case"]}

## What it teaches

{TODO_MARK}: two or three sentences: the decision, what Jev is asked, what Python owns.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/{slug}
python tools/execute_notebook.py recipes/{slug}
pytest recipes/{slug}
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
  {TODO_MARK}: if this recipe records real inference, replace the mode, model and date lines
  with the mode (`recorded` or `live`), the model the API returned, and the capture date or
  dates; state N for every reported metric. Leave them as they are for a synthetic recipe.
- **N:** {TODO_MARK}: the number of scored examples per split (the `demo` examples are not scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

{TODO_MARK}: while every answer is synthetic, keep this: the offline run replays synthetic answers
written for this recipe, so its numbers check that the pipeline works. For a recorded recipe,
replace it with the model, the capture dates and N. Then state what the evaluation covers.

## Sources

{_source_lines(catalog, recipe)}
"""


def helpers_text(recipe: dict) -> str:
    return f'''"""Python's half of recipe {recipe["rank"]:02d}: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from typing import Any

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.


def build_state(fields: dict[str, Any]):
    """The state Jev sees for one example. Keep identifiers and other Python-owned values out."""
    raise NotImplementedError("{TODO_MARK}: build the state from the example's fields")


def build_questions():
    """The questions asked about every example. Python builds option lists and criteria."""
    raise NotImplementedError("{TODO_MARK}: return {{name: Choice | Noul | Score}}")


# {TODO_MARK}: the rule or rules Python enforces whatever the model answers, with tests.
'''


def rows_hint(level: int) -> str:
    """How many examples to write, from the contract: tens at levels 1 and 2, more from level 3."""
    if level <= 2:
        return f"tens of examples (about twenty) at level {level}"
    return f"as many examples as level {level} needs to show its hard cases, more than at levels 1 and 2"


def build_fixtures_text(recipe: dict) -> str:
    return f'''"""Write fixtures/inputs.jsonl, labels.jsonl and responses.json for recipe {recipe["rank"]:02d}.

    python build_fixtures.py        # from anywhere; it writes next to this file

Every response is synthetic and deliberately imperfect: include some wrong answers and the
hard cases the use case names. See docs/fixtures.md and recipes/_template/build_fixtures.py.
"""

import json
from pathlib import Path

from jev_cookbook import DecisionResult, Provenance, load_helpers, replay_key

HERE = Path(__file__).resolve().parent
helpers = load_helpers(HERE)
QUESTIONS = helpers.build_questions()

# (id, split, fields, gold label or None for a demo example, how the stored answer is written)
ROWS = []  # {TODO_MARK}: {rows_hint(recipe["level"])}, across validation and test


def answers_for(spec, provenance: Provenance):
    """{{question name: answer}} for one row, for example ChoiceAnswer.from_probabilities(...)."""
    raise NotImplementedError("{TODO_MARK}: build the typed answers from the row's spec")


def main() -> None:
    if not ROWS:
        raise SystemExit("{TODO_MARK}: add examples to ROWS in build_fixtures.py")
    inputs, labels, responses = [], [], {{}}
    for ident, split, fields, label, spec in ROWS:
        key = replay_key(helpers.build_state(fields), QUESTIONS)
        inputs.append({{"id": ident, "split": split, "fields": fields, "replay_keys": [key]}})
        if label is not None:
            labels.append({{"id": ident, "label": label}})
        answers = answers_for(spec, Provenance.synthetic())
        responses[key] = DecisionResult(answers, "synthetic").to_dict()
    folder = HERE / "fixtures"
    folder.mkdir(exist_ok=True)
    for name, rows in (("inputs.jsonl", inputs), ("labels.jsonl", labels)):
        text = "".join(json.dumps(row) + "\\n" for row in rows)
        (folder / name).write_text(text, encoding="utf-8", newline="\\n")
    text = json.dumps(responses, indent=2) + "\\n"
    (folder / "responses.json").write_text(text, encoding="utf-8", newline="\\n")
    print(f"wrote {{len(inputs)}} examples, {{len(labels)}} labels, {{len(responses)}} responses")


if __name__ == "__main__":
    main()
'''


def tests_text(recipe: dict) -> str:
    return f'''"""Tests for recipe {recipe["rank"]:02d}'s helpers. They load the helpers by file path."""

from pathlib import Path

from jev_cookbook import load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_questions_are_built_by_python():
    # {TODO_MARK}: assert the option lists and criteria, then test every rule in helpers.py
    assert helpers.build_questions()


def test_every_replay_key_in_the_fixtures_matches_the_current_question():
    # The fixture validator cannot see question drift; this test can. It assumes one request per
    # example; adapt it when an example needs a dependent second request (CONTRIBUTING: a question that depends on an
    # earlier answer goes in a later request).
    questions = helpers.build_questions()
    for example in load_inputs(RECIPE):
        assert example.replay_keys == (replay_key(helpers.build_state(example.fields), questions),)
'''


def files_for(catalog: dict, recipe: dict) -> dict[str, str]:
    """``{relative path: text}`` of everything the scaffold creates."""
    return {
        "notebook.ipynb": notebook_json(catalog, recipe),
        "README.md": readme_text(catalog, recipe),
        "helpers.py": helpers_text(recipe),
        "build_fixtures.py": build_fixtures_text(recipe),
        "tests/test_helpers.py": tests_text(recipe),
    }


def scaffold(number: int, catalog_path: Path, recipes_dir: Path) -> Path:
    """Create ``recipes_dir/NN-slug/`` and return it. Raises ``ScaffoldError`` and writes
    nothing when the number is out of range, is not in the catalog, or the folder exists."""
    if not FIRST <= number <= LAST:
        raise ScaffoldError(f"recipe number must be {FIRST} to {LAST}, got {number}")
    catalog = _load_catalog(catalog_path)
    recipe = find_recipe(catalog, number)
    target = recipes_dir / recipe["slug"]
    if target.exists():
        raise ScaffoldError(f"{target.as_posix()} already exists; refusing to overwrite it")
    files = files_for(catalog, recipe)
    target.mkdir(parents=True)
    for name, text in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create recipes/NN-slug/ for recipe NN from catalog/recipes.json."
    )
    parser.add_argument("number", help=f"recipe number, {FIRST} to {LAST}")
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "catalog" / "recipes.json", help="catalog file"
    )
    parser.add_argument(
        "--recipes-dir", type=Path, default=ROOT / "recipes", help="where recipe folders live"
    )
    args = parser.parse_args(argv)
    if not args.number.isascii() or not args.number.isdigit():
        parser.error(f"recipe number must be a whole number, got {args.number!r}")
    number = int(args.number)
    if not FIRST <= number <= LAST:
        parser.error(f"recipe number must be {FIRST} to {LAST}, got {number}")
    try:
        target = scaffold(number, args.catalog, args.recipes_dir)
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"created {target.parent.name}/{target.name}/")
    print(f"next: grep -rn {TODO_MARK} {target.parent.name}/{target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
