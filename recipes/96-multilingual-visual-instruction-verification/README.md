# Multilingual visual instruction verification

Recipe 96 · Level 4 (Advanced) · `Choice` + images.

Compare a visible sign with an instruction in another language, returning `match`,
`contradiction`, or `insufficient`. The lesson pairs identical requests for pinned
`jev-1.13.0` and `jev-1.14.0`, freezes each arm's confidence threshold on validation,
and evaluates actual accept/review decisions against a finite visual-template baseline.
Both offline response files are **synthetic placeholders; not measured live**. Differences
between them provide no evidence of either model's quality.

The 26 authored 640 × 420 PNG drawings contain readable English, Spanish, and French text.
They are synthetic sign scenes, not photographs. There are 12 validation cases, 12 held-out
test cases, and two unscored demos, with prohibited entry, left/right, push/pull, exact
capacity limits, covered text, absent instructions, and a picture-embedded answer directive.
Both arms deliberately include a confident accepted negation error after policy freezing.
The generator contains readable transcripts and gold relations; inference gets pixels and
the proposed instruction only. See [asset notes](assets/README.md).

The OCR-free baseline compares a fixed image patch to 27 registered phrase bitmaps and uses
a small exact instruction dictionary. It has no access to labels or generation metadata.
It is deliberately limited to known text, font, scale, and layout. A two-line sign, an
unregistered font size, and an extra directive demonstrate failures. This vocabulary is
shared across splits; the holdout tests new sign/instruction pairs, not unseen vocabulary.

## Run offline

From the repository root, using Python 3.14 and the pinned plotting dependencies:

```bash
pip install -e ".[ml]" -c .github/constraints-notebooks.txt
python recipes/96-multilingual-visual-instruction-verification/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/96-multilingual-visual-instruction-verification
python tools/execute_notebook.py recipes/96-multilingual-visual-instruction-verification
python -m pytest recipes/96-multilingual-visual-instruction-verification -q
```

The generator reproduces both response files and images. If either response file contains
recorded answers or invalid data, it refuses to replace either response set without `--force`.
It still rebuilds authored inputs, labels, and images; preserve the entire capture dataset
before editing generator rows. Matplotlib supplies the bundled DejaVu Sans font, including
accented glyphs; pinned Matplotlib and Pillow versions reproduce the PNG bytes.

## Switch to live

Each model arm makes exactly **26** requests on a complete notebook pass: 2 demo + 12
validation + 12 test. The two-arm total is **52 application requests**, with one question
and one image per request. Each response file has 26 identical keys, not 52 different keys.
The application budget is 26 per arm and caches identical requests. HTTP retries consume
additional attempts under each live backend's separate budget; no global cross-run budget
is implied. Notebook metrics are suppressed for unrecorded live exploration.

For reportable measurements, follow [live setup](../../docs/live.md), install the live SDK,
opt in with `JEV_COOKBOOK_LIVE=1`, and set `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to an explicitly
chosen per-arm attempt limit (at least 26 for a retry-free complete capture). Model arguments
are pinned in code. Run from this recipe folder after supplying your own key through the
normal environment mechanism:

```python
from pathlib import Path
from jev_cookbook import load_helpers

helpers = load_helpers()
reports = helpers.record_arms(Path.cwd(), Path("captures/run-one"))
```

`record_arms` passes identical `(state, questions, assets)` triples to the shared `record`
function. It writes `responses.json` for 1.13 and `responses-jev-1.14.0.json` for 1.14, plus
separate request ledgers outside `fixtures/`. Existing captured keys are skipped, never
silently overwritten. Actual returned models, capture dates, reported token usage, request
IDs, and retry attempts come from the backend and recorder. Do not combine models into one
response file or put model labels in the state to manufacture different keys. Replay rejects
a recorded file whose model does not match its arm.

Inspect and validate a complete pair of captured response files with a preserved copy of
these input images and labels, then replace the corresponding synthetic response files in
that copy. Unset live opt-in and execute the notebook on the recorded data. Do not regenerate
author-written responses over captures. Latency and cost remain unknown because this recorder
does not measure them. Captures and ledger files are local artifacts, not shipped evidence.

## What was and was not measured

**Not measured live.** Synthetic results check plumbing, policy selection, and accounting;
they do not benchmark real model accuracy, cost, or speed. Each arm has N=12 validation and
N=12 test, plus two unscored demos. Unknown returned model, date, tokens, latency, and cost
remain null in synthetic accounting. A requested model name identifies an experimental arm,
not an actual model observation. Review is excluded from accepted coverage. All actions
are simulated proposed findings, never authorization to follow a sign.

This tiny Latin-script vocabulary cannot establish real photograph performance, translation
robustness, safety, or multilingual coverage. The confident false acceptance is intentionally
visible. Genuine Opus review and integration checks remain required before merge.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14 release](https://typesafe.ai/blog/jev-1-14)
