# Local images, boxes and ordered frames

Import these helpers from `jev_cookbook.vision`. They run locally with Pillow and do
not import the TypeSafe SDK, contact a service, decode video or perform an action.
The shared backend accepts their raw asset dictionaries through `assets=`.

## Image assets and reproducible references

```python
from pathlib import Path

from jev_cookbook.vision import image_asset, image_reference

photo = image_asset(Path("assets/screenshot.png"))
reference = image_reference(photo)
assets = {reference: photo}
state = {"screenshot": reference}
# result = backend.decide(state, questions, assets=assets)
```

`image_asset(path)` returns exactly `type`, `format` and `data_base64`. It inspects
the file's bytes, so a misleading suffix cannot change the detected format.

Literal paths in your own code can be passed as written. A path that comes out of data,
such as the `fields` of a fixture row, must be loaded with `root=` (the recipe folder):

```python
RECIPE_DIR = Path.cwd()  # notebooks run in their recipe folder
photo = image_asset(row["fields"]["image"], root=RECIPE_DIR)
```

`root=` resolves symbolic links and requires the real file to be inside the real root. An
absolute path, a URL, a `..` that leaves the folder or a symlink that points outside it raises
`AssetPathError` (a `ValueError`) before anything is opened; `assets/../assets/a.png`
stays inside and works. `image_assets(paths, root=...)` and `load_frames(frames, root=...)`
apply the same check to every path, and `resolve_asset_path(path, root=...)` returns the
contained real path for code that opens files itself.

`validate_image_asset(asset)` validates an existing raw descriptor and returns its
decoded, still-encoded PNG/JPEG file bytes. Neither function changes those bytes.

The accepted local files are PNG or JPEG stills, at most 16 MiB, with each
dimension 280–1568 and total area 78,400–2,458,624 pixels (all ranges include both ends;
the same numbers are `vision.IMAGE_LIMITS`). A 384 × 320 or a 280 × 280 fixture fits; a
256 × 256 or a 279 × 400 fixture does not, and neither does 400 × 279: the API rejects an
image with either side under 280 pixels, never resizing it, and rejects it only after the request
is sent, so the loader refuses it first. Scale up or pad a smaller image before saving it.
The loader rejects orientation metadata requiring a
rotation: prepare upright pixels explicitly with Pillow's `ImageOps.exif_transpose`
before saving. Limits follow the experimental [Images documentation](https://docs.typesafe.ai/images).

The reference is `image:sha256:` followed by the full hexadecimal SHA-256 digest
of the file bytes. Colons keep the content hash separate from its descriptive
prefix for fixture hygiene checks. Copies under different filenames share a
reference; changing a pixel or encoded metadata changes it.
This gives replay a deterministic input identity, not an image-similarity score.
Keep image files under the recipe's `assets/` directory. Store their relative paths
and timestamps in the `fields` of `fixtures/inputs.jsonl`, and gold labels in
`fixtures/labels.jsonl`. The strict
[fixture layout](fixtures.md) does not accept image files inside `fixtures/`.
Construct base64 descriptors in memory instead of committing them to fixture JSON.

For caller-defined references, `image_assets` loads a mapping of references to paths:

```python
from jev_cookbook.vision import image_assets

assets = image_assets(
    {
        "<reference-product-front>": "assets/product-front.png",
        "<reference-product-back>": "assets/product-back.jpg",
    }
)
```

Reuse these names in state, instructions or criterion **values**. Every supplied
asset must be referenced. References also substitute inside sentences, so choose
distinctive names. Repetition adds another image to the expanded request even when
one asset is reused. Local file validation does not certify the API's aggregate
request limits. See [image references and limits](https://docs.typesafe.ai/images).

## Rectangle coordinates

All geometry functions accept a plain mapping containing `top`, `bottom`, `left`
and `right`, a raw answer containing a `box` mapping, or an object with a `.box`
attribute. `normalized_box` returns a fresh validated mapping. Nonfinite, missing,
out-of-range, inverted and zero-area edges raise `ValueError`.

```python
from PIL import Image

from jev_cookbook.vision import crop_box, draw_boxes, normalized_to_pixels

box = {"left": 0.25, "top": 0.125, "right": 0.75, "bottom": 0.5}
assert normalized_to_pixels(box, 400, 200) == (100, 25, 300, 100)

with Image.open("assets/screenshot.png") as image:
    overlay = draw_boxes(image, {"target": box})
    crop = crop_box(image, box, expand=0.1)
```

Pixel bounds are `(left, top, right, bottom)` with exclusive right/bottom edges,
matching Pillow crops. Starting edges round down and ending edges round up, so
fractional pixels are enclosed. A full normalized image maps to `(0, 0, width,
height)`. The example's unexpanded crop is 200 × 75 pixels.

When an integer pixel edge is normalized and then scaled back, floating-point
rounding can place it just below or above the integer. The helper restores the
integer only within one representable floating-point increment and only when
dividing that integer by the image dimension gives the supplied normalized edge.
Other fractional edges retain the outward rounding rule.

`expand_box(box, fraction)` adds that fraction of the original box's width or height
to **each** side and clips to the image boundary. `crop_box(..., expand=fraction)`
uses the same operation. Geometry does not resize crops to API limits; pass `min_side=` to refuse a small crop,
or `prepare_image` to scale or pad it, then save and validate it with `image_asset`
before using it as a request asset.
`draw_boxes` returns a separate RGB image with named pink rectangles, paper label
backgrounds and ink text from the cookbook palette.

`box_iou(first, second)` computes intersection divided by union, using continuous
normalized geometry before pixel rounding. It returns zero for disjoint or merely
touching rectangles and one for identical rectangles. A valid but vanishingly small box
(for example 1e-200 wide) has an area that underflows to zero; when both do, the union is
zero and `box_iou` (and `localization_metrics`) raise `ValueError` rather than invent a score.
Because the union is at least as large as each area, this happens only when both boxes
underflow, so in `localization_metrics` it means a degenerate gold label: fix the fixture.

## Presence, confidence and evaluation

A Box returns one rectangle even when its target is absent. Determine presence
with a companion question before treating a rectangle as a detection.
[Box documentation](https://docs.typesafe.ai/primitives/box)

`box_confidence(answer)` returns the supplied confidence, including a reported `0.0`
or `1.0`, or `None` if missing/null (absence is never turned into a number);
invalid confidence values raise. A missing value cannot pass a confidence gate:

```python
from jev_cookbook.vision import box_confidence, normalized_box


def localization_outcome(answer, presence, threshold):
    """presence is True/False only after the recipe's Noul policy; None means review."""
    if presence is None:
        return "review", None
    if presence is False:
        return "absent", None
    confidence = box_confidence(answer)
    if confidence is None or confidence < threshold:
        return "review", None
    return "located", normalized_box(answer)
```

Choose the presence and confidence thresholds on validation examples and freeze
them before evaluating the test split. Keep reviews in the recipe's review queue
and account for them with `evaluation.evaluate_outcomes`; a review is not a claim
that the target is absent.

`localization_metrics(gold, predicted)` accepts equally sized, nonempty sequences.
Here `None` explicitly labels absence. Apply it to resolved outcomes and report
review counts separately:

```python
from jev_cookbook.vision import localization_metrics

metrics = localization_metrics(
    gold=[box, box, None, None],
    predicted=[box, None, box, None],
)
assert (metrics.present, metrics.absent) == (2, 2)
assert (metrics.missed, metrics.false_positives) == (1, 1)
assert metrics.mean_iou == 0.5
```

The missed present target contributes zero IoU. Absent gold contributes no IoU;
a predicted rectangle on an absent target instead increments `false_positives`.
If every target is absent, `mean_iou` is NaN. Malformed predictions raise even when
their corresponding gold target is absent.

## Tiles and coordinate transforms

```python
from jev_cookbook.vision import generate_tiles, tile_to_image

with Image.open("assets/screenshot.png") as image:
    tiles = generate_tiles(image, tile_size=(320, 280), overlap=32)
    selected = tiles[0]
    whole_box = tile_to_image(box, selected.bounds, *image.size)
```

`generate_tiles` returns `ImageTile` objects with copied `.image` pixels and exact
`.bounds` in the original image, in row-major order. `overlap` is an integer number
of pixels smaller than both tile dimensions. The last row/column anchors to the
bottom/right edge, which can increase overlap; there are no uncovered gaps or
partial sliver tiles. A source smaller than a requested tile keeps its full extent, so a
tile (or a source) under 280 pixels on a side must be scaled up or padded before
`image_asset` accepts it. The tile count is computed before any tile is cropped and
`max_tiles` (default 256) bounds it: the count grows with the inverse square of the
stride (tile size minus overlap), so an overlap near the tile size makes it explode, and a
configuration above the cap raises `ValueError`. Each tile is usually one API call, so
`max_tiles` also caps cost, not only memory. Pass a larger `max_tiles=` only deliberately.

`tile_to_image` applies an affine transform using the actual pixel bounds, so a
rectangle found inside a tile maps back to the whole image. It also handles an
entire tile resized before inference, provided coordinates still describe that
tile's full extent. Padding or further cropping has its own transform, below.

Both `generate_tiles(..., min_side=)` and `crop_box(..., min_side=)` accept a minimum
and raise `ValueError` for a tile or crop with a side below it, before anything is
copied. Pass `min_side=IMAGE_LIMITS["min_side"]` (280) for tiles that will be sent to
the API; the default `None` keeps the geometry-only behavior. Alternatively leave the
check off and pad or scale each tile with `prepare_image`. A tile size of `(320, 280)`
is valid; `(320, 279)` is refused.

### Preparing an image for the API

```python
from jev_cookbook.vision import prepare_image

prepared, transform = prepare_image(crop)  # both sides 280-1568
box_on_crop = transform.to_original(box_on_prepared)  # None if the box is only padding
```

`prepare_image(image, *, min_side=280, max_side=1568, pad_color=(255, 255, 255),
upscale=True)` returns the prepared image and an `ImageTransform`. The rules are fixed:
scale down uniformly if the longest side is over `max_side`; otherwise scale up
uniformly until the shortest side reaches `min_side`, but never past the longest side
reaching `max_side`; then pad any side still under `min_side`, centered, with
`pad_color`. So 100 × 100 becomes 280 × 280 by scaling, while 100 × 1568 is padded to
280 × 1568 because scaling up would exceed 1568, and 5000 × 100 is scaled to
1568 × 31 and padded to 1568 × 280 (the content is a thin strip: such an image is valid
but may not be useful). `upscale=False` pads a small image rather than enlarging it. An
image already inside the limits comes back as an identical copy with an identity
transform. Output is RGB, or RGBA when the input has transparency; the input is never
changed, and Lanczos resampling is deterministic for a given Pillow version, not across
versions. Apply `ImageOps.exif_transpose` first if orientation metadata matters.

`transform.to_original(box)` maps a normalized box on the prepared image back to the
original; `to_prepared(box)` maps the other way (to draw or label a gold box on the
prepared image). A box overlapping padding is clipped to the original image; a box that
lies wholly in the padding returns `None`, which is an answer to handle, not an
error. `point_to_original` and `point_to_prepared` do the same for a point
`{"x": ..., "y": ...}` and return `None` for a point in padding. The fields
`original_size`, `prepared_size`, `content_size` and `offset` record exactly what was
produced.

### From the full image into a tile, and across levels

`image_to_tile(box, tile_bounds, width, height)` is the inverse of `tile_to_image`: it
returns the box as seen inside one tile, clipped to the tile, or `None` when the box does
not overlap the tile with positive area (touching only along an edge is not overlap).
Run it over every tile to label a gold box per tile when evaluating tile selection.

For progressive search, describe each level with a `TileStep(bounds, parent_size)` (the
crop cut from an image of `parent_size`) or the `ImageTransform` from `prepare_image`,
outermost first, and map through the whole chain:

```python
from jev_cookbook.vision import TileStep, box_from_original, box_to_original

steps = [TileStep(tile.bounds, full.size), TileStep(crop_bounds, tile.image.size), transform]
whole = box_to_original(box_on_prepared, steps)  # deepest image -> full image
local = box_from_original(gold_box, steps)  # full image -> deepest image
```

`box_to_original` and `box_from_original` (and the point versions `point_to_original`
and `point_from_original`) compute with exact fractions and round to a float once, so
mapping a pixel-aligned box through any number of levels returns exactly the float
for the pixel position divided by the image size (`416 / 1568`, not a neighbor of it);
no error accumulates per level. Each step's `parent_size` is the size of the image *that
level was cut from*: the full image for the first, the previous level's image for the
next. A level resized uniformly needs no step, because normalized coordinates survive it;
only if you cut the next level in the resized pixels do you pass the resized size as that
step's `parent_size`. Round trips (forward then inverse) agree to well within `1e-12`
in normalized units, the tolerance the tests use. Inverses clip: a box partly outside a
level comes back as only its visible part, and a box fully outside as `None`.

## Worked example: tile, choose, crop, prepare, Box, map back

The example runs offline on a synthetic image. The lines that stand in for a model
answer compute the box a perfect answer would return; a recipe uses `answer.box` there.

```python
from PIL import Image, ImageDraw

from jev_cookbook.vision import (
    IMAGE_LIMITS,
    TileStep,
    box_from_original,
    box_to_original,
    expand_box,
    generate_tiles,
    normalized_to_pixels,
    prepare_image,
)

full = Image.new("RGB", (1400, 900), "white")
ImageDraw.Draw(full).rectangle((1010, 430, 1049, 469), fill="red")  # a 40 x 40 target
target = {"left": 1010 / 1400, "right": 1050 / 1400, "top": 430 / 900, "bottom": 470 / 900}

# 1. Tile. min_side refuses any tile the API would reject (here every tile is 640 x 480).
tiles = generate_tiles(full, tile_size=(640, 480), overlap=64, min_side=IMAGE_LIMITS["min_side"])

# 2. Choose. A Choice question over the tiles returns one index (stand-in: tiles[5]).
chosen = tiles[5]
tile_step = TileStep(chosen.bounds, full.size)

# 3. Box on the tile (stand-in for answer.box), then 4. crop around it, with margin.
on_tile = box_from_original(target, tile_step)
crop_bounds = normalized_to_pixels(expand_box(on_tile, 0.5), *chosen.image.size)
crop = chosen.image.crop(crop_bounds)
crop_step = TileStep(crop_bounds, chosen.image.size)

# 5. Prepare. The 80 x 80 crop is under 280 px, so it is scaled up to 280 x 280.
prepared, transform = prepare_image(crop)
steps = [tile_step, crop_step, transform]

# 6. Box on the prepared image (stand-in for answer.box), then 7. map back to the full image.
on_prepared = box_from_original(target, steps)
mapped = box_to_original(on_prepared, steps)

assert prepared.size == (280, 280)
assert all(abs(mapped[edge] - target[edge]) < 1e-12 for edge in target)
```

Save the prepared image and load it with `image_asset` to send it; the loader accepts it
because both sides are in range. A recipe keeps the `steps` list with the case so the
same rectangle can be re-mapped, and uses `box_from_original(gold, steps)` to label the
gold box at any level.

## Explicitly timestamped still frames

```python
from jev_cookbook.vision import load_frames

frames, assets = load_frames(
    [
        (0.0, "assets/door-closed.png"),
        (0.75, "assets/door-moving.png"),
        (1.5, "assets/door-open.png"),
    ]
)
state = {"frames": frames}
```

Each row contains `timestamp_seconds` and an `image` reference. Timestamps must be
finite, nonnegative and strictly increasing; the helper rejects duplicate or
reversed times. Identical image bytes share one asset without removing a frame's
timestamp. Explicit times avoid assuming that filenames or frame indexes encode
real elapsed time. The helper reads extracted PNG/JPEG files; it makes no native
video claim. If video is the source, decode and sample it separately and record the
actual selected timestamps.

## Honest accounting

`run_record(result, mode=...)` creates one row with mode, returned model,
input/output tokens, latency in seconds and cost in USD:

```python
from jev_cookbook.vision import run_record

# result is a DecisionResult from the recipe's existing replay or live backend.
# row = run_record(result, mode="synthetic")
# row = run_record(result, mode="recorded", measured_latency_seconds=captured_seconds)
```

Synthetic and scripted rows contain `None` for model, tokens, latency and cost,
even when the fixtures contain illustrative token counts. Supplying measured
latency/cost in those modes raises. Recorded/live modes require a recorded result
and retain the API's usage fields; unreported usage remains `None`.

Provide `measured_latency_seconds` only for actual inference timing, and
`measured_cost_usd` only for an actual measured charge. Replay execution time is
not inference latency. Token-derived price calculations are estimates and do not
belong in the measured-cost field. The helper neither times a request nor infers a
price. For a replay of recorded responses, load any actual measurements from the
capture record; leave missing ones null.

Continue to use `run_header`, the recipe's measured-results disclosure and the
[offline/live contract](offline-and-live.md). Accounting rows do not make a
synthetic pipeline check a model benchmark, or turn validation selection into a
held-out result.
