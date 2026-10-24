"""All committed pixels, including preflight-blocked frames, reproduce from the authoring code."""

import importlib.util
from io import BytesIO
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_all_png_bytes_reproduce_even_for_clips_with_no_replay_key():
    spec = importlib.util.spec_from_file_location(
        "recipe86_asset_author", RECIPE / "build_fixtures.py"
    )
    author = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(author)
    expected = set()
    for scene, row in enumerate(author.ROWS):
        for index, kind in enumerate(row[2]):
            name = f"{row[0]}-{index}.png"
            expected.add(name)
            image = author.draw_frame(kind, row[3], scene, index)
            encoded = BytesIO()
            image.save(encoded, format="PNG", optimize=False)
            assert encoded.getvalue() == (RECIPE / "assets" / name).read_bytes()
    assert expected == {p.name for p in (RECIPE / "assets").iterdir()}
