# Image-grounded bug report verification

**Recipe 93** · Level 3 (Intermediate) · Decision type: `Noul`

Verify two screenshot claims in a draft-save bug report alongside logs and expected behavior.
Four independent propositions share one request: current save error visible, expected Saved marker
missing, failure explicitly supported by logs, and expected page visible. Python checks exact
build/run/time association and routes coherent evidence to `supported` or `not_supported`; uncertain,
incomplete and contradictory evidence enters a simulated human review queue.

All screenshots are authored synthetic drawings. “Supported” describes supplied symptom evidence,
not root cause, reproducibility, an exploitable defect, or permission to execute report text.
`ActionLog` annotations remain `executed=False`; nothing updates an external ticket.

## Run offline

From the repository root, using the pinned notebook environment in
[development](../../docs/development.md):

```bash
python recipes/93-image-grounded-bug-report-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/93-image-grounded-bug-report-verification
python tools/execute_notebook.py recipes/93-image-grounded-bug-report-verification
python -m pytest recipes/93-image-grounded-bug-report-verification -q
```

The notebook loads image bytes from `assets/`; gold labels and drawing instructions never enter
inference. An unchanged request is cached by its image-bound replay key. The recipe budget stops
at 26 requests, with four Noul judgments per request. Stored answers include deliberate mistakes.
The generator refuses to overwrite recorded or malformed responses without explicit `--force`.

## What the comparison teaches

A validation-only policy selects the lowest derived Noul certainty meeting 95% pooled claim
accuracy. The candidate family is the observed validation certainties, and the resulting threshold
is frozen before test. This is a claim-level selection objective, not a report-level guarantee.
The final report metrics use the routing rule's actual acceptance flags through `evaluate_outcomes`.
Review always counts as abstention.

The baseline reads screenshot pixels in known banner/confirmation rectangles and explicit log
codes. Fixed red and green thresholds provide a useful stable-layout check; it cannot distinguish
red help text or read a page title. It sees the same inputs and hard metadata interlocks as the Noul
pipeline. Tests mutate pixels, text and irrelevant labels to verify those boundaries.

The fixtures cover amber errors, benign red help, wrong pages, mismatched build/run identity,
stale or late screenshots, old-build logs, log-only failures, contradictory status indicators,
waiting states and instructions embedded in descriptions. One confident held-out wrong-page answer
passes the frozen policy; the notebook displays it after reporting the test metrics.

## What was and was not measured

**Not measured live.** The committed notebook is a synthetic pipeline check, not a Jev benchmark.
There are 12 validation and 12 test reports (48 claims per split), two unscored demos, and 26 PNG
images of 480 × 360 pixels. The notebook makes exactly **26** calls, one unique image request per example, with 104 Noul judgments.
Model, capture date, input/output tokens, inference latency and cost are unknown, represented by
`None`. No replay timing is reported as model latency.

The manifest is assumed trusted; digest binding does not authenticate its timestamps or build.
One screenshot cannot establish causality or persistence. Evidence is correlated across questions,
and the narrow authored UI does not represent unseen products, layouts or adversarial security.

## Switch to live

The notebook makes exactly **26** calls with the same questions. For an intentional live run, install the optional live dependency,
set `JEV_COOKBOOK_LIVE=1` and supply `TYPESAFE_API_KEY` through your environment. Never put a key in a
notebook. For direct interactive notebook use, also set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26`
(the backend default is 25; retries consume that budget). The following opt-in command creates a **new directory outside the recipe**:

```bash
python recipes/93-image-grounded-bug-report-verification/capture.py --output /tmp/bug-evidence-recorded
python -m jev_cookbook.fixtures validate /tmp/bug-evidence-recorded
python tools/execute_notebook.py /tmp/bug-evidence-recorded
```

`capture.py` pins `jev-1.14.0`, enables experimental images, caps attempts at 26 and disables retries.
It uses `record(backend, triples, ...)`, preserving returned model/date/usage, an external-to-fixtures
request ledger and measured call durations. Billing remains null. Existing output directories are
refused. The copied notebook reads recorded responses offline and prints the actual model, dates
and sample N. Direct interactive live exploration suppresses held-out metrics until recorded.
No live inference was performed to build this recipe.

See [image helpers](../../docs/vision.md), [offline/live](../../docs/offline-and-live.md),
[recording](../../docs/live.md), and the executed notebook for request and evidence details.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
