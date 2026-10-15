# Screenshot error-state recognition

**Recipe 61 · Level 1 (Beginner) · `Choice` + image**

Recognize a visible crash, loading indicator, authentication failure, normal UI or insufficient
evidence in an application screenshot. The model receives pixels and one fixed question.
Python accepts a classification only when its confidence clears a threshold chosen on validation;
`uncertain` always enters a simulated review queue. This lesson performs no recovery actions.

The authored Northstar UI drawings include sign-in forms with and without rejection messages,
settled empty inboxes beside loading screens, and almost identical crash and promotional overlays.
A help article contains error phrases without being an active error. Cropped and blurred views
test insufficient evidence. These are synthetic examples, not screenshots from a deployed product.

## Run it offline

From the repository root, use Python 3.14 with the notebook constraints:

```bash
pip install -e ".[ml]" -c .github/constraints-notebooks.txt
python recipes/61-screenshot-error-state-recognition/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/61-screenshot-error-state-recognition
python tools/execute_notebook.py recipes/61-screenshot-error-state-recognition
pytest recipes/61-screenshot-error-state-recognition
```

Testing tools are provided by the separate `.[dev]` extra. No key or network is needed for replay.
The generator reproduces all 30 PNGs (640 × 440) using Pillow's embedded font. A recorded response
file requires `--force` to replace it; a refused run preserves its associated image bytes.
The scaffold intentionally regenerates input/label metadata even when response replacement is
refused. Keep your recorded dataset separate before changing authored scenarios or gold labels.

## What it teaches

The notebook displays six unscored examples with their typed probability distributions before
any aggregate. Twelve validation images select the lowest observed confidence threshold that
makes all eligible validation answers correct. The policy is frozen before twelve test images
are evaluated once. If validation cannot qualify a threshold, execution stops before test
evaluation with an explicit message. A confident test mistake remains accepted: a settled empty inbox is labelled
`loading`. Confidence is not a correctness certificate.

The deterministic baseline receives the same image pixels. It counts red error pixels, checks
whether the sidebar is dimmed, and recognizes a blue spinner in a fixed content region. Its
palette/layout constants were checked on validation; it has no OCR or semantic understanding and
always emits a class. It misses skeleton loading and muted session failures, mistakes a red
promotional icon for a crash, and cannot abstain on unreadable views. These are disclosed limits
of a small UI heuristic, not a competitive vision benchmark. The two splits contain different
pixels but share authored layouts; they do not measure generalization to unfamiliar products.

## Switch to live

The notebook makes exactly 30 calls when all examples are requested once. Repeated displays reuse
results by the complete request identity, including image bytes. Set `JEV_COOKBOOK_LIVE=1`,
provide `TYPESAFE_API_KEY` in your environment, and set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=30` or a higher retry allowance. The notebook pins `jev-1.14.0`
and passes `images=True`, enabling the experimental image header. The local session permits at
most 30 distinct requests; the live backend separately counts every network attempt. No live
calls were made for this lesson.

An exploratory live notebook run is not a reportable held-out evaluation. To capture real answers,
use the same request builder with the [recorder](../../docs/live.md#recorder); the example below
belongs in a separate capture session, with an environment-configured key:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(fixtures=Path("fixtures/responses.json"), images=True, model="jev-1.14.0")
if backend.mode != "live":
    raise RuntimeError("Explicit live opt-in is required for capture")
requests = []
for example in load_inputs():
    state, assets = helpers.build_state(example.fields)
    requests.append((state, helpers.build_questions(), assets))
record(backend, requests, Path("capture/responses.json"), ledger_path=Path("capture/ledger.json"))
```

This keeps captured responses separate from synthetic fixtures. The recorder stores actual
returned model, UTC capture date and reported usage. Record inference latency alongside the
capture only if measured, and charges only if known; never substitute replay execution time.
To evaluate a capture, put the reviewed recorded response file in a separate copy of this recipe,
use the original split and policy procedure, and make no prompt changes after viewing test answers.

## What was and was not measured

**Synthetic replay; not measured live.** There are 30 independent requests and 30 authored images:
12 validation, 12 test, and 6 unscored demos. Labels and stored answers are authored separately.
The notebook reports raw classification accuracy, resolved accuracy, coverage and abstention
using actual Python decisions, and compares the deterministic baseline on the same test images.
Every number is a pipeline check, not evidence of Jev quality. Model, capture date, inference
latency, tokens and cost are unknown or inapplicable in this run and remain `None`.

A screenshot establishes visible appearance only. It cannot show how long a spinner has run,
prove that a backend is healthy, or justify clicking a recovery control. Readable text in the
image is evidence, never an instruction to the classifier.

Continue with [sentiment classification](../01-sentiment-classification/) for the same
confidence-gating pattern on text, or [support-ticket triage](../04-support-ticket-routing/)
for a related bounded classification workflow.

## Sources

- S02: [TypeSafe primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
