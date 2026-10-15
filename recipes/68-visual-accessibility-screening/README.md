# Visual accessibility screening

**Recipe 68** · Level 3 (Intermediate) · Decision type: `Noul`

Screen an authored UI screenshot for apparent text clipping, low contrast, crowding, and overlapping controls. Four independent probabilities become a candidate set; a fifth readability judgment can defer the screenshot. Python owns exact contrast arithmetic, per-flag certainty thresholds, request limits, and the simulated review queue.

**Screenshots cannot certify accessibility, semantics, keyboard access, accessible names, focus behavior, or standards compliance.** An accepted empty set means no apparent candidate among these four questions. Nothing edits a DOM or changes an interface.

## Run it offline

From the repository root:

```bash
python recipes/68-visual-accessibility-screening/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/68-visual-accessibility-screening
python tools/execute_notebook.py recipes/68-visual-accessibility-screening
pytest recipes/68-visual-accessibility-screening
```

Use the repository development environment for tests. Reproduce committed outputs with Python 3.14 and `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. See [the template contract](../../docs/recipe-template.md). The notebook runs from its own folder, keyless and offline by default.

The generator creates 26 original 480 × 360 PNG UI drawings in `assets/`: 12 validation, 12 test, and two unscored demos. Pillow's bundled font avoids external font assets. Light/dark themes, font sizes, control orientation, benign compact layouts, truncation, faint text, occlusion, blur, and unfamiliar icons are authored locally. These are synthetic examples, not photographs or real browser captures. Readable gold rationales live in `fixtures/labels.jsonl`; image filenames and references are opaque hashes. No render specification or gold label reaches inference.

## Decisions and comparison

The main text region and two control colors are a public template contract supplied to both methods. Each flag uses `p >= 0.5`; Python derives certainty as `abs(2*p - 1)`. For each flag, validation chooses the lowest observed certainty threshold achieving complete agreement on its retained, assessable validation examples. The immutable policy is frozen before test responses are requested. Readability below 0.85, a missing answer, or any uncertain flag sends the entire screenshot to review. Accepted flags are notes for further testing; reviews count as reviews, not coverage.

The deterministic baseline consumes the same pixels. It estimates text colors from the two most frequent colors in the declared region, computes sRGB relative luminance and contrast, tests ink at the right edge, and reconstructs colored control rectangles from visible pixels. Its fixed cutoffs are 4.5 for text-color contrast and 12 pixels for spacing. The formula is exact for known colors, but color discovery and geometry inference are fallible. It receives no gold labels or hidden UI layout boxes. The documented fixed-template/palette assumption is a substantial limitation, not a general screenshot parser.

The notebook compares exact-set accuracy among completed screens, actual coverage and review counts, per-label TP/FP/FN, and micro precision/recall/F1. For end-to-end flag counts, deferred assessable examples emit no flags and therefore incur missed positives. Unassessable screenshots have no invented per-flag labels; an erroneous completed screen is reported separately. Both methods retain imperfect held-out outcomes. The Noul policy deliberately accepts a false crowding flag and misses faint text. No threshold is tuned on these test failures.

## What was and was not measured

**Not measured live.** All committed answers are synthetic. The executed notebook checks the pipeline on N=12 test screenshots (10 assessable, two unassessable), after selection on N=12 validation screenshots. The two demos are unscored. These numbers cannot establish Jev quality. Model, capture date, inference latency, token usage, and cost are unknown for this synthetic run and remain `None` in accounting rows.

Known limitations include the narrow scope, authored visual labels, one template family, small sample, independent marginal gates that do not guarantee complete-set correctness, and the inability to infer assistive-technology behavior. Exact contrast computation on known synthetic colors does not make this a conformance test. A full accessibility assessment requires additional evidence and testing.

## Switch to live

The notebook makes exactly **26** calls in live mode, one batch of five questions per distinct image, and caches repeat displays. This exceeds the default live budget of 25. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=26`, `JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`, and provide `TYPESAFE_API_KEY` through the environment. The notebook explicitly pins `jev-1.14.0` and enables experimental images. Backend retry attempts consume the live budget, so a failed request can prevent completion. Unrecorded live exploration produces no reportable held-out result. No live calls were made for this recipe.

For an intentional recording, use the same triples from this folder and a fresh destination outside `fixtures/`:

```python
from pathlib import Path
from jev_cookbook import LiveBackend, load_helpers, record
from jev_cookbook.fixtures import load_inputs

helpers = load_helpers()
triples = [helpers.build_request(e.fields) for e in load_inputs()]
backend = LiveBackend("jev-1.14.0", images=True, max_requests=26, max_retries=0)
record(
    backend,
    triples,
    Path("capture/responses.json"),
    ledger_path=Path("capture/ledger.json"),
)
```

The recorder saves returned model/date/usage, leaving unreported quantities unknown. It does not measure inference latency or billed cost. Keep any separately captured real measurements with the recording; never substitute replay timing. After a complete reviewed capture, replace the synthetic response file as a whole and validate it; do not mix provenance. Re-select policy using recorded validation and evaluate a newly held-out sample once. `build_fixtures.py` refuses to replace recorded responses unless explicitly given `--force` and still regenerates inputs/labels independently. See [live recording](../../docs/live.md#recorder).

## Continue

[Semantic feature extraction](../35-semantic-feature-extraction/) develops independent judgments, and [sentiment classification](../01-sentiment-classification/) introduces typed answers and confidence gates.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models and long context](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
