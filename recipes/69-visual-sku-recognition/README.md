# Visual SKU recognition

**Recipe 69** · Level 2 (Easy) · Decision type: `Choice`

Select a product variant from a fixed SKU catalog whose choice criteria contain reference photographs, with no-match and uncertain outcomes.

## What it teaches

The reference-first pattern for visual criteria. Python owns a fixed catalogue of six invented tea
tins and builds one `Choice` question over it. Each product option's criteria hold that product's
reference image, inserted with `image_reference`, beside two outcome options in words only:
`no_match` (a design the catalogue does not hold, or no tin at all) and `uncertain` (the picture
cannot tell two products apart, because a tag covers the one feature that separates them). Jev
compares the query image in the state against every reference and answers with the option, a
probability for each and a confidence. Python decides what the answer is worth: a product or
`no_match` is delivered only when its confidence clears a threshold frozen on `validation` with
`select_confidence_threshold`, and every other answer goes to a simulated review
queue. That includes all answers when validation yields no feasible cutoff. Each reference in
criteria travels with every request, so the notebook reports the encoded bytes and image copies
(one query image plus the six references) for each request. Every image is a drawing made by code
and a stand-in for a product photograph.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/69-visual-sku-recognition
python tools/execute_notebook.py recipes/69-visual-sku-recognition
pytest recipes/69-visual-sku-recognition
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/` and reading the images in `assets/`: six reference images, one per product, and 31 query images. `build_fixtures.py` draws those images and writes `assets-manifest.json`, which records where each came from, its licence and what it is attested not to be ([docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)); [docs/vision.md](../../docs/vision.md) covers what applies here, loading images with `image_asset` and `image_reference` and counting the image copies a request carries; its Box and coordinate sections do not, because this recipe asks only a `Choice` question.

The notebook constraints below pin the stack that generated the images. The bytes of each image,
including the references in the criteria, contribute to the request's replay key. Run
`python recipes/69-visual-sku-recognition/build_fixtures.py` from the root to regenerate the
hand-written synthetic answers under the replay keys for the current question. The script stops if
a regenerated image differs from the committed file unless you pass `--overwrite-assets`.
[Image byte stability and regeneration](../../docs/synthetic-images.md#byte-stability-and-regeneration)

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **31** requests, each decided once. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=31` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## Image copies per request

Each request carries seven image copies of seven distinct images: the query image once, in the
state, and the six reference images once each, in the question's criteria (a reference in criteria
goes with every call). Over all 31 requests that is 217 copies, and 217 as the per-request distinct images summed over the
requests (7 times 31), the `images` and `distinct_images` totals declared in `request_budget.json` and
printed by the audit line at the end of the notebook. The run itself uses 37 different image files, six
references and 31 queries, which the notebook counts from the content-hash asset keys beside the `image_request_profile` totals.
The profile also reports the maximum and summed per-request distinct and expanded file bytes.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers about drawn images). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 14 `validation` and 16 `test` examples are scored; the 1 `demo` example shown up close
  carries no gold label and is in no metric.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, about images drawn for it, some
of them deliberately wrong or unsure, so its numbers check that the pipeline works (the reference
images in the criteria, the threshold selection, the rule, the review queue and the request
accounting) and say nothing about how Jev performs, or about how it reads real product
photographs. The `validation` figures are a selection step. When the policy delivers at least one
validation answer, its objective forces accuracy among delivered answers to 1.0000 and risk to
0.0000. If every answer goes to review, both rates are undefined. Not measured live.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)

## Next steps

In the notebook's validation step, change `target_accuracy=1.0` to `0.8`. Restart the kernel
and run the whole notebook offline so the request audit starts empty. Watch held-out coverage
and risk rise. Compare the reference-image criteria here
with the text criteria in [CMDB asset matching](../22-cmdb-asset-matching/) and follow the
simulated review pattern in [Abstention and review queues](../38-abstention-and-review-queues/).
