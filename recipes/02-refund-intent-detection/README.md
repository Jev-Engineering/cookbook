# Refund intent detection

**Recipe 02** · Level 1 (Beginner) · Decision type: `Noul`

Judge whether a customer message explicitly requests a refund so Python can flag it for the appropriate workflow.

## What it teaches

Jev answers one narrow `Noul` proposition over a customer message: does it explicitly ask for a
refund? A `Noul` answer is a bare probability with no separate confidence field in the API
response, but a Noul's certainty is still defined (distance from an even split, `|2p - 1|`) and
the shared toolkit computes it. Python uses two things chosen on `validation` and then frozen:
a business threshold on the probability (`select_threshold`) and a certainty threshold on that
distance (`select_confidence_threshold`). A message too close to an even split goes to an
explicit review outcome, whichever way it leans; a message clear enough is flagged (and queued,
with `jev_cookbook.simulation.ReviewQueue`, for the refund workflow) or left alone, by the
business threshold alone. The notebook shows three typed answers up close (a clear request, a
policy question that only mentions refunds, and a message the thresholds get wrong on purpose),
then the rule and the queue it builds, then an evaluation that reports precision and recall
across the full threshold sweep and the real, non-zero coverage, accuracy and risk the frozen
certainty gate carries on `test`.

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
each of the 48 examples in `fixtures/`, and no other (each example is decided once and the stored
answer is reused wherever it is shown again). That is more than the default budget of 25, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=48` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 23 `validation` and 23 `test` examples are scored (48 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 48 invented customer messages with hand-written (synthetic)
probabilities, two of them wrong on purpose (one on each split): a message that raises a refund
only to decline it, stored far enough from an even split that the certainty gate does not catch
it, and above the frozen business threshold. Its precision, recall, and the coverage and risk the
frozen certainty gate buys check that the pipeline works; they say nothing about how Jev
performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
