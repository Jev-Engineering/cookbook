# Word sense selection

**Recipe 07** · Level 1 (Beginner) · Decision type: `Choice`

Select the intended meaning of an ambiguous word from a fixed sense inventory using its surrounding sentence.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over a fixed sense inventory Python builds for
each of four ambiguous words (`bank`, `crane`, `spring`, `bat`): one of that word's two senses, or
a shared `unclear` fallback for a sentence whose context does not decide between them. Python owns
everything else: the state Jev sees, the identifier that never reaches the model, and the rule that
accepts a sense only when it is a real sense of that word *and* its `confidence` clears a threshold
chosen on `validation` and then frozen. Choosing `unclear`, or anything that is not one of the
word's own senses, always goes to an explicit `review` outcome instead of being reported as a
result, whatever its confidence. The notebook shows three typed answers up close, all `demo`
examples never reached into by the evaluation (a sentence too thin to decide a sense, a clear one,
and one the stored answer gets wrong and confident), then the rule, then an evaluation that reports
accuracy overall and per target word, and the coverage, accuracy and risk the frozen rule buys on
`test`.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/07-word-sense-selection
python tools/execute_notebook.py recipes/07-word-sense-selection
pytest recipes/07-word-sense-selection
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
each of the 42 examples in `fixtures/`, and no other (each sentence is decided once and the stored
answer is reused wherever it is shown again). That is more than the live backend's default request
budget of 25, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=42` or higher before running this notebook
live, or it stops partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture,
or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (42 in the fixtures; the 4 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 42 invented sentences about four ambiguous words with hand-written
(synthetic) answers, some wrong on purpose: one per word is wrong at a moderate confidence on
`validation`. On `test`, only `crane` carries a wrong stored answer, and it carries two:
`t04-crane-thin` answers `unclear` at a low confidence (caught because it chose `unclear`, not
because of its confidence) and `t05-crane-wrong` is wrong *and* confident (not caught by the
threshold at all). `bank`, `spring` and `bat` each carry one `test` example that is right but at a
low confidence, caught by the threshold despite being correct. Its accuracy, overall and per target
word, and the coverage, accuracy and risk of the frozen rule check that the pipeline works; they
say nothing about how Jev performs, how fast it is, or what it costs. This recipe has no recorded
fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/07-word-sense-selection/`; the root `README.md` is
generated, and the five generated regions (between the `<!-- catalog:NAME:start -->` /
`<!-- catalog:NAME:end -->` markers) are regenerated inside this same pull request by a separate
integration worker after this branch is handed over, never by the recipe builder. Until that
happens, `Catalog (README is current)` is expected to be red on this pull request, which is not a
defect to fix here. No sentence anywhere in this folder states or implies Jev's real quality,
latency, or cost: every number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
