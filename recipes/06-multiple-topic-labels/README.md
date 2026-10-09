# Multiple topic labels

**Recipe 06** · Level 1 (Beginner) · Decision type: `Noul`

Tag customer feedback with every applicable topic by asking an independent yes-or-no question for each predefined label.

## What it teaches

Jev answers five independent `Noul` propositions over one piece of feedback, one per topic label in a fixed list Python builds (`pricing`, `reliability`, `usability`, `support`, `feature_request`), all sent together in a single request because they share the same state. Python turns the five yes-or-no answers into a tag set with a threshold chosen separately for each label, gates every label behind a shared confidence cutoff built from `|2p - 1|`, and sends anything it is not confident enough about to an explicit review outcome instead of guessing. The notebook shows feedback that raises no topic, feedback that only looks like it raises one, and feedback that raises three at once, then evaluates the frozen rule with per-label precision and recall, a micro and a macro F1, and the share of examples tagged exactly right.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/06-multiple-topic-labels
python tools/execute_notebook.py recipes/06-multiple-topic-labels
pytest recipes/06-multiple-topic-labels
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. In live mode this notebook makes exactly one request for each of the 40
examples in `fixtures/`, and no other (each example is decided once and the stored answer is reused
wherever it is shown again); every request carries all five labels' propositions together, so it
answers 200 individual yes-or-no decisions (40 examples times five labels) in those 40 requests,
not 200 requests. 40 is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Every attempt counts against that budget, including each retry. Never
put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored). Each scored example carries five label
  decisions, so the per-label and pooled numbers in the notebook cover 95 (example, label) pairs
  per split.

The committed run replays 40 invented feedback messages with hand-written (synthetic) answers,
several wrong on purpose: two benign look-alikes (a feedback message that uses a word associated
with a label, `price` or `feature`, without actually raising that topic); `t16-lookalike-wrong`'s
is wrong *and* confident on `test`, and the same `feature_request` threshold that keeps it out
also costs a real feature request, `t18`, a confident false negative two hundredths below it;
plus six low-confidence crossover pairs on `validation` that the shared confidence cutoff is
chosen to catch. Its per-label precision and recall, the micro and
macro F1, the exact-set match, and the coverage, accuracy and risk of the confidence gate check
that the pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs.
This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/06-multiple-topic-labels/`. The root `README.md`
is generated: its catalog tables are regenerated inside this same pull request by a separate
integration worker, once this branch is handed over to them — never by the recipe builder's own
commits. Until that handover happens, `Catalog (README is current)` is expected to be red on this
pull request, which is not a defect to fix here. No sentence anywhere in this folder states or
implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline check. The
full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
