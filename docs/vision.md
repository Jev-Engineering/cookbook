# Local images, boxes and ordered frames

Import these helpers from `jev_cookbook.vision`. They run locally with Pillow and do
not import the TypeSafe SDK, contact a service, decode video or perform an action.
The shared backend accepts their raw asset dictionaries through `assets=`.

The images themselves are drawn, not photographed: [`jev_cookbook.synthetic_images`](synthetic-images.md)
generates deterministic synthetic screenshots, defects, HUDs, logos and frame sequences, returns the
exact box of everything it draws (so gold labels are derived, not typed), and saves them under the
byte-stability rule that keeps replay keys valid.

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

The accepted local files are PNG or JPEG stills, at most 16 MiB (a committed fixture is held to
the stricter 1 MiB, no-metadata asset rule in [`docs/fixtures.md`](fixtures.md)), with each
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
request limits; [copies and the 32 MiB caps](#image-copies-and-the-32-mib-caps) below counts
what can be counted offline. See [image references and limits](https://docs.typesafe.ai/images).

## Image copies and the 32 MiB caps

Two numbers describe a request's images, and they differ whenever a reference repeats. A
**distinct image** is an asset uploaded once. A **copy** is a place its reference is replaced by
the image: "every place its reference appears adds another copy of the image to what the model
reads, and every copy counts toward the expanded request limit." The page's Limits table sets
three separate 32 MiB caps: one on the request body (the JSON, base64 text and multipart framing;
HTTP headers do not count), one on all distinct images in the request (measured after the API
processes them), and one on the expanded request (the text, questions and structure plus every
copy). The last two can be counted in part from the request alone, as below; the request-body cap
is not modelled.

`image_request_profile(state, questions, assets)` counts both from the request alone. It reads no
file, decodes nothing and keeps no bytes: sizes come from the length of each `data_base64`.

```python
from jev_cookbook.vision import image_request_profile

profile = image_request_profile(state, questions, assets)
profile.distinct_assets, profile.distinct_bytes  # the uploads
profile.copies, profile.expanded_bytes  # every replacement
profile.state_copies, dict(profile.per_question)  # where the copies are
```

The rules follow the upstream page. A string that is exactly a reference is one copy; in longer
strings references are replaced left to right and matches never overlap, so a reference used twice
in one string is two copies. Where two references start at the same character the longer wins
(the page does not say; this keeps a reference from being shadowed by its own prefix). Copies are
counted in state string values, in `Noul`, `Choice` and `Score` criteria values, and in each
question's `instructions`. An image in the instructions of three questions is three copies. Object
keys, question names and `Choice` option names are text. `per_question` holds the copies in each
question's own instructions and criteria, so `copies == state_copies + sum(per_question.values())`.

**Put a shared image in the `state` once and refer to it by path from each question's
instructions**, as upstream recommends. A 2 MiB chart named in the instructions of twenty questions
is twenty copies, 40 MiB, over the expanded cap; in the state it is one copy, 2 MiB, and the
instructions say "the `chart` image" in words. Repeating a reference in a criterion or in several
state fields is a deliberate choice that costs a copy each time.

`LiveBackend.decide` calls `preflight_image_request(profile)` after validating the request and
before importing the SDK or spending anything. If the distinct bytes or the expanded bytes exceed
32 MiB it raises `ImageRequestTooLarge` (a `ValueError`) that names the counts and the cure;
`requests_made` is unchanged. The check uses no network and covers only the distinct-image and
expanded caps, and only in part. It is necessary, not sufficient, and a request that passes can
still be refused:

- the sizes are encoded file bytes, and the API measures after processing;
- the expanded cap also counts text and structure, which the preflight does not add;
- the request-body cap is not modelled at all. The page says base64 makes each image about a
  third larger than the file, so on a base64 JSON request the body cap can bind before the image
  caps do. `LiveBackend` hands the bytes to the SDK as `Image` values, which the SDK uploads as
  multipart (see [live](live.md)); that is how this cookbook sends them, not something the
  preflight checks;
- a reference that is a complete prefix of a longer one can be shadowed. The page does not say how
  references that start at the same character resolve; this helper takes the longest, so an asset
  whose reference occurs only inside longer matches counts no copy and no distinct bytes, although
  it is still supplied. The page says every asset must be referenced and answers `400` otherwise,
  and the preflight does not refuse it.

Image tokens are not separable. They appear only inside the `usage.input_tokens` of a recorded
response, there is no estimator, and the cookbook does not guess one. What it records is the
count: `AuditedBackend` entries carry `images` (copies) and `distinct_images` per call (see
[backends](backends.md#actual-calls-and-distinct-requests)), and the `live.record` sidecar line
and `LiveBackend.ledger()` carry the same two counts beside `input_tokens`, so a recorded cost can
be read against how many images produced it. A text-only request carries neither field.

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
uses the same operation. Geometry does not resize crops to API limits: a crop under 280 pixels
on a side is refused by `crop_box(..., min_side=280)` or padded by `prepare_image` (see
[Preparing an image for the API](#preparing-an-image-for-the-api)), and a prepared crop is saved
and validated with `image_asset` before it is used as a request asset.
`draw_boxes` returns a separate RGB image with named pink rectangles, paper label
backgrounds and ink text from the cookbook palette.

`box_iou(first, second)` computes intersection divided by union, using continuous
normalized geometry before pixel rounding. It returns zero for disjoint or merely
touching rectangles and one for identical rectangles. A valid but vanishingly small box
(for example 1e-200 wide) has an area that underflows to zero; when both do, the union is
zero and `box_iou` (and `localization_metrics`) raise `ValueError` rather than invent a score.
Because the union is at least as large as each area, this happens only when both boxes
underflow, so against a gold box it means a degenerate gold label: `gold_box` rejects
such a label up front, so fix the fixture.

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
and account for them in `localization_report` (and, for the overall review rate,
`evaluation.evaluate_outcomes`); a review is not a claim that the target is absent.

### Gold labels

A Box recipe labels every example with a gold Box label (specified in
[Box labels](fixtures.md#box-labels)): `{"present": true, "box": {"top": ..., "bottom": ...,
"left": ..., "right": ...}}` when the target is in the image, `{"present": false}` when it is
not. `gold_box(label)` decodes one: it returns the validated normalized rectangle for a
present target and `None` for an absent one, and raises `ValueError` for anything malformed,
including a `box` on an absent label, a non-boolean `present`, edges outside [0, 1], zero
width or height, and a box so small its area underflows to zero (which `box_iou` cannot score).
The fixture validator applies the same check to every label file that uses the format.

### The localization report

`localization_report(gold, outcomes, *, iou_threshold=0.5)` is the entry every Box recipe
reports through. `gold` is one gold Box label per example; `outcomes` is one pair per example
from the localization policy above: `("located", box)`, `("absent", None)` or
`("review", None)`. Nothing is filtered, so no example can leave a denominator: each lands in
exactly one cell of a present table or an absent table.

| Gold | `located` (a box was returned) | `absent` | `review` |
| --- | --- | --- | --- |
| present | IoU is scored | missed (`present_missed`) | `present_review` |
| absent | false positive (`false_positives`) | correct absent (`correct_absents`) | `absent_review` |

A returned rectangle never proves a target exists, so a `located` box on absent gold is a
false positive, never an IoU. A review is never an absent prediction. The report states:

- `n_total`, `n_present`, `n_absent`;
- `mean_iou_located`: mean IoU over located present targets, denominator `present_located`;
- `mean_iou_present`: mean IoU over all present targets with missed and reviewed targets
  counted as 0, denominator `n_present`;
- `hit_rate`: located present targets with IoU at or above `iou_threshold` (default 0.5),
  over `n_present`;
- `false_positives` and `false_positive_rate` (over `n_absent`), `correct_absents` and
  `correct_absent_rate` (over `n_absent`), `absent_review`.

A mean or rate whose denominator is zero is NaN (and prints `n/a`), never 0. `str(report)`
names every denominator, and `report.denominators` returns them by metric name.

```python
from jev_cookbook.vision import localization_report

G = {"top": 0.0, "bottom": 0.5, "left": 0.0, "right": 0.5}
HALF = {"top": 0.0, "bottom": 0.25, "left": 0.0, "right": 0.5}  # IoU 0.5 with G
present, absent = {"present": True, "box": G}, {"present": False}

report = localization_report(
    gold=[present, present, present, present, absent, absent, absent],
    outcomes=[
        ("located", G),  # IoU 1.0
        ("located", HALF),  # IoU 0.5
        ("review", None),  # a present target in review keeps its place in the denominator
        ("absent", None),  # a present target called absent: missed
        ("located", G),  # a box returned for an absent target: a false positive
        ("absent", None),  # correct absent
        ("review", None),
    ],
)
assert (report.n_total, report.n_present, report.n_absent) == (7, 4, 3)
assert report.present_table == {"located": 2, "absent": 1, "review": 1}
assert report.absent_table == {"located": 1, "absent": 1, "review": 1}
assert report.mean_iou_located == 0.75  # (1.0 + 0.5) / 2 located present targets
assert report.mean_iou_present == 0.375  # (1.0 + 0.5) / 4 present targets
assert report.hit_rate == 0.5  # 2 of 4 present targets at IoU >= 0.5
print(report)
```

```text
Localization report: 7 examples (4 present + 3 absent), each counted once
Present targets (n = 4): box returned 2, said absent (missed) 1, sent to review 1
  mean IoU over located present targets: 0.7500 (denominator 2: located present targets)
  mean IoU over all present targets, missed and review counted as 0: 0.3750 (denominator 4: all present targets)
  hit rate at IoU >= 0.5: 2/4 = 0.5000 (denominator 4: all present targets)
Absent targets (n = 3): box returned (false positive) 1, correct absent 1, sent to review 1
  false positive rate: 1/3 = 0.3333 (denominator 3: all absent targets)
  correct absent rate: 1/3 = 0.3333 (denominator 3: all absent targets)
```

`tests/test_vision.py` runs this example and compares the printed text. Malformed gold,
an unknown outcome kind, a `located` outcome without a valid box, a box attached to `absent`
or `review`, empty or unequal-length inputs and an `iou_threshold` outside (0, 1] raise
`ValueError` naming the example index. Choose `iou_threshold` and the presence policy on
validation examples and freeze them before scoring the test split.

### Tiled and hierarchical recipes

When a recipe tiles the image (a Choice picks the tile, then a Box locates the target inside
it), one example is one image, not one tile. A target can be present in the full image and
absent from most tiles, so counting tiles would make `n_total` a tile count and
`correct_absent_rate` mostly a measure of empty tiles.

- The headline report is per image. `gold` is the full-image gold Box label (stored once,
  see [Box labels](fixtures.md#box-labels)) and each outcome is the final rectangle after
  `tile_to_image`, or, when the recipe also cropped or padded inside the tile, after
  `ImageTransform.to_original` on the chain that `.then` built from every step (see
  [Mapping boxes between an image and what you sent](#mapping-boxes-between-an-image-and-what-you-sent);
  `image_to_tile` goes the other way and labels the gold box per tile). If `to_original`
  returns `None` (the answer lies outside the content, for example only in padding), report
  `("review", None)`, never `("absent", None)`: a rectangle in padding is not evidence that
  the target is missing.
- Map the stage-1 result to an outcome before reporting: a stage-1 "no match" on an image
  whose gold is present is `("absent", None)` (a miss); an uncertain tile choice, or an
  uncertain Box in the chosen tile, is `("review", None)`.
- A per-tile report is a stage diagnostic. Label it as counting tiles, never quote it as the
  recipe's result, and state its rule for a target a tile edge cuts (the minimum visible
  fraction of the box that makes the target "present" in that tile), because that rule
  changes the per-tile denominators.

### The older `localization_metrics`

`localization_metrics(gold, predicted)` is kept for compatibility. It takes `None` for an
absent target, so the caller has to drop reviewed examples before calling it, and a present
target sent to review then silently leaves the `mean_iou` denominator. It also reports no
correct-absent count and no hit rate. Use `localization_report` in new work.

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
`image_asset` accepts it: pass `min_side=280` to refuse such tiles up front (see
[Minimum size for tiles and crops](#minimum-size-for-tiles-and-crops)). The tile count is computed before any tile is cropped and
`max_tiles` (default 256) bounds it: the count grows with the inverse square of the
stride (tile size minus overlap), so an overlap near the tile size makes it explode, and a
configuration above the cap raises `ValueError`. Each tile is usually one API call, so
`max_tiles` also caps cost, not only memory. Pass a larger `max_tiles=` only deliberately.

`tile_to_image` applies an affine transform using the actual pixel bounds, so a
rectangle found inside a tile maps back to the whole image. It also handles an
entire tile resized before inference, provided coordinates still describe that
tile's full extent. It knows nothing about padding or a second crop: for those, and for the
opposite direction, use the `ImageTransform` helpers below.

### Minimum size for tiles and crops

The API rejects an image with a side under 280 pixels, and rejects it only after the request is
sent. `generate_tiles` and `crop_box` take `min_side=` to refuse such a tile or crop first:

```python
from PIL import Image

from jev_cookbook.vision import IMAGE_LIMITS, generate_tiles

image = Image.new("RGB", (1000, 800))
tiles = generate_tiles(image, tile_size=(320, 280), min_side=IMAGE_LIMITS["min_side"])  # fine
# generate_tiles(image, tile_size=(320, 200), min_side=280)  -> ValueError, before any crop
# crop_box(image, small_box, min_side=280)                   -> ValueError for a crop under 280
```

`ValueError` names the size and points at `prepare_image`. The check is on the finished tile or
crop (after `expand`), a side of exactly 280 passes, and it runs before anything is cropped.
`min_side` defaults to `None`, which checks nothing, because the geometry functions are also used
on tiny synthetic images in tests; **a recipe that sends tiles or crops to Jev passes
`min_side=IMAGE_LIMITS["min_side"]` or runs each through `prepare_image`.** Refusing is the right
choice for tiles (a tile size under 280 is a configuration mistake). A crop around a found region
is often legitimately small, so pad or scale it instead.

### Preparing an image for the API

`prepare_image(image, *, min_side=280, max_side=1568, pad_color=(128, 128, 128), upscale=False)`
returns `(prepared, transform)`: a new RGB image with both sides between `min_side` and
`max_side` (so its area is inside 78,400 to 2,458,624 as well), and the transform that maps
boxes between `prepared` and the image you passed in. The [Images
documentation](https://docs.typesafe.ai/images) asks for this: scale the image so its longest
side is at most 1568, and scale up or pad an image smaller than the minimum. In order:

1. A longest side over `max_side` is scaled down to `max_side`, keeping the aspect ratio.
2. With `upscale=True` only, an image with a side under `min_side` that was not scaled down is
   scaled up (aspect ratio kept) until its shorter side is `min_side`, but not past `max_side`
   on the long side. The default never scales up, so no pixel is invented and the padded image
   holds the original pixels unchanged.
3. A side still under `min_side` is padded with `pad_color` (a gray level 0 to 255 or an `(r, g,
   b)` tuple), the content centered, an odd leftover pixel going to the right or bottom.

Scaled sizes are the exact ratio rounded half up (1000 × 1568 / 1601 = 979.39, so 979),
resampling is Lanczos, and nothing is cropped:

| Image | `prepare_image` result | Content inside it |
| --- | --- | --- |
| 400 × 300 | 400 × 300, a pixel-identical copy | the whole image |
| 300 × 200 | 300 × 280 | rows 40 to 240 |
| 200 × 100 | 280 × 280 | columns 40 to 240, rows 90 to 190 |
| 201 × 100 | 280 × 280 | columns 39 to 240 (79 pad pixels: 39 left, 40 right) |
| 1601 × 1000 | 1568 × 979 | the whole image, scaled |
| 4000 × 100 | 1568 × 280 | rows 120 to 159 (scaled to 1568 × 39, then padded) |
| 200 × 100, `upscale=True` | 560 × 280 | the whole image, scaled ×2.8 |

The mid-gray default is a neutral choice that has not been measured against Jev; pass `pad_color`
to use another, and keep it the same across a recipe's images. An image with transparency raises
`ValueError`: flatten it onto an explicit background first, since the colors under a transparent
pixel are arbitrary. The input image is not modified, and the result carries none of its metadata
(ICC profile, EXIF, text) on any path, so saving it as a PNG writes none of the chunks the
[image-file contract](fixtures.md) forbids. Because that drops the EXIF tag, an image whose EXIF
orientation is not 1 raises `ValueError`, as `image_asset` does: rotate the pixels first with
`ImageOps.exif_transpose`.

`prepare_image` does not certify the result for the API: save the prepared image and load it with
`image_asset`, which re-checks format, size and the file limit. `image_asset` does not check PNG
chunks; the metadata rules are `tools/check_recipe_assets.py`'s (run by CI on committed assets).

Choose `upscale` once per recipe. The default pads, which keeps every original pixel and clears
the 280 pixel minimum. A small crop is then almost all padding, and padding adds no detail: a
10 × 10 crop comes back 280 × 280 with the content covering 0.13% of the image, the target no
larger than it was in the source. `upscale=True` instead scales the crop up so the target fills
more of the image sent. Which of the two works better for a recipe has not been measured against
Jev; treat it as a design decision to settle on validation examples, then keep it, like
`pad_color`, the same across the recipe's images.

### Mapping boxes between an image and what you sent

A box that Jev returns is relative to the image it was shown. `ImageTransform` carries it back
(and carries a gold label forward). Every step that changes the image makes one, and they chain:

| Step | Transform |
| --- | --- |
| a tile from `generate_tiles` | `ImageTransform.crop(tile.bounds, *image.size)` |
| a crop around a region | `ImageTransform.crop(crop_bounds(box, *image.size, expand=...), *image.size)` |
| `prepare_image(image)` | the second value it returns |
| several steps, outermost first | `first.then(second).then(third)` |

```python
transform.to_original(box)  # a box on the derived image -> the original, or None
transform.to_derived(box)  # a box on the original -> the derived image, or None
transform.visible_fraction(box)  # share of an original box's area the derived image shows
```

- The *original* is the image you started from and the *derived* image is the one you sent.
  `chain = tile_step.then(crop_step).then(prepared_step)` maps between the full image and the
  prepared crop in one call, for any number of levels. `then` raises `ValueError` if the sizes
  do not line up (the second step must start from the first step's result) or if the second
  step only shows padding.
- Results are clipped. A derived box that reaches into padding comes back clipped to the content;
  one wholly in padding returns `None`. A full-image box a tile edge cuts is clipped to the tile,
  and one with no area inside it, including one that only touches the edge, returns `None`.
  A box found partly in padding is worth a look, not a result to trust blindly. In a Box recipe,
  a `None` from `to_original` is reported as `("review", None)`, not `("absent", None)` (see
  [Tiled and hierarchical recipes](#tiled-and-hierarchical-recipes)).
- `image_to_tile(box, tile_bounds, width, height)` is `tile_to_image`'s inverse (a single crop
  step): the tile-local, clipped box, or `None` when the box misses the tile. Use it to label the
  gold box per tile when evaluating tile selection, as a stage diagnostic (see "Tiled and
  hierarchical recipes" above); the per-image gold stays the full-image label.
  `visible_fraction` applies the minimum-visible-fraction rule that a per-tile report must state.
- Mapping is exact. Edges are held as exact fractions and rounded to a float once at the end,
  so a box found two or three levels down is the true full-image position, not a sum of one
  rounding error per level. A normalized edge that is the float nearest `k / width` is read as
  pixel `k`, so a box built from pixel coordinates that ends exactly on a tile edge returns
  `None` for the next tile rather than a sliver about 1e-17 wide.
- A mapped box too small to be a float rectangle raises `ValueError`, never a collapsed box.

### Worked example: tile, choose, crop, prepare, Box, map back

The example generates its own synthetic page, so it runs offline. The two model answers (which
tile, and where the target is) are written in the code where a recipe would call Jev; the
target's location is then read from pixels so that the arithmetic can be checked.

```python
from PIL import Image

from jev_cookbook.vision import (
    IMAGE_LIMITS,
    ImageTransform,
    box_iou,
    crop_bounds,
    crop_box,
    generate_tiles,
    image_to_tile,
    normalized_to_pixels,
    prepare_image,
)

MIN = IMAGE_LIMITS["min_side"]

# A synthetic 1200 x 900 page with a 120 x 60 blue target at pixels x 840-960, y 330-390.
page = Image.new("RGB", (1200, 900), "white")
page.paste((0, 0, 255), (840, 330, 960, 390))
gold = {"left": 840 / 1200, "top": 330 / 900, "right": 960 / 1200, "bottom": 390 / 900}

# 1. Tile: four 600 x 450 tiles, none under the 280 pixel minimum.
tiles = generate_tiles(page, tile_size=(600, 450), min_side=MIN)
print(len(tiles), "tiles of", tiles[0].image.size)

# 2. Choose: a Choice question would pick the tile. Gold labels for tile selection come from
#    the inverse mapping: which tiles hold the target?
holding = [i for i, t in enumerate(tiles) if image_to_tile(gold, t.bounds, *page.size)]
print("tiles holding the target:", holding)
chosen = tiles[1]  # the recorded Choice answer for this example

# 3. Crop: a first Box question over the tile returned this region (written in here). It is
#    200 x 120 pixels, so crop_box with min_side refuses it ...
region = {"left": 200 / 600, "top": 300 / 450, "right": 400 / 600, "bottom": 420 / 450}
try:
    crop_box(chosen.image, region, min_side=MIN)
except ValueError as error:
    print(error)

# ... and prepare_image pads the crop to 280 x 280.
bounds = crop_bounds(region, *chosen.image.size)
crop = chosen.image.crop(bounds)
prepared, step_3 = prepare_image(crop)
print(bounds, crop.size, prepared.size)

# 4. Box: ask the Box question on `prepared`. Here the answer is read from the pixels instead.
mask = prepared.getchannel("R").point(lambda value: 255 if value < 50 else 0)
left, top, right, bottom = mask.getbbox()
answer = {"left": left / 280, "top": top / 280, "right": right / 280, "bottom": bottom / 280}

# 5. Map back through every level at once: tile, then crop, then prepare.
chain = (
    ImageTransform.crop(chosen.bounds, *page.size)
    .then(ImageTransform.crop(bounds, *chosen.image.size))
    .then(step_3)
)
found = chain.to_original(answer)
print(normalized_to_pixels(found, *page.size), found == gold)
assert box_iou(found, gold) == 1.0
```

```text
4 tiles of (600, 450)
tiles holding the target: [1]
crop would be 200 x 120 pixels, under min_side=280 on a side; the API rejects such an image. Pad or scale it up with prepare_image, or use a larger region
(200, 300, 400, 420) (200, 120) (280, 280)
(840, 330, 960, 390) True
```

`tests/test_vision.py` runs this example and compares the printed text. The box in the padded
crop is pixels 80-200 by 110-170; the three steps add the padding offset (40, 80), the crop
origin (200, 300) and the tile origin (600, 0), and divide by the page size, which is what
`found == gold` checks to the last bit.

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

### Sampling, intervals and windows

`jev_cookbook.frames` (pure Python, no Pillow, no model call) holds the deterministic
arithmetic on a state-frame list. It is a separate module, not part of `vision`, and
`jev_cookbook.frames` is the one import path. No video is decoded anywhere in the cookbook:
frames are stills that were already extracted, and the timestamps you pass are the truth,
**elapsed seconds since the start of the sequence** (never Unix time; the 1e-9 s slack below
is meaningless at epoch scale). Python owns order, sampling and every time calculation; the
model only sees the rows you choose to send. The block below continues from the `frames`
loaded above (timestamps 0.0, 0.75 and 1.5 s):

```python
from jev_cookbook.frames import (
    earliest_transition,
    frame_at,
    frame_intervals,
    frame_timestamps,
    frame_windows,
    relative_frames,
    sample_frames,
    select_frames,
    transition_time,
    window_timestamps,
)

times = frame_timestamps(frames)  # validated: finite, nonnegative, strictly increasing
chosen = sample_frames(times, every_seconds=0.5)  # [0, 1, 2]: ascending, no repeats
sampled = select_frames(frames, chosen)  # copies of those rows, each with frame_index
gaps = frame_intervals(sampled)  # [0.75, 0.75]: seconds between rows, n - 1 values
labelled = relative_frames(sampled)  # seconds_ago = last time - time: 1.5, 0.75, 0.0
window = window_timestamps(sampled, 1, 2)  # start 0.75, end 1.5, duration 0.75 seconds
```

`sample_frames(timestamps, *, every_seconds=None, count=None, start=None, end=None)`:

- `start` / `end` bound an inclusive window (default: first and last timestamp). A window with
  no frame raises rather than returning nothing.
- `every_seconds`: targets are `window_start + k * every_seconds` (multiplied, never
  accumulated) up to `end`. Each target takes the **nearest** frame in the window. Frames whose
  distance from the target is within the 1e-9 s slack of the smallest distance are tied,
  however many there are and on either side of the target, and **the earliest tied frame
  wins**, so an exact midpoint goes to the earlier frame. Repeats are
  dropped, so a sparse sequence returns fewer indices than targets. Use this when even
  spacing **in time** matters.
- `count`: exactly `count` frames spread by **position**, not by time, across the window,
  always including its first and last frame (`count=1` keeps the first). With uneven gaps this
  is not uniform in time: `[0, .1, .2, .3, 10]` with `count=3` keeps 0.0, 0.2 and 10.0.
  Position `i` is the frame at `round(i * (n - 1) / (count - 1))`, an exact half **rounding
  down to the earlier frame**, in integer arithmetic. A `count` of at least the window size
  returns every frame.
- At most one of `every_seconds` and `count`; with neither, the whole window is kept.
- Comparisons carry 1e-9 s of slack (`frames.TIME_EPSILON`), so `0.1 + 0.2` against `0.3`
  cannot flip a boundary or a tie. Empty input, a duplicate, reversed, negative or non-finite
  time, and a non-positive rate raise `ValueError`. Rates need not be integers.

Other helpers:

- `frame_intervals` returns `[]` for one frame. `relative_frames(frames, now=None)` copies each
  row, keeps its order and other keys, and adds `seconds_ago = now - timestamp_seconds`; `now`
  defaults to the last frame (whose `seconds_ago` is `0.0`) and may not be earlier than it.
  The [Images documentation](https://docs.typesafe.ai/images) recommends relative labels for
  frame histories, oldest first; drop `timestamp_seconds` from the state if the model should
  see only `seconds_ago`, and drop `frame_index` too (`select_frames` adds it, and it is part of
  the row you send as state).
- `window_timestamps(frames, first_index, last_index)` maps an inclusive index window (for
  example a candidate highlight window) back to seconds. Its duration runs from the first to
  the last frame in the window, so a window of `k` frames at gap `g` has duration `(k - 1) * g`.
- `frame_at(timestamps, seconds, *, side="before")` returns the index of the frame at or
  before (`"before"`), at or after (`"after"`) or nearest to (`"nearest"`, ties to the earlier
  frame) a log line or recorded agent-state time; it raises when no frame qualifies.
- `frame_windows(timestamps, *, width_seconds, stride_seconds)` enumerates sliding windows
  (ranks 89 and 92) as `{"window_start_seconds", "window_end_seconds", "indices"}`, edges
  inclusive, only windows that fit by stride. If the last of those stops short of the end, one
  final window aligned to the end (`[end - width, end]`) is added: frames every 0.5 s to 8 s
  with width 3 and stride 2 give windows starting at 0, 2, 4 and 5. **When
  `stride_seconds <= width_seconds`, every frame lies in some window.** A larger stride is
  accepted, not rejected, because scoring only some stretches of a sequence is a valid choice;
  a frame that falls between two windows is then in none, and nothing is raised. Whether any
  frame does depends on where the frames fall: with frames every second to 10 s and width 1,
  stride 5 gives the windows `[0, 1]`, `[5, 6]` and `[9, 10]`, so frames 2, 3, 4, 7 and 8 are
  in none, while stride 1.5 leaves no frame out. With the default `start` and `end`, the
  frames in no window are `set(range(n)) - {i for w in windows for i in w["indices"]}` for `n`
  timestamps. Use a stride no larger than the width when every frame must be scored. A window
  in a gap is kept with `indices == []`, so the recipe decides what an empty window means.
- `transition_time(frames, first_new_index)` and `earliest_transition(frames, changed)` apply
  the cookbook's single convention for when a transition happened: the timestamp of the
  **first frame in which the new state is visible**. `changed[i]` is the answer to "did the
  state change between frame `i` and `i + 1`?" (`True`, `False`, or `None` for an undetermined
  pair); the first `True` gives that time, but an undetermined pair before it returns
  `{"review": True, ...}` instead of a later transition. Gold labels use the same rule and
  have a stated format ([Transition labels](fixtures.md#transition-labels)), and the metric
  that compares them is `evaluation.transition_metrics` ([evaluation.md](evaluation.md)),
  whose tolerance should be at least the largest sampled gap.

**Index spaces.** `sample_frames` returns indices into the list it was given. `select_frames`
copies the rows and adds `frame_index`, the position in the list selected from (kept when you
select from a selection), so a pair index found on the sampled list can be mapped back to the
original sequence. `window_timestamps`, `earliest_transition` and `transition_time` take
indices into the list you hand them: pass the sampled list with sampled indices, never the
full list.

**Record what was selected.** Sampling changes what the recipe measures, so store the
selection in the example's `fields` rather than recomputing it silently:

```python
fields = {
    "frames": [
        {"timestamp_seconds": row["timestamp_seconds"], "frame_index": row["frame_index"]}
        for row in sampled
    ],
    "sampling": {"every_seconds": 0.5, "start": None, "end": None, "indices": chosen},
}
```

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
