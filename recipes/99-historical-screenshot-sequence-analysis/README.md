# Historical screenshot sequence analysis

**Recipe 99 · Level 4 (Advanced) · Noul + images + long context**

Find the earliest **retained, visibly supported** chart-collapse transition in a synthetic
3.5-hour UI test session. Python sorts screenshots and logs, supplies every adjacent-frame
candidate, and checks timestamps, log freshness, sampling completeness and request limits.
Jev supplies bounded visual and log-association judgments. A positive association does not
establish cause, and the after-frame time does not identify the exact onset between samples.

The original Pillow drawings depict a fictional Telemetry Lab application. Eight scheduled
screenshots and approximately 218 log entries per session include recovery and recurrence,
large benign theme changes, loading placeholders, covered panels, stale sessions, contradictory
logs, missing captures and instruction-like text inside logs. The generator is the asset source;
there is no external image license or real user data. Paths and content references are opaque;
rendering plans, split names and gold annotations never enter inference state.

## Run offline

From the repository root, with the development dependencies installed:

```bash
python recipes/99-historical-screenshot-sequence-analysis/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/99-historical-screenshot-sequence-analysis
pytest recipes/99-historical-screenshot-sequence-analysis -q
python tools/execute_notebook.py recipes/99-historical-screenshot-sequence-analysis
```

The notebook runs without a key or network. Reproducing its committed outputs requires
Python 3.14 and `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`;
`.[dev]` separately supplies pytest and ruff. See the
[notebook execution contract](../../docs/recipe-template.md#executing-a-notebook).

## Policy and comparison

Each complete session supplies 15 independent Noul propositions in **one** request: initial
presence and one visual-transition plus one log-association judgment for each of seven pairs.
Incomplete sessions still receive a bounded diagnostic request, but Python always sends them
to review. Unknown earlier candidates block a later earliest claim. Existing symptoms at the
first frame, stale or missing relevant logs and contradictory outcomes also require review.
A confident negative result means no target transition among the retained screenshots.

Validation selects certainty from the fixed family `(0.4, 0.6, 0.8, 0.95)` by maximizing
correct accepted sessions minus four times wrong accepted sessions, breaking ties by accepted
count and then lower threshold. Python freezes the chosen value before the held-out test pass.
The baseline uses actual whole-image mean absolute pixel change of at least 0.02 and an
`error` keyword in a log within the same interval; it does not read annotations. Its tendency
to flag theme changes and trust stale or conflicting context is part of the comparison.

## What was and was not measured

**Synthetic pipeline checks; not measured live.** There are 12 validation sessions, 12 test
sessions and 2 unscored demonstrations, with 205 PNGs and 26 stored request responses.
At the frozen certainty threshold 0.6, the test policy accepts 6/12 sessions and gets 5/6
accepted events correct; 6/12 defer to review. The deliberately wrong accepted session is
shown in the notebook. These are authored replay outcomes, not estimates of Jev quality.
Model, capture date, token counts, inference latency and cost are unknown (`None`).

`long_context=True` enables the experimental capability for the same full-history request.
The notebook prints actual serialized text characters and image counts; it does not claim to
fill or benchmark a 262K-token window. The fixed 30-minute sampling cadence can miss brief
changes even with no missing scheduled frame. Missing scheduled captures require review.
A denser capture policy, authentic logs and a new untouched test set would be needed to assess
real session histories. Every report and queue entry is simulated.

## Switch to live

The notebook makes exactly **26 calls** in a successful live run without retries, one per
unique session; repeated threshold evaluation reuses the cached typed answers. Set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 26 (for example 32 to allow some retries).
The recipe also caps logical requests at 26, screenshots at 8, log rows at 256 and serialized
text at 200,000 characters. These local limits do not assert an API-wide image or token limit.
Every HTTP attempt, including retries, is additionally bounded by the backend budget.

Install `.[live]`, set `JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0` and
provide `TYPESAFE_API_KEY` through the environment. Open the notebook from this folder.
Its backend explicitly pins `jev-1.14.0`, `images=True` and `long_context=True`.
The executor always clears live variables. Unrecorded live exploration is not a reportable
held-out measurement; its evaluation cells withhold aggregate results.

For a deliberate recording, run this from the recipe folder with the same opt-in environment:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(
    fixtures=Path("fixtures/responses.json"),
    model="jev-1.14.0",
    images=True,
    long_context=True,
)
if backend.mode != "live":
    raise RuntimeError("Recording requires explicit live opt-in")
triples = [helpers.request(row.fields) for row in load_inputs()]
report = record(
    backend,
    triples,
    Path("capture/responses.json"),
    ledger_path=Path("capture/ledger.json"),
    overwrite=False,
)
print(report)
```

The separate destination avoids mixing synthetic and recorded provenance. Inspect the
returned model, capture dates and usage in the recorded responses and the attempt ledger;
leave unreported token counts, latency and charges unknown. This snippet does not time live
inference or measure charges. The run-accounting helper preserves unknown values. After an
intentional all-recorded replacement of `fixtures/responses.json`, replay the notebook to
select only on validation and report the held-out split once, naming returned model, date and
N. Keep any real inference timing or measured billing in a separate capture artifact; never
substitute replay duration. The generator refuses to overwrite recorded answers without
`--force`. See [the recorder contract](../../docs/live.md#recorder).

## Next steps

[Evidence conflict diagnosis](../47-evidence-conflict-diagnosis/) expands contradictory-record
handling; [abstention and review queues](../38-abstention-and-review-queues/) examines the
cost of deferring a decision. A real recording needs denser sampling and a new held-out set
before drawing conclusions about real defects.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
