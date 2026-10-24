"""Rebuild image bytes and prove the authored query layouts differ across splits."""

import importlib.util
from pathlib import Path

from jev_cookbook.vision import image_asset

ROOT = Path(__file__).resolve().parent.parent


def generator():
    spec = importlib.util.spec_from_file_location(
        "recipe82_asset_author", ROOT / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_query_layouts_are_disjoint_across_validation_and_test():
    module = generator()
    layouts = [tuple(module.layout(row[4])) for row in module.ROWS]
    assert len(set(layouts)) == len(module.ROWS)


def test_all_image_bytes_reproduce_and_validate(tmp_path):
    module = generator()
    module.HERE = tmp_path
    module.build_assets(module.ROWS)
    actual = sorted((tmp_path / "assets").glob("*.png"))
    assert len(actual) == 29
    for image in actual:
        assert image.read_bytes() == (ROOT / "assets" / image.name).read_bytes()
        image_asset(image)
