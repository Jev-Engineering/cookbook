# Sentiment classification

**Recipe 01** · Level 1 (Beginner) · Decision type: `Choice`

Classify a short customer review as positive, neutral, negative, or mixed using a fixed set of labels.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over four fixed options Python builds: `positive`,
`neutral`, `negative`, `mixed`. Python owns everything else: the state Jev sees, the identifier that
never reaches the model, and the rule that accepts a label only when its `confidence` clears a
threshold chosen on `validation` and then frozen. Anything below the threshold goes to an explicit
`review` outcome instead of being reported as a result. The notebook shows three typed answers up
close (a genuinely mixed review, a very short one, and a sarcastic one), then the rule, then an
evaluation that reports accuracy, a confusion matrix, per-class precision and recall with `mixed`
discussed on its own, and the coverage and accuracy the frozen threshold buys.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/01-sentiment-classification
python tools/execute_notebook.py recipes/01-sentiment-classification
pytest recipes/01-sentiment-classification
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definition is the same in both
modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`
and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome into
a committed notebook. In live mode this notebook makes exactly one call for each of the 40 examples
in `fixtures/`, and no other (each example is decided once and the stored answer is reused wherever
it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo` examples
  are shown in the notebook but never scored).

The committed run replays 40 invented reviews with hand-written (synthetic) answers, some wrong on
purpose (a sarcastic review, a `mixed` review whose complaint comes second, and a short, lukewarm
review are all misread as `positive`). Its accuracy, confusion matrix, per-class metrics and the
coverage of the frozen confidence threshold check that the pipeline works; they say nothing about how
Jev performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/01-sentiment-classification/`; the root `README.md`
is generated and is regenerated separately by an integration worker after this branch is handed over,
never by this recipe's own pull request. Until that happens, `Catalog (README is current)` is expected
to be red on this pull request, which is not a defect to fix here. No sentence anywhere in this folder
states or implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline
check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
