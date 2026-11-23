# Screenshot error-state recognition

**Recipe 61** · Level 1 (Beginner) · Decision type: `Choice`

Classify an application screenshot as a crash, loading state, authentication failure, normal operation, or unknown using fixed visual categories.

## What it teaches

How to ask one `Choice` question over one synthetic application screenshot with a fixed category set that includes a fallback. Python owns the option list (`crash`, `loading`, `auth_failure`, `normal` and `unknown`), the [gold label](../../docs/glossary.md#gold-label) of every drawing, and the rule that acts on Jev's answer. Jev answers with one option, a probability for each and a confidence. A category is delivered only when its confidence clears a [confidence gate](../../docs/glossary.md#confidence-gate) frozen on `validation` with `select_confidence_threshold`; every `unknown` answer is a deferral and always goes to a simulated [review](../../docs/glossary.md#review) queue, as does every answer the gate withholds. The fixtures include look-alike pairs (a loading screen that shows error-like text, an authentication failure that resembles a normal form), screens that fit none of the four categories and a partially rendered screen. Every image is a drawing made by code and a stand-in for a screenshot.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev,ml]"` (the `ml` extra adds
scikit-learn, which the `Tests` jobs install and a recipe's `helpers.py` may use):

```bash
python -m jev_cookbook.fixtures validate recipes/61-screenshot-error-state-recognition
python tools/execute_notebook.py recipes/61-screenshot-error-state-recognition
pytest recipes/61-screenshot-error-state-recognition
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/` and reading the 29 screenshots in `assets/`. `build_fixtures.py` draws those images and writes `assets-manifest.json`, which records where each came from, its licence and what it is attested not to be ([docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)); [docs/vision.md](../../docs/vision.md) covers loading images and Box answers.

The notebook constraints below pin the stack that generated the images. The bytes of each image contribute to the request's replay key. Run `python recipes/61-screenshot-error-state-recognition/build_fixtures.py` from the root to regenerate the hand-written synthetic answers under the replay keys for the current question. The script stops if a regenerated image differs from the committed file unless you pass `--overwrite-assets` ([image byte stability and regeneration](../../docs/synthetic-images.md#byte-stability-and-regeneration)).

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — the `dev` extra above adds `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **29** requests, each decided once. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=29` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## Image copies per request

Each request carries one image copy of one distinct image: the screenshot, once, in the state. The question's criteria are words only, so no image repeats. Over all 29 requests (one per example) that is 29 copies and 29 as the per-request distinct images summed over the requests, the `images` and `distinct_images` totals declared in `request_budget.json` and printed by the audit line at the end of the notebook. The profile also reports the maximum and summed per-request distinct and expanded file bytes.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers about drawn images). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 12 `validation` and 16 `test` examples are scored; the 1 `demo` example shown up close
  carries no [gold label](../../docs/glossary.md#gold-label) and is in no metric.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, about images drawn for it, some of them deliberately wrong or unsure, so its numbers check that the pipeline works (the threshold selection, the rule, the review queue and the request accounting) and say nothing about how Jev performs, or about how it reads real screenshots. The `validation` figures are a selection step. When the policy delivers at least one validation answer, its objective forces [accuracy](../../docs/glossary.md#accuracy) among delivered answers to 1.0000 and [risk](../../docs/glossary.md#risk) to 0.0000. If every answer goes to review, both rates are undefined. Not measured live.

## Pull request rules

This recipe's pull request changes only `recipes/61-screenshot-error-state-recognition/`. The root `README.md` is generated; per
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

## Next steps

In the notebook's validation step, change `target_accuracy=1.0` to `0.8`. Restart the kernel and run the whole notebook offline so the request audit starts empty. The frozen threshold falls and the held-out [coverage](../../docs/glossary.md#coverage) rises, because a lower target accuracy lets the threshold admit lower confidences. Compare the words-only criteria here with the reference images in the criteria of [Visual SKU recognition](../69-visual-sku-recognition/), and follow the simulated review pattern in [Abstention and review queues](../38-abstention-and-review-queues/).
