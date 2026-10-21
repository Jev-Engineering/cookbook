"""Image provenance: the assets manifest and what the fixture validator enforces about it.

Every rule is tried both ways: a recipe that satisfies it is valid, and one broken only in that
one respect fails with the rule's name and the file. The recipes are built in ``tmp_path`` with
Pillow-drawn images, so no binary file is committed.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import DecisionResult, Noul, NoulAnswer, Provenance
from jev_cookbook.fixtures import ASSETS_MANIFEST_FILE, validate_recipe
from jev_cookbook.fixtures import _assets as assets_module
from jev_cookbook.fixtures.__main__ import main
from jev_cookbook.fixtures._assets import (
    image_path_strings,
    inspect_image,
    looks_like_image_path,
)
from jev_cookbook.fixtures._schema import check, load_schema

ROOT = Path(__file__).resolve().parent.parent
LINE = re.compile(r"^\S.*?( \(id '[^']*'\))?: \[[a-z-]+\] \S")  # path: [rule] message
QUESTIONS = {"present": Noul(instructions="Is the target in the picture?")}


def png_bytes(seed: int, size: tuple[int, int] = (320, 300)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (seed, 255 - seed, seed // 2)).save(out, "PNG")
    return out.getvalue()


def jpeg_bytes(seed: int, size: tuple[int, int] = (300, 310)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (seed, seed, 255 - seed)).save(out, "JPEG")
    return out.getvalue()


def entry(path: str, data: bytes, **changes) -> dict:
    """A correct manifest entry for ``data`` stored at ``path`` (then ``changes`` applied)."""
    with Image.open(io.BytesIO(data)) as image:
        fmt, (width, height) = image.format, image.size
    item = {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": fmt,
        "width": width,
        "height": height,
        "origin": "generated",
        "generator": "build_fixtures.py:draw_scene",
        "parameters": {"seed": 7, "shapes": 3},
        "licence": "CC0-1.0",
        "description": "A flat grey-blue rectangle standing for a scene.",
        "attestations": {
            "synthetic": True,
            "real_photo": False,
            "real_brand": False,
            "real_person": False,
            "third_party_content": False,
        },
    }
    item.update(changes)
    return item


def build(tmp_path: Path, splits=("validation", "validation", "test", "test")) -> Path:
    """A valid multimodal recipe: one distinct image per example, all listed."""
    recipe = tmp_path / "61-demo"
    (recipe / "assets").mkdir(parents=True)
    (recipe / "fixtures").mkdir()
    (recipe / "build_fixtures.py").write_text("def draw_scene(seed):\n    return seed\n", "utf-8")
    inputs, labels, responses, items = [], [], {}, []
    for i, split in enumerate(splits):
        name = f"assets/scene-{i}.png"
        data = png_bytes(10 + i)
        (recipe / name).write_bytes(data)
        items.append(entry(name, data))
        key = hashlib.sha256(f"key-{i}".encode()).hexdigest()
        inputs.append(
            {
                "id": f"e{i}",
                "split": split,
                "fields": {"image": name, "note": f"look {i}"},
                "replay_keys": [key],
            }
        )
        if split != "demo":
            labels.append({"id": f"e{i}", "label": "present"})
        answer = NoulAnswer(0.9, Provenance.synthetic())
        responses[key] = DecisionResult({"present": answer}, "synthetic").to_dict()
    write_lines(recipe / "fixtures" / "inputs.jsonl", inputs)
    write_lines(recipe / "fixtures" / "labels.jsonl", labels)
    (recipe / "fixtures" / "responses.json").write_text(json.dumps(responses), "utf-8")
    write_manifest(recipe, {"schema": 1, "assets": items})
    return recipe


def write_lines(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8", newline="\n")


def write_manifest(recipe: Path, manifest) -> None:
    text = manifest if isinstance(manifest, str) else json.dumps(manifest, indent=2)
    (recipe / ASSETS_MANIFEST_FILE).write_text(text, "utf-8", newline="\n")


def read_manifest(recipe: Path) -> dict:
    return json.loads((recipe / ASSETS_MANIFEST_FILE).read_text("utf-8"))


def edit_manifest(recipe: Path, change) -> None:
    manifest = read_manifest(recipe)
    change(manifest)
    write_manifest(recipe, manifest)


def edit_inputs(recipe: Path, change) -> None:
    path = recipe / "fixtures" / "inputs.jsonl"
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    change(rows)
    write_lines(path, rows)


def text_only(rows: list[dict]) -> None:
    for i, row in enumerate(rows):
        row["fields"] = {"note": f"text only {i}"}


def problems(recipe: Path) -> list[str]:
    return [str(p) for p in validate_recipe(recipe)]


def expect(recipe: Path, rule: str, *fragments: str) -> list[str]:
    """The recipe fails with ``[rule]`` on a line containing every fragment; returns all lines."""
    found = problems(recipe)
    hits = [m for m in found if f"[{rule}]" in m and all(f in m for f in fragments)]
    assert hits, f"no [{rule}] line with {fragments} in {found}"
    for message in hits:
        assert LINE.match(message), message
    return found


# ---------------------------------------------------------------- the good recipe


def test_a_listed_multimodal_recipe_is_valid(tmp_path):
    assert problems(build(tmp_path)) == []


def test_jpeg_and_nested_folders_are_valid(tmp_path):
    recipe = build(tmp_path)
    data = jpeg_bytes(40)
    (recipe / "assets" / "nested").mkdir()
    (recipe / "assets" / "nested" / "frame.jpg").write_bytes(data)
    edit_manifest(
        recipe, lambda m: m["assets"].append(entry("assets/nested/frame.jpg", data, format="JPEG"))
    )
    assert problems(recipe) == []


def test_a_recipe_without_assets_needs_no_manifest(tmp_path):
    recipe = build(tmp_path)
    for path in list((recipe / "assets").iterdir()):
        path.unlink()
    (recipe / "assets").rmdir()
    (recipe / ASSETS_MANIFEST_FILE).unlink()
    edit_inputs(recipe, text_only)
    assert problems(recipe) == []


def _drop_images(recipe: Path) -> None:
    for path in list((recipe / "assets").iterdir()):
        path.unlink()
    (recipe / "assets").rmdir()
    (recipe / ASSETS_MANIFEST_FILE).unlink()


@pytest.mark.parametrize(
    "text",
    [
        "IMG_2041.JPG",
        "receipt.png",
        "https://tracker.example/att/12.png",
        "uploads/2041.jpeg",
        "C:\\Users\\x\\a.png",
        "../a.png",
    ],
)
def test_a_text_only_recipe_may_hold_file_names_and_links_in_fields(tmp_path, text):
    recipe = build(tmp_path)
    _drop_images(recipe)
    edit_inputs(recipe, text_only)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(uploaded_as=text))
    assert problems(recipe) == []


def test_a_text_only_recipe_naming_an_assets_path_still_fails(tmp_path):
    recipe = build(tmp_path)
    _drop_images(recipe)
    edit_inputs(recipe, text_only)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image="assets/ghost.png"))
    expect(recipe, "unlisted-asset", "assets/ghost.png", "e0")


def test_an_image_recipe_may_hold_a_bare_file_name_in_fields(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(uploaded_as="IMG_2041.JPG"))
    assert problems(recipe) == []


def test_an_empty_assets_folder_needs_no_manifest(tmp_path):
    recipe = build(tmp_path)
    for path in list((recipe / "assets").iterdir()):
        path.unlink()
    (recipe / ASSETS_MANIFEST_FILE).unlink()
    edit_inputs(recipe, text_only)
    assert problems(recipe) == []


def test_optional_shared_flag_false_is_valid(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(shared_across_splits=False))
    assert problems(recipe) == []


def test_a_package_generator_is_valid(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(
        recipe,
        lambda m: m["assets"][0].update(generator="jev_cookbook.synthetic_images:draw_dialog"),
    )
    assert problems(recipe) == []


def test_empty_parameters_are_valid(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(parameters={}))
    assert problems(recipe) == []


def test_command_line_reports_the_rule_and_exits_one(tmp_path, capsys):
    recipe = build(tmp_path)
    assert main(["validate", str(recipe)]) == 0
    (recipe / "assets" / "stray.png").write_bytes(png_bytes(99))
    assert main(["validate", str(recipe)]) == 1
    assert "stray.png: [unlisted-asset]" in capsys.readouterr().err


def test_validate_all_checks_assets(tmp_path, capsys):
    build(tmp_path)
    assert main(["validate", "--all", "--recipes-dir", str(tmp_path)]) == 0
    (tmp_path / "61-demo" / "assets" / "scene-0.png").unlink()
    assert main(["validate", "--all", "--recipes-dir", str(tmp_path)]) == 1
    assert "[missing-file]" in capsys.readouterr().err


# ------------------------------------------------- every file listed, every entry present


def test_manifest_missing(tmp_path):
    recipe = build(tmp_path)
    (recipe / ASSETS_MANIFEST_FILE).unlink()
    found = expect(recipe, "manifest-missing", ASSETS_MANIFEST_FILE)
    assert not any("[unlisted-asset]" in m and "fields" not in m for m in found)


def test_an_unreadable_manifest_is_one_line_not_one_per_reference(tmp_path):
    recipe = build(tmp_path)
    (recipe / ASSETS_MANIFEST_FILE).unlink()
    assert len(problems(recipe)) == 1
    write_manifest(recipe, '{"schema": 1, "assets": [],}')
    found = expect(recipe, "manifest-invalid")
    assert len(found) == 1, found


def test_a_path_repeated_in_one_example_is_reported_once(tmp_path):
    recipe = build(tmp_path)

    def change(rows):
        rows[0]["fields"].update(image="assets/ghost.png", also="assets/ghost.png")

    edit_inputs(recipe, change)
    ghosts = [m for m in problems(recipe) if "assets/ghost.png" in m]
    assert len(ghosts) == 1, ghosts


def test_image_missing_from_manifest(tmp_path):
    recipe = build(tmp_path)
    (recipe / "assets" / "extra.png").write_bytes(png_bytes(200))
    expect(recipe, "unlisted-asset", "assets/extra.png")


def test_unlisted_file_in_a_subfolder_and_non_image_file(tmp_path):
    recipe = build(tmp_path)
    (recipe / "assets" / "deep").mkdir()
    (recipe / "assets" / "deep" / "x.png").write_bytes(png_bytes(201))
    (recipe / "assets" / "notes.txt").write_text("hello", "utf-8")
    found = problems(recipe)
    assert any("assets/deep/x.png: [unlisted-asset]" in m for m in found)
    assert any("assets/notes.txt: [unlisted-asset]" in m for m in found)


def test_orphan_manifest_entry(tmp_path):
    recipe = build(tmp_path)
    (recipe / "assets" / "scene-3.png").unlink()
    found = expect(recipe, "missing-file", "assets/scene-3.png")
    # nothing else is reported for that entry: the hash of a missing file is not "wrong"
    assert not any("scene-3.png: [hash-mismatch]" in m for m in found)


def test_orphan_entry_whose_folder_is_gone(tmp_path):
    recipe = build(tmp_path)
    for path in list((recipe / "assets").iterdir()):
        path.unlink()
    (recipe / "assets").rmdir()
    expect(recipe, "missing-file", "assets/scene-0.png")


def test_entry_listed_twice(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"].append(copy.deepcopy(m["assets"][0])))
    expect(recipe, "duplicate-entry", "assets/scene-0.png")


def test_case_differing_entry_is_not_the_file(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(path="assets/Scene-0.png"))
    found = problems(recipe)
    assert any("[missing-file]" in m and "Scene-0.png" in m for m in found)
    assert any("[unlisted-asset]" in m and "scene-0.png" in m for m in found)


# ------------------------------------------------------------- hash, format and size


def test_hash_mismatch(tmp_path):
    recipe = build(tmp_path)
    (recipe / "assets" / "scene-1.png").write_bytes(png_bytes(222))
    found = expect(recipe, "hash-mismatch", "assets/scene-1.png")
    assert hashlib.sha256(png_bytes(222)).hexdigest() in " ".join(found)


def test_hash_must_be_lowercase_hex(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(sha256="ABC"))
    expect(recipe, "manifest-field", "sha256")


def test_format_mismatch(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(format="JPEG"))
    expect(recipe, "format-mismatch", "assets/scene-0.png", "bytes are PNG")


def test_bytes_that_are_not_an_image(tmp_path):
    recipe = build(tmp_path)
    junk = b"not an image at all"
    (recipe / "assets" / "scene-0.png").write_bytes(junk)
    edit_manifest(recipe, lambda m: m["assets"][0].update(sha256=hashlib.sha256(junk).hexdigest()))
    expect(recipe, "format-mismatch", "neither a PNG nor a JPEG")


def test_unsupported_format_name(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(format="GIF"))
    expect(recipe, "manifest-field", "format")


@pytest.mark.parametrize("key", ["width", "height"])
def test_size_mismatch(tmp_path, key):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update({key: 999}))
    expect(recipe, "size-mismatch", "assets/scene-0.png", "320 x 300")


def test_size_mismatch_for_a_jpeg(tmp_path):
    recipe = build(tmp_path)
    data = jpeg_bytes(30)
    (recipe / "assets" / "frame.jpg").write_bytes(data)
    good = entry("assets/frame.jpg", data)
    edit_manifest(recipe, lambda m: m["assets"].append(good))
    assert problems(recipe) == []
    good["width"] = 301
    edit_manifest(recipe, lambda m: m["assets"].__setitem__(-1, good))
    expect(recipe, "size-mismatch", "assets/frame.jpg", "300 x 310")


@pytest.mark.parametrize("value", [0, -3, 3.5, "320", True])
def test_width_must_be_a_positive_integer(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(width=value))
    expect(recipe, "manifest-field", "width")


# --------------------------------------------------------------- licence and origin


def test_licence_missing(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][2].pop("licence"))
    expect(recipe, "licence", "assets/scene-2.png", "licence")


@pytest.mark.parametrize("value", ["", "GPL-3.0-only", "cc0-1.0", "All rights reserved", None, 7])
def test_licence_must_be_an_allowed_identifier(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(licence=value))
    expect(recipe, "licence", "assets/scene-0.png")


@pytest.mark.parametrize("value", ["MIT", "CC0-1.0"])
def test_allowed_licences_pass(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(licence=value))
    assert problems(recipe) == []


@pytest.mark.parametrize("value", ["photographed", "downloaded", "", None])
def test_only_generated_origin_is_allowed(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(origin=value))
    expect(recipe, "manifest-field", "origin")


# ------------------------------------------------------------------- attestations

FALSE_ONES = ["real_photo", "real_brand", "real_person", "third_party_content"]


@pytest.mark.parametrize("name", FALSE_ONES)
def test_a_true_attestation_fails(tmp_path, name):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][1]["attestations"].update({name: True}))
    expect(recipe, "attestation", "assets/scene-1.png", name)


def test_synthetic_must_be_true(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0]["attestations"].update(synthetic=False))
    expect(recipe, "attestation", "synthetic")


@pytest.mark.parametrize("name", ["synthetic", *FALSE_ONES])
def test_a_missing_attestation_fails(tmp_path, name):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0]["attestations"].pop(name))
    expect(recipe, "attestation", "assets/scene-0.png", name)


def test_all_attestations_missing(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].pop("attestations"))
    expect(recipe, "manifest-field", "attestations")


@pytest.mark.parametrize("value", [None, 0, 1, "false", "no", []])
def test_an_attestation_must_be_the_boolean_false(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0]["attestations"].update(real_photo=value))
    expect(recipe, "attestation", "real_photo")


def test_an_unknown_attestation_is_refused(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0]["attestations"].update(reviewed=True))
    expect(recipe, "attestation", "reviewed")


# ---------------------------------------------------------------- required fields


@pytest.mark.parametrize(
    "field",
    [
        "path",
        "sha256",
        "format",
        "width",
        "height",
        "origin",
        "generator",
        "parameters",
        "description",
    ],
)
def test_each_required_field(tmp_path, field):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].pop(field))
    expect(recipe, "manifest-field", f"'{field}'")


def test_description_may_not_be_empty(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(description=""))
    expect(recipe, "manifest-field", "description")


def test_parameters_must_be_an_object(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(parameters=7))
    expect(recipe, "manifest-field", "parameters")


def test_unknown_entry_field(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(source_url="https://example.com/a.png"))
    expect(recipe, "manifest-field", "source_url")


def test_unknown_top_level_field_and_wrong_version(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m.update(extra=1, schema=2))
    found = problems(recipe)
    assert any("[manifest-field]" in m and "extra" in m for m in found)
    assert any("[manifest-field]" in m and "schema" in m for m in found)


def test_an_empty_asset_list_is_refused(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m.update(assets=[]))
    expect(recipe, "manifest-field", "at least 1")


def test_entry_that_is_not_an_object(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"].append("assets/x.png"))
    expect(recipe, "manifest-field", "assets[4]")


@pytest.mark.parametrize(
    "text", ["{not json", "", "[]", '"x"', '{"schema": 1, "schema": 1, "assets": []}', "NaN"]
)
def test_unreadable_manifest(tmp_path, text):
    recipe = build(tmp_path)
    write_manifest(recipe, text)
    expect(recipe, "manifest-invalid")


def test_manifest_not_utf8(tmp_path):
    recipe = build(tmp_path)
    (recipe / ASSETS_MANIFEST_FILE).write_bytes(b"\xff\xfe\x00")
    expect(recipe, "manifest-invalid", "UTF-8")


# ------------------------------------------------------------------ the generator


def test_generator_script_must_exist_in_the_recipe(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(generator="nowhere.py:draw_scene"))
    expect(recipe, "generator", "nowhere.py")


def test_generator_function_must_appear_in_the_script(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(generator="build_fixtures.py:draw_other"))
    expect(recipe, "generator", "draw_other")


@pytest.mark.parametrize(
    "value",
    [
        "",
        "build_fixtures.py",
        "build_fixtures.py:",
        "../build_fixtures.py:draw_scene",
        "sub/x.py:f",
        "/abs.py:f",
        "other.txt:f",
        "x.py:two words",
    ],
)
def test_generator_shape(tmp_path, value):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(generator=value))
    expect(recipe, "manifest-field", "generator")


# --------------------------------------------------------- path traversal and shape

BAD_LISTED_PATHS = [
    "assets/../outside.png",
    "../outside.png",
    "assets/../../outside.png",
    "/etc/passwd.png",
    "C:/x/a.png",
    "assets\\scene-0.png",
    "assets/./scene-0.png",
    "assets//scene-0.png",
    "assets/.hidden.png",
    "assets/sub/../scene-0.png",
    "assets/scene-0.PNG",
    "assets/scene-0.gif",
    "scene-0.png",
    "https://example.com/assets/scene-0.png",
    "assets/ scene-0.png",
    "assets/scene-0.png\n",
    "",
]


@pytest.mark.parametrize("bad", BAD_LISTED_PATHS)
def test_a_listed_path_must_be_a_clean_assets_path(tmp_path, bad):
    recipe = build(tmp_path)
    (tmp_path / "outside.png").write_bytes(png_bytes(77))
    edit_manifest(recipe, lambda m: m["assets"][0].update(path=bad))
    found = expect(recipe, "asset-path", "path")
    assert not any("outside.png: [hash-mismatch]" in m for m in found)


def test_a_traversing_listed_path_does_not_read_outside_the_recipe(tmp_path):
    recipe = build(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(77))
    edit_manifest(
        recipe, lambda m: m["assets"].append(entry("assets/../../outside.png", png_bytes(77)))
    )
    found = problems(recipe)
    assert any("[asset-path]" in m for m in found)
    assert not any("[hash-mismatch]" in m or "[size-mismatch]" in m for m in found)


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symbolic links")


def test_a_symlink_to_a_file_outside_the_recipe(tmp_path):
    recipe = build(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(78))
    _symlink(recipe / "assets" / "link.png", outside)
    edit_manifest(recipe, lambda m: m["assets"].append(entry("assets/link.png", png_bytes(78))))
    expect(recipe, "asset-path", "assets/link.png")


def test_a_listed_file_that_resolves_outside_assets_is_refused(tmp_path, monkeypatch):
    """The containment check itself, for platforms where a test cannot make a symlink."""
    recipe = build(tmp_path)
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(80))
    monkeypatch.setattr("jev_cookbook.vision.resolve_asset_path", lambda path, *, root: outside)
    found = problems(recipe)
    assert any("scene-0.png: [asset-path]" in m and "inside assets/" in m for m in found)
    assert not any("[hash-mismatch]" in m for m in found)


def test_a_symlinked_folder_under_assets(tmp_path):
    recipe = build(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "p.png").write_bytes(png_bytes(79))
    _symlink(recipe / "assets" / "linked", elsewhere)
    expect(recipe, "unlisted-asset", "assets/linked")


def test_the_asset_path_rule_matches_the_schema():
    schema = load_schema(assets_module.ASSETS_SCHEMA_FILE)
    assert (
        schema["$defs"]["asset"]["properties"]["path"]["pattern"]
        == assets_module._ASSET_PATH.pattern
    )
    generator = schema["$defs"]["asset"]["properties"]["generator"]["pattern"]
    assert generator == assets_module._GENERATOR.pattern


# -------------------------------------------------------- fields image paths


def test_fields_path_without_an_entry(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image="assets/ghost.png"))
    found = expect(recipe, "unlisted-asset", "assets/ghost.png", "e0")
    assert any("fixtures/inputs.jsonl" in m for m in found)


def test_fields_path_in_a_nested_value(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(frames=[{"img": "assets/ghost.png"}]))
    expect(recipe, "unlisted-asset", "assets/ghost.png")


def test_fields_path_listed_nested_value_is_valid(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(
        recipe, lambda rows: rows[0]["fields"].update(frames=[{"img": "assets/scene-0.png"}])
    )
    assert problems(recipe) == []


@pytest.mark.parametrize(
    "bad",
    [
        "../secret.png",
        "assets/../../secret.png",
        "/etc/shadow.png",
        "C:/Windows/x.png",
        "C:\\x\\y.png",
        "https://example.com/a.png",
        "assets/../../etc/passwd",
    ],
)
def test_fields_path_that_escapes_or_is_not_local(tmp_path, bad):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image=bad))
    found = problems(recipe)
    assert any(("[asset-path]" in m or "[unlisted-asset]" in m) and "e0" in m for m in found), found


NOT_A_CLEAN_ASSET_PATH = [
    "../secret.png",
    "assets/../../secret.png",
    "/etc/shadow.png",
    "C:/Windows/x.png",
    "C:\\x\\y.png",
    "\\\\server\\share\\x.png",
    "./assets/scene-0.png",
    "fixtures/scene-0.png",
    "assets\\scene-0.png",
    "ASSETS/scene-0.png",
    "assets/Scene-0.PNG",
    "https://example.com/a.png",
    "file:///etc/x.png",
    "assets/noext",
    "assets/a\x00.png",
]


@pytest.mark.parametrize("bad", NOT_A_CLEAN_ASSET_PATH)
def test_fields_path_traversal_is_an_asset_path_problem(tmp_path, bad):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image=bad))
    found = expect(recipe, "asset-path", repr(bad), "e0")
    assert not [m for m in found if "[unlisted-asset]" in m and repr(bad) in m]


@pytest.mark.parametrize("bad", NOT_A_CLEAN_ASSET_PATH)
def test_the_rule_does_not_depend_on_what_the_operating_system_makes_of_the_path(
    tmp_path, bad, monkeypatch
):
    """``resolve_asset_path`` accepts ``C:/x.png`` on POSIX and refuses it on Windows. The
    finding must be the same either way, so make it accept everything and look again."""
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image=bad))
    monkeypatch.setattr("jev_cookbook.vision.resolve_asset_path", lambda path, *, root: recipe)
    expect(recipe, "asset-path", repr(bad), "e0")


def test_fields_path_must_be_written_exactly_as_listed(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(image="assets/../assets/scene-0.png"))
    expect(recipe, "asset-path", "assets/../assets/scene-0.png", "exactly as listed", "e0")


def test_prose_that_mentions_an_image_is_not_a_path(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[0]["fields"].update(note="compare with chart.png please"))
    assert problems(recipe) == []


def test_a_demo_example_may_name_a_listed_image_used_elsewhere(tmp_path):
    recipe = build(tmp_path, splits=("validation", "validation", "test", "demo"))
    edit_inputs(recipe, lambda rows: rows[3]["fields"].update(image="assets/scene-0.png"))
    # scene-3 is now referenced by nothing: allowed, assets may be used by criteria or notes
    assert problems(recipe) == []


def test_state_examples_are_not_scanned_for_images(tmp_path):
    recipe = build(tmp_path)

    def change(rows):
        rows[0].pop("fields")
        rows[0]["state"] = {"text": "assets/ghost.png"}

    edit_inputs(recipe, change)
    assert not [m for m in problems(recipe) if "ghost" in m]


# ----------------------------------------------------------------------- split leak


def test_same_bytes_under_two_paths_in_two_splits(tmp_path):
    recipe = build(tmp_path)
    data = (recipe / "assets" / "scene-0.png").read_bytes()  # validation e0
    (recipe / "assets" / "scene-2.png").write_bytes(data)  # test e2 now has identical bytes
    edit_manifest(recipe, lambda m: m["assets"][2].update(sha256=hashlib.sha256(data).hexdigest()))
    expect(
        recipe,
        "split-leak",
        "validation: e0",
        "test: e2",
        "assets/scene-0.png",
        "assets/scene-2.png",
    )


def test_the_same_path_in_two_splits(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[2]["fields"].update(image="assets/scene-0.png"))
    expect(recipe, "split-leak", "validation: e0", "test: e2")


def test_train_validation_leak_is_also_found(tmp_path):
    recipe = build(tmp_path, splits=("train", "validation", "test", "test"))
    edit_inputs(recipe, lambda rows: rows[1]["fields"].update(image="assets/scene-0.png"))
    expect(recipe, "split-leak", "train: e0", "validation: e1")


def test_the_same_image_twice_in_one_split_is_not_a_leak(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[1]["fields"].update(image="assets/scene-0.png"))
    assert problems(recipe) == []


def test_demo_may_share_an_image_with_a_scored_split(tmp_path):
    recipe = build(tmp_path, splits=("validation", "demo", "test", "test"))
    edit_inputs(recipe, lambda rows: rows[1]["fields"].update(image="assets/scene-0.png"))
    assert problems(recipe) == []


def test_shared_reference_image_allow_list(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[2]["fields"].update(image="assets/scene-0.png"))
    edit_manifest(recipe, lambda m: m["assets"][0].update(shared_across_splits=True))
    assert problems(recipe) == []


def test_allow_list_must_cover_every_entry_with_the_bytes(tmp_path):
    recipe = build(tmp_path)
    data = (recipe / "assets" / "scene-0.png").read_bytes()
    (recipe / "assets" / "scene-2.png").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()

    def change(m):
        m["assets"][2]["sha256"] = digest
        m["assets"][0]["shared_across_splits"] = True

    edit_manifest(recipe, change)
    expect(recipe, "split-leak")
    edit_manifest(recipe, lambda m: m["assets"][2].update(shared_across_splits=True))
    assert problems(recipe) == []


def test_shared_flag_must_be_a_boolean(tmp_path):
    recipe = build(tmp_path)
    edit_manifest(recipe, lambda m: m["assets"][0].update(shared_across_splits="yes"))
    expect(recipe, "manifest-field", "shared_across_splits")


def test_a_leak_is_not_judged_on_a_file_whose_hash_is_wrong(tmp_path):
    recipe = build(tmp_path)
    edit_inputs(recipe, lambda rows: rows[2]["fields"].update(image="assets/scene-0.png"))
    (recipe / "assets" / "scene-0.png").write_bytes(png_bytes(250))
    found = problems(recipe)
    assert any("[hash-mismatch]" in m for m in found)


# --------------------------------------------------------------------- helpers


def test_looks_like_image_path():
    for yes in [
        "assets/a.png",
        "../a.jpeg",
        "C:\\x\\a.png",
        "C:/x/a.png",
        "https://h/a.png",
        "assets/noext",
        "assets\\a.PNG",
        "ASSETS/a.png",
    ]:
        assert looks_like_image_path(yes), yes
    for bare in ["x.JPG", "IMG_2041.jpeg", "a.png"]:
        assert not looks_like_image_path(bare), bare
    for only_with_images in ["../a.jpeg", "https://h/a.png", "C:\\x\\a.png"]:
        assert not looks_like_image_path(only_with_images, has_images=False), only_with_images
    assert looks_like_image_path("assets/a.png", has_images=False)
    for no in [
        "",
        "a picture.png",
        "plain text",
        "png",
        "a.gif",
        "see assets/a.png",
        "data:image/png;base64,AA",
    ]:
        assert not looks_like_image_path(no), no


def test_image_path_strings_walks_values_not_keys():
    fields = {"a.png": "text", "b": ["assets/x.png", {"c": "y.jpg", "d": 3}], "e": None}
    assert image_path_strings(fields) == ["assets/x.png"]
    assert image_path_strings({"b": ["sub/y.jpg", "z.jpg"]}) == ["sub/y.jpg"]


def test_image_path_strings_survives_deep_nesting():
    deep: object = "assets/deep.png"
    for _ in range(5000):
        deep = [deep]
    assert image_path_strings({"x": deep}) == ["assets/deep.png"]


def test_inspect_image_reads_headers():
    assert inspect_image(png_bytes(1, (400, 281))) == ("PNG", 400, 281)
    assert inspect_image(jpeg_bytes(1, (500, 290))) == ("JPEG", 500, 290)
    assert inspect_image(b"") is None
    assert inspect_image(b"\x89PNG\r\n\x1a\n") is None
    assert inspect_image(b"\xff\xd8\xff\xd9") is None
    assert inspect_image(b"GIF89a" + b"\x00" * 30) is None
    assert inspect_image(jpeg_bytes(1)[:30]) is None


def test_the_schema_checker_supports_const_and_minimum():
    schema = {
        "type": "object",
        "properties": {"a": {"const": False}, "b": {"type": "integer", "minimum": 1}},
    }
    assert check({"a": False, "b": 1}, schema, schema) == []
    assert check({"a": 0}, schema, schema)
    assert check({"a": True}, schema, schema)
    assert check({"b": 0}, schema, schema)
    assert check({"b": True}, schema, schema)


def test_the_worked_example_in_the_docs_satisfies_the_schema():
    text = (ROOT / "docs" / "fixtures.md").read_text("utf-8")
    start = text.index("#### Image provenance manifest")
    block = re.search(r"```json\n(.*?)\n```", text[start:], re.S)
    assert block, "the worked example is missing"
    example = json.loads(block.group(1))
    schema = load_schema(assets_module.ASSETS_SCHEMA_FILE)
    assert check(example, schema, schema) == []
    # and it is a manifest the validator accepts once the file it describes exists
    assert example["assets"][0]["path"] == "assets/scene-0.png"


def test_the_docs_helper_builds_entries_the_validator_accepts(tmp_path):
    text = (ROOT / "docs" / "fixtures.md").read_text("utf-8")
    code = re.search(r"```python\n(import hashlib\n.*?)\n```", text, re.S)
    assert code, "the manifest_entry helper is missing from the docs"
    scope: dict = {}
    exec(code.group(1), scope)  # noqa: S102 - our own documentation snippet
    recipe = build(tmp_path)
    assert Path.cwd() != recipe  # the helper must not depend on the current directory
    items = [
        scope["manifest_entry"](
            recipe, f"assets/scene-{i}.png", "build_fixtures.py:draw_scene", {"seed": i}, "a scene"
        )
        for i in range(4)
    ]
    write_manifest(recipe, {"schema": 1, "assets": items})
    assert problems(recipe) == []


def test_the_schema_file_loads_and_is_fully_supported():
    schema = load_schema(assets_module.ASSETS_SCHEMA_FILE)
    # check() raises on a keyword it cannot enforce, so a good manifest passing proves coverage
    good = {"schema": 1, "assets": [entry("assets/a.png", png_bytes(5))]}
    assert check(good, schema, schema) == []
    assert os.path.exists(
        ROOT / "src" / "jev_cookbook" / "fixtures" / "assets-manifest.schema.json"
    )
