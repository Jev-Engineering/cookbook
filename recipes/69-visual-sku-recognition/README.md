# Visual SKU recognition

**Recipe 69** · Level 2 (Easy) · Decision type: `Choice` with image criteria

Match a query image against a fixed catalog whose options contain reference images. Python owns the four SKUs, the `no_match` and `unknown` alternatives, and the rule that sends uncertain matches to a simulated review queue. An accepted answer is a proposed visual match; nothing purchases an item, changes stock, or edits a catalog.

## What it teaches

The four fictional TERN variants differ in package shape, color, or label symbol. Two coral bottles are deliberate lookalikes. Each SKU criterion contains an actual attached reference image. Query and reference assets live in separate directories, and content-derived references prevent filenames or gold labels from becoming model hints. A changed reference image changes replay identity even when the query is unchanged.

The notebook compares synthetic image-Choice answers with a Python nearest-reference baseline using foreground color, aspect ratio, and fill ratio. Validation selects the baseline's rejection radius and a separate confidence gate for each method; held-out test evaluation uses the frozen settings. Coverage comes from actual accepted/review outcomes, including unconditional review for `unknown`. Both low-confidence matches and low-confidence `no_match` answers go to review.

## Run it offline

From the repository root, after `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/69-visual-sku-recognition
python tools/execute_notebook.py recipes/69-visual-sku-recognition
pytest recipes/69-visual-sku-recognition
```

The notebook runs from its own directory without a key or network. To regenerate original assets and synthetic responses, run `python recipes/69-visual-sku-recognition/build_fixtures.py`. The generator refuses to replace recorded responses without an explicit `--force`; it still regenerates inputs and labels. The Pillow drawings are authored here, carry no personal or scraped content, and are covered by the repository license.

Reproducing committed notebook outputs requires Python 3.14 and the CI stack:
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt`. See
[notebook execution](../../docs/recipe-template.md#executing-a-notebook).

## Switch to live

Install `pip install -e ".[live]"`, set `TYPESAFE_API_KEY` in the environment, and set
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL=jev-1.14.0`. Open the notebook in Jupyter
from this directory. It requests `jev-1.14.0` explicitly and enables the experimental image header
through `get_backend(images=True, model="jev-1.14.0", ...)`. The same question criteria and
PNG assets are used in both modes. `tools/execute_notebook.py` deliberately strips live settings.

The notebook makes exactly **34** calls in live mode when every first attempt succeeds: 16
validation queries, 16 test queries, and two demos. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at
least 34; retries consume additional attempts. Results are cached per example, so repeated
visualization does not send a second request. Never store a key in this folder.

For reproducible measurements, use [the recorder](../../docs/live.md), passing each
`helpers.build_request(example.fields)` triple `(state, questions, assets)`. Save the recorded
responses and the returned versioned model/capture date; keep usage or timing ledgers outside
`fixtures/`. Recording over the synthetic response file is an explicit replacement operation;
keep a copy of synthetic fixtures first and follow the recorder's overwrite instructions.
The notebook suppresses held-out metric reporting for an unrecorded live run.

## What was and was not measured

- **Mode:** synthetic, offline replay. **Not measured live.**
- **N:** 16 validation queries for selection, 16 held-out test queries for pipeline evaluation,
  and two unscored demos. Four catalog references are shared context, not scored examples.
- **Assets:** 38 original RGB PNG drawings at 384 × 320 pixels: four references and 34 queries.
- **Checks:** raw label accuracy, accepted-answer accuracy, coverage, risk, review counts, and
  the label confusion matrix. Synthetic responses include an accepted, confidently wrong match.
- **Not measured:** live Jev quality, latency, input/output tokens, or API cost. No model version
  or capture date applies to synthetic responses.

These are controlled drawings, not retail product photographs. The foreground baseline assumes a
neutral background and cannot read the lookalike labels; its distance-derived score is not a
calibrated probability. The comparison tests the pipeline on a small authored sample and supports
no conclusion about real-world product recognition. Fresh photographs require new disjoint
validation/test data and new calibration.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S09: [TypeSafe AI: Images](https://docs.typesafe.ai/images)
- S11: [TypeSafe AI: Models](https://docs.typesafe.ai/models)
- S12: [TypeSafe AI: Jev 1.14](https://typesafe.ai/blog/jev-1-14)
