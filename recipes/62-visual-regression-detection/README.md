# Visual regression detection

**Recipe 62** · Level 3 (Intermediate) · Decision type: `Noul` + `Score`

Compare before-and-after screenshots for missing elements, misalignment, clipping, and other predefined visual changes, then score each change against an explicit severity rubric.

## What it teaches

How to compare a `before` and an `after` screenshot with independent `Noul` propositions, one per predefined change category (`missing_element`, `misalignment`, `clipping` and `overlap`), score each category's change on a four-level severity rubric with a `Score`, and combine the answers into a verdict in Python. All eight questions go in one request per pair, because none of them needs another's answer to be built; Python reads a category's severity only when that category is detected. Python owns the categories, the rubric, the [gold label](../../docs/glossary.md#gold-label) of every drawn pair, and the three settings frozen on `validation`: a [business threshold](../../docs/glossary.md#business-threshold) per category with `select_threshold`, a severity cutoff with `select_threshold`, and a [confidence gate](../../docs/glossary.md#confidence-gate) on the severity answers with `select_confidence_threshold`. A pair passes, fails, or goes to a simulated [review](../../docs/glossary.md#review) queue. The fixtures include an unchanged pair, benign look-alikes (a different button colour, a later time stamp), pairs with two simultaneous changes of different severity, a change at the boundary between two rubric levels, and every combination of the four propositions. Every image is a drawing made by code and a stand-in for a screenshot.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev,ml]"` (the `ml` extra adds
scikit-learn, which the `Tests` jobs install and a recipe's `helpers.py` may use):

```bash
python -m jev_cookbook.fixtures validate recipes/62-visual-regression-detection
python tools/execute_notebook.py recipes/62-visual-regression-detection
pytest recipes/62-visual-regression-detection
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/` and reading the screenshots in `assets/`. `build_fixtures.py` draws those images and writes `assets-manifest.json`, which records where each came from, its licence and what it is attested not to be ([docs/fixtures.md](../../docs/fixtures.md#image-provenance-manifest)); [docs/vision.md](../../docs/vision.md) covers loading images.

The notebook constraints below pin the stack that generated the images. The bytes of each image contribute to the request's replay key. Run `python recipes/62-visual-regression-detection/build_fixtures.py` from the root to regenerate the hand-written synthetic answers under the replay keys for the current questions. The script stops if a regenerated image differs from the committed file unless you pass `--overwrite-assets` ([image byte stability and regeneration](../../docs/synthetic-images.md#byte-stability-and-regeneration)).

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
In live mode this notebook makes exactly **45** requests, each decided once. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=45` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## Image copies per request

Each request carries two image copies: the `before` and the `after` screenshot, each once, in the state. Every question's text is words only, so no image repeats. An unchanged pair's two screenshots have the same bytes and so the same reference, so its request carries two copies of one distinct image. Over all 45 requests (one per pair) that is 90 copies and 88 as the per-request distinct images summed over the requests, the `images` and `distinct_images` totals declared in `request_budget.json` and printed by the audit line at the end of the notebook. The profile also reports the maximum and summed per-request distinct and expanded file bytes.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers about drawn images). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 22 `validation` and 22 `test` pairs are scored; the 1 `demo` pair shown up close
  carries no gold label and is in no metric.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, about images drawn for it, some of them deliberately wrong or unsure, so its numbers check that the pipeline works (the three selections, the composition rule, the review queue and the request accounting) and say nothing about how Jev performs, or about how it reads real screenshots. The `validation` figures are a selection step. The gate's objective, `target_accuracy=1.0`, forces every detected `validation` change at or above the gate onto the right side of the severity cutoff; it does not force the `validation` verdicts, because a change below its business threshold never reaches the gate. The `test` figures are reported once, after every setting is frozen: the verdict's [coverage](../../docs/glossary.md#coverage), review rate, [accuracy](../../docs/glossary.md#accuracy) among delivered verdicts and [risk](../../docs/glossary.md#risk); each proposition's counts at its threshold; and the exact agreement of each severity's most probable level with its labelled level. Not measured live.

## Pull request rules

This recipe's pull request changes only `recipes/62-visual-regression-detection/`. The root `README.md` is generated; per
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

In the notebook's "Python's part" cell that calls `helpers.choose_gate`, change `target_accuracy=1.0` to `0.95`. Restart the kernel and run the whole notebook offline so the request audit starts empty. The confidence gate falls, because a lower target accuracy lets the gate admit lower confidences, so the two `test` reviews become verdicts: the held-out coverage rises, and so does the risk among the delivered verdicts, because one of the two pairs the gate was holding back is then failed when its gold verdict is `pass`. Follow one image through a fixed category set with a fallback option in [Screenshot error-state recognition](../61-screenshot-error-state-recognition/), locate an element on a screenshot with a presence check in [Visual browser element locator](../77-visual-browser-element-locator/), and see several `Noul` labels with a threshold per label in [Multiple topic labels](../06-multiple-topic-labels/).
