# Conveyor jam detection

**Recipe 89 · Level 3 (Intermediate) · Multiframe `Noul` + `Score`**

Build a bounded visual event assessor for short synthetic factory sequences. Three independent
`Noul` propositions ask whether the lane is visible, parcels are present, and parcels move.
One `Score` rates visible obstruction using four described levels. All four judgments share one
request. Python samples frames, checks timing and operating metadata, selects a confidence gate
on validation, and records only a simulated jam flag or a review entry.

Stationary parcels alone produce `halted_cause_unobserved`, never a claim about a hidden mechanical
fault. A stopped command produces `stopped_as_commanded`; unavailable commands, stale metadata,
repeated frames, unclear visibility, and contradictory judgments require review. Identical frames
cannot distinguish a frozen feed from a truly static scene. A changing indicator in these drawings
is illustrative evidence of image freshness, not camera authentication. No machine is controlled.

## Run offline

From the repository root, use Python 3.14 and the pinned notebook stack:

```bash
pip install -e ".[ml]" -c .github/constraints-notebooks.txt
python recipes/89-conveyor-jam-detection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/89-conveyor-jam-detection
python tools/execute_notebook.py recipes/89-conveyor-jam-detection
pytest recipes/89-conveyor-jam-detection
```

Install `.[dev]` separately for pytest and lint tools. The notebook runs without a key or network.
Its 78 PNGs are original Pillow drawings, 384 × 320 pixels, not real factory photographs.
There are 12 validation sequences, 12 held-out test sequences, and 2 unscored demonstrations.
Four sequences stop at Python interlocks without inference; the other 22 have synthetic responses.
The generator reproduces assets and fixtures and refuses to replace recorded responses unless
`--force` is supplied. Gold event descriptions stay outside inference state.

## Evaluation and limits

Validation selects the lowest observed confidence that attains perfect accepted-event accuracy
among structurally eligible validation candidates. This empirical objective is not a guarantee.
An empty pool or unattainable objective disables event acceptance and sends all test sequences
to review; no substitute threshold is claimed to meet the objective.
The fixed obstruction rubric endpoints (expected score ≤ 0.5 or ≥ 2.5) determine which answers
are semantically resolvable; the remaining scores require review. A separate pixel baseline tracks
orange parcel centroids and red obstruction pixels in a declared belt region. Validation selects
its displacement threshold from 2, 6, or 12 pixels by event agreement, breaking ties toward 2.
Both policies freeze before test evaluation. Review is never counted as coverage. The notebook
reports event accuracy, accepted-event accuracy, coverage, abstention, jam misses and false flags,
with N and printed chart values. A confident false jam survives the frozen gate.

**Not measured live.** All committed figures are synthetic pipeline checks, not Jev results.
Latency, tokens and cost remain `None`. Tiny authored drawings do not establish performance on
industrial video. Sampling can miss movement between frames; repeated images, camera motion,
lighting, hidden causes, invalid telemetry and changing parcel colors need independent handling.
The baseline's fixed color segmentation deliberately fails on dark parcels.

## Switch to live

The notebook makes exactly **22 calls** on this fixture set, each containing four questions.
The local session caps calls at 26 and caches identical requests. The live backend also caps HTTP
attempts, including retries; use `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` and expect fewer successful
calls if retries consume the budget. No retries occur in the recipe itself.

Install `.[live]`, use `JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`, and supply
`TYPESAFE_API_KEY` in the environment. The notebook pins `jev-1.14.0` and `images=True`, enabling
the experimental image header. Its questions and sampled image bytes are unchanged between
replay and live. Video decoding is outside this recipe; inputs are ordered still images.
An unrecorded live exploration is not a reportable held-out result.

To capture the same image requests deliberately, use the recorder's triples and write to a new
location outside the committed synthetic fixtures:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

recipe = Path("recipes/89-conveyor-jam-detection")
helpers = load_helpers(recipe)
triples = helpers.recording_requests(load_inputs(recipe), recipe)
backend = LiveBackend("jev-1.14.0", images=True, max_requests=26, max_retries=0)
record(
    backend,
    triples,
    Path("captures/conveyor-responses.json"),
    ledger_path=Path("captures/conveyor-ledger.json"),
)
```

The recorder preserves actual returned model, capture date and reported token usage. Capture
actual inference latency separately if needed; replay time is not inference latency. Missing
latency and billing remain unknown. See [live recording](../../docs/live.md) and
[image contracts](../../docs/vision.md). Genuine Opus review and integration remain separate gates.

## Sources

- S02: [TypeSafe AI: Primitives](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
