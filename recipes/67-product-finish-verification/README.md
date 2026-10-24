# Product finish verification

**Recipe 67** · Level 3 (Intermediate) · `Noul` + `Score`

Compare a manufactured enclosure's visible color family, material appearance and finish with a visual
reference. Python combines separate judgments with a discrepancy-severity score, then simulates
approval or review. This recipe uses **synthetic Pillow illustrations**, not actual product photos,
calibrated colorimetry, gloss measurements or verified material composition.

## What it teaches

Four independent Noul propositions cover comparability and the three appearance attributes. One
Score has a complete five-level discrepancy rubric. Python owns the reference-presence check,
certainty cutoff, severity interlock, request budget, ActionLog and ReviewQueue. Review remains
abstention, even when the answer confidently says the images cannot be compared.

The pixel baseline measures masked foreground mean RGB and adjacent-pixel variation on the same
pairs. Both policies are selected on validation and frozen before the held-out test. Illumination
glare and shadow, hue changes, matte/gloss differences, stipple, grain, occlusion, unknown appearance,
absent products and missing references exercise the workflow. A deliberately confident wrong test
answer passes the frozen approval gate; no safety or manufacturing-quality guarantee is implied.

## Run it offline

From the repository root after `pip install -e ".[dev]"`:

```bash
python recipes/67-product-finish-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/67-product-finish-verification
python tools/execute_notebook.py recipes/67-product-finish-verification
pytest recipes/67-product-finish-verification
```

The notebook uses its recipe folder as the working directory. No key or network is needed.
Reproduce committed outputs using Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`;
see [development](../../docs/development.md) and the [notebook contract](../../docs/recipe-template.md).
`build_fixtures.py` regenerates images and readable gold labels, and requires `--force` before
replacing a recorded, unreadable or malformed response file. Existing bytes are preserved unless the
file validates as a wholly synthetic replay or replacement is explicitly forced.
Drawing parameters and labels never enter requests. Assets are
opaque content-addressed PNGs outside the strictly validated `fixtures/` directory.

## Switch to live

**Not measured live.** Install `pip install -e ".[live]"`, set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`, and
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=30`; open the notebook from this folder in Jupyter. Image inference
is experimental; `get_backend` uses `images=True` and the same question definitions and image assets.
The executor intentionally strips live settings and always runs offline.

The notebook makes exactly **24** calls in a successful live run: one batched request per available
pair, with five questions in each request. The two missing references consume no call; all displayed
answers are cached. The local limit is 24 logical requests. Set the live HTTP-attempt budget to at
least 30 for retry room, since retries count and the default is 25; a larger budget still does not
promise completion. The backend's budget refusal stops the run before another attempt.

Unrecorded live exploration does not print held-out metrics. The notebook supplies
`recording_requests()` and an unexecuted example using `record(backend, triples, ...)`. Capture to a
fresh directory outside `fixtures/` to avoid synthetic responses being treated as already recorded.
Inspect captured results before installing the recorded response file. The recorder preserves the
actual returned model, capture date, usage and request ledger. Latency and billing stay unknown unless
separately measured during inference; replay time is never inference latency.

## What was and was not measured

- **Mode:** synthetic; **not measured live**. Model, capture date, input/output tokens, latency and
  cost are unknown or inapplicable (`None`).
- **N:** 12 validation and 12 test cases, plus two unscored demos; 50 independent PNG assets;
  24 requests and 120 typed answers.
- **Measurements:** per-attribute Noul accuracy and Score mean absolute error on eight determinate
  cases per split; actual approval accuracy, coverage, abstention, false approvals and route accuracy
  on all 12 cases per split. These are synthetic pipeline checks, not Jev quality results.
- **Limits:** images and probabilities were authored for this lesson. Foreground segmentation assumes
  a uniform light backdrop. No conclusion transfers to real photographs or physical material,
  color, gloss or texture specifications without independent measurement and validation.

In a future recorded run the notebook prints the returned model, capture dates and sample sizes.
For further routing patterns, see [sentiment classification](../01-sentiment-classification/) and
[abstention and review queues](../38-abstention-and-review-queues/).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
