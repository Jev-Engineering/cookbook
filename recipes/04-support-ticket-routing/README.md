# Support ticket routing

**Recipe 04** · Level 1 (Beginner) · Decision type: `Choice`

Assign a support ticket to a fixed service category or an unclear-request outcome using its subject and description.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over five fixed options Python builds: four
service categories, `billing`, `technical_issue`, `account_access`, `feature_request`, and the
explicit fallback `unclear_request` the use case names for a ticket that does not resolve to one
category. Python owns everything else: the state Jev sees (the subject and description, kept as
two structured fields rather than one concatenated string), the identifier that never reaches the
model, and the rule that routes a confident real-category answer to its simulated queue, sends
`unclear_request` to a separate, un-queued outcome whatever its confidence, and sends anything else
uncertain to an explicit `review` outcome. The notebook shows three typed answers up close (a ticket
that could be `billing` or `account_access`, a vague one-line ticket, and one this recipe's stored
answer gets wrong), then the rule, then an evaluation that reports accuracy, a confusion matrix,
per-category precision and recall, how the unclear tickets were handled, and the coverage, accuracy
and risk the threshold chosen on `validation` and frozen before `test` produces.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/04-support-ticket-routing
python tools/execute_notebook.py recipes/04-support-ticket-routing
pytest recipes/04-support-ticket-routing
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definition is the same in
both modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in
Jupyter (not a dependency of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` removes those variables on purpose
and always runs offline. In live mode this notebook makes exactly one call for each of the 40
examples in `fixtures/`, and no other (each example is decided once and the stored answer is reused
wherever it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 40 invented tickets with hand-written (synthetic) answers, two wrong on
purpose: one wrong and confident (a ticket about a broken export button that also asks for a new
export format, read as a feature request instead of the technical issue it is), and one wrong but
not confident (a ticket mixing an invoice complaint, a search bug and a feature request, read as
billing instead of the `unclear_request` it is). Its accuracy, confusion matrix, per-category
metrics and the coverage and risk of the frozen confidence threshold check that the pipeline works;
they say nothing about how Jev performs, how fast it is, or what it costs. This recipe has no
recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/04-support-ticket-routing/`. The root `README.md`
is generated: its catalog tables are regenerated inside this same pull request by a separate
integration worker, once this branch is handed over to them — never by the recipe builder's own
commits. Until that handover happens, `Catalog (README is current)` is expected to be red on this
pull request, which is not a defect to fix here. No sentence anywhere in this folder states or
implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline check. The
full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
