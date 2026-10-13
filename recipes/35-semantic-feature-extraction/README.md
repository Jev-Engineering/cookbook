# Semantic feature extraction

**Recipe 35** · Level 3 (Intermediate) · Decision type: `Noul`

Convert text into predefined semantic features with independent judgments and compare a classifier trained on those features with a fixed baseline.

## What it teaches

Jev answers six independent `Noul` propositions over one piece of customer feedback, one per predefined semantic feature (mentions a price, expresses frustration, asks for a refund or cancellation, names a competitor, reports a technical issue, expresses satisfaction), all sent together in a single request because they share the same state. Python applies a business threshold chosen separately for each feature on `validation`, composes the six into a feature vector, and trains a small Naive Bayes classifier on those vectors against a second, independently-authored gold label (whether the feedback should be escalated to a human specialist) -- compared against a fixed majority-class baseline, both frozen on `train` before `test` is ever touched. The lesson is as much methodological as technical: the feature list, the split assignment and the baseline are all fixed in code before any `test`-split number is computed, and the notebook's own order of cells shows that discipline rather than merely stating it.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/35-semantic-feature-extraction
python tools/execute_notebook.py recipes/35-semantic-feature-extraction
pytest recipes/35-semantic-feature-extraction
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
against that budget, including each retry. In live mode this notebook makes exactly one request
for each of the 50 texts in `fixtures/` (16 `train`, 16 `validation`, 16 `test`, 2 `demo`), and no
other: each text is decided once, in the "One answer up close" section, and every later section
reuses that same stored answer rather than asking again (the setup cell counts and prints the
real request total, instrumented at the one place requests are made). Each request carries all
six features' propositions together, so it answers 300 individual true-or-false judgments (50
texts times six features) in those 50 requests, not 300 requests. 50 is more than the live
backend's default request budget of 25 (`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)),
so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=50` or higher before running this notebook live, or it
stops partway through with `BudgetExceeded`. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** three different quantities, none interchangeable with another. 16 `validation` and 16
  `test` **texts** are scored (50 in the fixtures; the 16 `train` texts fit the baseline and the
  classifier but are never themselves scored, and the 2 `demo` texts are shown in the notebook
  but never scored). Each scored text carries six feature decisions, so the per-feature and
  pooled numbers cover 96 **(text, feature) pairs** per split (192 total). The task-level
  classifier-versus-baseline comparison covers 16 **classifier examples** per split -- the same
  16 texts as the scored count, but a different quantity: one escalation decision per text, not
  per feature.

The committed run replays 50 invented feedback messages with hand-written (synthetic) answers,
several wrong on purpose: eight (text, feature) pairs across `train`, `validation` and `test` are
deliberately mis-scored (a stated feature's answer sits on the wrong side of the frozen threshold
from its own gold label), spread across all six features so every one of them has at least one
real mistake to be measured against. Per-feature precision, recall and F1 on `validation` and
`test`, the pooled accuracy across all (text, feature) pairs, and the classifier's and baseline's
held-out accuracy all check that the pipeline works; they say nothing about how Jev performs, how
fast it is, or what it costs. The classifier (a small Naive Bayes model over the six composed
features) outperforms the fixed majority-class baseline on both `validation` and `test` in this
run, but neither reaches perfect accuracy: several `test` texts (a long-time customer leaving with
none of the six features present, among others) are missed by the classifier and the baseline
alike, because a fixed boolean feature list cannot capture every signal a human reader would use --
see the notebook's "Evaluation" section for which texts and why. This recipe has no recorded
fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/35-semantic-feature-extraction/`. The root `README.md` is generated; per
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
