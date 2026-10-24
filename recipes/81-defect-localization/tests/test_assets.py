"""The image corpus is reproduced independently from the authored drawing source."""

import importlib.util
from io import BytesIO
from pathlib import Path

from PIL import Image

RECIPE = Path(__file__).resolve().parent.parent


def test_every_authored_png_rebuilds_identically_with_valid_dimensions():
    spec = importlib.util.spec_from_file_location("recipe81_assets", RECIPE / "build_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for index, row in enumerate(module.ROWS):
        expected = RECIPE / module.fields_for(row)["image"]
        rebuilt = module.draw_scene(row, index)
        stream = BytesIO()
        rebuilt.save(stream, format="PNG")
        assert stream.getvalue() == expected.read_bytes()
        with Image.open(expected) as image:
            assert image.size == (480, 360) and image.mode == "RGB"


def test_authored_defect_marks_fit_their_gold_rectangles():
    from PIL import ImageDraw

    spec = importlib.util.spec_from_file_location(
        "recipe81_gold_marks", RECIPE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for row in module.ROWS:
        if row["scene"] not in ("scratch", "faint", "dent", "broken"):
            continue
        mask = Image.new("RGBA", module.SIZE, (0, 0, 0, 0))
        draw = ImageDraw.Draw(mask)
        renderer = module.scratch if row["scene"] == "faint" else getattr(module, row["scene"])
        renderer(draw, row["bounds"])
        x, y, r, b = mask.getbbox()
        left, top, right, bottom = row["bounds"]
        assert left <= x < r <= right and top <= y < b <= bottom, row["id"]
