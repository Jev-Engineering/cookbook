"""Extra issue-506 batch checks through the generated builder's public interface.

Only temporary synthetic PNGs and monkeypatched draw functions are used. Validation
must precede destination mutations; this does not promise rollback after later disk
I/O failures or protection against concurrent filesystem changes.
"""

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

from jev_cookbook import synthetic_images as si

REPO = Path(__file__).resolve().parent.parent
CATALOG = json.loads((REPO / "catalog/recipes.json").read_text("utf-8"))
RECIPE = next(row for row in CATALOG["recipes"] if row["rank"] == 77)


def _load(path, name, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def generated(tmp_path, monkeypatch):
    scaffolder = _load(REPO / "tools/new_recipe.py", "batch_safety_scaffolder", monkeypatch)
    folder = tmp_path / "recipe"
    for name, text in scaffolder.files_for(CATALOG, RECIPE, "replay-images").items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    builder = _load(folder / "build_fixtures.py", "batch_safety_builder", monkeypatch)
    builder.ROWS = builder.ROWS[:3]
    return folder, builder


def _canvas(row, *, variant=0):
    return si.Canvas(320, 320, background=(35 + variant, 89, 121)).provenance(
        "build_fixtures.py:draw", {"row": list(row), "variant": variant}
    )


def _snapshot(folder):
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def _prepare_early_destination(folder, builder, existing):
    if existing:
        # A valid prospective replacement must stay untouched when a later row
        # fails validation, including when overwriting has been authorized.
        _canvas(builder.ROWS[0], variant=17).write(
            folder, builder.image_path(builder.ROWS[0][0]), overwrite=True
        )


@pytest.mark.parametrize("existing", [False, True], ids=["new-file", "overwrite-file"])
@pytest.mark.parametrize(
    "problem",
    ["missing_generator", "missing_parameters", "unknown_generator", "non_json", "nan"],
)
def test_late_invalid_provenance_is_refused_before_any_png_changes(
    generated, monkeypatch, existing, problem
):
    folder, builder = generated
    _prepare_early_destination(folder, builder, existing)

    def draw(row):
        canvas = _canvas(row)
        if row == builder.ROWS[-1]:
            if problem == "missing_generator":
                canvas.generator = None
            elif problem == "missing_parameters":
                canvas.parameters = None
            elif problem == "unknown_generator":
                canvas.generator = "build_fixtures.py:no_such_synthetic_draw"
            else:
                # Canvas provenance is public mutable state. Check its current
                # value, even when it was valid when provenance() was called.
                canvas.parameters["invalid"] = object() if problem == "non_json" else float("nan")
        return canvas

    monkeypatch.setattr(builder, "draw", draw)
    before = _snapshot(folder)
    with pytest.raises(ValueError):
        builder.write_images(builder.ROWS, overwrite=existing)
    assert _snapshot(folder) == before


@pytest.mark.parametrize("existing", [False, True], ids=["new-file", "overwrite-file"])
@pytest.mark.parametrize("problem", ["invalid_suffix", "parent_escape", "symlink_escape"])
def test_late_invalid_destination_is_refused_before_any_png_changes(
    generated, monkeypatch, existing, problem
):
    folder, builder = generated
    _prepare_early_destination(folder, builder, existing)
    original_path = builder.image_path
    if problem == "symlink_escape":
        outside = folder.parent / "outside"
        outside.mkdir()
        (folder / "assets").mkdir(exist_ok=True)
        (folder / "assets/escape").symlink_to(outside, target_is_directory=True)
        invalid = "assets/escape/late.png"
    else:
        invalid = "assets/late.jpg" if problem == "invalid_suffix" else "assets/../../late.png"
    monkeypatch.setattr(
        builder,
        "image_path",
        lambda ident: invalid if ident == builder.ROWS[-1][0] else original_path(ident),
    )
    monkeypatch.setattr(builder, "draw", _canvas)
    before = _snapshot(folder.parent)
    with pytest.raises(ValueError):
        builder.write_images(builder.ROWS, overwrite=existing)
    assert _snapshot(folder.parent) == before


@pytest.mark.parametrize("alias", [False, True], ids=["same-path", "resolved-symlink-alias"])
def test_duplicate_resolved_destinations_are_refused_before_writing(generated, monkeypatch, alias):
    folder, builder = generated
    (folder / "assets/real").mkdir(parents=True)
    if alias:
        (folder / "assets/alias").symlink_to(folder / "assets/real", target_is_directory=True)
    paths = [
        "assets/first.png",
        "assets/real/shared.png",
        "assets/alias/shared.png" if alias else "assets/real/shared.png",
    ]
    destinations = dict(zip((row[0] for row in builder.ROWS), paths, strict=True))
    monkeypatch.setattr(builder, "image_path", destinations.__getitem__)
    monkeypatch.setattr(builder, "draw", _canvas)
    before = _snapshot(folder)
    with pytest.raises(ValueError):
        builder.write_images(builder.ROWS, overwrite=False)
    assert _snapshot(folder) == before


def test_noncanonical_equal_pixels_keep_saved_bytes_and_hash_the_saved_file(generated, monkeypatch):
    folder, builder = generated
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: False)
    monkeypatch.setattr(builder, "draw", _canvas)
    retained = {}
    for row in builder.ROWS:
        canvas = _canvas(row)
        buffer = io.BytesIO()
        canvas.image.save(buffer, "PNG", compress_level=0)
        data = buffer.getvalue()
        assert data != canvas.png()
        assert si.png_pixels_equal(data, canvas.png())
        path = builder.image_path(row[0])
        destination = folder / path
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(data)
        retained[path] = data
    before = _snapshot(folder)
    entries = builder.write_images(builder.ROWS, overwrite=False)
    assert _snapshot(folder) == before
    assert {entry["path"] for entry in entries} == set(retained)
    for entry in entries:
        assert entry["sha256"] == hashlib.sha256(retained[entry["path"]]).hexdigest()


def test_overwrite_replaces_changed_pixels_and_returns_matching_manifest(generated, monkeypatch):
    folder, builder = generated
    for row in builder.ROWS:
        _canvas(row, variant=17).write(folder, builder.image_path(row[0]), overwrite=True)
    monkeypatch.setattr(builder, "draw", _canvas)
    entries = builder.write_images(builder.ROWS, overwrite=True)
    assert len(entries) == len(builder.ROWS)
    by_path = {builder.image_path(row[0]): row for row in builder.ROWS}
    for entry in entries:
        data = (folder / entry["path"]).read_bytes()
        assert data == _canvas(by_path[entry["path"]]).png()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["generator"] == "build_fixtures.py:draw"
        assert entry["parameters"] == _canvas(by_path[entry["path"]]).parameters


def test_custom_recipe_generator_draws_once_per_row_and_cache_is_run_local(generated, monkeypatch):
    folder, builder = generated
    calls = []

    def draw(row):
        canvas = _canvas(row)
        calls.append((row, canvas))
        return canvas

    monkeypatch.setattr(builder, "draw", draw)
    caches = []
    for _run in range(2):
        cached = []
        entries = builder.write_images(builder.ROWS, overwrite=False, canvases=cached)
        expected = calls[-len(builder.ROWS) :]
        assert [row for row, _canvas_value in expected] == builder.ROWS
        assert len(cached) == len(builder.ROWS)
        assert all(actual is drawn for actual, (_row, drawn) in zip(cached, expected, strict=True))
        for entry in entries:
            assert entry["generator"] == "build_fixtures.py:draw"
            row = next(row for row in builder.ROWS if builder.image_path(row[0]) == entry["path"])
            assert entry["parameters"] == json.loads(json.dumps({"row": list(row), "variant": 0}))
            assert (
                entry["sha256"] == hashlib.sha256((folder / entry["path"]).read_bytes()).hexdigest()
            )
        caches.append(cached)
    assert len(calls) == 2 * len(builder.ROWS)
    assert all(first is not second for first, second in zip(*caches, strict=True))
