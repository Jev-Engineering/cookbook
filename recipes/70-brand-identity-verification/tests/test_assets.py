"""Artwork generation is reproducible and uses the authored parameters, not gold labels."""

import importlib.util
from io import BytesIO
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def test_every_committed_png_is_byte_reproducible():
    spec = importlib.util.spec_from_file_location("brand_fixture_art", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pictures = [
        (relative, module.draw_asset(variant))
        for variant, relative in module.helpers.REFERENCES.items()
    ]
    for index, row in enumerate(module.ROWS, 1):
        _, _, theme, scale, offset, alteration, *_ = row
        pictures.append(
            (f"assets/asset-{index:03d}.png", module.draw_asset(theme, scale, offset, alteration))
        )
    assert len(pictures) == 33
    for relative, image in pictures:
        output = BytesIO()
        image.save(output, format="PNG")
        assert output.getvalue() == (RECIPE / relative).read_bytes()
