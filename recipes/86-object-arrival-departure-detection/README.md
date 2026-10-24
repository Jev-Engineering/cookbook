# Object arrival/departure detection

**Recipe 86** · Level 2 (Easy) · Decision type: `Choice`

Classify the visible history of a blue-taped parcel across ordered timestamped stills.
Python checks sampling, brightness and a fixed camera reference before inference, then gates
resolved answers and simulates observation notes. `uncertain` always goes to review. An apparent
arrival or departure is a visibility change in the samples, not proof of delivery, removal or theft.

The 26 authored clips contain 78 synthetic Pillow drawings (480 × 360): 12 validation, 12 test,
and two unscored demos. Hard cases include moving distractors, a brown crate, a blue ball,
partial observation through occlusion, camera shift, darkness, wide sampling gaps, an object
that returns between endpoints, and a transient object visible only in the middle frame.
A tan-pixel occupancy baseline reads the same ordered images without gold labels or metadata.

## Run it offline

From the repository root:

```bash
python recipes/86-object-arrival-departure-detection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/86-object-arrival-departure-detection
python tools/execute_notebook.py recipes/86-object-arrival-departure-detection
pytest recipes/86-object-arrival-departure-detection -q
```

The notebook needs no key or network. Reproducing committed outputs uses Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`; development tests use `.[dev]`.
The generator rebuilds images and labels deterministically; it refuses to overwrite recorded
responses without `--force`. Tests pin the generator, image-aware keys, timestamp and request
stops, actual routing, the validation objective and a wrong test answer accepted by the frozen gate.

## Policy and measurements

**Not measured live.** All committed answers are synthetic; every metric is a pipeline check,
not a Jev quality result. Sampling limits (three or four frames, gaps ≤2 seconds, span ≤4 seconds),
camera checks and baseline pixel thresholds are fixed before evaluation. Among eligible resolved
validation answers, select the lowest observed confidence attaining accuracy 1.0, then freeze it.
Report test once using actual accept/review outcomes. An accepted wrong brown-crate answer shows
why confidence cannot guarantee correct identity. Model, capture date, tokens, inference latency
and cost are unknown for this synthetic run; accounting uses `None`.

Occlusion and multiple transitions remain uncertainty. The empty wall reference is a local camera
assumption; the checks do not detect every shifted or blurred image. Between-frame events are
unobservable. The task does not identify who moved an object or establish a physical event.

## Switch to live or record for offline replay

Install `.[live]`, set `TYPESAFE_API_KEY` privately and `JEV_COOKBOOK_LIVE=1`, then open the notebook
from its folder. The notebook pins `jev-1.14.0` and `images=True`; those experimental image calls
use the same question and pixels as replay. This notebook makes exactly **20 requests** on the
committed inputs: nine eligible clips in each scored split plus two demos. Six quality-blocked
clips spend no requests. Cached demonstrations are not requested again. The local request cap is
20; `JEV_COOKBOOK_LIVE_MAX_REQUESTS` also caps transport attempts (default 25), including retries.
Unrecorded exploration is not a reportable held-out result.

For a deliberate recording, run this from the recipe folder with a privately configured key. It
writes into a separate empty capture directory so synthetic and recorded responses cannot mix:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
root = Path.cwd()
triples = []
for example in load_inputs():
    prepared = helpers.prepare(example.fields, root)
    if not prepared.issues:
        triples.append((prepared.state, helpers.build_questions(), prepared.assets))
capture = Path("capture")
capture.mkdir(exist_ok=True)
backend = LiveBackend("jev-1.14.0", images=True, max_requests=20, max_retries=0)
report = record(
    backend,
    triples,
    capture / "responses.json",
    ledger_path=capture / "request-ledger.json",
)
print(report)
```

After a complete capture, preserve the synthetic file separately and replace only
`fixtures/responses.json` with the captured responses. Validate fixtures and re-execute offline.
Select the recorded validation gate before reading recorded test outcomes; the synthetic gate is
not a measured calibration. The recorder stores actual returned model, capture dates and usage.
The request ledger stays outside `fixtures/`; it does not supply inference timing or billing, so
those fields remain `None` unless separately measured during capture. Do not commit keys, raw
request bodies or base64 assets. See [the live recorder](../../docs/live.md) for partial captures,
conflicts and retries, and [image helpers](../../docs/vision.md) for image byte validation.

## Next steps

[Sentiment classification](../01-sentiment-classification/) introduces the frozen gate;
[Tool outcome verification](../29-tool-outcome-verification/) limits claims to evidence;
[Abstention and review queues](../38-abstention-and-review-queues/) shows review accounting.
Local implementation and checks are not Opus approval; integration and genuine review remain pending.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
