# Thesaurus word selection

**Recipe 12** · Level 2 (Easy) · Decision type: `Choice`

Choose a context-appropriate synonym from a supplied thesaurus list while retaining the original word when no alternative preserves its meaning.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over a small set of candidate synonyms that
Python assembles fresh for each sentence, plus a shared fallback, `keep_original`, for a sentence
where none of the candidates preserve the target word's meaning. Python owns everything else: the
state Jev sees, the identifier that never reaches the model, and the rule that accepts the chosen
option only when it was actually offered *and* its `confidence` clears a threshold chosen on
`validation` and then frozen. Unlike a Choice option that only ever means "the model could not
decide," `keep_original` is a real, final answer here — it is the correct, scorable outcome
whenever no candidate fits, and it is held to the same confidence gate as every other option
rather than an automatic review. The notebook shows three typed answers up close (a clear pick, a
correct `keep_original`, and a wrong, confident pick), then the rule, then an evaluation that
reports the share of selections inside each sentence's own acceptable set, how correctly the rule
uses `keep_original`, and the coverage, accuracy and risk the frozen threshold buys on `test`.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/12-thesaurus-word-selection
python tools/execute_notebook.py recipes/12-thesaurus-word-selection
pytest recipes/12-thesaurus-word-selection
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. The live backend's default request budget is 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry. In live mode this notebook makes exactly one call for
each of the 43 examples in `fixtures/`, and no other (each sentence is decided once and the stored
answer is reused wherever it is shown again). That is more than the live backend's default request
budget of 25, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=43` or higher before running this notebook
live, or it stops partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture,
or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 20 `validation` and 20 `test` examples are scored (43 in the fixtures; the 3 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 43 invented sentences about four target words with hand-written
(synthetic) answers, some wrong on purpose: one `validation` sentence is wrong at a moderate
confidence, which is what the threshold search on `validation` actually has to exclude. On `test`,
one sentence is wrong at a high confidence (the threshold does not catch it, so the reported risk
is non-zero) and one more is wrong at a low confidence (the threshold does catch that one). The
share of selections inside each sentence's acceptable set, the precision and recall of
`keep_original`, and the coverage, accuracy and risk of the frozen rule all check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/12-thesaurus-word-selection/`. The root
`README.md` is generated: its catalog tables are regenerated inside this same pull request by a
separate integration worker, once this branch is handed over to them — never by the recipe
builder's own commits. Until that handover happens, `Catalog (README is current)` is expected to
be red on this pull request, which is not a defect to fix here. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
