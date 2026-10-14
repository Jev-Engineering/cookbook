# Plan constraint assessment

**Recipe 44** · Level 4 (Advanced) · Decision type: `Noul`

Evaluate each candidate plan against individual user constraints so deterministic policy can reject ineligible plans and route unresolved judgments to review.

## What it teaches

A candidate plan carries four of the user's own constraints -- budget, timeline, vendor, data handling -- and Jev answers one independent `Noul` per (plan, constraint) pair, all four together in one request: does the plan violate this one constraint? Python never asks the model to weigh the four against each other. A deterministic rule in `helpers.py` composes the four answers into exactly one of three outcomes: `ineligible` the moment any one constraint is confidently flagged as violated, whatever any other constraint's own confidence is doing; `review` when nothing is a confirmed violation but at least one judgment is not confident enough to trust; `eligible` only when every constraint is both confidently resolved and confidently clear. The recipe's named hard case -- a plan that satisfies every constraint but one -- makes that precedence concrete: one confident violation is always enough, however clean the other three read. A confidence gate on a Noul is measured here, not derived: the band around 0.5 is exact algebra, but whether it actually changes an outcome depends on how the composition wires it in, so the notebook sweeps a 401-point grid through the real rule, with and without the gate, and reports what changed.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/44-plan-constraint-assessment
python tools/execute_notebook.py recipes/44-plan-constraint-assessment
pytest recipes/44-plan-constraint-assessment
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
In live mode this notebook makes exactly **35** calls, one for each of the 35 examples in
`fixtures/` -- the 5 `demo` plans plus the 15 `validation` and 15 `test` requests, each decided
once and the stored answer reused wherever it is shown again. That is **above** the live
backend's default request budget of 25: set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=35` (or higher, to
allow for a retry) before running this notebook live, or it stops partway through with
`BudgetExceeded`. Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic. A recorded recipe
  would replace this line with the model the API returned and the capture date or dates.
- **N:** 15 `validation` and 15 `test` plans are scored (30 total; the 5 `demo` plans are
  shown but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The offline run replays 35 hand-written (synthetic) requests with synthetic answers, some wrong
on purpose: a confidently wrong `test` answer slips through the frozen gate as a wrongly-approved
plan (`t09-adversarial-data`), two confidently wrong answers wrongly reject clean plans
(`t12-falsepositive-vendor`, `t13-falsepositive-budget`), and two low-confidence plans go to
review regardless of which way their gold label actually falls. The business thresholds, the
confidence gate and its measured (not derived) effect on outcomes, the per-constraint precision
and recall, the plan-level coverage, accuracy and risk, the named hard case, and the three
zero-request baseline comparisons are all checks that the pipeline works; they say nothing about
how Jev performs, how fast it is, or what it costs.

## Pull request rules

This recipe's pull request changes only `recipes/44-plan-constraint-assessment/`. The root `README.md` is generated; per
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
