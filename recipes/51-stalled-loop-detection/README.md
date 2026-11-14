# Stalled-loop detection

**Recipe 51** · Level 4 (Advanced) · Decision type: `Choice`

Classify progress across recorded agent turns as advancing, repeating, regressing, or complete so Python can apply a continue, change-strategy, or stop policy.

## What it teaches

A recorded agent works toward a goal one turn at a time: an action, the result it observed and a note it wrote itself. Sometimes it stalls: it reruns the same failing command, rewords a search that already found nothing, or undoes work it had finished. At every checkpoint (each turn after the first) Python renders the goal and the turns so far, and Jev answers one `Choice`: compared with the turns before it, is the latest turn `advancing`, `repeating`, `regressing` or `complete`, or `unclear` from what is shown? The agent's own note is treated as a claim, not evidence. Python owns everything after that: a confidence gate frozen on `validation` with `select_confidence_threshold` (before the budget turn, a low-confidence answer goes to a review queue with the reason `confidence below the threshold`), the table from a label to continue, change strategy or stop, a limit of one strategy change per transcript, and a hard turn budget no answer can extend, which stops the run at its turn whatever the answer. The supervisor runs in shadow mode on recorded transcripts, so a strategy change or a stop is only logged, never executed. The evaluation reports label accuracy and detection delay (how many turns after the gold stall point the supervisor first intervened) and compares both with a baseline that flags only a character-for-character repeat.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/51-stalled-loop-detection
python tools/execute_notebook.py recipes/51-stalled-loop-detection
pytest recipes/51-stalled-loop-detection
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
In live mode this notebook makes exactly **52** requests, each decided once. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 29 validation and 21 test checkpoints; the 2 `demo` checkpoints are shown but never scored.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, so its numbers check that the pipeline works: the question, the confidence gate, the policy table, the strategy-change limit, the turn budget and the detection-delay arithmetic, including on the hard cases the use case names (reworded repeats, a note that claims progress the results contradict, a regression after progress, and near-identical retries that are genuinely different). Validation numbers are a selection step. Two are forced by that selection: accuracy and risk among the answered checkpoints on `validation` come out `1.0000` and `0.0000` because the gate is chosen so that every validation answer that clears it, before the budget turn, is right; the notebook says so beside them. A checkpoint the turn budget decides is not counted as answered by the model. Label accuracy and coverage are measured per checkpoint over every checkpoint, each answered in shadow mode, and are separate from the run-level detection metrics. The test split is read once, after the gate is frozen. Not measured live: nothing here says how Jev performs, how fast it is, or what it costs.

## Pull request rules

This recipe's pull request changes only `recipes/51-stalled-loop-detection/`. The root `README.md` is generated; per
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
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
