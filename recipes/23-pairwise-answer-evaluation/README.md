# Pairwise answer evaluation

**Recipe 23** · Level 2 (Easy) · Decision type: `Choice`

Compare two candidate answers against one explicit rubric criterion while retaining tie and insufficient-evidence outcomes for evaluation against human labels.

## What it teaches

Jev supplies one narrow, purely positional judgment, asked twice per comparison: given one
rubric criterion and two candidate answers to a question, does the first candidate shown satisfy
the criterion better, does the second, are they equal, or is there not enough evidence in either.
Python builds the two requests (the candidates in one order, then the same two swapped), owns
which candidate is "a" and which is "b" (Jev never sees those labels), and accepts a verdict only
when both orders agree, once relabelled, and the lower of their two confidences clears a
threshold chosen on `validation`. A disagreement between the two orders, or a confidence below
that threshold, sends the comparison to an explicit `review` outcome instead; a comparison both
orders agree is `insufficient_evidence` is accepted immediately, with no confidence check, because
it promotes neither candidate and has no side effect to protect. The notebook shows one comparison
the two orders agree on and one they do not, then evaluates the frozen rule against human labels:
raw accuracy and Cohen's kappa on the rule's accepted verdicts and on every single-request
verdict (so the swap-and-gate pipeline's benefit is visible, not assumed), the order-consistency
rate, and the coverage, accuracy, and risk `jev_cookbook.evaluation.evaluate_outcomes` computes
from the rule's own decisions.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/23-pairwise-answer-evaluation
python tools/execute_notebook.py recipes/23-pairwise-answer-evaluation
pytest recipes/23-pairwise-answer-evaluation
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

Every comparison needs two calls, not one: the two candidates in one order, then the same two
with the order swapped. This notebook makes exactly 82 calls in live mode (two for each of the
41 comparisons in `fixtures/`, including the two `demo` ones shown up close), and no other: each
request is cached by comparison id and order, so an answer shown earlier and scored again later
is never requested twice. 82 is well above the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=82` or higher
before running this notebook live, or it stops partway through with `BudgetExceeded`. Never put a
key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 20 `test` comparisons are scored (41 comparisons and 82 requests in
  the fixtures; the 2 `demo` comparisons are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 82 stored answers (two per comparison) for 41 hand-written comparisons,
some deliberately wrong and some deliberately inconsistent between the two orders. Its accuracy,
Cohen's kappa, order-consistency rate, and the coverage/accuracy/risk of the frozen confidence
gate check that the pipeline works; they say nothing about how Jev performs, how fast it is, or
what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/23-pairwise-answer-evaluation/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. Until that
integration step has run, `Catalog (README is current)` is expected to be red on this pull
request, which is not a defect to fix here. No sentence anywhere in this folder states or implies
Jev's real quality, latency, or cost: every number above is a synthetic pipeline check, and the
position-swap disagreements in `fixtures/` are authored by hand to exercise the swap-consistency
check, not a finding about how Jev actually behaves. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
