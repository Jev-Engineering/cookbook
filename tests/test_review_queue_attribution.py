"""A review queue entry records the answer that sent the item to review (#222, gap 1).

``ReviewQueue.submit(item, reason, answer=...)`` stores the ``answer`` beside the ``reason`` a
reviewer reads as "why this item needs review". On a multi-label recipe (several propositions
answered for one item) an answer fixed to one named proposition, such as
``decide(example)["redirect"]``, is the wrong answer on every row another proposition tripped
the gate. This reads each published notebook's committed source (no execution) and fails when a
``submit`` call's ``answer`` indexes a typed answer by a fixed label: a string literal or an
upper-case module constant such as ``helpers.BUDGET``. A label chosen per item, such as the
``gating`` name from a recipe's ``helpers.gating_label``, or a loop variable over the labels
(a recipe that queues one entry per label), is not fixed and passes.
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


def _fixed_label_answers(source: str) -> list[str]:
    """Source text of every ``.submit(..., answer=X[<fixed label>])`` call in ``source``."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # a cell with notebook magics is not a queue cell
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
            if keyword.arg != "answer" or not isinstance(keyword.value, ast.Subscript):
                continue
            index = keyword.value.slice
            fixed_string = isinstance(index, ast.Constant) and isinstance(index.value, str)
            fixed_constant = (
                isinstance(index, ast.Attribute)
                and index.attr.isupper()
                and isinstance(index.value, ast.Name)
            )
            if fixed_string or fixed_constant:
                found.append(ast.unparse(keyword.value))
    return found


def _fixed_label_answers_in_notebook(path: Path) -> list[str]:
    notebook = json.loads(path.read_text("utf-8"))
    found = []
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            found += _fixed_label_answers("".join(cell["source"]))
    return found


@pytest.mark.parametrize("slug", PUBLISHED)
def test_no_queue_records_an_answer_fixed_to_one_label(slug):
    found = _fixed_label_answers_in_notebook(RECIPES_DIR / slug / "notebook.ipynb")
    assert not found, (
        f"recipe {slug} queues items with an answer fixed to one label ({found}); on a "
        "multi-label recipe that is the wrong answer whenever another label sent the item to "
        "review. Record the answer of the label that gated it (see recipe 25's "
        "helpers.gating_label) or do not call it the cause."
    )


# --------------------------------------------------------------------------------------------
# the check itself: it must fail on the defect and pass on the corrections
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        'queue.submit(item, result.reason, answer=decide(example)["redirect"])',
        "queue.submit(item, result.reason, answer=decide(example)[helpers.REDIRECT])",
        "queue.submit(item, result.reason, answer=source_answers[example_id][helpers.BUDGET])",
        "review_queue.submit(item, reason, answer=answers['intent_mismatch'])",
    ],
)
def test_the_check_rejects_an_answer_fixed_to_one_label(source):
    assert _fixed_label_answers(source)


@pytest.mark.parametrize(
    "source",
    [
        "queue.submit(item, result.reason, answer=decide(example)[gating])",
        "queue.submit(item, result.reason, answer=source_answers[example_id][gating])",
        "review_queue.submit(item, reason, answer=decide(e)[label])",
        "queue.submit(item, result.reason, answer=answer_)",
        "queue.submit(item, result.reason)",
        "queue.submit(item, result.reason, answer=decide(example)[gating_label(result)])",
    ],
)
def test_the_check_accepts_a_label_chosen_per_item(source):
    assert not _fixed_label_answers(source)
