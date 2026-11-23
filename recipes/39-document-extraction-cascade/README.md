# Document extraction cascade

**Recipe 39** · Level 3 (Intermediate) · Decision type: `Choice` + `Noul`

Select candidate values for document fields, verify each selection against its source span, and route uncertain or inconsistent records to review.

## What it teaches

A two-stage extraction cascade over a short purchase document with two fields, `invoice_number` and `total_amount`. Stage 1 is a `Choice` per field, over candidate spans Python extracts from the document text plus a shared `not_found` fallback; stage 2, in a later request, is a `Noul` per field that verifies the chosen span really states that field rather than a related but different figure (a purchase order number, a subtotal, a previous balance). Python composes the two stages into a field result (`not_found`, `extracted`, or sent to review for being uncertain or inconsistent) and then a document result (accepted only when neither field is in review), and evaluates both levels: field-level accuracy, review rate and error rate among records not sent to review, and task-level accuracy, coverage and risk over whole documents. On this fixture pool the two review reasons are not two independent safeguards: the confidence gate sits exactly at the lowest confidence any accepted verification can reach, so it only ever relabels which reason a withheld field carries and never changes which fields are withheld — the notebook demonstrates this directly rather than asking a reader to take it on trust.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev,ml]"` (the `ml` extra adds
scikit-learn, which the `Tests` jobs install and a recipe's `helpers.py` may use):

```bash
python -m jev_cookbook.fixtures validate recipes/39-document-extraction-cascade
python tools/execute_notebook.py recipes/39-document-extraction-cascade
pytest recipes/39-document-extraction-cascade
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — the `dev` extra above adds `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. The live backend's default request budget is 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry. The notebook caches each document's cascade and
reuses it in the demos, comparisons, and evaluation. On the supplied inputs, a live run makes
at most **52** logical requests. The candidate extractor finds at least one candidate in 26
documents. Each gets one stage-1 request bundling its `Choice` questions and at most one stage-2
request bundling its `Noul` questions. Stage 2 is skipped when every stage-1 answer for a
document is `not_found`. Documents with no candidates skip both stages. The offline replay
makes exactly **52** requests because every document queried at stage 1 reaches stage 2.

Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or higher to cover the longest path without retries.
With the live backend's default allowance of two retries per logical request, a run can consume
up to **156** attempts. A run that reaches the configured cap stops with `BudgetExceeded` if
it needs another attempt. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 13 `validation` and 14 `test` documents are scored (29 documents in the fixtures; the 2
  `demo` documents are shown in the notebook but never scored). Each document has two fields, so
  the field-level evaluation covers 26 `validation` and 28 `test` (document, field) pairs — twice
  as many scored examples as there are documents, because this cascade asks up to two questions
  per field and up to two fields per document.
- **Confidence gate:** on this fixture pool, the frozen confidence gate (`0.7000`) is exactly the
  lowest confidence any verification clearing the business threshold can have, so it can never
  withhold a field the business threshold would not already withhold. The notebook samples 1001
  verifier probabilities from 0 through 1. The gate changes 0 field outcomes on either side of the
  threshold and changes 699 review reasons below it. Removing the gate also leaves the `test`
  field-level numbers unchanged. On the accept side, a higher confidence gate acts as a higher
  business threshold expressed in confidence units.

The committed run replays 29 invented purchase documents (27 of them scored) with hand-written
(synthetic) answers, several wrong on purpose: `v04`, `v06`, `v12` on `validation` and `t12` on
`test` have a field sent to review (a decoy stage 1 wrongly preferred that stage 2 catches, or a
correct pick stage 2 wrongly doubts); `t08` has a field sent to review for being unconfident
rather than inconsistent; and `t04` has a field stage 2 confidently, wrongly verifies — the one
`test` error the frozen confidence gate and business threshold do not catch. Its field-level and
task-level accuracy, coverage and risk, and the verification probability sweep, check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/39-document-extraction-cascade/`. The root `README.md` is generated; per
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
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
