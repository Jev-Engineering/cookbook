"""The fixture builder checks its own rows: a bad answer row, an unknown product, a query that is a
reference image and the no-tin wording all fail or read as documented, and ``build_responses``
reuses the keys it is given."""

import importlib.util
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_bad_answer_row_raises_naming_the_row():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_answers")
    good = ("x1", "test", "Q-9", "DEGUM", None, "studio", 1, ("DEGUM", 60, "BIVEN", 20))
    assert module.answers_for(good, module.Provenance.synthetic())
    for bad in (
        ("DEGUM", 60, "NOPE", 20),  # runner-up not an option
        ("NOPE", 60, "BIVEN", 20),  # top not an option
        ("DEGUM", 60, "DEGUM", 20),  # the same option twice
        ("DEGUM", 20, "BIVEN", 60),  # weights out of order
        ("DEGUM", 40, "BIVEN", 40),  # a tie
    ):
        with pytest.raises(ValueError, match="x1"):
            module.answers_for(good[:-1] + (bad,), module.Provenance.synthetic())


def test_an_unknown_product_name_raises_naming_it():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_design_of")
    assert module.design_of("DEGUM") == module.helpers.CATALOG[0].design()
    with pytest.raises(ValueError, match="ZZZZZ"):
        module.design_of("ZZZZZ")


def test_no_tin_description_follows_the_condition():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_describe")
    shelf = ("n1", "test", "Q-9", None, None, "shelf", 41, ("no_match", 92, "uncertain", 2))
    assert module.describe(shelf) == (
        "An invented shelf frame under 'shelf' conditions with no tin in it (seed 41)."
    )
    dim = shelf[:5] + ("dim",) + shelf[6:]
    assert "shelf" not in module.describe(dim).replace("'shelf'", "")
    assert "'dim'" in module.describe(dim)


def test_every_committed_query_differs_from_every_reference_image():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_queries")
    module.check_queries_differ_from_references(module.ROWS)
    reference_row = ("r1", "test", "Q-9", None, None, "studio", 1, ("no_match", 9, "uncertain", 2))
    # A query that is a catalogue image is a fixture mistake, caught here and not in build_request.
    original = module.draw
    module.draw = lambda row: module.draw_reference(module.helpers.CATALOG[0])
    try:
        with pytest.raises(ValueError, match="bytes of the reference"):
            module.check_queries_differ_from_references([reference_row])
    finally:
        module.draw = original


def test_a_colliding_query_raises_before_any_file_is_written(tmp_path, monkeypatch):
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_main_collision")
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr(
        module, "draw", lambda row: module.draw_reference(module.helpers.CATALOG[0])
    )
    monkeypatch.setattr("sys.argv", ["build_fixtures.py"])
    with pytest.raises(ValueError, match="bytes of the reference"):
        module.main()
    assert list(tmp_path.rglob("*")) == []


def test_build_responses_uses_the_keys_it_is_given():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_keys")
    keys = [f"k{index}" for index in range(len(module.ROWS))]
    assert list(module.build_responses(module.ROWS, keys)) == keys


def test_main_draws_each_picture_once_for_the_check_and_the_writer(tmp_path, monkeypatch):
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_draw_once")
    (tmp_path / "build_fixtures.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_fixtures.py"])
    drawn = []
    real_draw, real_reference = module.draw, module.draw_reference
    monkeypatch.setattr(module, "draw", lambda row: drawn.append(row[0]) or real_draw(row))
    monkeypatch.setattr(
        module, "draw_reference", lambda sku: drawn.append(sku.name) or real_reference(sku)
    )
    monkeypatch.setattr(module, "build_inputs_and_labels", lambda rows: ([], []))
    monkeypatch.setattr(module, "build_responses", lambda rows, keys=None: {})
    module.main()
    assert len(drawn) == len(module.ROWS) + len(module.helpers.CATALOG)
    assert len(set(drawn)) == len(drawn)
