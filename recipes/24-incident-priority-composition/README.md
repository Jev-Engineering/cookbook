# Incident priority composition

**Recipe 24** · Level 3 (Intermediate) · Decision type: `Score`

Score reported business impact and urgency against separate rubrics so Python can map the scores to defined categories and apply a fixed service-priority matrix.

## What it teaches

Jev answers two independent `Score` questions about one incident report, in a single request: how much business impact it has, and how urgently it needs a response, each against its own four-level rubric Python builds. Python owns everything else: it maps each answer's most likely level to a named category, looks up the pair of categories in `PRIORITY_MATRIX` (a fixed table in `helpers.py`, not a formula), and reports that priority only when both answers clear a confidence gate chosen on `validation`; a ticket where either answer is too uncertain goes to an explicit `review` outcome instead. The notebook shows a ticket where the two questions disagree in direction (small impact, critical urgency) up close, prints the matrix, and evaluates both per-question agreement with the gold category and task-level agreement of the composed priority with the gold priority, including the non-zero risk a frozen gate does not catch.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/24-incident-priority-composition
python tools/execute_notebook.py recipes/24-incident-priority-composition
pytest recipes/24-incident-priority-composition
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
against that budget, including each retry. In live mode this notebook makes exactly one call for
each of the 40 tickets in `fixtures/` (both questions go in that one request), and no other: each
ticket is decided once and the stored answer is reused wherever it is shown again. That is more
than the default budget of 25, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running
this notebook live, or it stops partway through with `BudgetExceeded`. Never put a key in a
notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` tickets are scored (40 in the fixtures; the 2 `demo`
  tickets are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 40 invented incident reports with hand-written (synthetic) answers.
One `validation` ticket (`v18-wrong`) is wrong at a moderate confidence, so the threshold
selection has a real mistake to exclude rather than finding every answer trustworthy by default;
one `test` ticket (`t19-wrong`) is wrong *and* confident, at the same confidence as several
correctly-answered tickets, so the task-level selective-prediction numbers show a real,
non-zero risk on `test` rather than a guarantee that happens to hold. Business-impact and
urgency category agreement, task-level priority agreement, and the coverage of the frozen
confidence gate check that the pipeline works; they say nothing about how Jev performs, how fast
it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/24-incident-priority-composition/`. The root `README.md` is generated; per
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
