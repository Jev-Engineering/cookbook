# Hierarchical classification

**Recipe 40** · Level 4 (Advanced) · Decision type: `Choice`

Route documents through a taxonomy in stages while Python carries competing branches forward when early judgments are uncertain.

## What it teaches

A two-level taxonomy for routing a short support message: first to one of three departments (`account_billing`, `product_technical`, `people_policy`) or an explicit fallback, `unclassified`, then, inside a real department, to one of its own topics. Jev answers one narrow `Choice` at each stage; Python decides how many stages to spend, in `helpers.resolve_path`: if the department answer is confident, it commits to the single top-ranked department (greedy); otherwise it carries the top two real departments forward, asks a topic question for each, and scores every candidate full path, fallback included, as `department_probability * topic_probability`. `helpers.gate_path` then accepts the winning path only when that composite confidence clears a second, independent threshold, sending anything below it to review. The notebook reports leaf accuracy -- exact `department.topic` match -- and request count for this policy against the two baselines the use case names: a greedy single path (the same function, with branching turned off) and a flat classifier that asks one combined question per document. It also reports department-level accuracy separately from full-path leaf accuracy, since the two can disagree, and walks through a document whose two bare topic names coincide across departments, where comparing full paths (not bare names) is what keeps a wrong department from scoring as correct.

This recipe builds on [`05-document-classification`](../05-document-classification/)'s one-stage `Choice` router and [`38-abstention-and-review-queues`](../38-abstention-and-review-queues/)'s confidence-gated review queue.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/40-hierarchical-classification
python tools/execute_notebook.py recipes/40-hierarchical-classification
pytest recipes/40-hierarchical-classification
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
This notebook makes exactly **124** calls: four for each of its 31 documents (14 validation, 15
test, 2 demo) -- the department question, a topic question for each of the two real departments
that document's own department probabilities rank highest, and the flat baseline's question --
each document decided once per question, never twice. That is far above the live backend's
default request budget of 25 (`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)),
so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=124` or higher before running this notebook live, or it
stops partway through with `BudgetExceeded`. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 14 `validation` and 15 `test` documents are scored (29 total; the 2 `demo` documents are
  shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 31 invented documents with hand-written (synthetic) answers. Several are
wrong on purpose: four (two in each split) are cases where the department answer's own top choice,
by raw probability, is wrong and the second-ranked real department is the correct one -- carrying
both forward, rather than committing to the first, is what recovers the right answer; one (`test`)
is confidently wrong at the department stage and happens to land on a topic that shares its bare
name with the correct answer's own topic, so comparing full paths rather than bare topic names is
what keeps it from scoring as correct; one (`test`) has the right department and a confidently wrong
topic inside it. Leaf accuracy, department-level accuracy, request counts and the risk-coverage
curve this notebook reports check that the pipeline works; they say nothing about how Jev performs,
how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/40-hierarchical-classification/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
