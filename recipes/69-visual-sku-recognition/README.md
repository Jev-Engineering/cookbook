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
`select_confidence_threshold`, and everything else, every `uncertain` answer included, goes to a
simulated review queue. Because a reference in criteria is sent again with every request, the
notebook counts the image copies each request carries (one query image plus the six references)
and states them beside the request count. Every image is a drawing made by code and a stand-in
for a product photograph.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/69-visual-sku-recognition
python tools/execute_notebook.py recipes/69-visual-sku-recognition
pytest recipes/69-visual-sku-recognition
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/` and reading the images in `assets/`: six reference images, one per product, and 31 query images. `build_fixtures.py` draws those images and writes `assets-manifest.json`, which records where each came from, its licence and what it is attested not to be ([docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)); [docs/vision.md](../../docs/vision.md) covers what applies here, loading images with `image_asset` and `image_reference` and counting the image copies a request carries; its Box and coordinate sections do not, because this recipe asks only a `Choice` question.

The committed images were written under the notebook constraints pin (the install in the paragraph below). Their bytes are part of the replay key of each request that carries them, the six references in the criteria included, so `build_fixtures.py` refuses a picture whose bytes differ from the committed file unless `--overwrite-assets` accepts the change ([docs/synthetic-images.md](../../docs/synthetic-images.md#byte-stability-and-regeneration)).

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
references and 31 queries, which the notebook counts from the image bytes beside the `image_request_profile` totals.

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
photographs. The `validation` figures are a selection step. Two `validation` figures cannot come
out otherwise, accuracy among the delivered answers, which the selection objective forces to
1.0000, and its complement, risk 0.0000, and the notebook says so beside them. Not measured live.

## Pull request rules

This recipe's pull request changes only `recipes/69-visual-sku-recognition/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
