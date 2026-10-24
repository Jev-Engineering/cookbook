# Long-form visual evidence audit

Recipe 94 · Advanced · `Noul` · Images and opt-in long context

Audit one bounded claim against a complete maintenance history and historical/current inspection
images. Four independent Noul propositions separate visible support and contradiction from written
support and contradiction. Python checks source identity and dates, freezes a validation-selected
certainty gate, and writes a simulated audit entry or review item. `image_supported`, `report_only`,
`contradicted`, and `unknown` remain distinct; unknown is review, never resolved coverage.

The 26 independently identified synthetic cases include 52 inspection drawings and 26 extended
44-entry histories. Each history places an archived fault near the beginning and a current sign-off
at the end, separated by substantive maintenance records. Cases cover hidden internal service,
removed and partially fitted guards, an obscuring cloth, dry/wet trays, a blue tool, conflicting
same-day statements, copied instructions, wrong equipment, stale/future photos, and unknown sources.
The drawings are authored examples, not real photographs. The fixture builder keeps drawing states
and gold rationales out of inference; `assets/history-*.json` contains the complete readable reports.

## Run it offline

Use Python 3.14 with the repository's notebook constraints to reproduce committed figures:

```bash
pip install -e '.[ml]' -c .github/constraints-notebooks.txt
python recipes/94-long-form-visual-evidence-audit/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/94-long-form-visual-evidence-audit
python -m pytest recipes/94-long-form-visual-evidence-audit -q
python tools/execute_notebook.py recipes/94-long-form-visual-evidence-audit
```

The executor removes live settings and credentials from its kernel. Generation is deterministic.
A recorded `responses.json` cannot be replaced without `--force`; inputs and labels are rebuilt
even on refusal. The generator never performs inference.

## Switch to live

Not measured live. Install the optional live dependencies and use your own environment credentials
as described in [live.md](../../docs/live.md). Set `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=26` or higher before interactive execution. The notebook pins
`model="jev-1.14.0"`, `images=True`, and `long_context=True`. The flags enable two separate headers:
`TypeSafe-Danger-Zone-Images: true` and `TypeSafe-Danger-Zone-Long-Context: true`.
These capabilities are experimental; the flags alone establish no measurement.

This notebook makes exactly **26** calls, one per case with four independent questions batched.
Its local budget stops at 26 and duplicate case calls are rejected. The transport counts retries
against its separate attempt budget; the default transport budget of 25 is insufficient.
No credential belongs in a notebook or source file.

For an intentional capture, the same request triples work with the shared recorder (run from this
recipe directory after explicitly configuring live mode). Keep the capture outside the synthetic
fixtures until its provenance, usage, and frozen held-out protocol have been reviewed:

```python
from pathlib import Path
from jev_cookbook import get_backend, load_helpers, record
from jev_cookbook.fixtures import load_inputs, responses_path

helpers = load_helpers()
backend = get_backend(fixtures=responses_path(), model="jev-1.14.0", images=True, long_context=True)
requests = [helpers.build_request(e.fields) for e in load_inputs()]
record(
    backend, requests, Path("recordings/responses.json"), ledger_path=Path("recordings/calls.json")
)
```

`record` requires a live backend and stores actual returned model, capture date, and usage.
Keep unreported usage, latency, and charges null; the recipe does not time replay as inference.
A live notebook run without recording is exploration, not a reportable held-out result.

## What was and was not measured

The committed run is synthetic: 12 validation, 12 held-out test, and 2 unscored demonstration
cases. No model generated these answers. The candidate gates are observed minimum Noul certainties;
validation chooses maximum accuracy with at least 75% coverage among structurally eligible cases.
The selected gate is 0.82. Total coverage uses the actual policy's accepted flags, including all
source, timestamp, conflict, and unknown review branches.

Synthetic test pipeline checks (N=12): full-report audit category accuracy 11/12, accepted 8/12,
accepted accuracy 7/8, and 4 reviews. The frozen policy deliberately accepts the wrong `t11`
judgment. A real lexical top-two retrieval plus pixel-region baseline has category accuracy 8/12,
accepted 9/12, accepted accuracy 5/9, and 3 reviews on the same inputs. Its color and negation
failures are explained in the notebook. These are pipeline checks, not Jev quality results.

Reports contain over 4,000 body words each; the notebook prints exact local word and character
ranges. These are not token counts. Input/output tokens, inference latency, cost, and synthetic
model identity remain `None`. This is not a 262K-token measurement. No real photograph evaluation,
authenticity verification, maintenance compliance decision, or safety guarantee is claimed.

The snapshot policy admits only this asset's report observations on the audit date and current
photos at most two days old, published by the cutoff. It preserves source identifiers but does
not localize exact supporting spans. Real installations need a justified retention window and
verified source manifests. All logged actions remain simulated.

Only this recipe folder is built locally. Catalog integration and genuine Opus review remain
pending; Codex implementation is not Opus approval. See [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
