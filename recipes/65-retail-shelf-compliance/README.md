# Retail shelf compliance

**Recipe 65** · Level 3 (Intermediate) · Decision type: `Noul`

Compare a shelf observation with an approved planogram image. Three independent group-to-zone
statements check oats, tea, and soup; Python combines them into compliant, noncompliant, or review
outcomes. The visual assets are original **synthetic drawings**, not shelf photographs.

## What it teaches

The approved groups and shelf zones are fixed in Python. Each request includes the actual shelf
and reference image bytes through opaque references; no gold label or drawing specification enters
inference. One batched request asks three Noul statements. Any positive facing count and spacing are
acceptable, so a correctly stocked shelf can differ substantially from its planogram drawing.
A failed relationship flags its group/zone; it does not separately diagnose missing versus misplaced.

Python applies a certainty gate selected on validation, requires all group judgments for a completed
report, and simulates audit reports or review queue entries. It never creates a restock order. A
pixel-only baseline extracts each approved zone's dominant product color from the same reference,
then matches the corresponding observed zone. Its assumptions about registration, lighting, and
package color are explicit. Readable alternate packaging and same-color unknown products expose
those limits.

## Run offline

From the repository root, with `pip install -e ".[dev]"`:

```bash
python recipes/65-retail-shelf-compliance/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/65-retail-shelf-compliance
python tools/execute_notebook.py recipes/65-retail-shelf-compliance
pytest recipes/65-retail-shelf-compliance
```

The notebook runs from this folder without a key or network. Reproducing committed outputs uses
Python 3.14 and `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. The generator is
reproducible and refuses to overwrite recorded responses without `--force`.

## Switch to live

Not measured live. Install `.[live]`, provide `TYPESAFE_API_KEY` only through the environment,
and enable `JEV_COOKBOOK_LIVE=1` when opening the notebook interactively. The notebook pins
`jev-1.14.0` and enables experimental images. It makes exactly **26** calls, each with two images
and three independent questions. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher; retries also
consume the budget, and exhaustion stops the run. The executor always strips live settings.

To deliberately record the same requests, run this from the recipe folder after configuring
credentials and live access. Keep the destination separate from the committed synthetic responses:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
triples = [helpers.request(e.fields) for e in load_inputs()]
report = record(
    LiveBackend("jev-1.14.0", images=True, max_requests=26),
    triples,
    Path("captures/responses.json"),
    ledger_path=Path("captures/ledger.json"),
)
```

The recorder retains actual returned model, capture date, and reported usage. To evaluate a recording,
use its response path with the same definitions; freeze policy on its validation split before test.
Unrecorded live exploration is not a reportable held-out result. Missing inference timing or charges
remain unknown; replay timing is never API latency.

## What was and was not measured

- **Mode:** synthetic replay; not measured live. Model and capture date are not applicable.
- **N:** 12 validation and 12 test shelves, with 36 group judgments per split; two unscored demos.
- **Assets:** 26 unique shelf drawings and one separately rendered approved planogram, 600 × 400.
- **Coverage:** group-level and complete-shelf acceptance, reported separately from correct review.

The notebook reports three-way agreement, accepted accuracy, abstention, and a confusion matrix
against readable gold labels. It shows variable counts/spacing, swaps, empty/restocked zones,
blocked views, changed packaging, mixed product groups, and an unknown look-alike. A confidently
wrong held-out answer remains accepted after the frozen gate. All numbers are synthetic pipeline
checks and say nothing about Jev quality, latency, tokens, cost, or real-world inventory accuracy.
Accounting fields remain `None` when unmeasured.

## Scope and review

This local Codex implementation changes only this recipe folder. The root README remains the
integration worker's responsibility under [CONTRIBUTING.md](../../CONTRIBUTING.md). Local checks
are not Opus approval; the existing review and merge gate remains required. The catalog entry has
no assigned recipe issue, so this work remains local until an assignment and integration review.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
