"""The top-level gold-label reservation and the image example that avoids it.

All fixture stores are tiny synthetic, text-only inputs with no requests. The docs example
is inspected as syntax, so checking its question names never reads images or builds a backend.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from jev_cookbook.fixtures import validate_recipe
from jev_cookbook.vision import gold_box

ROOT = Path(__file__).resolve().parent.parent
BOX = {"present": True, "box": {"top": 0.2, "bottom": 0.8, "left": 0.1, "right": 0.9}}


def _validate_label(tmp_path, label):
    """Exercise the public validator without unrelated response or image-asset setup."""
    recipe = tmp_path / "01-demo"
    folder = recipe / "fixtures"
    folder.mkdir(parents=True)
    inputs = [
        {"id": ident, "split": split, "fields": {"n": n}, "replay_keys": []}
        for n, (ident, split) in enumerate((("v0", "validation"), ("t0", "test")))
    ]
    labels = [{"id": row["id"], "label": label} for row in inputs]
    for name, rows in (("inputs", inputs), ("labels", labels)):
        text = "".join(json.dumps(row) + "\n" for row in rows)
        (folder / f"{name}.jsonl").write_text(text, encoding="utf-8")
    return validate_recipe(recipe)


@pytest.mark.parametrize(
    ("label", "detail"),
    [
        pytest.param(
            {"present": 0.9, "button": {"present": False}},
            "'present' to be true or false",
            id="answer-by-question-name",
        ),
        pytest.param({"present": "yes"}, "'present' to be true or false", id="nonboolean"),
        pytest.param({"present": None}, "'present' to be true or false", id="null"),
        pytest.param({"present": False, "other": 1}, "exactly {'present': false}", id="extra-key"),
        pytest.param({"present": True}, "exactly 'present' and 'box'", id="missing-box"),
        pytest.param(
            {"present": True, "box": {"top": 0.2, "bottom": 0.8, "left": 0.1, "right": 2}},
            "right must be in [0, 1]",
            id="invalid-coordinate",
        ),
    ],
)
def test_malformed_top_level_present_labels_explain_the_reservation(tmp_path, label, detail):
    problems = _validate_label(tmp_path, label)
    assert len(problems) == 2
    assert [(p.ident, p.line) for p in problems] == [("v0", 1), ("t0", 2)]
    for problem in problems:
        assert problem.file.endswith("labels.jsonl")
        assert problem.message.startswith("malformed Box label:")
        assert detail in problem.message
        assert "present" in problem.message
        assert "reserved" in problem.message.lower()
        assert re.search(r"top[ -]level", problem.message.lower()), problem.message


@pytest.mark.parametrize(
    "label",
    [{"present": "yes"}, {"present": False, "other": 1}, {"present": 0.9, "rubric": 3}],
    ids=["nonboolean", "extra-key", "nonboolean-and-extra-key"],
)
def test_top_level_present_recognition_does_not_silently_drop_malformed_labels(tmp_path, label):
    problems = _validate_label(tmp_path, label)
    assert len(problems) == 2
    assert all(p.message.startswith("malformed Box label:") for p in problems)


@pytest.mark.parametrize("label", [{"present": False}, BOX], ids=["absent", "present"])
def test_well_formed_top_level_box_labels_still_validate(tmp_path, label):
    assert _validate_label(tmp_path, label) == []


@pytest.mark.parametrize(
    ("label", "where", "detail"),
    [
        ({"target": {"present": "yes"}}, "label.target", "'present' to be true or false"),
        ({"targets": [{"present": True}]}, "label.targets[0]", "exactly 'present' and 'box'"),
        (
            {"target": {"present": False, "box": None}},
            "label.target",
            "exactly {'present': false}",
        ),
    ],
)
def test_nested_malformed_box_labels_keep_their_path_without_top_level_notice(
    tmp_path, label, where, detail
):
    problems = _validate_label(tmp_path, label)
    assert len(problems) == 2
    for problem in problems:
        assert problem.message.startswith(f"malformed Box label at {where}:")
        assert detail in problem.message
        assert "reserved" not in problem.message.lower()
        assert not re.search(r"top[ -]level", problem.message.lower())


def test_nested_present_field_with_other_keys_is_not_a_box_label(tmp_path):
    label = {"answers": {"present": 0.9, "button": {"present": False}}}
    assert _validate_label(tmp_path, label) == []


@pytest.mark.parametrize(
    "label",
    [
        {"visible": True, "button": {"present": False}},
        {"visible": False, "button": BOX},
    ],
    ids=["visible-but-absent-box", "invisible-but-present-box"],
)
def test_separate_presence_answers_are_not_compared_by_the_validator(tmp_path, label):
    assert _validate_label(tmp_path, label) == []
    # A recipe that selects button for localization reads its Box gold, not visible.
    assert (gold_box(label["button"]) is not None) is not label["visible"]


def _image_section(text):
    return text.split("\n## Images and Box\n", 1)[1].split("\n## ", 1)[0]


def _assert_image_question_names(text):
    dictionaries = []
    for block in re.findall(r"```python\n(.*?)```", _image_section(text), re.S):
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "questions" for target in node.targets
            ):
                assert isinstance(node.value, ast.Dict)
                dictionaries.append(node.value)
    assert len(dictionaries) == 1, "the image example must have one explicit questions mapping"
    question_types = {}
    for key, value in zip(dictionaries[0].keys, dictionaries[0].values, strict=True):
        assert isinstance(key, ast.Constant) and isinstance(key.value, str)
        assert isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
        assert key.value not in question_types, "duplicate question name in image example"
        question_types[key.value] = value.func.id
    assert question_types == {"visible": "Noul", "button": "Box"}


def test_image_example_uses_visible_noul_and_button_box():
    _assert_image_question_names((ROOT / "docs" / "backends.md").read_text("utf-8"))


def test_image_question_pin_rejects_a_code_rename_with_explanatory_prose_unchanged():
    text = (ROOT / "docs" / "backends.md").read_text("utf-8")
    original = _image_section(text)
    before, code, after = original.partition('"visible": Noul(')
    assert code, "the mutation must rename the actual question constructor's key"
    mutated_section = before + '"present": Noul(' + after
    assert "The presence question is named `visible`" in after
    assert mutated_section.partition('"present": Noul(')[2] == after
    mutated = text.replace(original, mutated_section, 1)
    with pytest.raises(AssertionError):
        _assert_image_question_names(mutated)
