# Hierarchical visual search

**Recipe 83 · Level 4 (Advanced) · `Choice` + `Box`**

Find a small pink plus marker in a large authored diagram. Two dependent `Choice` requests
select overlapping tiles, then a separate `Box` localizes the marker in the last crop.
Python builds the tiles, accumulates their offsets, converts normalized coordinates back
to the original image, and enforces depth, request, confidence, and rectangle-size limits.
Every drawing action is simulated.

The notebook shows the whole image, the four candidate tiles, each typed answer, the final
crop, and its returned rectangle before reporting any aggregate. It compares two overlap
policies on validation, then evaluates the frozen policy, a full-image semantic comparator,
and a deterministic pixel baseline on the same held-out scenes. The semantic comparator
uses a presence `Choice` before its own `Box`.
`Box` always produces coordinates even for absent objects; it is never an absence detector.
Root `none` can yield absence; `none` in a selected subcrop requires review.

The pixel baseline detects pink connected components, then scores white interior pixels
against a plus template. Color tolerance, component dimensions, and the two-pixel outline
come from the authored drawing specification. Only its minimum shape score is selected on
validation, from 0.65, 0.8, and 0.95. The objective rewards end-to-end hits and penalizes wrong
accepted outcomes twice; ties choose the higher threshold. All three thresholds tie on this
exact-palette validation sample, selecting 0.95. No matching component means absent, and
multiple matches mean review. This narrow detector assumes the authored palette, orientation,
and border width; it is not validated on photographs, lighting changes, or compression.

## Run offline

From the repository root, using the development environment described in
[development.md](../../docs/development.md):

```bash
python -m jev_cookbook.fixtures validate recipes/83-hierarchical-visual-search
pytest recipes/83-hierarchical-visual-search
python tools/execute_notebook.py recipes/83-hierarchical-visual-search
```

Use Python 3.14 with the [notebook constraints](../../.github/constraints-notebooks.txt)
to reproduce committed outputs. Pillow draws and crops every image locally.
No network, key, or model is used. `build_fixtures.py` reproduces the JSON and PNG files.
It refuses to overwrite recorded responses unless `--force` is supplied deliberately;
inputs, labels, and images are regenerated before that refusal.

## Switch to live

Install `.[live]`, set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`, and
`JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`, then open the notebook from this folder.
The same request builders run in both modes. `get_backend(..., images=True,
model="jev-1.14.0")` pins the version and opts into experimental images and Box.
Do not use a moving model alias. The notebook executor deliberately clears live settings.

Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=160` for this notebook: the conservative upper bound
is 80 unique validation calls, 50 test calls, and 6 demo calls before retries. The default
25-request backend budget is insufficient. Actual request counts depend on responses;
cached requests are reused across validation gates. The hierarchy allows at most three
logical requests per scene and policy; the direct semantic comparator allows two. SDK retries additionally
consume the global live attempt budget. No call is retried by the recipe.
The committed adaptive run uses 112 distinct backend requests. The pixel detector adds no
model requests; its local computation is not timed or priced.
The complete fixture inventory has 151 distinct request triples. Recording that fixed
inventory makes exactly 151 calls before retries; the adaptive notebook uses the smaller
bound above and can follow different branches when live answers differ.

To capture an adaptive run, replace the setup cell's cache construction with:

```python
capture = helpers.CaptureBackend(backend, "recorded-run.json", ledger_path="recorded-ledger.json")
cache = helpers.RequestCache(capture)
```

This wrapper calls the shared recorder with `(state, questions, assets)` before using each
answer. Consequently the next tile request follows the recorded answer, including branches
different from the synthetic path. The two output files are outside `fixtures/`; inspect
the returned versioned model, dates, request inventory, and measurements before promoting a
complete captured run into fixtures. Changed branches require updating each input's
`replay_keys` from the exact captured requests. The cache's `requests` mapping exposes those
triples without changing their questions; it does not infer gold locations. A synthetic
response file is never relabeled as recorded. See [live.md](../../docs/live.md).

## What was and was not measured

**Synthetic; not measured live.** N = 10 validation and 10 test scenes, plus 2 unscored demos.
The 1024 × 768 PNGs are locally authored diagrams, not scraped or licensed photographs.
They include seam and edge targets, absence, duplicate matches, clutter, missing confidence,
low confidence, confidently wrong tiles, and confidently wrong rectangles.

End-to-end hits include presence localization at IoU ≥ 0.5, correct absence, and appropriate
review for ambiguous scenes. Each split contains **8 present, 1 absent, and 1 ambiguous**
scene. End-to-end hit rate has denominator 10; mean IoU and present localization hit rate
have denominator 8; absent false-positive rate has denominator 1. Every report prints these
denominators. Undefined rates are `null`.

Present cases split into localization hits, wrong returned rectangles, and misses with no
rectangle. Failed localizations include both wrong rectangles and misses. Mean IoU assigns
zero only when no rectangle is delivered; an incorrect delivered rectangle retains its
measured IoU. Absent cases split into false-positive rectangles, correct absence, and review.
Thus a false positive on an absent scene is counted separately from a wrong rectangle on a
present target. Coverage, accepted risk, explicit review counts, and logical model-request
counts describe each policy. Validation chooses overlap, confidence gates, and the pixel
shape threshold; test is used once with frozen settings. All numbers are pipeline checks.
Zero pixel-arm model calls does not establish zero computation or cost. Model, capture date,
input/output tokens, latency, and cost are `null` in the committed run.

Continue with [40 · Hierarchical classification](../40-hierarchical-classification/notebook.ipynb)
or [46 · Semantic context paging](../46-semantic-context-paging/notebook.ipynb).

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
