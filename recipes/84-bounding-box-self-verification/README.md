# Bounding-box self-verification

**Recipe 84 · Level 4 (Advanced) · `Box` + `Noul`**

Propose a complete crop of a bench clamp: check presence and uniqueness, localize, batch four independent
edge judgments, expand flagged sides, then reevaluate the crop. Python limits every path to
six requests and two adjustments, with area and image-boundary interlocks. A successful
self-check is still an unverified prediction. The notebook preserves confident accepted failures.

## Run it offline

From the repository root, with the development environment installed:

```bash
python recipes/84-bounding-box-self-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/84-bounding-box-self-verification
python tools/execute_notebook.py recipes/84-bounding-box-self-verification
pytest recipes/84-bounding-box-self-verification
```

Offline execution needs no network or key. To reproduce committed outputs use Python 3.14 and
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`; development tests use `.[dev]`.
The generator refuses to replace recorded responses without `--force`. It always rebuilds authored
inputs, labels and images. `assets/` contains 26 original synthetic PNG scenes, each 480 × 360.
Runtime crops are made from the candidate pixels, scaled with preserved aspect ratio, and
letterboxed to 480 × 360. Gold geometry never enters a request.

## Switch to live

The committed replay makes exactly **85 requests**, after caching duplicate validation paths.
That count describes these synthetic paths. Live answers can change the path: the upper bound
is **156 application requests** (26 × 6), plus any backend retry attempts. Install `.[live]`, set
`JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`, and your own `TYPESAFE_API_KEY`
in the environment. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=156` or an explicitly budgeted higher
attempt limit if retries are allowed; the default 25 can stop this run early. Open the notebook
in Jupyter; the executor deliberately always runs offline. The setup uses `images=True`.
Never commit a key. Experimental images and Box are documented in S09–S12 below.

For a new recording, wrap one opted-in backend before the notebook makes its first decision:

```python
from jev_cookbook import get_backend

backend = get_backend(fixtures="fixtures/responses.json", images=True, model="jev-1.14.0")
capture = helpers.RecordingBackend(backend, "capture/responses.json")
cached = helpers.CachedBackend(capture)
```

Create the `capture/` directory first. This optional wrapper uses shared `record` on each actual
`(state, questions, assets)` triple, so later crops follow the newly returned coordinates. It
captures the returned model, date and usage fields without storing image base64. Preserve the
exact source/crop lineage and actual observed request keys when preparing a new recorded fixture
set; synthetic paths may differ. The fixture generator intentionally authors synthetic responses,
so do not use it to promote a recording. See [live recording](../../docs/live.md#recorder).
No inference timing or billing is measured by this wrapper. Leave unknown latency/cost null;
unrecorded exploration is not a reportable held-out result.

## What was and was not measured

**Synthetic; not measured live.** N = 12 validation + 12 test, with 2 unscored demonstrations.
Every number is a pipeline check, not a Jev result. Validation selects one shared confidence gate
from completed paths with `target_accuracy=1.0`; structural reviews remain reviews. It freezes
at 0.83 before test. The fixed correctness rule requires complete enclosure and IoU ≥ 0.60.
The held-out policy resolves 9/12, with accepted accuracy 6/9. It still accepts one clipped
clamp, one false detection on an absent image, and one false absence. Three cases go to review.
All figures here describe synthetic fixtures only.

The notebook compares initial/final IoU and clipping on the same accepted present targets,
reports missed targets, absent-image false positives, and review counts separately, and compares
with a real magenta-pixel baseline on the same source images. Ambiguous multiple-target scenes
are excluded from localization denominators and their acceptance is separately counted. A
color baseline can miss the screw and steel parts; self-checks can share the locator's mistake.
These drawings do not establish photographic performance, calibration or production safety.
Token counts, inference latency and cost remain unknown. Crop actions are simulated only.

This local Codex implementation still requires genuine Opus review and integration checks before
merge. The root catalog README is reserved for the integration worker; this recipe does not edit it.
See [the contribution contract](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S10: [TypeSafe AI: Box](https://docs.typesafe.ai/primitives/box)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
