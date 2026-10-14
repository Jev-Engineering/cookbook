# Model comparison and calibration

**Recipe 50** · Level 4 (Advanced) · Decision type: `Choice` + `Noul` + `Score`

Compare Jev and alternative decision backends on identical labeled tasks, calibrating each model separately and measuring held-out quality, latency, and cost.

## What it teaches

A harness that sends the same vendor compliance statement to three decision backends through one
typed interface (`jev_cookbook.backends.Backend`): Jev, and two fabricated decision adapters,
`atlas-compact` and `northstar-7b`. Every statement gets one always-sent request -- a `Choice`
category and two `Noul` propositions, asked together -- and, only when the category answer calls
for it, a dependent second request: a `Score` rubric rating how specific the statement is.
Python combines the typed answers into one outcome, and each backend is calibrated separately,
on its own validation answers, never on a value borrowed from another backend.

**This recipe draws no comparison.** No live run has been recorded (coverage: 0 of 60 live
requests made), so every number the notebook prints is a pipeline check on synthetic fixtures:
proof that the harness wires the questions, dispatches them identically to all three backends,
and turns the typed answers into a composed outcome without crashing. It is not evidence that
any one backend is more accurate, faster, or cheaper than another -- see "What was and was not
measured" below for exactly what that means and this section's "Switch to live" for how a real
comparison would be produced.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/50-model-comparison-and-calibration
python tools/execute_notebook.py recipes/50-model-comparison-and-calibration
pytest recipes/50-model-comparison-and-calibration
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook — `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the `jev` backend: `atlas-compact` and
`northstar-7b` are fabricated decision adapters this recipe never calls live, whatever the
environment says (see "Setup and run mode" in the notebook). Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline.

**Request count.** In live mode this notebook makes exactly **41** calls to `jev`, and no other:
23 examples (3 `demo`, 10 `validation`, 10 `test`) each ask request A once, and the 18 of those
23 that are worth a second request (for `demo`, whenever any backend's own category is not
`other`; for `validation` and `test`, whenever the gold category is not `other`) also ask
request B once, for 23 + 18 = 41. Every example is decided once per request it needs, never twice: a repeated
`decide()` on the same state and questions would be a second request, and this notebook does not
make one. The other two backends are never called live at all, so they contribute nothing to
this count.

**That is above the live backend's default request budget of 25**
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry. Raise it before running this notebook live:

```bash
export JEV_COOKBOOK_LIVE_MAX_REQUESTS=45
```

45 rather than 41 leaves headroom for a retried request (a 429 or a transient connection error)
to still complete inside the budget; 41 exactly would abort the final request after 40 succeeded
if even one earlier attempt needed a retry. Never put a key in a notebook or a fixture.

**What would actually be measured.** A recorded run would answer the same 41 requests from the
real API, with a pinned model (`jev-1.13.0`, never an alias) and the UTC date of the call, and
the recorder would write those responses into `fixtures/responses.json` in place of the
synthetic ones there now. The notebook's questions, state, and calibration code would not
change at all -- only the backend. Reporting a real comparison after that would still need a
second step this recipe does not take: recording `atlas-compact` and `northstar-7b` from their
own real APIs is out of scope here (they are fabricated stand-ins, not real services this
repository can call), so a live run of this recipe can only ever produce a recorded number for
`jev` alone, never a three-way comparison.

## What was and was not measured

- **Mode:** synthetic, for all three backends (offline replay of hand-written answers). Not
  measured live.
- **Model, capture date:** not applicable; no answer in this run came from a model. A recorded
  recipe names the model the API returned and the capture date or dates.
- **N:** 10 `validation` and 10 `test` examples are scored, per backend (3 `demo` examples are
  shown but never scored). Four quantities this recipe's evaluation mixes, named separately so
  none is read as another:
  - **Input rows:** 10 per scored split (20 total; 23 with the 3 `demo` rows).
  - **Requests** (what a live run bills, `len(fixtures/responses.json)`): 41, for `jev` alone --
    one per row for request A (23), plus one more for each of the 18 rows worth a second
    request. `atlas-compact` and `northstar-7b` each also have 41 *stored* responses (the
    comparison format requires every backend to answer the same requests), but neither backend
    is ever billed against a live budget, because neither is ever called live.
  - **Questions:** 3 in every request A (`category`, `verifiable`, `names_control`) plus 1 in
    every request B (`specificity`). The gold design asks request B on 8 of 10 rows in each
    scored split, for 10 × 3 + 8 × 1 = 38 questions per split under gold, but a backend's own
    path can ask a different count: `jev` and `northstar-7b` both ask request B on the same 8
    rows their own `category` answers name as the gold design does, on both splits, while
    `atlas-compact` asks it on only 7 of the 10 `test` rows (37 questions), one fewer, because
    its one wrong `test` answer (`t03`) names `other` instead of `business_continuity` -- see
    the notebook's "The composition boundary" for exactly this row.
  - **Task-level units:** 10 per scored split (one composed `triage` outcome per row; this
    recipe groups nothing, so this equals the input-row count).

**The harness ran and produced tables; none of those cells is evidence about any model's
quality, latency, or cost.** Every accuracy, coverage, and risk number above is a pipeline
check: proof that the questions got asked, dispatched identically across backends, and turned
into a composed outcome, on fixtures written for this recipe. Latency and cost are not printed
anywhere in the notebook: a replay backend's "latency" is a dict lookup and its "cost" is zero
because nothing was billed, and printing either would read as a measurement of something it
is not. No ranking, no winner, no margin, and no "beats" appears anywhere in this recipe.

## Pull request rules

This recipe's pull request changes only `recipes/50-model-comparison-and-calibration/`. The root `README.md` is generated; per
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
- S08: [TypeSafe AI: System One Adapter](https://github.com/typesafe-ai/system-one-adapter-python)
