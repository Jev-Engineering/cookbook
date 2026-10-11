# Regression test selection

**Recipe 32** · Level 3 (Intermediate) · Decision type: `Score`

Score candidate tests against the behavior changed by a patch so Python can propose a focused regression suite.

## What it teaches

Jev supplies one narrow judgment, a typed `Score` over a four-level relevance rubric Python builds: `unrelated`, `same_area`, `exercises_change`, `direct_regression`, asked once per (patch, candidate test) pair. Python owns everything else: the state Jev sees, the patch and test identifiers that never reach the model, a small file-path-and-lexical baseline standing in for however the candidate set itself might otherwise be ranked, the fixed business cutoff that decides which levels count as relevant, the confidence gate (chosen on `validation`, then frozen) that decides whether a score is trustworthy enough to act on at all, and the suite-composition function that turns several per-candidate judgments, under a fixed size budget, into one bounded regression suite. The notebook shows three typed answers up close, the rule, the baseline, and the suite-composition function (including two worked patches that isolate what each of the gate and the budget binds), then an evaluation that reports per-candidate agreement with the rubric and selective-prediction numbers, the recall of each patch's gold-relevant tests within the proposed suite against that baseline (per patch and averaged across every patch), and two counterfactuals that show exactly what removing the confidence gate and removing the size budget each cost.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/32-regression-test-selection
python tools/execute_notebook.py recipes/32-regression-test-selection
pytest recipes/32-regression-test-selection
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. The live backend's default request budget is 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry.
In live mode this notebook makes exactly one call for each of the 163 candidates it decides
(one `Score` question per patch-candidate pair: the 160 scored `validation` and `test`
candidates, plus the 3 `demo` candidates shown up close), and no other: each candidate is
decided once and the stored answer is reused wherever it is shown again (the notebook's
"measured" cell counts this directly from its own decide cache, not by multiplying). That is
far more than the live backend's default request budget of 25, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=163` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 79 `validation` and 81 `test` candidates are scored, grouped into 19 patches per split
  (160 scored across both splits; 163 in the fixtures, the 3 `demo` candidates across 2 more
  patches shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 163 invented (patch, candidate test) relevance judgments with
hand-written (synthetic) answers, some wrong on purpose: several `validation` candidates are
wrong at low confidence (so the confidence gate this notebook selects on `validation` is a real
choice, not a vacuous one), and two `test` candidates -- each written to advertise regression
coverage it does not actually have -- are wrong *and* confident, above the gate this notebook
freezes on `validation`, so the per-candidate selective-prediction numbers on `test` show a
real, non-zero risk rather than a gate that happens to look perfect, and the task-level recall
of the gold-relevant tests at the size budget, against the file-path-and-lexical baseline, shows
a real, non-degenerate number rather than a perfect score the budget and the gate could not have
produced any other way (several patches have more gold-relevant candidates than the budget can
ever hold, and several others have a gold-relevant candidate stored at too low a confidence to
be trusted). Exact agreement, mean absolute error, the coverage of the frozen confidence gate,
and the recall of the gold-relevant tests within the proposed suite all check that the pipeline
works; they say nothing about how Jev performs, how fast it is, or what it costs. Every stored
answer was written from its gold label, so the proposed suite reproduces that label wherever it
decides a patch, and any margin over the baseline is a property of this fixture set, not a
measurement of a real suite proposer (the notebook's "Evaluation" section says so where the
comparison is made, and traces the patches where this recipe's own design -- the confidence gate,
the size budget, or both -- costs it something instead). This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/32-regression-test-selection/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S05: [TypeSafe AI: Example use cases](https://docs.typesafe.ai/concepts/use-case-map)
