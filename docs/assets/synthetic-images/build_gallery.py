"""Regenerates the gallery images shown in docs/synthetic-images.md.

    python docs/assets/synthetic-images/build_gallery.py            # from the repository root
    python docs/assets/synthetic-images/build_gallery.py --overwrite  # accept a changed picture

Every image is drawn by jev_cookbook.synthetic_images with fixed seeds: no photograph, brand or
screenshot is involved, and every name in it is invented. The files are written next to this
script under the byte-stability policy of ``write_png``: a file whose decoded pixels differ is
refused (never silently rewritten), and one whose pixels match but whose bytes differ under a
Pillow other than ``CANONICAL_PILLOW`` keeps its committed bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from jev_cookbook import synthetic_images as si

HERE = Path(__file__).resolve().parent


def montage(images: list[Image.Image], columns: int) -> Image.Image:
    """Equal-sized images in a grid with a 8 pixel gutter (integer pastes only)."""
    width, height = images[0].size
    rows = -(-len(images) // columns)
    sheet = Image.new(
        "RGB", (columns * (width + 8) + 8, rows * (height + 8) + 8), si.PALETTE["mid"]
    )
    for index, image in enumerate(images):
        sheet.paste(
            image, (8 + (index % columns) * (width + 8), 8 + (index // columns) * (height + 8))
        )
    return sheet


def primitives_sheet() -> si.Canvas:
    c = si.Canvas(800, 480, "paper", seed=11)
    c.text(20, 20, "TEXT IN THE BUILT-IN FONT: 0123456789 (UPPER CASE ONLY)", "ink", 2)
    c.text(20, 44, "SCALE 1", "ink", 1)
    c.text(100, 44, "SCALE 3", "ink", 3)
    c.labelled_object(20, 90, 110, 60, "blue", name="rect", label="RECT")
    c.labelled_object(150, 90, 110, 60, "teal", name="ellipse", label="OVAL", shape="ellipse")
    c.labelled_object(280, 90, 110, 60, "amber", name="triangle", shape="triangle", label="UP")
    c.labelled_object(410, 90, 110, 60, "purple", name="right", shape="triangle-right")
    c.stamp(540, 80, 90, 90, "PAID", name="stamp")
    c.signature(650, 90, 130, 60, name="signature")
    for i, kind in enumerate(("resistor", "capacitor", "valve", "ground")):
        c.schematic_symbol(20 + i * 130, 190, 110, 60, kind, name=kind)
    for i in range(4):
        c.wordmark(
            20 + (i % 2) * 380, 290 + (i // 2) * 90, 340, 70, style_seed=i + 1, name=f"logo_{i}"
        )
    return c


def perturbations() -> list[Image.Image]:
    images = []
    for kind in ("original", "blur", "noise", "lighting", "occlusion", "dent"):
        c = si.part_photo(defect="none", seed=1)
        if kind == "blur":
            c.blur(2)
        elif kind == "noise":
            c.noise(14, region="part")
        elif kind == "lighting":
            c.lighting(85, gradient_percent=60)
        elif kind == "occlusion":
            c.occlude("connector", fraction=0.4, side="left", fill="ink")
        elif kind == "dent":
            c.dent("part", depth_percent=60, size_percent=35)
        images.append(c.image)
    return images


def gallery() -> dict[str, Image.Image]:
    states = ("normal", "error", "loading", "crash")
    defects = ("none", "scratch", "dent", "missing_screw")
    frames = si.moving_object_frames([0.0, 0.75, 1.5, 2.25, 3.0, 4.0], appear_at=0.5)
    return {
        "login-states.png": montage([si.login_screen(state=s, seed=3).image for s in states], 2),
        "part-defects.png": montage([si.part_photo(defect=d, seed=1).image for d in defects], 2),
        "deck-hud.png": si.deck_hud(cards=5, enemies=3, energy=2, seed=4).image,
        "frames.png": montage([f.image for f in frames], 3),
        "perturbations.png": montage(perturbations(), 3),
        "primitives.png": primitives_sheet().image,
    }


def main(argv: list[str]) -> int:
    overwrite = "--overwrite" in argv
    code = 0
    for name, image in gallery().items():
        try:
            status = si.write_png(image, HERE / name, overwrite=overwrite)
        except si.RegenerationMismatch as error:
            print(f"MISMATCH {error}")
            code = 1
        else:
            print(f"{status:22} {name}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
