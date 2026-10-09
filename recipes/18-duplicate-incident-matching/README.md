# Duplicate incident matching

**Recipe 18** · Level 2 (Easy) · Decision type: `Choice`

Select a matching incident from a retrieved ticket shortlist, or no match, using descriptions of the symptoms and affected service.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over four options Python builds fresh for each
new ticket: three candidate incident identifiers, retrieved by plain word overlap with the ticket's
own symptoms (no model call), and the explicit fallback `no_match` the use case names for a ticket
that matches none of them. Python owns everything else: the state Jev sees (the ticket's symptoms
and affected service, as separate fields), the retrieval, and the rule that links a confident real
match to its candidate -- the one outcome with a simulated side effect -- reports `no_match` as a
final result whatever its confidence, and sends anything else uncertain to an explicit `review`
outcome. The notebook shows three typed answers up close (a near duplicate on the wrong service,
this recipe's central trap; a ticket that matches nothing; and a `validation` ticket whose stored
answer falls into the trap and gets it wrong), then the rule and its one simulated action (an
`ActionLog` entry recording a link, never executed), a sweep of the confidence gate so the choice
of cut-off can be checked rather than taken on faith, then an evaluation that reports top-1 match
accuracy, and coverage, risk and the false-merge rate taken from
`jev_cookbook.evaluation.evaluate_outcomes` and the rule's own outcomes.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/18-duplicate-incident-matching
python tools/execute_notebook.py recipes/18-duplicate-incident-matching
pytest recipes/18-duplicate-incident-matching
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for the
`Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python
3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute the
notebook -- `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definitions are the same in
both modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in
Jupyter (not a dependency of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome
into a committed notebook. In live mode this notebook makes exactly one call for each of the 31
examples in `fixtures/`, and no other (each ticket is decided once and the stored answer is reused
wherever it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)); every attempt counts
against that budget, including each retry, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=31` or higher
before running this notebook live, or it stops partway through with `BudgetExceeded`. Never put a
key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 14 `validation` and 15 `test` examples are scored (31 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 31 invented tickets against a fixed pool of 8 open incidents, with
hand-written (synthetic) answers, four wrong on purpose and in four different ways: one in
`validation` itself (a near duplicate on the wrong service, named with a real but wrong candidate
at a low confidence, which is exactly the error the confidence gate chosen there excludes), and
three in `test` (the same wrong-service trap, confident enough this time to clear the frozen gate
and become a real false merge; a real duplicate reported as `no_match`, confidently, and never
checked by any confidence gate at all; and a real duplicate named with the wrong candidate at a
low confidence, caught and sent to review). A fifth ticket breaks a pattern the rest of the
fixtures share without meaning to: every other real-incident gold label happens to be the
shortlist's top-ranked candidate, so this one's gold match is deliberately the second-ranked
candidate instead, worded to outrank it on word overlap while naming the matching service. Its
top-1 match accuracy, confusion matrix, per-option precision and recall for `no_match`, and the
coverage, accuracy, risk and false-merge rate taken from the rule's own outcomes check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/18-duplicate-incident-matching/`. The root
`README.md` is generated: its catalog tables are regenerated inside this same pull request by a
separate integration worker, once this branch is handed over to them -- never by the recipe
builder's own commits. Until that handover happens, `Catalog (README is current)` is expected to
be red on this pull request, which is not a defect to fix here. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
