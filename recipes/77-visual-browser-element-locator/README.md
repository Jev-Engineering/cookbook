# Visual browser element locator

Recipe 77 · Level 3 · Intermediate · `Box` + `Noul` + image

Locate a named button, form input, or menu item in an authored screenshot before a **simulated**
browser action. Three independent `Noul` propositions assess presence, uniqueness and enabled
state. Python requests a `Box` only after those gates pass, checks confidence and image bounds,
and records a simulated click or focus in `ActionLog`. Missing confidence, duplicates, disabled
controls and uncertain results go to `ReviewQueue`.

The notebook shows the typed answers, an annotated screenshot and a crop before evaluation.
It selects presence and Box thresholds on 10 validation screenshots, freezes them, then evaluates
12 held-out screenshots once. Two additional screenshots are unscored demonstrations. A fixed
known-layout baseline exposes reflow failures and absent-target false localizations. The report
includes localization misses, absence, abstention and accepted errors; it does not report only
successfully located targets.

All 24 screenshots are original Pillow drawings committed in `assets/`. Their gold presence
labels and normalized rectangles stay in `fixtures/labels.jsonl`, outside inference state.
`build_fixtures.py` reproduces the PNGs, input rows and synthetic responses, including deliberately
wrong answers. Image references derive from file content and reveal no gold coordinates.

**Not measured live.** All committed results are synthetic pipeline checks, not Jev results.
Latency, tokens and cost are unmeasured (`null`); no inference call was made. A high Box confidence
does not establish object presence: an absent-target demonstration shows why the first gate
matters. Confidently wrong visual judgments can still pass, and the held-out fixtures include an
accepted wrong rectangle. This is a teaching prototype, with no browser connection.

From the repository root, after the [development setup](../../docs/development.md):

```bash
python recipes/77-visual-browser-element-locator/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/77-visual-browser-element-locator
python tools/execute_notebook.py recipes/77-visual-browser-element-locator
pytest recipes/77-visual-browser-element-locator
```

Open `notebook.ipynb` to read the executed recipe.

## Switch to live

Live inference is opt-in through
`JEV_COOKBOOK_LIVE=1`, `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0` and `TYPESAFE_API_KEY`, with the
optional live dependencies installed. The notebook pins `jev-1.14.0` and enables the experimental
images header with `images=True`. The request budget must cover the first-stage requests,
eligible dependent Box requests and the explicit absent-target demonstration; the shared default
of 25 is too small for a full run, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=60` deliberately.
The committed replay makes exactly **38** calls, including the unscored demonstrations.
Actual live gating can change that count, up to 49 calls before retries.
The executor always runs offline. A direct unrecorded live run is exploratory, not a reportable
model result; recording and provenance rules are in [offline and live](../../docs/offline-and-live.md).

Continue with [tool outcome verification](../29-tool-outcome-verification/) or
[abstention and review queues](../38-abstention-and-review-queues/).

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14](https://typesafe.ai/blog/jev-1-14)
