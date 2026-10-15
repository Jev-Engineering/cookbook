"""The requests carry image evidence without disclosing the fixture labels or filenames."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs
from jev_cookbook.vision import image_asset, image_reference

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def test_reference_and_query_sets_are_separate_valid_opaque_pngs():
    examples = load_inputs(RECIPE)
    references = {RECIPE / relative for relative in helpers.CATALOG.values()}
    queries = {RECIPE / example.fields["image"] for example in examples}
    assert len(references) == 4
    assert len(queries) == len(examples)
    assert references.isdisjoint(queries)
    assert references == set((RECIPE / "assets" / "references").glob("*.png"))
    assert queries == set((RECIPE / "assets" / "queries").glob("*.png"))
    assert {path.read_bytes() for path in references}.isdisjoint(
        {path.read_bytes() for path in queries}
    )
    for path in references | queries:
        pattern = r"ref-\d{2}\.png" if path in references else r"q-\d{3}\.png"
        assert re.fullmatch(pattern, path.name)
        with Image.open(path) as image:
            image.load()
            assert image.format == "PNG"
            assert image.mode == "RGB"
            assert image.width >= 384 and image.height >= 320
            assert not image.info, "the PNG must not carry hidden labels or authoring metadata"


def test_every_catalog_choice_has_its_own_actual_reference_and_state_has_only_the_query():
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields)
    query = image_reference(image_asset(RECIPE / example.fields["image"]))
    assert state == {"query_image": query}
    assert set(questions) == {"sku"}
    criteria = questions["sku"].criteria
    assert list(criteria) == ["sku_101", "sku_102", "sku_103", "sku_104", "no_match", "unknown"]
    references = set()
    for sku, relative in helpers.CATALOG.items():
        expected_asset = image_asset(RECIPE / relative)
        expected_reference = image_reference(expected_asset)
        assert criteria[sku]["reference_image"] == expected_reference
        assert criteria[sku]["match_rule"]
        assert assets[expected_reference] == expected_asset
        references.add(expected_reference)
    assert len(references) == 4
    assert query not in references
    assert set(assets) == references | {query}
    assert assets[query] == image_asset(RECIPE / example.fields["image"])
    assert isinstance(criteria["no_match"], str) and criteria["no_match"]
    assert isinstance(criteria["unknown"], str) and criteria["unknown"]


def test_ids_gold_and_drawing_parameters_cannot_change_the_request():
    example = load_inputs(RECIPE)[0]
    original = helpers.build_request(example.fields)
    fields = {
        **example.fields,
        "id": "secret-query-identity",
        "split": "secret-split",
        "label": "secret-gold-label",
        "variant": "secret-drawing-variant",
        "lighting": "secret-lighting",
        "obstruction": "secret-obstruction",
    }
    changed = helpers.build_request(fields)
    assert changed == original
    state, questions, _assets = original
    request_text = json.dumps(
        {
            "state": state,
            "questions": {name: question.to_dict() for name, question in questions.items()},
        }
    )
    for forbidden in (
        "assets/",
        ".png",
        "secret-",
        '"label"',
        '"split"',
        '"variant"',
        '"lighting"',
        '"obstruction"',
    ):
        assert forbidden not in request_text


def test_every_replay_key_matches_the_current_pixels_and_question():
    for example in load_inputs(RECIPE):
        state, questions, assets = helpers.build_request(example.fields)
        assert example.replay_keys == (replay_key(state, questions, assets=assets),)


@pytest.mark.parametrize("changed_asset", ["query", "reference"])
def test_changing_query_or_reference_pixels_changes_request_identity(tmp_path, changed_asset):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    example = load_inputs(RECIPE)[0]
    state, questions, assets = helpers.build_request(example.fields, root=tmp_path)
    original_key = replay_key(state, questions, assets=assets)
    relative = (
        example.fields["image"]
        if changed_asset == "query"
        else next(iter(helpers.CATALOG.values()))
    )
    path = tmp_path / relative
    original_bytes = path.read_bytes()
    with Image.open(path) as source:
        changed = source.convert("RGB")
    red, green, blue = changed.getpixel((0, 0))
    changed.putpixel((0, 0), ((red + 1) % 256, green, blue))
    changed.save(path)

    altered_state, altered_questions, altered_assets = helpers.build_request(
        example.fields, root=tmp_path
    )
    altered_key = replay_key(altered_state, altered_questions, assets=altered_assets)
    assert altered_key != original_key
    if changed_asset == "reference":
        assert altered_state == state
        assert altered_questions != questions
    else:
        assert altered_state != state
        assert altered_questions == questions

    path.write_bytes(original_bytes)
    restored_state, restored_questions, restored_assets = helpers.build_request(
        example.fields, root=tmp_path
    )
    assert replay_key(restored_state, restored_questions, assets=restored_assets) == original_key


def test_an_opaque_rename_does_not_change_image_identity(tmp_path):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    example = load_inputs(RECIPE)[0]
    original = helpers.build_request(example.fields, root=tmp_path)
    renamed = tmp_path / "assets" / "queries" / "unrelated-name.png"
    shutil.copyfile(tmp_path / example.fields["image"], renamed)
    changed = helpers.build_request({"image": "assets/queries/unrelated-name.png"}, root=tmp_path)
    assert changed == original


@pytest.mark.parametrize("path", ["../outside.png", "assets/../../outside.png", "assets/q.jpg"])
def test_images_must_stay_in_the_recipes_png_asset_directory(path):
    with pytest.raises(ValueError, match="PNG under this recipe's assets"):
        helpers.asset_path(path)


def test_a_symlink_cannot_escape_the_asset_directory(tmp_path):
    (tmp_path / "assets").mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not used")
    (tmp_path / "assets" / "escape.png").symlink_to(outside)
    with pytest.raises(ValueError, match="PNG under this recipe's assets"):
        helpers.asset_path("assets/escape.png", root=tmp_path)


def test_a_blank_image_gives_the_pixel_baseline_unknown(tmp_path):
    path = tmp_path / "assets" / "queries" / "blank.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (384, 320), (235, 235, 235)).save(path)
    evidence = helpers.baseline_evidence({"image": "assets/queries/blank.png"}, root=tmp_path)
    assert evidence.nearest == "unknown"
    assert evidence.confidence == 0.0
    assert helpers.baseline_prediction(evidence, 0.5).choice == "unknown"


def test_the_generator_reproduces_all_reference_and_query_pixels(tmp_path):
    copy = tmp_path / "69-visual-sku-recognition"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(RECIPE / name, copy / name)
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    expected = {
        path.relative_to(RECIPE): path.read_bytes() for path in (RECIPE / "assets").rglob("*.png")
    }
    generated = {
        path.relative_to(copy): path.read_bytes() for path in (copy / "assets").rglob("*.png")
    }
    assert expected
    assert generated == expected
