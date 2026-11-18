# Visual browser element locator

Recipe 77 · Level 3 (Intermediate) · `Box` and `Noul`

Locate a named button, form input, or menu item in a synthetic screenshot. A
[question](../../docs/glossary.md#question) asks for one typed judgment. A
[Noul](../../docs/glossary.md#noul) answer reports the probability of presence, uniqueness or
enabled state. When those checks pass, `Box` proposes the visible rectangle. Python checks
its [confidence](../../docs/glossary.md#confidence), the reported certainty of the location, and
its bounds. It draws the rectangle and previews a simulated click or focus. The action log
records the proposal with `executed=False`.

The notebook shows typed answers and annotated screenshots. It freezes thresholds on validation,
then reports held-out presence [accuracy](../../docs/glossary.md#accuracy), the fraction correct
among answered examples, and [coverage](../../docs/glossary.md#coverage), the fraction answered.
[Risk](../../docs/glossary.md#risk) is the fraction wrong among answered examples. The notebook
also reports localization with its denominators. The [fixtures](../../docs/glossary.md#fixture)
are saved examples, labels and responses that include absent targets, duplicates, disabled
controls, a clipped control and a similar-looking menu label. A fixed-layout baseline illustrates
how reflow and absent targets affect a coordinate-only rule.

The recipe's generator draws all screenshots. The asset manifest records where they came from.
The [gold labels](../../docs/glossary.md#gold-label) give the authored geometry for evaluation.
Every committed response records its [provenance](../../docs/glossary.md#provenance), identifying
it as an authored synthetic answer.

From the repository root, after the [development setup](../../docs/development.md):

```bash
python recipes/77-visual-browser-element-locator/build_fixtures.py
python -m jev_cookbook.fixtures validate recipes/77-visual-browser-element-locator
python tools/execute_notebook.py recipes/77-visual-browser-element-locator
pytest recipes/77-visual-browser-element-locator
```

Run fixture generation and response recording for this recipe sequentially. Start the next
writer only after the previous one finishes so it sees the latest response file.

Open [the notebook](notebook.ipynb) to read the executed recipe.

## Switch to live

Install the optional live dependencies and opt in with `JEV_COOKBOOK_LIVE=1` and
`TYPESAFE_API_KEY`. The notebook uses the same questions as replay and sets the experimental
images header with the pinned `jev-1.14.0` model. Either request stage places its image in
[state](../../docs/glossary.md#state), the data Jev is asked about, for one image copy per request.
The notebook prints the raw and expanded image-byte
ranges beside those counts. See [offline and live](../../docs/offline-and-live.md) for the
recording and provenance requirements.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **37** requests, each decided once when every live answer matches the committed one, and up to **46** when a live answer sends it down a longer path. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=46` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## What was and was not measured

- **Mode:** synthetic (offline replay of authored answers). Not measured live.
- Reported metrics cover the fixture sample. Jev quality, latency, token use and cost are unmeasured.

## Next steps

Continue with [tool outcome verification](../29-tool-outcome-verification/) or
[abstention and review queues](../38-abstention-and-review-queues/).

## Sources

- S02: [Primitives](https://docs.typesafe.ai/primitives)
- S03: [Confidence](https://docs.typesafe.ai/confidence)
- S09: [Images](https://docs.typesafe.ai/images)
- S10: [Box](https://docs.typesafe.ai/primitives/box)
- S11: [Models](https://docs.typesafe.ai/models)
- S12: [Jev 1.14](https://typesafe.ai/blog/jev-1-14)
