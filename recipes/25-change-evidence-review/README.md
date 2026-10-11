# Change evidence review

**Recipe 25** · Level 3 (Intermediate) · Decision type: `Noul`

Check whether a proposed change includes sufficient implementation, validation, and rollback evidence so a deterministic checklist can identify review gaps.

## What it teaches

Jev supplies three narrow judgments over one change record, sent together in one request: a typed `Noul` for "this record supplies sufficient implementation evidence," a second for "sufficient validation evidence," and a third for "sufficient rollback evidence." The fixtures cover every one of the eight combinations the three propositions can take, so every pair of them is exercised in all four of its own combinations -- each alone, both at once, and neither -- and include the use case's own named hard case: a record that mentions a rollback plan without describing one. Python owns everything else: a business threshold chosen per proposition (by F1, on `validation`), one confidence gate shared by all three (chosen on their pooled decisions), and a single tested function, `helpers.review_checklist`, that composes the three label decisions into one of three outcomes -- `ready`, `gaps` naming exactly which evidence types are missing, or an explicit `review` outcome that lands in a simulated `ReviewQueue`, sorted least-confident first. The evaluation reports precision and recall for each proposition on its own, and, at the level of the whole change record, how often the composed gap list matches the record's gold combination of evidence types exactly. `tests/test_helpers.py` proves all three propositions independently consequential directly, by flipping one stored decision at a time on real fixtures and checking the composed outcome changes.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/25-change-evidence-review
python tools/execute_notebook.py recipes/25-change-evidence-review
pytest recipes/25-change-evidence-review
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
against that budget, including each retry. In live mode this notebook makes exactly one call
for each of the 40 examples in `fixtures/`, and no other (each change record is decided once
and the stored answer is reused wherever it is shown again). That is more than the default
budget, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live,
or it stops partway through with `BudgetExceeded`. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` change records are scored (40 in the fixtures; the 2
  `demo` records are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 40 invented change records with hand-written (synthetic) answers,
covering every one of the eight combinations the three propositions can take. Six `validation`
change records are sent to review by the shared confidence gate, including the three records --
one per proposition -- that mention an evidence type without describing it; on `test`, one such
record (a mention of a rollback plan with no description) clears the gate on all three
propositions and is confidently wrong: its composed outcome reads `ready` when the gold
combination has a gap on rollback evidence alone. On `test` the composed checklist reports
coverage 0.6842, accuracy among answered 0.9231, risk among answered 0.0769, and a gap-list match
of 0.9231 among the 13 records it answered; each proposition's own business rule (no gate) scores
F1 0.9000 (implementation and rollback evidence) or F1 0.9474 (validation evidence) on the same
split. These numbers, the threshold sweep, and the pooled confidence-only view check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/25-change-evidence-review/`. The root `README.md` is generated; per
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
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
