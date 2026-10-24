# Sports action phase recognition

**Recipe 91 · Level 3 (Intermediate) · Choice**

Classify the phase **at the last timestamp** of one stationary basketball set-shot attempt: preparation, execution, recovery, or unrecognized. Earlier sampled frames establish whether a held ball precedes release or whether lowered hands follow it. Python validates chronology, samples four stills, freezes a validation-selected confidence cutoff, and writes only simulated annotations or review entries.

The original 400 × 320 schematic drawings are synthetic, not athlete photographs. Definitions describe visible poses and order; they make no biomechanics, coaching, injury, or medical claim. The 26 clips contain 182 source PNGs: 12 validation clips, 12 held-out test clips, and two unscored demonstrations. Four frames per clip give 104 selected frame appearances in 26 requests. Cases include mirror views, camera translation, occlusion, waving without a ball, misleading scene text, mixed phases, and a reset after release.

## Run offline

From the repository root with the development dependencies installed:

```bash
python recipes/91-sports-action-phase-recognition/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/91-sports-action-phase-recognition
python tools/execute_notebook.py recipes/91-sports-action-phase-recognition
pytest recipes/91-sports-action-phase-recognition -q
```

Reproducing committed notebook outputs requires Python 3.14 and the versions in
[constraints-notebooks.txt](../../.github/constraints-notebooks.txt). Run
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` in your own environment.
The generator is deterministic and protects recorded responses unless `--force` is explicit.
PNG assets are outside the strict `fixtures/` folder. Gold labels include readable reasons;
only opaque image references, timestamps, and the fixed task enter inference.

## What was and was not measured

**Synthetic replay; not measured live.** The confidence policy chooses maximum validation coverage subject to perfect accepted validation accuracy, among observed confidence cutoffs for recognized answers. It freezes at 0.7600 before test evaluation. `unrecognized` always enters review and never counts as an accepted annotation. If no validation cutoff meets the objective, the frozen policy defers every window.

On the **12 synthetic test windows**, the Choice policy's raw four-way event accuracy is 9/12. It accepts 8/12 windows, with accepted event accuracy 7/8 and abstention 4/12. The deterministic ball/hand pixel-centroid baseline reads the same selected images: raw event accuracy 11/12, accepted event accuracy 8/9, and abstention 3/12. These are pipeline checks, not Jev results or a model comparison. The confident accepted mistake is a reset after release labelled preparation. All events are scored per window, not per frame.

No inference latency, API tokens, or billing were measured; accounting values remain `None`. Exact color segmentation is suited only to these illustrations. Shared rendering grammar and a tiny sample do not support real-world generalization. No decoded frame is shared across scored splits. Sampling can miss brief intermediate motion; the lesson does not detect every event inside a window.

## Switch to live

The notebook's `get_backend(..., images=True, model="jev-1.14.0")` uses the same request builder in every mode. Interactive live mode needs the opt-ins in the [live guide](../../docs/live.md), performs the two demos plus 12 validation calls, and suppresses held-out reporting until responses are recorded. The offline executor always strips live configuration.

A complete fresh recording makes exactly **26** calls before retries, one per window.
To capture all 26 windows deliberately, run this from the recipe directory after configuring your own credentials as described in that guide. It writes to a new `capture/` tree, leaving the synthetic fixtures available. A 36-attempt backend budget gives limited room for retries; each retry consumes budget, so partial capture is possible. The local recorder deduplicates identical requests and can resume an incomplete capture. No live calls were made for this recipe.

```python
from pathlib import Path
from shutil import copy2, copytree
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
capture = Path("capture")
(capture / "fixtures").mkdir(parents=True, exist_ok=True)
copytree("assets", capture / "assets", dirs_exist_ok=True)
for name in ("helpers.py", "notebook.ipynb"):
    copy2(name, capture / name)
for name in ("inputs.jsonl", "labels.jsonl"):
    copy2(Path("fixtures") / name, capture / "fixtures" / name)
requests = [helpers.build_request(e.fields) for e in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=36)
report = record(
    backend,
    requests,
    capture / "fixtures" / "responses.json",
    ledger_path=capture / "capture-ledger.json",
)
```

`build_request` returns `(state, questions, assets)` triples. The recorder retains the actual returned model, UTC date, and available usage. Its sidecar stores request metadata outside `fixtures/`; neither it nor replay duration invents latency or billing. Execute the copied notebook offline after a complete capture to evaluate recorded answers. New policy experiments need a new held-out set.

[Notebook](notebook.ipynb) · [Sentiment classification](../01-sentiment-classification/) · [Image and frame helpers](../../docs/vision.md)

## Sources

- S02: [Decision primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
