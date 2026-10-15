# Authored document assets

All 26 PNGs are synthetic drawings produced locally by
[`build_fixtures.py`](../build_fixtures.py) using Pillow. No external images,
customer documents, actual identities, real signatures or approval authority are
represented. Neri Vale and Tavi Fen are fictional names. The signature strokes
come from two sine functions and a short underline; they are meaningless marks.

The source canvas is 600 × 760 pixels with upright pixels and no EXIF rotation.
Individual marks rotate between −14° and +13° while the page remains upright.
The generator uses Pillow's bundled default font, fixed colors and deterministic
geometry. The notebook environment pins Pillow 12.3.0. Filename stems are SHA-256
hashes of source pixel bytes; request references independently hash encoded image
bytes through `image_reference`.

`ROWS` is the readable authoring inventory. It defines drawing cases, placements,
rotations and explicitly synthetic response probabilities. The generator creates
target alpha masks internally and labels the tight envelope of visible target
ink after any occlusion. Masks and drawing coordinates never enter inference
state. Labels list both rectangles for duplicate stamps; the policy must review
such documents instead of choosing one. Blank lines, printed names and an
ARCHIVE EMBLEM decoration have no gold target.

Input fixture fields contain a relative image path and requested mark kind only.
`helpers.request_data` supplies only the actual image and a request description
to the backend. Gold labels live in `fixtures/labels.jsonl`.

The crop visualization uses actual image dimensions, exclusive pixel bounds and
a 10% display margin. Crops may be smaller than API image minimums because they
are displayed locally and never submitted as assets. None is saved over an input.
