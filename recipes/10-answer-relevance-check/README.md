# Answer relevance check

**Recipe 10** · Level 1 (Beginner) · Decision type: `Noul`

Judge whether a candidate response addresses the user's question so a notebook can separate relevant answers from off-topic replies.

## What it teaches

Jev supplies one narrow judgment, a typed `Noul` over a single proposition Python writes: "this response addresses the question the user actually asked." Python owns everything else: the question and response text, an identifier that never reaches the model, the business threshold that turns a probability into a relevant/not-relevant decision (chosen on `validation` with `select_threshold`, then frozen), and a separate confidence gate (`noul_confidence`, distance from an even split, chosen on `validation` with a coverage floor) that sends a pair to an explicit `review` outcome instead of a forced guess. The notebook shows four typed answers up close -- a clearly relevant pair, a clearly off-topic pair, a pair that only partly addresses its question, and a pair where a fluent, confident-sounding response answers a different question from the one asked -- then the rule, a simulated `ReviewQueue` for the pairs it is not confident enough to decide, and an evaluation that reports precision and recall across the full threshold sweep plus the confidence gate's own coverage-versus-accuracy curve: on this fixture set the gate genuinely raises accuracy on the pairs it still decides, by catching one kind of near-even mistake, while still missing a fluent, confidently-wrong response the confidence formula cannot tell apart from a confidently-right one.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
the `Notebook (<recipe>)` CI job uses, and the one that reproduces the committed notebook outputs
byte for byte, see [docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"`
alone is enough for the fixture and test commands below, which do not re-execute the notebook):

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
each of the 52 pairs in `fixtures/`, and no other (each pair is decided once and the stored answer
is reused wherever it is shown again). That is more than the default budget, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 25 `validation` and 25 `test` pairs are scored (52 in the fixtures; the 2 `demo` pairs are
  shown in the notebook but never scored).

The committed run replays 52 invented (question, response) pairs with hand-written (synthetic)
answers, some wrong on purpose: a fluent response that confidently answers a different question
from the one asked (one per split, stored well clear of the confidence gate, so the gate cannot
catch it), a raw-decision mistake near the business threshold (one per split, stored close enough
to an even split that the gate does catch it), and three pairs per split held close to an even
split with gold labels not all one way. Its precision, recall, the threshold sweep, and the
confidence gate's own coverage-versus-accuracy curve check that the pipeline works; they say
nothing about how Jev performs, how fast it is, or what it costs. This recipe has no recorded
fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/10-answer-relevance-check/`. The root `README.md`
is generated; per the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by a
separate pull request, and this recipe's own builder never runs the renderer. Until that
integration step has run, `Catalog (README is current)` is expected to be red on this pull request,
which is not a defect to fix here. No sentence anywhere in this folder states or implies Jev's real
quality, latency, or cost: every number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
