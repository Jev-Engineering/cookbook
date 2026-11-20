# Adversarial harness evaluation

**Recipe 56** · Level 5 (Expert) · Decision type: `Noul`

Evaluate Jev screening at input, retrieved-context, proposed-action, and output boundaries using adversarial replay while measuring attack success, false positives, and task completion.

## What it teaches

How to evaluate a layered screening harness rather than a single screen. A support agent's episode has four boundaries (the user's message, a retrieved passage, the tool call it proposes, its draft reply), and Jev answers one `Noul` proposition per boundary, each about that artifact alone. Python owns everything else: the per-boundary business thresholds and the shared confidence gate (chosen on `validation`, frozen before `test` is read once), stopping an episode at the first block or review, a request `Budget` that sends an unscreened step to review instead of letting it through, the simulated `ActionLog` that only what passed every screen reaches, and the metrics. An adversarial corpus and a benign task corpus are replayed with each boundary screened alone and with all four combined, and a deterministic keyword baseline runs through the same harness on the same episodes; the notebook reports attack success rate, false-positive rate and task completion rate for every configuration, with reviews counted separately.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/56-adversarial-harness-evaluation
python tools/execute_notebook.py recipes/56-adversarial-harness-evaluation
pytest recipes/56-adversarial-harness-evaluation
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
In live mode this notebook makes exactly **229** requests, of which 168 are distinct (the other 61 repeat a request on purpose) when every live answer matches the committed one, and up to **257** when a live answer sends it down a longer path. Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=257` or higher before running it live (the default cap is 25): the cap is inclusive and every attempt counts against it, retries included, so a lower cap stops the run partway through with `BudgetExceeded` and a run that retries needs more.
<!-- request-budget:end -->

Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 20 `validation` episodes (12 attacks, 8 benign), on which every setting is chosen, and 20 `test` episodes (12 attacks, 8 benign), read once after everything is frozen. The four boundary tags give 16 truth combinations; the 13 the use case admits each have an episode in both splits, and the 3 it excludes (an attack whose only true tags are the input and context ones) have none. The 2 `demo` episodes are not scored. Each episode is screened at up to four boundaries, one request each.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays synthetic answers written for this recipe, so its numbers check that the pipeline works and say nothing about how Jev performs. Every probability, including every miss and near-miss, was written by hand, so the rates describe the harness applied to those answers and the fixture author's choices. What the run does show holds whatever the answers are: the harness stops at the first block or review, never spends more than its budget, sends a step it could not screen to review, lets nothing past a stop reach the log, and an output screen cannot undo a tool call that already ran.

## Pull request rules

This recipe's pull request changes only `recipes/56-adversarial-harness-evaluation/`. The root `README.md` is generated; per
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
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
