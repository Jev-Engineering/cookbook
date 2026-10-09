# Clarification selection

**Recipe 11** · Level 2 (Easy) · Decision type: `Choice`

Select a useful follow-up question from a predefined catalog when a task description omits information needed for the next step.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over seven fixed options Python builds: six
catalog identifiers (`ask_deadline`, `ask_recipient`, `ask_scope`, `ask_format`, `ask_budget`,
`ask_access_level`), each one specific follow-up question, and the explicit fallback
`no_clarification_needed` the use case names for a task that already states everything its next
step needs. Python owns everything else: the state Jev sees (the task description, and nothing
else), the stored question text for each catalog entry (the model never writes it, only picks
the identifier), and the rule that asks a confident real match's stored question, accepts
`no_clarification_needed` as a final "nothing to ask" result whatever its confidence, and sends
anything else uncertain to an explicit `review` outcome instead of guessing. The notebook shows
three typed answers up close (a task that could plausibly need two different follow-ups, a task
that needs none of them, and a validation task whose stored answer is simply wrong), then the
rule, then an evaluation that reports the accuracy of the selected follow-up across all seven
options, the coarser accuracy of the ask-or-proceed decision underneath it, and a coverage,
accuracy and risk computed from what the rule itself did -- not from reapplying a confidence gate
the rule's `no_clarification_needed` branch never uses. The 40 stored answers in `fixtures/` are
all synthetic.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
the `Notebook (<recipe>)` CI job uses, and the one that reproduces the committed notebook outputs
byte for byte, see [docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"`
alone is enough for the fixture and test commands below, which do not re-execute the notebook):

```bash
python -m jev_cookbook.fixtures validate recipes/11-clarification-selection
python tools/execute_notebook.py recipes/11-clarification-selection
pytest recipes/11-clarification-selection
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
examples in `fixtures/`, and no other (each task is decided once and the stored answer is reused
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

The committed run replays 40 invented task descriptions with hand-written (synthetic) answers,
four wrong on purpose and in different ways. One is in `validation` itself: a report request read
as missing its deliverable's shape when it is really missing the report's scope, confidently
enough that it is what drives the frozen confidence gate up to exclude it. Two are in `test`: one
wrong and confident through the confidence gate (a spend-breakdown request read as missing its
scope when it is really missing its format), and one wrong but caught by the gate at low
confidence (an access-level request misread as missing a recipient instead). The fourth is in
`test` too, and wrong in a different way again: a travel-booking request read as needing nothing
asked when it is really missing a budget, at a confidence that sits *below* the gate -- a
confidence-only rule would have caught it, but the `no_clarification_needed` branch never checks
confidence at all, so it is delivered as a final result anyway. Its accuracy of the selected
follow-up, confusion matrix, per-option precision and recall, the accuracy of the coarser
ask-or-proceed decision, and the coverage, accuracy and risk of the rule's own outcomes check that
the pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/11-clarification-selection/`. The root `README.md`
is generated: its catalog tables are regenerated inside this same pull request by a separate
integration worker, once this branch is handed over to them -- never by the recipe builder's own
commits. While this recipe remains unpublished and that handover has not yet happened,
`Catalog (README is current)` is expected to be red on its pull request, which is not a defect to
fix here; once the catalog is regenerated for it, the check turns green and stays that way. No
sentence anywhere in this folder states or implies Jev's real quality, latency, or cost: every
number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
