#!/usr/bin/env python3
"""Regenerate (or verify) the gallery shown in docs/synthetic-images.md.

    python docs/assets/synthetic-images/make_gallery.py            # write into this folder
    python docs/assets/synthetic-images/make_gallery.py --out DIR  # DIR must be under 'assets'

Every image is produced by ``jev_cookbook.synthetic_images`` with a fixed seed, so the files are
byte-for-byte reproducible. The script never replaces an existing file (it verifies it, and exits
1 with a message if it differs), so running it on a clean checkout is also a freshness check.
``tests/test_synthetic_images.py`` runs it into a temporary folder and compares every byte.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jev_cookbook import synthetic_images as si


def gallery() -> dict[str, si.SyntheticImage]:
    """The gallery images by file stem. Each ``*-boxes`` entry shows the derived gold boxes."""
    shapes = si.shapes_scene(4, count=5)
    ui_error = si.ui_mock(1, error="SAVE FAILED: NAME IS REQUIRED", spinner=True)
    ui_dialog = si.ui_mock(2, dialog="CHANGES WILL BE LOST. CONTINUE?")
    shelf = si.product_shelf(5, count=4, gaps=[2])
    panel_scratch = si.defect_panel(6, defect="scratch")
    moving = si.moving_object_frames([0.0, 0.75, 1.5], seed=7)
    arriving = si.appearing_object_frames([0.0, 1.0, 2.0], seed=7, appear_at=1.0)
    out: dict[str, si.SyntheticImage] = {
        "shapes-scene": shapes,
        "shapes-scene-boxes": si.with_gold_boxes(
            shapes, [n for n in shapes.elements if not n.startswith("label_")]
        ),
        "shapes-scene-hard": si.shapes_scene(4, count=5, perturbations=[("blur", 1), ("dim", 30)]),
        "ui-mock": si.ui_mock(0),
        "ui-mock-error": ui_error,
        "ui-mock-error-boxes": si.with_gold_boxes(
            ui_error, ["error_banner", "spinner", "button_save", "input_name"]
        ),
        "ui-mock-dialog": ui_dialog,
        "wordmark": si.wordmark(8),
        "document-page": si.document_page(9),
        "product-shelf": shelf,
        "product-shelf-boxes": si.with_gold_boxes(shelf, ["product_0", "gap_2", "product_3"]),
        "defect-scratch": panel_scratch,
        "defect-scratch-boxes": si.with_gold_boxes(panel_scratch, ["defect"]),
        "defect-dent": si.defect_panel(6, defect="dent"),
        "defect-missing-part": si.defect_panel(6, defect="missing_part"),
        "deck-builder-hud": si.deck_builder_hud(10),
        "schematic": si.schematic(11),
    }
    for index, frame in enumerate(moving.frames):
        out[f"moving-frame-{index}"] = frame.image
    for index, frame in enumerate(arriving.frames):
        out[f"arriving-frame-{index}"] = frame.image
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args(argv)
    images = gallery()
    try:
        for stem, image in images.items():
            saved = si.write_asset(image, args.out / f"{stem}.png")
            print(f"{saved.status:10} {saved.path.name} ({saved.size_bytes:,} bytes)")
    except si.AssetMismatchError as error:
        print(f"make_gallery: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
