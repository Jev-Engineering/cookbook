# Skill selection

**Recipe 28** · Level 3 (Intermediate) · Decision type: `Score`

Score retrieved skill descriptions for relevance to a task so Python can select a suitable skill or request clarification.

## What it teaches

Python retrieves a short list of candidate skills from a fixed catalog for each task (a small
lexical overlap scorer standing in for a real search step), and Jev scores exactly one thing,
once per candidate: how well that one skill's own description shows it can carry out the task,
on a four-level `Score` rubric. Python never asks Jev to compare skills against each other. The
rule that composes several of those scores into one task-level decision is code, in
`helpers.select_skill`: it ranks the candidates by their expected score and selects the top one
only when its score clears a fixed business cutoff *and* it clearly beats the runner-up by a
margin threshold chosen on `validation` -- the margin check being the one for the hard case the
use case names, two skills whose descriptions are both genuinely plausible for the task, scored
close together. Either check failing sends the task to review for a person to clarify, never an
automatic guess; each check is independently consequential, proved on the committed fixtures by
deleting one at a time and confirming the evaluation's reported numbers actually change, not
just a reason string (`tests/test_helpers.py`). The evaluation reports two different things: per
question, how well each individual relevance score agrees with its own gold level; per task, how
often the composed decision names a correct skill versus asks for clarification, and at what
rate.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/28-skill-selection
python tools/execute_notebook.py recipes/28-skill-selection
pytest recipes/28-skill-selection
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
each of the 150 (task, skill) requests in `fixtures/` -- one relevance `Score` question per
candidate skill a task retrieved, not one call per task, so the count is 50 tasks times 3
retrieved candidates each -- and no other: every request is decided once (cached by its example
id) and the stored answer is reused wherever it is shown again. That is more than the live
backend's default request budget of 25, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=150` or higher
before running this notebook live, or it stops partway through with `BudgetExceeded`. Never put a
key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable while every answer is synthetic.
- **N:** 72 validation and 69 test (task, skill) requests for the per-question agreement
  numbers; 24 validation and 23 test tasks for the composed, task-level selection numbers. The
  three `demo` tasks (9 requests) are shown up close but never scored.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

Every answer here is synthetic: the offline run replays answers written for this recipe, so its
numbers check that the pipeline works -- that the catalog is retrieved from correctly, the
relevance rubric is asked and read correctly, and `select_skill` composes several answers into
one decision correctly -- and say nothing about how Jev actually scores skill descriptions for
relevance. The evaluation covers exact-level agreement and mean absolute error against each
request's own gold level (per question), and top-1 accuracy among automatically selected tasks,
risk, and the clarification rate (per task, from `jev_cookbook.evaluation.evaluate_outcomes`,
since the rule has two independent review branches -- the business cutoff and the margin -- so
a task can be sent to review for either of two separate reasons).

## Pull request rules

This recipe's pull request changes only `recipes/28-skill-selection/`. The root `README.md` is generated; per
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
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
