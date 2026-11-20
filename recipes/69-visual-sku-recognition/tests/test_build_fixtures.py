"""build_fixtures.py follows the recipes/_template/build_fixtures.py pattern, with images: inputs
and labels generation is separate from responses generation, a recorded responses.json is never
silently overwritten, a picture that differs from the committed file is refused rather than
rewritten, and the committed files match what the script writes: the images and
assets-manifest.json unchanged, and responses.json byte for byte what jev_cookbook.live's writer
produces."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from jev_cookbook import dump_responses
from jev_cookbook import synthetic_images as si

RECIPE = Path(__file__).resolve().parent.parent
SCRIPT = RECIPE / "build_fixtures.py"


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values (ROWS,
    build_responses) are plain Python objects, not subprocess output or a re-dump of the file
    it wrote."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def _copy_of_the_recipe(folder):
    """A folder holding what a rerun needs: the two scripts and the committed images. The images
    are copied because their bytes are part of the replay key of each request that carries
    them: with the committed files beside it the script compares each picture it draws with the
    committed one, and without them it would create the pictures afresh with whatever PNG
    encoder this environment has."""
    folder.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (folder / name).write_bytes((RECIPE / name).read_bytes())
    shutil.copytree(RECIPE / "assets", folder / "assets")
    return folder / "build_fixtures.py"


def test_the_committed_responses_are_byte_identical_to_the_recorders_writer():
    """jev_cookbook.dump_responses sorts only the top-level keys; json.dumps(..., sort_keys=True)
    sorts every nested dict too and so disagrees with it on every response's field order. The
    committed file must match dump_responses exactly, not just agree with it on top-level order.

    Comparing against dump_responses(json.loads(raw)) (re-dumping the file's own parsed content)
    cannot catch a sort_keys=True regression: json.loads preserves whatever nested order the file
    already has, and dump_responses only re-sorts the top level, so that round trip would pass no
    matter which writer produced the file. Instead, import build_fixtures.py and compare against
    dump_responses of what build_responses computes directly from ROWS, independent of what
    main() actually wrote to disk."""
    raw = (RECIPE / "fixtures" / "responses.json").read_text("utf-8")
    module = load_module_at(SCRIPT, "recipe69_build_fixtures_for_test")
    assert len(module.ROWS) > 1
    assert raw == dump_responses(module.build_responses(module.ROWS))


def test_build_fixtures_separates_inputs_labels_from_responses(tmp_path):
    """Mutation check: regenerating must never silently overwrite a recorded responses.json,
    and --force must restore the exact synthetic bytes. inputs.jsonl and labels.jsonl are
    rewritten from ROWS on every run, refused or not: only responses.json is guarded, and this
    also proves it by corrupting both files before the refused run and checking that they come
    back exactly as build_inputs_and_labels(ROWS) computes them, not merely "changed"."""
    script = _copy_of_the_recipe(tmp_path / "69-visual-sku-recognition")
    copy = script.parent
    first = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr

    responses = copy / "fixtures" / "responses.json"
    data = json.loads(responses.read_text("utf-8"))
    for value in data.values():
        value["model"] = "jev-1.13.0"
    responses.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    before = responses.read_bytes()

    inputs_path = copy / "fixtures" / "inputs.jsonl"
    labels_path = copy / "fixtures" / "labels.jsonl"
    inputs_path.write_bytes(b"corrupted")
    labels_path.write_bytes(b"corrupted")

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == before
    module = load_module_at(script, "recipe69_build_fixtures_for_test_refused")
    expected_inputs, expected_labels = module.build_inputs_and_labels(module.ROWS)
    assert inputs_path.read_text("utf-8") == _jsonl(expected_inputs)
    assert labels_path.read_text("utf-8") == _jsonl(expected_labels)

    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    after = json.loads(responses.read_text("utf-8"))
    assert all(v["model"] == "synthetic" for v in after.values())


def test_the_generator_reproduces_the_committed_fixtures_and_images(tmp_path):
    script = _copy_of_the_recipe(tmp_path / "69-visual-sku-recognition")
    copy = script.parent
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()
    assert (copy / "assets-manifest.json").read_bytes() == (
        RECIPE / "assets-manifest.json"
    ).read_bytes()
    committed = sorted(p.relative_to(RECIPE) for p in (RECIPE / "assets").rglob("*") if p.is_file())
    assert committed
    assert sorted(p.relative_to(copy) for p in (copy / "assets").rglob("*") if p.is_file()) == (
        committed
    )
    for path in committed:
        assert (copy / path).read_bytes() == (RECIPE / path).read_bytes(), path


def test_a_picture_that_differs_from_the_committed_file_is_refused_not_rewritten(tmp_path):
    """The byte policy of docs/synthetic-images.md: a changed picture is a new hash and so new
    replay keys, which is a decision. The script stops, names the problem and writes nothing more;
    --overwrite-assets accepts the redrawn picture and restores the committed one."""
    script = _copy_of_the_recipe(tmp_path / "69-visual-sku-recognition")
    copy = script.parent
    picture = sorted((copy / "assets").glob("*.png"))[0]
    committed = picture.read_bytes()
    with Image.open(picture) as original:
        size = original.size
    Image.new("RGB", size, "white").save(picture)
    changed = picture.read_bytes()
    assert changed != committed
    manifest = copy / "assets-manifest.json"
    assert not manifest.exists()

    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0
    assert "refused" in refused.stderr and "nothing else was written" in refused.stderr
    assert picture.read_bytes() == changed
    assert not manifest.exists() and not (copy / "fixtures").exists()

    accepted = subprocess.run(
        [sys.executable, str(script), "--overwrite-assets"], capture_output=True, text=True
    )
    assert accepted.returncode == 0, accepted.stderr
    # The same pixels as the committed picture. Whether the bytes are the committed ones too
    # depends on the PNG encoder of the environment running this test (docs/synthetic-images.md).
    assert picture.read_bytes() != changed
    assert si.png_pixels_equal(picture.read_bytes(), committed)
