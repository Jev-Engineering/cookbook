# Answer relevance check

**Recipe 10** · Level 1 (Beginner) · Decision type: `Noul`

Judge whether a candidate response addresses the user's question so a notebook can separate relevant answers from off-topic replies.

## What it teaches

Jev supplies one narrow judgment, a typed `Noul` over a single proposition Python writes: "this response addresses the question the user actually asked." Python owns everything else: the question and response text, an identifier that never reaches the model, the business threshold that turns a probability into a relevant/not-relevant decision (chosen on `validation` with `select_threshold`, then frozen), and a separate certainty gate (`noul_confidence`, distance from an even split) that sends a pair to an explicit `review` outcome instead of a forced guess. The notebook shows four typed answers up close -- a clearly relevant pair, a clearly off-topic pair, a pair that only partly addresses its question, and a pair where a fluent, confident-sounding response answers a different question from the one asked -- then the rule, a simulated `ReviewQueue` for the pairs it is not confident enough to decide, and an evaluation that reports precision and recall across the full threshold sweep plus the coverage, accuracy and risk the frozen certainty gate actually buys.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/10-answer-relevance-check
python tools/execute_notebook.py recipes/10-answer-relevance-check
pytest recipes/10-answer-relevance-check
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
each of the 48 pairs in `fixtures/`, and no other (each pair is decided once and the stored answer
is reused wherever it is shown again). That is more than the default budget, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=48` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 23 `validation` and 23 `test` pairs are scored (48 in the fixtures; the 2 `demo` pairs are
  shown in the notebook but never scored).

The committed run replays 48 invented (question, response) pairs with hand-written (synthetic)
answers, some wrong on purpose (a fluent response that confidently answers a different question
from the one asked, on both splits, and four pairs per split held deliberately close to an even
split with gold labels split both ways). Its precision, recall, the threshold sweep, and the
coverage, accuracy and risk of the frozen certainty gate check that the pipeline works; they say
nothing about how Jev performs, how fast it is, or what it costs. This recipe has no recorded
fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/10-answer-relevance-check/`; the root `README.md`
is generated and is regenerated separately by an integration worker after this branch is handed over,
never by this recipe's own pull request. Until that happens, `Catalog (README is current)` is expected
to be red on this pull request, which is not a defect to fix here. No sentence anywhere in this folder
states or implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline
check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
