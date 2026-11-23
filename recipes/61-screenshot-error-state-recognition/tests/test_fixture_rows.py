"""The fixture builder's rows: every kind carries the evidence its gold label rests on, every
stored answer is well formed, and a bad row fails naming itself."""

import importlib.util
from pathlib import Path

import pytest

from jev_cookbook import Provenance, load_helpers

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_kind_is_drawn_with_the_objects_its_label_rests_on():
    module = load_module("recipe61_build_fixtures_for_test_evidence")
    assert set(module.EVIDENCE) == set(helpers.KINDS)
    for row in module.ROWS:
        canvas = module.draw(row)
        for name in module.EVIDENCE[row[3]]:
            assert name in canvas.objects, (row[0], row[3], name)


def test_the_drawing_kind_decides_what_is_drawn_not_the_stored_answer():
    module = load_module("recipe61_build_fixtures_for_test_kinds")
    kinds = {row[3] for row in module.ROWS}
    assert kinds == set(helpers.KINDS)
    # A crash drawing has a dialog and no spinner; a waiting drawing has a spinner and no dialog.
    crashed = module.draw(next(r for r in module.ROWS if r[3] == "sign_in_crashed"))
    waiting = module.draw(next(r for r in module.ROWS if r[3] == "sign_in_waiting"))
    assert "dialog" in crashed.objects and "spinner" not in crashed.objects
    assert "spinner" in waiting.objects and "dialog" not in waiting.objects


def test_the_look_alike_kinds_have_the_text_that_misleads():
    module = load_module("recipe61_build_fixtures_for_test_lookalikes")
    waiting = module.draw(next(r for r in module.ROWS if r[3] == "waiting_with_warning"))
    # error-like text, yet the screen is still waiting: a spinner and a warning banner together
    assert {"spinner", "warning_banner"} <= set(waiting.objects)
    assert "error_banner" not in waiting.objects
    inline = module.draw(next(r for r in module.ROWS if r[3] == "rejected_inline"))
    # a rejected sign-in with no banner at all
    assert "inline_message" in inline.objects and "error_banner" not in inline.objects


def test_an_unlabelled_kind_raises_before_anything_is_drawn():
    module = load_module("recipe61_build_fixtures_for_test_unlabelled")
    with pytest.raises(ValueError, match="mystery"):
        module.draw(("x1", "test", "S-9", "mystery", 1, ("normal", 50, "crash", 10)))


def test_a_bad_answer_row_raises_naming_the_row():
    module = load_module("recipe61_build_fixtures_for_test_answers")
    good = ("x1", "test", "S-9", "sign_in", 1, ("normal", 50, "crash", 10))
    assert module.answers_for(good, Provenance.synthetic())
    for bad in (
        ("normal", 50, "nope", 10),  # runner-up not an option
        ("nope", 50, "crash", 10),  # top not an option
        ("normal", 50, "normal", 10),  # the same option twice
        ("normal", 10, "crash", 50),  # weights out of order
        ("normal", 30, "crash", 30),  # a tie
        ("normal", 50, "crash", 0),  # a zero weight
        ("normal", 50, "crash", 1.5),  # a fractional weight
    ):
        with pytest.raises(ValueError, match="x1"):
            module.answers_for(good[:-1] + (bad,), Provenance.synthetic())


def test_the_stored_probabilities_are_the_weights_over_their_total():
    module = load_module("recipe61_build_fixtures_for_test_probabilities")
    row = ("x1", "test", "S-9", "sign_in", 1, ("normal", 50, "crash", 10))
    answer = module.answers_for(row, Provenance.synthetic())["app_state"]
    # weights: normal 50, crash 10, and 1 for each of the three other options, total 63
    assert answer.probabilities["normal"] == pytest.approx(50 / 63)
    assert answer.probabilities["crash"] == pytest.approx(10 / 63)
    assert answer.probabilities["unknown"] == pytest.approx(1 / 63)
    assert answer.choice == "normal"
