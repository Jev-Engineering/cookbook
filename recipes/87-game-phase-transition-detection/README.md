# Game phase transition detection

**Recipe 87** · Level 3 (Intermediate) · Decision type: `Choice`

Recognize transitions between combat, menus, map selection, and rewards from ordered game
screenshots while Python records the phase history and handles uncertain transitions.

## What it teaches

Batch three independent foreground-phase judgments in one image request. Python chooses chronological
frames, derives the ordered event path, checks an allowed transition graph, and gates simulated
history updates with a threshold selected only on validation. An intermediate menu survives a
combat → menu → combat round trip. Unknown phases, capture problems and forbidden jumps go to a
`ReviewQueue`; accepted histories go to an `ActionLog` with `executed=False`.

The **Lantern Trail** screenshots are original synthetic interface drawings, not captures from an
actual proprietary game. The 92 PNG images are authored by `build_fixtures.py`, with scene details
varied independently for each clip. A fixed background-color pixel baseline runs on the same frames.
Alternate themes, text distractors, an incomplete fade, a shop, unexpected transitions, stale
captures, reversed/duplicate timestamps and sparse samples exercise failure paths.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python recipes/87-game-phase-transition-detection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/87-game-phase-transition-detection
python tools/execute_notebook.py recipes/87-game-phase-transition-detection
pytest recipes/87-game-phase-transition-detection
```

The notebook runs without a key or network. To reproduce committed outputs, use Python 3.14 with
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. The generator reproduces images,
inputs, gold labels and authored responses. It refuses to replace recorded responses without
`--force`; inputs, labels and assets are regenerated even on refusal, so review any resulting
request-key changes before recording missing answers.

## Switch to live

Live calls are opt-in. Install the image-capable SDK through `pip install -e ".[live]"`, set
`TYPESAFE_API_KEY` and `JEV_COOKBOOK_LIVE=1` in the environment, and open the notebook from this
folder in Jupyter. The setup uses the same questions with `images=True` and pinned
`model="jev-1.14.0"`. The experimental image capability uses extracted stills, not native video.
The executor always clears live settings and runs offline.

The notebook makes exactly **24** requests without retries: 11 validation clips, 11 test clips
and two demos. Each request batches three questions over three images (72 phase judgments).
Six clips fail capture checks before any call. The local reader caps logical requests at 24;
the backend separately counts transport attempts. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=48` for
retry headroom, or keep the default 25 to stop sooner. All retries spend that backend budget.

An unrecorded live notebook is exploration and suppresses held-out metrics. For reportable evidence,
record the same requests first using [the recorder](../../docs/live.md#recorder). This snippet runs
only when deliberately executed with live settings and a key; no call was made for this recipe:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
examples = load_inputs()
backend = get_backend(fixtures=Path("fixtures/responses.json"), images=True, model="jev-1.14.0")
if backend.mode != "live":
    raise RuntimeError("Recording requires deliberate live opt-in")
triples = [
    helpers.build_request(e.fields, Path("."))
    for e in examples
    if helpers.preflight(e.fields) is None
]
Path("recordings").mkdir(exist_ok=True)
report = record(
    backend,
    triples,
    Path("recordings/responses.json"),
    ledger_path=Path("recordings/ledger.json"),
)
```

Use a separate recording file to preserve the committed synthetic fixture. After a deliberate
recording is complete, validate and replay those responses with the same inputs and questions.
The recorder retains the actual returned model, capture date and usage; the optional ledger stores
request metadata outside `fixtures/`. Record actual inference timing or charges separately if
needed; this recipe neither infers billing nor substitutes replay time for inference latency.

## What was and was not measured

**Not measured live.** The committed run is synthetic: 14 validation clips, 14 held-out test clips
and two unscored demos. Event accuracy covers the 11 test clips with valid capture metadata;
policy coverage and review use all 14. Frame diagnostics cover 33 judgments from those 11 clips.
These are pipeline checks, not Jev quality claims. Inference latency, token usage and cost are
unknown (`None`). The notebook prints the relevant N beside each aggregate.

Validation maximizes accepted count subject to perfect event accuracy, choosing among the distinct
minimum frame confidences of structurally eligible clips. The resulting threshold is frozen before
test. One confidently wrong test transition is accepted deliberately: a graph can permit both the
true and mistaken event. Review is never counted as coverage. The baseline uses fixed pixel colors
and the same sampling/graph rules, without a confidence threshold or any gold-label access.

The sample shares one invented game's drawing vocabulary. Independent pixels and seeds across
splits prevent exact image reuse, not domain bias. Selected frames can miss short events, and the
one-second freshness rule and allowed graph are explicit assumptions that need revisiting for a
real capture pipeline. A recorded sample would describe only its returned model, capture dates and
held-out clips, with no broader claim.

## Next steps

Use the [confidence-gating lesson](../01-sentiment-classification/) or
[failure recovery selection](../43-failure-recovery-selection/) for related bounded decisions.
The [vision helpers](../../docs/vision.md) explain image identity and timestamped frame loading.

## Sources

- S02: [Decision primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
