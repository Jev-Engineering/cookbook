# Visual regression detection

Compare before/after screenshots with four independent `Noul` defect judgments and a `Score`
severity rubric. Python applies a validation-selected review gate, checks contradictions,
and compares the result with a pixel-difference baseline. Level 3, intermediate.

The notebook displays the screenshot pairs, typed answers, pixel mask, frozen-policy outcomes,
confusion matrices and an accepted mistake. Nothing controls a browser or changes a build status.
The synthetic screenshots and answers were authored for this recipe. **Not measured live.**

## Run offline

From the repository root:

```bash
python -m pip install -e ".[dev]"
python -m pip install -e ".[ml]" -c .github/constraints-notebooks.txt
python -m jev_cookbook.fixtures validate recipes/62-visual-regression-detection
python -m pytest recipes/62-visual-regression-detection/tests
python tools/execute_notebook.py recipes/62-visual-regression-detection
```

Use Python 3.14 and the pinned notebook stack to reproduce committed outputs. Open the notebook
from this directory for an interactive run. No network or API key is needed offline.

There are **26 pairs**: 12 validation, 12 held-out test and two unscored demonstrations. Each
480 × 360 PNG is drawn by Pillow with its bundled font. Assets live in `assets/`, named by content
hash; fixture rows refer to them without exposing the authored change or gold label to inference.
Unchanged pages, harmless restyling, missing elements, misalignment, clipping, overlays and subtle
defects all appear. Some synthetic answers are confidently wrong and survive the review gate.

Regenerate with `python recipes/62-visual-regression-detection/build_fixtures.py`. It rebuilds
inputs, labels and image assets, but refuses to replace recorded responses without explicit
`--force`. Questions, pixels and request keys are generated together. Images are entirely original
synthetic artwork covered by the repository license; no screenshots were scraped or downloaded.

## What the comparison means

The pixel baseline counts pixels with a maximum RGB-channel difference above 20/255. Validation
selects the changed-area threshold by F1. It is an independently useful detector for stable,
aligned captures, but cannot distinguish an allowed theme change from a content regression.

The semantic policy requires a consistent defect-label set and modal severity, then checks the
weakest answer certainty. Validation selects the lowest threshold achieving full correctness on
its consistent accepted subset. Test applies both frozen thresholds once. Coverage and risk use
the policy's actual decisions, including contradiction reviews. Binary baseline comparisons use
all 12 test pairs for both methods. If validation cannot meet the target, the notebook stops
before test; it does not substitute a guessed threshold.

Every offline metric is a **synthetic pipeline check, not a Jev result**. The notebook reports N
beside metrics. Model and capture date are not applicable for synthetic responses. Latency, input
tokens and billed cost remain null; no replay timer, pixel count or invented tariff fills them in.
Actual inference wall time and returned token usage are available in the live measurement path;
missing usage and unmeasured billed cost remain null. Record real responses and capture
measurements before reporting held-out results for a returned model version and capture date.

## Switch to live

Install `.[live]`, set `TYPESAFE_API_KEY` outside the notebook, and explicitly set:

```bash
export JEV_COOKBOOK_LIVE=1
export JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0
export JEV_COOKBOOK_LIVE_MAX_REQUESTS=26
```

Run interactively from this folder. The notebook requests `images=True` and `model="jev-1.14.0"`;
the backend supplies the experimental image header. It makes exactly **26** requests for the
committed pairs. Cache keys include current image bytes, state and questions, so unchanged requests
reuse their answers; changed evidence under the same example ID makes a new request and requires
extra budget. Measurement records use those same keys. Increase the budget to allow retry attempts.
`tools/execute_notebook.py` deliberately removes live settings and always runs offline.
See [live recording](../../docs/live.md) for preserving genuine returned answers; unrecorded live
previews are not reportable results.

## Read next

- [Semantic feature extraction](../35-semantic-feature-extraction/) develops independent labels.
- [Plan constraint assessment](../44-plan-constraint-assessment/) combines judgments in Python.
- [Fixture contract](../../docs/fixtures.md), [evaluation](../../docs/evaluation.md), and
  [offline/live disclosure](../../docs/offline-and-live.md) explain the shared conventions.

## Sources

- S02: [TypeSafe AI: Primitives](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
