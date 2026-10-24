# Door state transition detection

**Recipe 85** · Level 2 (Easy) · Decision type: `Choice`

A door monitor built from ordered still images. Jev supplies one bounded judgment:
`opened`, `closed`, `unchanged`, or `uncertain`. Python validates actual timestamps,
samples at most three frames, chooses a validation confidence gate, and records only
simulated observations. No native video input or door-control operation is involved.

The sampling example shows why identical sampled endpoints cannot prove that no opening
occurred between captures. A pixel baseline measures dark-gap area and motion in a fixed
door region; lighting, shadows, camera shifts, absent doors and occlusion challenge it.

## Run it offline

From the repository root, install the development dependencies with `pip install -e ".[dev]"`:

```bash
python recipes/85-door-state-transition-detection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/85-door-state-transition-detection
python tools/execute_notebook.py recipes/85-door-state-transition-detection
pytest recipes/85-door-state-transition-detection
```

To reproduce committed notebook figures, use Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.
The executor always runs offline. The generator draws all 80 PNG frames with Pillow;
no photographs, external assets, private data or model-created imagery are included.
The drawings and replay probabilities are authored synthetic examples. The generator
refuses to replace recorded responses unless `--force` is explicit; inputs and labels
are regenerated independently. Tests retain the current scaffold guard verbatim.

## Switch to live

Install `.[live]`, supply `TYPESAFE_API_KEY` through your environment, and set
`JEV_COOKBOOK_LIVE=1`. The notebook requests pinned `jev-1.14.0` with `images=True`,
which enables the experimental image header. Read [the live contract](../../docs/live.md).
A successful full notebook run makes exactly **25** requests: 12 validation examples,
12 test examples and one sampled demo. The reversed-time demo is rejected before inference.
The cache prevents repeated inspection from spending a second request. Python allows at
most 25 logical calls; the live backend's default 25-attempt limit also counts retries,
so retrying can stop a run early. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=30` if you explicitly
want five retry attempts of headroom. There is no automatic retry after budget exhaustion.

Unrecorded live exploration is not a reportable held-out result. For durable capture,
run this separately from this recipe folder in a live-enabled environment, with a fresh
output directory:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(fixtures=Path("fixtures/responses.json"), images=True, model="jev-1.14.0")
assert backend.mode == "live", "recording requires explicit live opt-in"
requests = [
    helpers.build_request(e.fields)
    for e in load_inputs()
    if helpers.preflight_reason(e.fields) is None
]
report = record(backend, requests, "captures/responses.json", ledger_path="captures/ledger.json")
```

The recorder uses the same `(state, questions, assets)` triples and stores the actual
returned model, capture date and available token usage. Review a complete capture before
replacing `fixtures/responses.json`; never merge synthetic and recorded answers. Re-select
on validation and freeze before reporting the test split from that recording. This path
does not time inference or obtain billing, so latency and cost remain `None`; add them
only with actual recorded measurements. Do not substitute replay runtime.

## What was and was not measured

Not measured live. The committed run is synthetic: 12 validation observations select
policies, 12 test observations check the frozen pipeline, and two demos are unscored.
The raw event labels include `uncertain`; review never counts as coverage. The accepted
shadow error demonstrates that a confidence gate can let a wrong observation through.
All reported metrics are synthetic pipeline checks, not evidence about Jev quality.
Model, capture date, input/output tokens, inference latency and cost are unknown here.

Rendered pixels are distinct across splits, but paired scenarios reuse drawing templates,
nuisance families and layouts. These held-out pipeline checks do not measure transfer to
new scene families or real cameras. A fixed region
baseline has no registration or camera calibration. The monitor observes sampled states;
it does not estimate an exact event time, identify unobserved cycles, or provide a safety
interlock. Review and action containers stay in memory and all actions have `executed=False`.

Continue with [tool outcome verification](../29-tool-outcome-verification/) and
[sentiment classification](../01-sentiment-classification/).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
