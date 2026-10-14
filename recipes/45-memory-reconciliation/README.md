# Memory reconciliation

**Recipe 45** · Level 4 (Advanced) · Decision type: `Choice`

Classify a new memory statement as corroborating, superseding, contradicting, or unrelated to existing evidence so a versioned store can preserve provenance and unresolved conflicts.

## What it teaches

A memory system holds one short factual statement per topic. A new statement arrives, and Jev classifies its relationship to the existing memory: `corroborating`, `superseding`, `contradicting`, or `unrelated` (the named fallback). Python owns the store and every write to it: `jev_cookbook.simulation.Store`, a versioned key-value store that never deletes, holds every memory, and this recipe's own policy layer (`helpers.reconcile`) decides what write each outcome earns -- a below-gate answer writes nothing, `corroborating`/`superseding` both update the live value while the superseded value stays in history, and `contradicting` never overwrites the live value at all: it records the contested statement under a parallel key and preserves it as an unresolved conflict rather than resolving it by picking a winner. The notebook walks through two stateful hard cases: a statement whose correct classification depends on which version of a memory the store currently holds, and two statements that each read as a clean correction of the other depending on which arrives first.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/45-memory-reconciliation
python tools/execute_notebook.py recipes/45-memory-reconciliation
pytest recipes/45-memory-reconciliation
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
This notebook makes exactly **38** calls in live mode: 32 scored examples (16 validation, 16 test)
plus 6 demo examples (the two stateful hard-case walkthroughs), each decided exactly once (the
notebook's own `decide_once` cache guard, pinned by
`tests/test_helpers.py::test_the_request_cache_guard_is_pinned_in_the_notebook`, is what makes
that true). 38 is above the default budget of 25, so raise `JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at
least 38 before running this notebook live, or it stops partway through with `BudgetExceeded`.
Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 32 scored examples (16 validation, 16 test; four per outcome in each split); 6 further
  demo examples are shown but not scored. 38 total requests across the whole notebook (see
  "Switch to live" above), one per example, never repeated.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, so its numbers check that the
pipeline works, not how Jev performs. The evaluation covers: raw per-question label accuracy
against the gold outcome; the confidence-gated selective-prediction view (coverage, accuracy and
risk of "answer when confidence clears the threshold `select_confidence_threshold` chose on
`validation`"); a confusion matrix among the four outcomes on `test`; the store invariants
`helpers.reconcile` is built to hold (a below-gate answer writes nothing; `corroborating` and
`superseding` keep the superseded value reachable in history; `contradicting` leaves the live
value untouched and records a conflict; the write log alone reconstructs the final snapshot) --
proven exhaustively in `tests/test_helpers.py` over every outcome and a grid of confidences, and
shown as a pipeline check over the real `test` split in the notebook; and three zero-request
baselines. Two are constant predictions (majority class; always `unrelated`), which on this
exactly-balanced, four-way test split both sit at exactly 0.2500 by arithmetic alone -- a
structural floor, not two independent comparisons, since no constant prediction can ever score
otherwise on a balanced pool. The third, `helpers.keyword_overlap_baseline`, is not constant --
it earns its answer from the statements' own text (an explicit correction cue, then word
overlap with the existing memory) -- and is the one capable of actually tying or beating Jev; on
`test` it does not (0.8125 against Jev's 0.9375).

## Pull request rules

This recipe's pull request changes only `recipes/45-memory-reconciliation/`. The root `README.md` is generated; per
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

- S01: [TypeSafe AI: Introduction](https://docs.typesafe.ai/introduction)
- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
