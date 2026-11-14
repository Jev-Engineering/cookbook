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
    original = module.query_path
    module.query_path = lambda ident: module.helpers.CATALOG[0].reference_path
    try:
        with pytest.raises(ValueError, match="bytes of the reference"):
            module.check_queries_differ_from_references([reference_row])
    finally:
        module.query_path = original


def test_build_responses_uses_the_keys_it_is_given():
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test_keys")
    inputs, _labels = module.build_inputs_and_labels(module.ROWS)
    keys = [row["replay_keys"][0] for row in inputs]
    assert module.build_responses(module.ROWS, keys) == module.build_responses(module.ROWS)
