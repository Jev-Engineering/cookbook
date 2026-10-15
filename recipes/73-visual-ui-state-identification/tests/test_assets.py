"""Generated image bytes and their visual constraints are part of the fixture contract."""

import importlib.util
from pathlib import Path

from PIL import Image

from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent


def test_all_image_files_are_upright_valid_assets_and_reproduce(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "recipe73_asset_build", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = tmp_path
    module.build_assets(module.ROWS)
    originals = sorted((RECIPE / "assets").glob("*.png"))
    assert len(originals) == 74
    assert {p.name for p in originals} == {p.name for p in (tmp_path / "assets").glob("*.png")}
    for path in originals:
        assert path.read_bytes() == (tmp_path / "assets" / path.name).read_bytes()
        assert image_asset(path)["type"] == "image"
        with Image.open(path) as image:
            assert image.size == (480, 360)
            assert image.getexif().get(274, 1) == 1
