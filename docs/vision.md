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
dimension 256–1568 and total area 78,400–2,458,624 pixels. A 384 × 320 fixture fits;
a 256 × 256 fixture does not. The loader rejects orientation metadata requiring a
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
uses the same operation. Geometry does not resize crops to API limits; save and
validate a prepared crop with `image_asset` before using it as a request asset.
`draw_boxes` returns a separate RGB image with named pink rectangles, paper label
backgrounds and ink text from the cookbook palette.

`box_iou(first, second)` computes intersection divided by union, using continuous
normalized geometry before pixel rounding. It returns zero for disjoint or merely
touching rectangles and one for identical rectangles.

## Presence, confidence and evaluation

A Box returns one rectangle even when its target is absent. Determine presence
with a companion question before treating a rectangle as a detection.
[Box documentation](https://docs.typesafe.ai/primitives/box)

`box_confidence(answer)` returns the supplied confidence or `None` if missing/null;
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
partial sliver tiles. A source smaller than a requested tile keeps its full extent.

`tile_to_image` applies an affine transform using the actual pixel bounds, so a
rectangle found inside a tile maps back to the whole image. It also handles an
entire tile resized before inference, provided coordinates still describe that
tile's full extent. Padding or further cropping requires its own transform.

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
model only sees the rows you choose to send.

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
chosen = sample_frames(times, every_seconds=2.0)  # indices, ascending, no repeats
sampled = select_frames(frames, chosen)  # copies of those rows, each with frame_index
gaps = frame_intervals(sampled)  # seconds between consecutive rows, n - 1 values
labelled = relative_frames(sampled)  # adds seconds_ago = last time - time
window = window_timestamps(sampled, 1, 2)  # start_seconds, end_seconds, duration_seconds
```

`sample_frames(timestamps, *, every_seconds=None, count=None, start=None, end=None)`:

- `start` / `end` bound an inclusive window (default: first and last timestamp). A window with
  no frame raises rather than returning nothing.
- `every_seconds`: targets are `window_start + k * every_seconds` (multiplied, never
  accumulated) up to `end`. Each target takes the **nearest** frame in the window; **a tie
  goes to the earlier frame**. Frames within the 1e-9 s slack of each other are not
  distinguishable by time: the rule is guaranteed for up to two such frames around a target, and
  real elapsed-time data does not contain them. Repeats are
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
  final window aligned to the end (`[end - width, end]`, overlapping the previous one) is
  added, so no frame is left out: frames every 0.5 s to 8 s with width 3 and stride 2 give
  windows starting at 0, 2, 4 and 5. A window in a gap is kept with `indices == []`, so the
  recipe decides what an empty window means.
- `transition_time(frames, first_new_index)` and `earliest_transition(frames, changed)` apply
  the cookbook's single convention for when a transition happened: the timestamp of the
  **first frame in which the new state is visible**. `changed[i]` is the answer to "did the
  state change between frame `i` and `i + 1`?" (`True`, `False`, or `None` for an undetermined
  pair); the first `True` gives that time, but an undetermined pair before it returns
  `{"review": True, ...}` instead of a later transition. Gold labels
  use the same rule, and the metric that compares them is `evaluation.transition_metrics`
  ([evaluation.md](evaluation.md)), whose tolerance should be at least the largest sampled gap.

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
    "sampling": {"every_seconds": 2.0, "start": None, "end": None, "indices": chosen},
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
