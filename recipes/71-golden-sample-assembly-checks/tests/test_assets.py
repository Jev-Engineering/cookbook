"""The committed image library must be independently reproducible from authored scenes."""

import importlib.util
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_every_committed_image_is_reproducible(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "assembly_asset_author", RECIPE / "build_fixtures.py"
    )
    author = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(author)
    author.HERE = tmp_path
    author.build_assets(author.ROWS)
    actual = {path.name: path.read_bytes() for path in (tmp_path / "assets").glob("*.png")}
    expected = {path.name: path.read_bytes() for path in (RECIPE / "assets").glob("*.png")}
    assert actual == expected
