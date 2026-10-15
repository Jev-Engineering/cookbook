# Manufacturing defect inspection

**Recipe 63** · Level 3 (Intermediate) · Decision types: `Noul`, `Score`

Build an inspection report for a synthetic front panel: four independent defect judgments,
visibility, and a four-level severity rubric. Python combines these into a simulated inspection
note or an explicit review outcome. Nothing controls equipment, rejects a physical part, or
certifies a product. The 480 × 360 images are controlled drawings, **not real photographs**;
this lesson provides no industrial qualification.

The notebook shows the approved reference and two examples before evaluation. It compares the
stored answers with a deterministic pixel/template discrepancy baseline using the same images
and inspection specification. Normal seams, shadows, lighting changes, faint marks, covered
components, mixed defects, reversed connectors, and an instruction-like sticker exercise distinct
failure modes. One accepted held-out response invents a scratch from a shadow; another understates
a broad gouge's severity. A confident answer can be wrong.

## Run offline

From the repository root, after the normal [development setup](../../docs/development.md):

```bash
python recipes/63-manufacturing-defect-inspection/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/63-manufacturing-defect-inspection
python tools/execute_notebook.py recipes/63-manufacturing-defect-inspection
pytest recipes/63-manufacturing-defect-inspection
```

The notebook needs no key or network. To reproduce committed figures, use Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. The generator recreates all 27 PNGs,
26 inputs, 24 labels and 26 synthetic responses. It refuses to overwrite recorded responses unless
`--force` is explicit. Image bytes bind each replay key; labels, split names and drawing parameters
never enter a request. Query pixels are distinct across validation and test; the fixed approved
reference is intentionally shared.

## What was and was not measured

**Synthetic pipeline checks; not measured live.** There are 12 validation and 12 test examples,
plus 2 unscored demos. Validation chooses the joint certainty threshold from
`(0, 0.4, 0.6, 0.8, 1)` by maximum coverage subject to zero accepted validation errors; the actual
inspection rule includes visibility and consistency checks. A separate validation grid chooses
the pixel-baseline multiplier by complete disposition accuracy. Its fixed scratch-area cutoff of 3 separates fine from broad
marks in validation; that cutoff is frozen with the multiplier. Both are frozen before the
12-example test report. Per-label denominators omit unknown gold values; severity uses the 10 test
panels with a defined ordinal level. Review counts toward review, never resolved coverage.

The baseline subtracts median lighting shift and compares fixed surface/component regions against
the approved template. It is intentionally simple: a displaced panel or shadow can resemble damage,
and its fixed surface descriptors do not infer depth. Both systems receive only the front view,
so hidden or internal faults are outside scope. No fixture metric measures real Jev quality.
Model, date, inference latency, tokens and cost are unknown for this synthetic run and remain null.

## Switch to live

The same six questions run with `get_backend(..., images=True, model="jev-1.14.0")`.
The full recording workflow makes exactly **26** calls before retries, one per distinct image pair.
The notebook's unrecorded live preview makes two demo calls, caches them, and stops before
selection or reporting; use the recorder below to capture the full evaluation. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or a larger explicit retry allowance;
the recipe also caps distinct requests at 26. Use the opt-in and credential handling in
[the live guide](../../docs/live.md). An unrecorded live exploration is not a reportable held-out
result, and the notebook refuses its evaluation section.

For an intentional capture, use a fresh output location and the same request triples; do not run
this during offline execution:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

folder = Path("recipes/63-manufacturing-defect-inspection")
helpers = load_helpers(folder)
requests = [helpers.build_request(e.fields, folder) for e in load_inputs(folder)]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=30)
report = record(
    backend, requests, Path("capture63/responses.json"), ledger_path=Path("capture63/ledger.json")
)
```

The recorder preserves the actual returned model, capture date and reported usage. Archive the
synthetic response file before deliberately promoting a complete validated recording into
`fixtures/responses.json`; do not mix synthetic and recorded provenance. `run_record` leaves
latency and cost null unless separately captured from actual inference/charges. Reuse the frozen
policy and an untouched held-out sample for any subsequent model claim.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)

Continue with [semantic feature extraction](../35-semantic-feature-extraction/) for independent
labels and [response clarity scoring](../03-response-clarity-scoring/) for ordinal rubrics.
