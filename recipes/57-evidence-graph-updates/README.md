# Evidence graph updates

**Recipe 57** · Level 5 (Expert) · Decision type: `Choice` + `Noul`

Combine entity, relationship, and evidence judgments into a proposed graph update that Python validates and applies transactionally in a simulated store with replayable provenance.

## What it teaches

An upstream extractor proposes "this mention now works at this organisation", with short
excerpts as evidence. Jev answers narrow questions in two requests: request 1 asks a `Choice`
(which person in the graph the mention is, or `no_match`) and a `Noul` (do the excerpts
conflict?) together; request 2, which depends on the person request 1 named, asks two `Noul`
propositions (do the excerpts state the new employment, and that the old one ended?). Python owns
everything else: the candidate shortlist, the confidence gate and thresholds frozen on
`validation`, a request `Budget`, the composition into one proposed update, and the transactional
apply in a simulated `Store` through a `Transactor` that validates the update, checks the graph
invariant (one employer per person) on the staged writes, rolls back on failure and logs every
attempt with its provenance. The notebook evaluates update accuracy against gold, runs a rollback
test and a replay test (`replay_transactions` rebuilds the graph from the log with identical
history), and compares a keyword baseline run under the same conditions.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/57-evidence-graph-updates
python tools/execute_notebook.py recipes/57-evidence-graph-updates
pytest recipes/57-evidence-graph-updates
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
and always runs offline.

<!-- request-budget:begin -->
In live mode this notebook makes exactly **45** requests, each decided once when every live answer matches the committed one, and up to **52** when a live answer sends it down a longer path. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

The count above is declared once, in [`request_budget.json`](request_budget.json), and rendered
here by `jev_cookbook.accounting.render_recipe_note`, never typed by hand. The second request is sent only
when the rule lets the first one through, so a live answer that differs from the stored one can change
how many second requests are made; the notebook's own `Budget` also refuses any request past its
limit and sends that proposal to review. The setup, the cap and the recorder are in
[docs/live.md](../../docs/live.md). Never put a key in a notebook, fixture or committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model.
- **N:** 12 `validation` and 12 `test` proposals are scored (26 in the fixtures; the 2 `demo`
  proposals are not scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, some wrong on purpose (a
confidently wrong person match, a missed conflict, a missed relationship, an over-read "ended"),
so its numbers check that the pipeline works and say nothing about how Jev performs, how fast it
is, or what it costs. The evaluation covers update accuracy, coverage and wrong writes on
`validation` (a selection step) and `test` (read once), each proposition at its frozen threshold,
the keyword baseline, the rollback test and the replay test. The graph, the people and the
organisations are invented.

## Pull request rules

This recipe's pull request changes only `recipes/57-evidence-graph-updates/`. The root `README.md` is generated; per
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
