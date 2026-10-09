# FAQ selection

**Recipe 08** · Level 1 (Beginner) · Decision type: `Choice`

Select the best matching FAQ from a short candidate list, including a no-match outcome when none addresses the question.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over seven fixed options Python builds: six
FAQ identifiers (`password_reset`, `change_email`, `cancel_subscription`, `billing_cycle`,
`export_data`, `delete_account`) and the explicit fallback `no_match` the use case names for a
question none of the six addresses. Python owns everything else: the state Jev sees (the
customer's question text, and nothing else), the stored answer text for each FAQ (the model
never writes it, only picks the identifier), and the rule that returns a confident real match's
stored answer, reports `no_match` as a final result whatever its confidence (there is no stored
answer a confidence check could protect there), and sends anything else uncertain to an explicit
`review` outcome. The notebook shows three typed answers up close (a question that could be
`change_email` or `password_reset`, a question no FAQ addresses, and the validation question
whose confidence becomes the frozen threshold), then the rule, then an evaluation that reports
top-1 accuracy, `no_match`'s own precision and recall, and a selective accuracy, coverage and
risk computed from what the rule itself did -- not from reapplying a threshold the rule's
`no_match` branch never uses.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/08-faq-selection
python tools/execute_notebook.py recipes/08-faq-selection
pytest recipes/08-faq-selection
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
examples in `fixtures/`, and no other (each question is decided once and the stored answer is
reused wherever it is shown again). That is more than the live backend's default request budget of
25 (`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 40 invented customer questions with hand-written (synthetic) answers,
three wrong on purpose and in three different ways: one wrong and confident through the
confidence gate (a cancellation question read as a billing-date question), one wrong and
confident through the un-gated `no_match` branch (an export question read as having no match at
all), and one wrong but caught by the gate (a question about automatic trial conversion read as a
billing-date question, at too low a confidence to be reported). Its top-1 accuracy, confusion
matrix, `no_match` precision and recall, and the coverage, accuracy and risk of the frozen
threshold check that the pipeline works; they say nothing about how Jev performs, how fast it is,
or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/08-faq-selection/`. The root `README.md` is
generated: its catalog tables are regenerated inside this same pull request by a separate
integration worker, once this branch is handed over to them -- never by the recipe builder's own
commits. Until that handover happens, `Catalog (README is current)` is expected to be red on this
pull request, which is not a defect to fix here. No sentence anywhere in this folder states or
implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline check. The
full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
