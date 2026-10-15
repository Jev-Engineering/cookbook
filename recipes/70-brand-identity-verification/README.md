# Brand identity verification

**Recipe 70** · Level 2 (Easy) · Decision type: `Noul` + reference images

Compare a displayed logo with three approved PNG variants of the fictional exercise brand
**KIVORA**. This is bounded visual conformance, not trademark, ownership, authenticity, or legal
verification. All assets are original synthetic Pillow drawings, not photographs.

## What it teaches

Four independent Noul propositions are batched: inspectability plus one match per approved light,
dark, and monochrome reference. Each reference is embedded directly in its question instructions.
Python combines the answers, rejects contradictory matches, gates resolved findings on certainty,
and records simulated findings or explicit review entries. It never publishes an asset.

Uniform scale and translation are allowed; stretching, wrong symbols or characters, altered
spacing, and unapproved color are not. Occluded, tiny, blurred, and absent marks require review.
A drawn claim of approval cannot change the policy. A minimum certainty gate is selected on
validation and frozen before test; a deliberately confident wrong test match survives it.

The deterministic baseline receives the same candidate and all approved reference images. It
aligns foreground bounding rectangles and compares pixels, aspect ratio, and color. Validation
selects its acceptance/rejection boundaries from a declared fixed grid; the gap means abstention.
Its flat-background segmentation and lack of OCR limit it on clutter, blur, and small word changes.

## Run it offline

From the repository root, with `pip install -e ".[dev]"`:

```bash
python recipes/70-brand-identity-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/70-brand-identity-verification
python tools/execute_notebook.py recipes/70-brand-identity-verification
pytest recipes/70-brand-identity-verification
```

To reproduce committed outputs, use Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.
The notebook executes from this recipe folder with no network or API key.

`build_fixtures.py` authors 33 PNGs at 480×320: three approved references and 30 distinct candidates.
The 14 validation and 14 test labels carry readable rationales; two demos have no labels.
Input fields contain neutral image paths only. Drawing parameters and gold labels never enter
inference or the baseline. Reference pixels are intentionally shared across splits; query pixels
are unique. The generator refuses to overwrite recorded answers without `--force`.

## Switch to live

Install `pip install -e ".[live]"`, provide `TYPESAFE_API_KEY` in your environment, and opt in with
`JEV_COOKBOOK_LIVE=1`. The notebook pins `jev-1.14.0` and enables the experimental images header.
It makes exactly **30** calls in live mode, one per example, with four independent questions per call.
Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=36` for 30 calls plus up to six retry attempts. Every attempt
counts; exhausting the budget stops the run. Its separate logical-request limit is 30.
`tools/execute_notebook.py` always runs offline. Never put a key in a notebook or fixture.

An unrecorded live exploration yields no reportable held-out claim. To capture the same requests,
run the following deliberately, from this recipe directory, after the environment opt-in above:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(fixtures=Path("fixtures/responses.json"), images=True, model="jev-1.14.0")
requests = [helpers.build_request(e.fields) for e in load_inputs()]
report = record(
    backend,
    requests,
    Path("capture/responses.json"),
    ledger_path=Path("capture/ledger.json"),
)
```

The separate capture file preserves synthetic fixtures. The recorder saves the API's returned model,
UTC capture date, and usage, deduplicates requests by pixel-bound replay key, and leaves unknown
measurements unknown.

After reviewing the capture, disable live mode with `unset JEV_COOKBOOK_LIVE` before launching a
fresh notebook kernel. In the setup cell, replace its backend construction with:

```python
backend = get_backend(fixtures="capture/responses.json", images=True, model="jev-1.14.0")
```

Restart and run all cells. The header must now say `recorded`, name the returned model and capture
date, and the setup must use the capture path above. This selects the recording while preserving
the same questions and synthetic fixture files. Freeze policy using validation before reporting
recorded test outcomes. See [live recording](../../docs/live.md). Inference latency and charges
need separate actual measurements; replay time is not inference time.

## What was and was not measured

- **Mode:** synthetic offline replay; **not measured live**.
- **N:** 14 validation examples for policy selection, 14 held-out test examples, two unscored demos.
- **Measures:** actual accepted coverage, abstention, accepted accuracy/risk, and a confusion matrix
  including review, compared with an aligned pixel baseline on identical inputs.
- **Unknown:** model behavior, inference latency, token usage, and billing. Accounting leaves these
  as `None` for synthetic replay.

Every number is a pipeline check, not a Jev result. The corpus shares an authored drawing grammar
across splits and does not establish performance on real marketing materials. The notebook shows
an accepted wrong wordmark match and the cost of reviewing correct but uncertain examples.

## Next steps

Read [refund intent detection](../02-refund-intent-detection/),
[multiple topic labels](../06-multiple-topic-labels/), and
[abstention and review queues](../38-abstention-and-review-queues/).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
