# Document revision consistency

**Recipe 48** · Level 4 (Advanced) · Decision type: `Choice` + `Noul`

Select among externally supplied sentence revisions and check their consistency with paragraph context as Python assembles a versioned document.

## What it teaches

A `Choice` selects among a fixed set of externally supplied candidate rewrites for one sentence slot, plus the named `keep_original` fallback. A two-proposition `Noul` battery then checks only the candidate Jev actually picked for consistency with the surrounding paragraph -- a request that always comes *after* the choice, and is skipped entirely whenever the choice itself is gated or names `keep_original`. Python composes both answers, through `helpers.decide`, over `jev_cookbook.simulation.Store`, a versioned key-value store that never deletes: an inconsistent candidate is never written over a slot's live text, and a confident, confidently-consistent candidate becomes a new version rather than erasing the one it replaces. The notebook walks through one slot revised over two rounds -- the second round's own "original sentence" is the first round's applied text, read back from the live store -- including a candidate with an embedded instruction aimed at the model, and a rollback that undoes an applied write without erasing anything.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/48-document-revision-consistency
python tools/execute_notebook.py recipes/48-document-revision-consistency
pytest recipes/48-document-revision-consistency
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

This notebook makes **one request per example always** (the revision `Choice`) **plus one more
exactly when that choice both clears the gate and names a real candidate** (the two-proposition
consistency `Noul` battery) -- never a fixed count, and never more than once per example for
either request (`decide_choice_once`'s cache guard). This notebook makes exactly **36** calls
against the committed fixtures and the frozen gates they select. The theoretical worst case, if
every live answer happened to need stage two, is 44 (22 examples × 2); raise
`JEV_COOKBOOK_LIVE_MAX_REQUESTS` to at least **44** before running this notebook live, so a
different real answer pattern cannot stop it partway through with `BudgetExceeded`. Never put a
key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 20 scored examples (10 `validation`, 10 `test`; the 2 `demo` examples carry no gold
  label and are not scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, so its numbers check that the
pipeline works and say nothing about how Jev performs. The evaluation covers: raw and
gate-selective agreement between the revision `Choice` and gold on `test`; precision and recall
of the composed consistency flag (`introduces_new_fact` or `breaks_reference`) against gold,
among the items stage two was actually asked about; task-level outcome coverage, accuracy and
risk (`applied` / `kept_original` / `review` against a flawless rule's own composed outcome,
including the "full-path trap" of a confidently wrong candidate landing in the right outcome
*class*); and a version-history test (`Store.history`/`rollback` after the demo walkthrough).
Every number above and in the notebook is a pipeline check, not a statement about Jev's quality,
latency, or cost.

## Pull request rules

This recipe's pull request changes only `recipes/48-document-revision-consistency/`. The root `README.md` is generated; per
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
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
