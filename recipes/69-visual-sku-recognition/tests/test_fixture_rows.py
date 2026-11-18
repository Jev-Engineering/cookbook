"""The fixture builder checks its own rows: a bad answer row, an unknown product, a query that is a
reference image and the no-tin wording all fail or read as documented, and ``build_responses``
reuses the keys it is given."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from jev_cookbook import Provenance, dump_responses
from jev_cookbook.fixtures import load_inputs, load_responses

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


def _module(name, tmp_path, monkeypatch):
    module = load_module_at(SCRIPT, name)
    monkeypatch.setattr(module, "HERE", tmp_path)
    monkeypatch.setattr("sys.argv", ["build_fixtures.py"])
    return module


def test_a_duplicate_ident_raises_naming_both_rows_before_any_file_is_written(
    tmp_path, monkeypatch
):
    module = _module("recipe69_build_fixtures_for_test_dup_ident", tmp_path, monkeypatch)
    monkeypatch.setattr(module, "ROWS", [*module.ROWS, module.ROWS[0]])
    with pytest.raises(ValueError, match=r"rows 0 and \d+ share the ident"):
        module.main()
    assert list(tmp_path.rglob("*")) == []


def test_two_rows_with_one_replay_key_raise_naming_both_rows(tmp_path, monkeypatch):
    module = _module("recipe69_build_fixtures_for_test_dup_key", tmp_path, monkeypatch)
    first = module.ROWS[0]
    twin = (first[0] + "-twin", *first[1:])  # a new ident that draws the very same picture
    monkeypatch.setattr(module, "ROWS", [first, twin])
    with pytest.raises(ValueError, match="draw the same picture") as caught:
        module.main()
    assert first[0] in str(caught.value) and twin[0] in str(caught.value)
    assert list(tmp_path.rglob("*")) == []
    # The key checks themselves, for callers that never go through main.
    with pytest.raises(ValueError, match="same replay key"):
        module.build_responses([first, twin], ["k", "k"])
    with pytest.raises(ValueError, match="same replay key"):
        module._check_distinct_keys([first, twin], ["k", "k"])


def test_a_mismatching_query_leaves_a_missing_reference_unwritten(tmp_path, monkeypatch):
    module = _module("recipe69_build_fixtures_for_test_preflight", tmp_path, monkeypatch)
    (tmp_path / "build_fixtures.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    rows = module.ROWS[:2]
    monkeypatch.setattr(module, "ROWS", rows)
    # Every file present and right except: one reference missing, one query holding other pixels.
    module.write_images(rows, False)
    missing = tmp_path / module.helpers.CATALOG[0].reference_path
    missing.unlink()
    bad = tmp_path / module.query_path(rows[1][0])
    other = module.draw_reference(module.helpers.CATALOG[1])
    other.write(tmp_path, module.query_path(rows[1][0]), overwrite=True)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.png")}
    with pytest.raises(SystemExit, match="nothing else was written"):
        module.main()
    assert not missing.exists()
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.png")} == before
    assert bad.exists()


@pytest.mark.parametrize(
    "contents",
    [None, b"{", b"[]", b"{}", b"\xff", b'{"' + b"a" * 64 + b'":{"model":"synthetic"}}'],
    ids=[
        "unreadable",
        "invalid-json",
        "non-object",
        "empty",
        "invalid-utf8",
        "invalid-synthetic-result",
    ],
)
def test_default_regeneration_preserves_invalid_existing_responses(tmp_path, monkeypatch, contents):
    module = _module("recipe69_build_fixtures_for_test_response_protection", tmp_path, monkeypatch)
    (tmp_path / "build_fixtures.py").write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(module, "ROWS", module.ROWS[:1])
    monkeypatch.setattr(module.helpers, "ROOT", tmp_path)

    responses = tmp_path / "fixtures" / "responses.json"
    responses.parent.mkdir()
    unreadable = contents is None
    if unreadable:
        contents = (RECIPE / "fixtures" / "responses.json").read_bytes()
    responses.write_bytes(contents)
    read_bytes = Path.read_bytes

    def simulate_unreadable(path):
        if unreadable and path == responses:
            raise PermissionError("simulated unreadable fixture")
        return read_bytes(path)

    with monkeypatch.context() as attempt:
        attempt.setattr(Path, "read_bytes", simulate_unreadable)
        with pytest.raises(SystemExit, match="cannot be validated as synthetic.*--force"):
            module.main()
        assert read_bytes(responses) == contents

        attempt.setattr("sys.argv", ["build_fixtures.py", "--overwrite-assets"])
        with pytest.raises(SystemExit, match=r"refusing --overwrite-assets.*cannot be validated"):
            module.main()
        assert read_bytes(responses) == contents


def test_regeneration_protects_valid_recorded_provenance_until_forced(tmp_path, monkeypatch):
    module = _module("recipe69_build_fixtures_for_test_recorded", tmp_path, monkeypatch)
    (tmp_path / "build_fixtures.py").write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(module, "ROWS", [next(row for row in module.ROWS if row[1] == "test")])
    monkeypatch.setattr(module.helpers, "ROOT", tmp_path)
    module.main()

    responses = tmp_path / "fixtures" / "responses.json"
    synthetic = responses.read_bytes()
    data = json.loads(synthetic)
    (sample,) = load_inputs(tmp_path)
    key = sample.replay_keys[0]
    provenance = Provenance.recorded("test-model", "2026-01-01").to_dict()
    data[key]["model"] = provenance["model"]
    for answer in data[key]["answers"].values():
        answer["provenance"] = provenance
    responses.write_text(dump_responses(data), encoding="utf-8", newline="\n")
    assert load_responses(tmp_path)[key] == data[key]
    recorded = responses.read_bytes()

    with pytest.raises(SystemExit, match="it holds a recorded response.*--force"):
        module.main()
    assert responses.read_bytes() == recorded

    monkeypatch.setattr("sys.argv", ["build_fixtures.py", "--force"])
    module.main()
    assert responses.read_bytes() == synthetic


@pytest.mark.parametrize(
    "path_kind",
    ["symlink", "dangling", "directory", "fifo", "uninspectable", "linked-parent", "file-parent"],
)
def test_force_refuses_unsafe_response_destinations(tmp_path, monkeypatch, path_kind):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    module = _module("recipe69_build_fixtures_unsafe_destination", recipe, monkeypatch)
    monkeypatch.setattr("sys.argv", ["build_fixtures.py", "--force", "--overwrite-assets"])
    responses = recipe / "fixtures" / "responses.json"
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    target = outside / responses.name
    if path_kind != "dangling":
        target.write_bytes(b"synthetic sentinel outside the recipe")

    if path_kind in {"linked-parent", "file-parent"}:
        if path_kind == "linked-parent":
            responses.parent.symlink_to(outside, target_is_directory=True)
        else:
            responses.parent.write_bytes(b"synthetic parent sentinel")
        error = "its parent must be a real directory"
    else:
        responses.parent.mkdir()
        error = "not a regular file"
        if path_kind in {"symlink", "dangling"}:
            responses.symlink_to(target)
        elif path_kind == "directory":
            responses.mkdir()
        elif path_kind == "fifo":
            if not hasattr(os, "mkfifo"):
                pytest.skip("named pipes are unavailable on this platform")
            os.mkfifo(responses)
        else:
            responses.write_bytes(b"synthetic file whose metadata cannot be inspected")
            lstat = Path.lstat

            def simulate_uninspectable(path):
                if path == responses:
                    raise PermissionError("simulated lstat failure")
                return lstat(path)

            monkeypatch.setattr(Path, "lstat", simulate_uninspectable)
            error = "the path cannot be inspected"

    with pytest.raises(SystemExit, match=error):
        module.main()
    assert not (recipe / "assets").exists()
    if path_kind == "dangling":
        assert not target.exists()
    else:
        assert target.read_bytes() == b"synthetic sentinel outside the recipe"
    if path_kind == "uninspectable":
        assert responses.read_bytes() == b"synthetic file whose metadata cannot be inspected"
    if path_kind == "file-parent":
        assert responses.parent.read_bytes() == b"synthetic parent sentinel"


@pytest.mark.parametrize("flags", [[], ["--force"]], ids=["default", "force"])
@pytest.mark.parametrize(
    "output", ["assets-manifest.json", "fixtures/inputs.jsonl", "fixtures/labels.jsonl"]
)
def test_text_output_symlinks_are_refused(tmp_path, monkeypatch, flags, output):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    module = _module("recipe69_build_fixtures_unsafe_text_output", recipe, monkeypatch)
    monkeypatch.setattr("sys.argv", ["build_fixtures.py", *flags])
    target = tmp_path / "sentinel"
    target.write_bytes(b"synthetic sentinel outside the recipe")
    path = recipe / output
    path.parent.mkdir(exist_ok=True)
    path.symlink_to(target)

    with pytest.raises(SystemExit, match="not a regular file"):
        module.main()
    assert target.read_bytes() == b"synthetic sentinel outside the recipe"
    assert path.is_symlink()
    assert not (recipe / "assets").exists()
