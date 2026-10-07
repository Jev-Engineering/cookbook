"""Tests for jev_cookbook.recipe.load_helpers: recipes with the same helper names do not collide."""

import sys

import pytest

from jev_cookbook import load_helpers
from jev_cookbook.recipe import helpers_module_name


def make_recipe(parent, name, body):
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "helpers.py").write_text(body, encoding="utf-8")
    return folder


def test_two_recipes_with_the_same_function_name_do_not_collide(tmp_path):
    one = make_recipe(tmp_path, "01-one", "def rule():\n    return 'one'\n")
    two = make_recipe(tmp_path, "02-two", "def rule():\n    return 'two'\n")
    a, b = load_helpers(one), load_helpers(two)
    assert (a.rule(), b.rule()) == ("one", "two")
    assert a is not b
    assert a.__name__ == "recipe_01_one_helpers"
    assert b.__name__ == "recipe_02_two_helpers"


def test_the_name_comes_from_the_folder(tmp_path):
    folder = make_recipe(tmp_path, "01-Sentiment Classification", "X = 1\n")
    assert helpers_module_name(folder) == "recipe_01_sentiment_classification_helpers"


def test_same_folder_name_in_different_places_does_not_collide(tmp_path):
    one = make_recipe(tmp_path / "a", "recipe", "VALUE = 1\n")
    two = make_recipe(tmp_path / "b", "recipe", "VALUE = 2\n")
    assert (load_helpers(one).VALUE, load_helpers(two).VALUE) == (1, 2)
    assert load_helpers(one).VALUE == 1


def test_the_module_is_cached_per_path_and_reload_runs_the_file_again(tmp_path):
    folder = make_recipe(tmp_path, "03-cache", "VALUE = 1\n")
    first = load_helpers(folder)
    assert load_helpers(folder) is first
    (folder / "helpers.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert load_helpers(folder).VALUE == 1
    assert load_helpers(folder, reload=True).VALUE == 2


def test_the_default_folder_is_the_working_directory(tmp_path, monkeypatch):
    folder = make_recipe(tmp_path, "04-cwd", "VALUE = 4\n")
    monkeypatch.chdir(folder)
    assert load_helpers().VALUE == 4


def test_dataclasses_work_in_helpers(tmp_path):
    body = (
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n\n\n"
        "@dataclass(frozen=True)\nclass Point:\n    x: int\n"
    )
    module = load_helpers(make_recipe(tmp_path, "05-data", body))
    assert module.Point(3).x == 3


def test_loading_leaves_no_trace_in_sys_modules_or_sys_path(tmp_path):
    folder = make_recipe(tmp_path, "06-trace", "VALUE = 6\n")
    modules, path = set(sys.modules), list(sys.path)
    load_helpers(folder)
    assert set(sys.modules) == modules
    assert sys.path == path


def test_a_module_that_held_the_name_is_put_back(tmp_path):
    folder = make_recipe(tmp_path, "07-other", "VALUE = 7\n")
    sentinel = object()
    sys.modules["recipe_07_other_helpers"] = sentinel
    try:
        load_helpers(folder)
        assert sys.modules["recipe_07_other_helpers"] is sentinel
    finally:
        del sys.modules["recipe_07_other_helpers"]


def test_a_missing_file_names_the_folder(tmp_path):
    (tmp_path / "08-empty").mkdir()
    with pytest.raises(FileNotFoundError, match="08-empty"):
        load_helpers(tmp_path / "08-empty")


def test_an_error_in_helpers_propagates_and_is_not_cached(tmp_path):
    folder = make_recipe(tmp_path, "09-broken", "raise RuntimeError('boom')\n")
    with pytest.raises(RuntimeError, match="boom"):
        load_helpers(folder)
    assert "recipe_09_broken_helpers" not in sys.modules
    (folder / "helpers.py").write_text("VALUE = 9\n", encoding="utf-8")
    assert load_helpers(folder).VALUE == 9
