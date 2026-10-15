# Visual UI state identification

**Recipe 73 · Level 2 · Choice with image criteria**

Compare a cropped button, toggle or text field against six reference images for that same
component: selected, disabled, active, hovered, error and unknown. The controlled legend makes
most appearances distinguishable. A second legend deliberately makes active, hover and keyboard
focus identical; those cases belong to unknown because a still image cannot recover interaction
history. Python gates observations and queues review. No code clicks a control or treats its
appearance as a permission.

## Run offline

From the repository root, with `pip install -e ".[dev]"`:

```bash
python recipes/73-visual-ui-state-identification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/73-visual-ui-state-identification
python tools/execute_notebook.py recipes/73-visual-ui-state-identification
python -m pytest recipes/73-visual-ui-state-identification -q
```

Reproducing committed output uses Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. The generator reproduces the
Pillow-authored images and hand-written distributions; it refuses to replace recorded responses
without `--force`. Inputs, labels and authored pixels are regenerated even on refusal. Review
those changes before recording again, because image bytes participate in replay identity.

## Data and evaluation

The 26 synthetic examples comprise **12 validation, 12 held-out test and two unscored demos**.
There are 74 PNG files at 480 × 360: 26 queries and 48 references covering eight component/theme
legends. Queries have different pixels from their references. All images are synthetic drawings,
not real screenshots. Fixtures cover scale and position changes, dark and light themes, absent or
obscured controls, conflicting cues, neutral controls and screenshot text that tries to redirect
the answer. Drawing parameters and gold labels stay outside model input.

Validation selects the lowest observed confidence with perfect accuracy among eligible concrete
predictions, then freezes the policy. Unknown always means review and never coverage. Test is
reported once, alongside a deterministic nearest-reference baseline using central RGB pixels,
fixed distance and tie bounds, and the same input/reference images. A confidently wrong held-out
answer survives the gate; the notebook shows it and the pending review notes.

**Not measured live:** all committed metrics are synthetic pipeline checks, not Jev quality
measurements. No latency, token count or cost is fabricated. The notebook leaves unmeasured
accounting fields as `None`. Reused synthetic drawing rules make this split unsuitable for claims
about real browser rendering, accessibility, actual disabled state, or permission to act.

## Switch to live

Install `.[live]` and configure the key using [the live setup](../../docs/live.md). The full
request set makes exactly **26** calls, one per example, with one Choice and seven image occurrences
per call. The session cache prevents repeats. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or more
for notebook exploration; the default 25 cannot cover the full set, and retries consume attempts.
Direct live exploration stops before held-out metrics. Record first to report a recorded sample.
The versioned model is `jev-1.14.0`, with `images=True` for the experimental image header.

Run the following deliberately from this recipe folder to capture into a new destination,
keeping the committed synthetic fixtures separate:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
requests = [helpers.build_request(example.fields) for example in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=26, max_retries=0)
report = record(
    backend,
    requests,
    Path("recordings/responses.json"),
    ledger_path=Path("recordings/ledger.json"),
)
```

The recorder stores the actual returned model, capture date and reported usage. Unreported usage
stays unknown; latency and cost require independent measured records. After reviewing a complete
recording, explicitly replace the synthetic response file and rerun the notebook. Report only the
recorded model/date and held-out N. See [image handling](../../docs/vision.md) and
[fixture provenance](../../docs/offline-and-live.md).

## Continue

[Sentiment classification](../01-sentiment-classification/) introduces the typed Choice gate;
[tool outcome verification](../29-tool-outcome-verification/) separates a claimed outcome from
verification. Local Codex implementation still requires the repository's integration checks and
Opus review before merge.

## Sources

- S02: [TypeSafe AI: Primitives](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
