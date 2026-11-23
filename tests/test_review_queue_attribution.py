"""A review queue entry records the answer that sent the item to review (#222, gap 1).

``ReviewQueue.submit(item, reason, answer=...)`` stores the ``answer`` beside the ``reason`` a
reviewer reads as "why this item needs review". On a multi-label recipe (several propositions
answered for one item) an answer fixed to one named proposition, such as
``decide(example)["redirect"]``, is the wrong answer on every row another proposition tripped
the gate.

What this checks. It reads each published recipe's committed ``notebook.ipynb`` and
``helpers.py`` source (no execution) and walks the whole ``answer=`` expression of every
``.submit(...)`` call. It fails when that expression indexes by, or calls ``.get`` with, one of
the recipe's own labels written as a fixed value: the label's string (``["redirect"]``) or its
module constant (``[REDIRECT]``, ``[helpers.REDIRECT]``). A label chosen per item (the
``gating`` name from a recipe's ``helpers.gating_label``, or a loop variable over the labels)
passes.

Which false positives are avoided. The approach chosen is to scope the check to multi-label
recipes and to the recipe's own labels: only a recipe whose ``helpers.py`` defines a
module-level ``LABELS`` with more than one entry is checked, and only an index or ``.get``
argument equal to one of those labels (string value or constant name) counts. An index by any
other literal, such as ``row["answer"]`` or an id string, is not flagged, and a single-label
recipe is out of scope because it has no other proposition to confuse. Notebook lines that
start with ``%`` or ``!`` are replaced by ``pass`` before parsing, so a cell with magics is
still read.

Documented limits, forms this does NOT catch:

* a fixed label passed through a local variable (``label = "budget"; answers[label]``, or
  ``a = answers["budget"]; submit(..., answer=a)``), which needs data-flow analysis;
* attribute access or ``getattr`` instead of an index (``result.redirect``,
  ``getattr(result, "redirect")``);
* a label built indirectly (``answers[helpers.LABELS[0]]``, an f-string, a computed key);
* a ``submit`` reached through an alias (``submit = queue.submit``) or a ``**{"answer": ...}``
  keyword expansion;
* a fixed label inside a helper function that a ``submit`` call's ``answer=`` merely calls.
"""

import ast
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RECIPES_DIR = REPO / "recipes"
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
PUBLISHED = [
    recipe["slug"]
    for recipe in CATALOG["recipes"]
    if (RECIPES_DIR / recipe["slug"] / "notebook.ipynb").is_file()
]


def _label_vocabulary(helpers_source: str) -> tuple[set[str], set[str]]:
    """``(constant names, string values)`` of a helpers module's ``LABELS``, or two empty sets
    when it has no module-level ``LABELS`` naming more than one label."""
    consts: dict[str, ast.expr] = {}
    for node in ast.parse(helpers_source).body:
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target = node.target
        if isinstance(target, ast.Name):
            consts[target.id] = node.value
    labels = consts.get("LABELS")
    while isinstance(labels, ast.Name):  # LABELS = CONSTRAINTS
        labels = consts.get(labels.id)
    if not isinstance(labels, ast.Tuple | ast.List) or len(labels.elts) < 2:
        return set(), set()
    names, values = set(), set()
    for element in labels.elts:
        if isinstance(element, ast.Name):
            names.add(element.id)
            value = consts.get(element.id)
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                values.add(value.value)
        elif isinstance(element, ast.Constant) and isinstance(element.value, str):
            values.add(element.value)
    return names, values


def _is_fixed_label(node: ast.AST, names: set[str], values: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value in values
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr in names
    return False


def _fixed_label_answers(source: str, names: set[str], values: set[str]) -> list[str]:
    """Source text of every ``.submit(..., answer=<expr>)`` whose expression indexes by, or
    ``.get``s, one of the recipe's labels as a fixed value."""
    lines = [
        "pass" if line.lstrip().startswith(("%", "!")) else line for line in source.splitlines()
    ]
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "submit"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg != "answer":
                continue
            for inner in ast.walk(keyword.value):
                indexed = isinstance(inner, ast.Subscript) and _is_fixed_label(
                    inner.slice, names, values
                )
                fetched = (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "get"
                    and bool(inner.args)
                    and _is_fixed_label(inner.args[0], names, values)
                )
                if indexed or fetched:
                    found.append(ast.unparse(keyword.value))
                    break
    return found


def _recipe_hits(slug: str) -> list[str]:
    recipe = RECIPES_DIR / slug
    helpers_source = (recipe / "helpers.py").read_text("utf-8")
    names, values = _label_vocabulary(helpers_source)
    if not names and not values:
        return []
    found = _fixed_label_answers(helpers_source, names, values)
    notebook = json.loads((recipe / "notebook.ipynb").read_text("utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            found += _fixed_label_answers("".join(cell["source"]), names, values)
    return found


@pytest.mark.parametrize("slug", PUBLISHED)
def test_no_queue_records_an_answer_fixed_to_one_label(slug):
    found = _recipe_hits(slug)
    assert not found, (
        f"recipe {slug} queues items with an answer fixed to one label ({found}); on a "
        "multi-label recipe that is the wrong answer whenever another label sent the item to "
        "review. Record the answer of the label that gated it (see recipe 25's "
        "helpers.gating_label) or do not call it the cause."
    )


def test_the_sweep_covers_the_multi_label_recipes():
    covered = {
        slug
        for slug in PUBLISHED
        if any(_label_vocabulary((RECIPES_DIR / slug / "helpers.py").read_text("utf-8")))
    }
    assert {"25-change-evidence-review", "26-prompt-injection-screening"} <= covered


# --------------------------------------------------------------------------------------------
# the check itself: it must fail on the defect and pass on the corrections
# --------------------------------------------------------------------------------------------

NAMES = {"REDIRECT", "DISCUSSES", "BUDGET", "TIMELINE"}
VALUES = {"redirect", "discusses", "budget", "timeline"}


@pytest.mark.parametrize(
    "source",
    [
        'queue.submit(item, result.reason, answer=decide(example)["redirect"])',
        "queue.submit(item, result.reason, answer=decide(example)[helpers.REDIRECT])",
        "queue.submit(item, result.reason, answer=source_answers[example_id][helpers.BUDGET])",
        "review_queue.submit(item, reason, answer=answers['discusses'])",
        'queue.submit(item, reason, answer=decide(example)["redirect"].to_dict())',
        "queue.submit(item, reason, answer=decide(example)[REDIRECT])",
        'queue.submit(item, reason, answer=answers.get("redirect"))',
        "queue.submit(item, reason, answer=answers.get(helpers.BUDGET))",
        "queue.submit(item, reason, answer=answers[helpers.BUDGET][example_id])",
        '%matplotlib inline\nqueue.submit(item, reason, answer=answers["budget"])',
        '!pip list\nqueue.submit(item, reason, answer=answers["budget"])',
    ],
)
def test_the_check_rejects_an_answer_fixed_to_one_label(source):
    assert _fixed_label_answers(source, NAMES, VALUES)


@pytest.mark.parametrize(
    "source",
    [
        "queue.submit(item, result.reason, answer=decide(example)[gating])",
        "queue.submit(item, result.reason, answer=source_answers[example_id][gating])",
        "review_queue.submit(item, reason, answer=decide(e)[label])",
        "queue.submit(item, result.reason, answer=answer_)",
        "queue.submit(item, result.reason)",
        "queue.submit(item, result.reason, answer=decide(example)[gating_label(result)])",
        'queue.submit(item, result.reason, answer=row["answer"])',
        'queue.submit(item, result.reason, answer=answers_by_id["ex-01"])',
        "queue.submit(item, reason, answer=answers.get(gating))",
        "%matplotlib inline\nqueue.submit(item, reason, answer=decide(e)[gating])",
    ],
)
def test_the_check_accepts_a_label_chosen_per_item(source):
    assert not _fixed_label_answers(source, NAMES, VALUES)


def test_a_single_label_vocabulary_is_out_of_scope_and_aliases_resolve():
    single = 'QUESTION = "is_spam"\nLABELS = (QUESTION,)\n'
    assert _label_vocabulary(single) == (set(), set())
    two = 'A = "a"\nB = "b"\nLABELS = (A, B)\n'
    assert _label_vocabulary(two) == ({"A", "B"}, {"a", "b"})
    alias = 'A = "a"\nB = "b"\nCS = (A, B)\nLABELS = CS\n'
    assert _label_vocabulary(alias) == ({"A", "B"}, {"a", "b"})
