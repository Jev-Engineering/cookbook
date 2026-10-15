# Technical schematic recognition

**Recipe 66 · Level 2 (Easy) · `Choice` + image**

Recognize one symbol in a supplied schematic crop using an explicit teaching legend:
zigzag resistor, parallel-plate capacitor, single-lead terminal, open switch,
dotted junction, or undotted crossing. `none` means a clear unlisted shape;
`uncertain` means insufficient visible evidence. Both go to human review.
This is diagram recognition, not circuit analysis or engineering certification.
The crossing convention belongs to this authored legend, not every drawing standard.

Python builds fixed options, validates confidence, freezes a threshold on validation,
and records accepted proposals in an in-memory `ActionLog`. Every action is simulated.
The notebook compares the actual accept/review outcomes with a deterministic ink-template
baseline on identical crops, shows a confidently wrong accepted answer, and reports
raw accuracy, accepted accuracy, coverage, abstention and a confusion matrix.

## Run offline

From the repository root, use the notebook stack pinned by
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14), with
pytest and ruff available for development:

```bash
python recipes/66-technical-schematic-recognition/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/66-technical-schematic-recognition
python tools/execute_notebook.py recipes/66-technical-schematic-recognition
pytest recipes/66-technical-schematic-recognition
```

The generator writes 30 independent synthetic crops and six legend templates, all
384 × 320 PNGs. It uniformly resizes 480 × 400 crops, preserving proportions.
Images live in `assets/`; fixtures contain paths, labels and typed responses, never
base64 data. `ROWS` exposes drawing parameters and authored labels for inspection,
but only pixels and the teaching legend reach inference. The six baseline templates
are separate images from every query. All drawings use the same small set of authored
primitives, so independent files are not evidence of real-world generalization.

## Evaluation and limits

**Not measured live.** There are 14 validation and 14 test examples, plus two unscored
demos. All responses are synthetic and intentionally imperfect. The 30 stored responses
check the pipeline, not Jev quality. Unknown model, tokens, latency and cost stay `None`.
No timing of replay is reported as inference latency.

Each classifier selects its own lowest observed score threshold that gives perfect
accepted validation accuracy, then freezes it before test. `none` and `uncertain`
are excluded from selection and count as review in the full-denominator evaluation.
The baseline's score is ink-mask intersection-over-union, not model confidence. It
normalizes tight ink bounds onto a padded 96 × 96 grid and tests four quarter-turn
rotations. Both use the same crop; the baseline only recognizes blank paper as `none`
and otherwise relies on its gate to reject unfamiliar shapes.

Fixtures cover rotated and heavy strokes, crossed wires versus dotted junctions,
a partly cut zigzag body, an obscured intersection, unlisted shapes, blank paper,
and a misleading image annotation. A confidently wrong test answer survives the
frozen gate. Recognition must not authorize electrical operation, design approval,
or a claim about circuit-wide connectivity.

## Switch to live

Install the optional SDK with `pip install -e ".[live]"`. For exploratory notebook
runs set `JEV_COOKBOOK_LIVE=1`, `TYPESAFE_API_KEY`, and
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=30` or higher. The notebook explicitly requests
`jev-1.14.0` with `images=True`; the question definitions stay unchanged.
In live mode this notebook makes exactly one call for each of the 30 examples,
and no other; the cache reuses repeated displays. Its local cap is 30 distinct
calls, while the backend's HTTP budget also counts retries. Budget or inference
errors stop the run. The offline executor never enables live mode.

Unrecorded live exploration is not a reportable held-out result. To record intentionally,
run the following from this recipe folder with the live opt-in and key configured:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
backend = get_backend(images=True, model="jev-1.14.0")
questions = helpers.build_questions()
requests = []
for example in load_inputs():
    state, assets = helpers.build_state(example.fields)
    requests.append((state, questions, assets))
record(
    backend,
    requests,
    Path("capture/responses.json"),
    ledger_path=Path("capture/ledger.json"),
)
```

The capture uses a separate destination so synthetic fixtures cannot mix with recorded
responses. The recorder preserves the actual returned model, date and token usage;
the ledger preserves request identifiers. A later deliberate fixture replacement can
replay the recording with the same inputs and questions. See [live.md](../../docs/live.md)
for capture and budget details. `build_fixtures.py` refuses to overwrite recorded
responses without `--force`; inputs, labels and assets are still regenerated, so check
replay keys after changing drawing definitions. Do not commit keys or private captures.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
