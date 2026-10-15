# Field maintenance photo triage

**Recipe 64 · Level 3 (Intermediate) · Choice + Noul**

Classify visible equipment conditions while preserving coexisting corrosion, leakage, and disconnected
cabling. Five independent questions share one image request. Python requires visibility, consistent
evidence, a validation-selected confidence gate, and a proposal interlock before logging a fixed
simulated visual follow-up. Mixed and unclear cases enter a review queue; no equipment is operated,
repaired, or cleared for use. `normal` means no specified condition is visible.

The 26 PNG assets are labelled **synthetic equipment drawings, not actual photographs**. Twelve
validation examples select the policy, twelve test examples report held-out pipeline behavior,
and two demonstrations show typed answers and simulated logs. Fixtures include smooth rust-colored
paint, floor shadows, isolated wet marks, coexisting conditions, and a covered assembly. A deliberately
confident paint/corrosion mistake survives the frozen policy. A deterministic color/continuity baseline
uses the same pixels and category vocabulary without labels, drawing specifications, or stored answers.

## Run it offline

From the repository root with the development dependencies installed:

```bash
python recipes/64-field-maintenance-photo-triage/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/64-field-maintenance-photo-triage
pytest recipes/64-field-maintenance-photo-triage
python tools/execute_notebook.py recipes/64-field-maintenance-photo-triage
```

Reproduce committed outputs using Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`.
The generator recreates the drawings and fixture JSON; it refuses to replace recorded responses
without `--force`. Tests cover arbitrary-answer interlocks, mixed conditions, request limits, image
identity, pixel/label isolation, fixture reproducibility, and a wrong accepted test answer.

## Switch to live

Install `.[live]`, provide `TYPESAFE_API_KEY` in the environment, and explicitly opt in with
`JEV_COOKBOOK_LIVE=1`. The code pins `jev-1.14.0` with `images=True`, enabling the experimental image
header. Raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least 26; the default is 25, and retries consume
additional attempts. The full recorded/offline path makes exactly **26** calls, one per image, with
five batched questions per call. Direct unrecorded notebook exploration stops after its 14 demo and
validation calls, before held-out reporting. The executor itself always runs offline.

To deliberately record the full set, use the same requests and a separate empty destination, then
inspect the returned model/date and usage before adopting those recordings. From the recipe folder:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
triples = [helpers.build_request(e.fields) for e in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=32)
report = record(
    backend,
    triples,
    Path("capture/responses.json"),
    ledger_path=Path("capture/request-ledger.json"),
)
```

`record` stores actual returned model, capture date and reported usage. The ledger preserves request
identifiers and attempts; it does not measure latency or billing. Capture those separately if needed.
See [live recording](../../docs/live.md#recorder) and [image assets](../../docs/vision.md).

## What was and was not measured

**Synthetic replay; not measured live.** N=12 validation, N=12 test, plus 2 unscored demonstrations.
The notebook reports raw classification, independent condition accuracy on adequately visible cases,
visibility accuracy, coverage, abstention and error rate among accepted outcomes. Review never counts
as coverage. All reported values are pipeline checks, not Jev quality results. Model, date, latency,
tokens and cost are unknown or inapplicable and are left null. The controlled drawings are unsuitable
for claims about field photograph performance; the accepted error demonstrates why confidence is not
a safety guarantee.

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
