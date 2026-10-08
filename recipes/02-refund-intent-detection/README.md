# Refund intent detection

**Recipe 02** · Level 1 (Beginner) · Decision type: `Noul`

Judge whether a customer message explicitly requests a refund so Python can flag it for the appropriate workflow.

## What it teaches

Jev answers one narrow `Noul` proposition over a customer message: does it explicitly ask for a
refund? A `Noul` answer is a bare probability with no separate confidence field, so Python's only
design lever is a threshold on that probability, chosen on `validation` with
`select_threshold` and then frozen. A message whose probability clears the frozen threshold is
flagged and queued for the refund workflow to review; everything else needs no further action.
The notebook shows three typed answers up close (a clear request, a policy question that only
mentions refunds, and a message the threshold gets wrong on purpose), then the rule, then an
evaluation that reports precision and recall across the full threshold sweep and the real,
non-zero risk the frozen threshold carries on `test`.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/02-refund-intent-detection
python tools/execute_notebook.py recipes/02-refund-intent-detection
pytest recipes/02-refund-intent-detection
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

## Switch to live

Live calls are opt-in and change nothing but the backend. Install the SDK
(`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1` and
`JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. The live backend's default request budget is 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry. In live mode this notebook makes exactly one call for
each of the 40 examples in `fixtures/`, and no other (each example is decided once and the stored
answer is reused wherever it is shown again). That is more than the default budget of 25, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 40 invented customer messages with hand-written (synthetic)
probabilities, two of them wrong on purpose (one on each split): a message that raises a refund
only to decline it, stored confidently above the frozen threshold. Its precision, recall, and the
coverage and risk of the frozen threshold check that the pipeline works; they say nothing about
how Jev performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
