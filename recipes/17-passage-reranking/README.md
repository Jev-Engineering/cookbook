# Passage reranking

**Recipe 17** · Level 2 (Easy) · Decision type: `Score`

Score retrieved passages against a question so Python can rank candidate evidence and retain each passage's source reference.

## What it teaches

Jev supplies one narrow judgment, a typed `Score` over a four-level relevance rubric Python
builds: `not_relevant`, `tangential`, `relevant`, `direct`, asked once per (query, passage) pair.
Python owns everything else: the state Jev sees, the query and passage identifiers that never
reach the model, the small lexical scorer that stands in for the original retrieval step, the
fixed business cutoff that decides which levels count as a match, the confidence gate (chosen on
`validation`, then frozen) that decides whether a score is trustworthy enough to act on at all,
and the sort that turns several per-passage scores into one ranked list, ties broken by the
original retrieval order. The notebook shows three typed answers up close (a direct answer, an
on-topic but non-specific passage, and a passage written to claim its own relevance without
stating anything that answers the query), then the rule and the lexical baseline, then an
evaluation that reports exact-level agreement and mean absolute error against the human rubric,
the coverage, accuracy and risk the frozen confidence gate buys, and two ranking metrics -- nDCG
and top-1 accuracy -- comparing Jev's reranking against the lexical baseline's order on every
query in both splits.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/17-passage-reranking
python tools/execute_notebook.py recipes/17-passage-reranking
pytest recipes/17-passage-reranking
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definition is the same in
both modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in
Jupyter (not a dependency of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome
into a committed notebook. In live mode this notebook makes exactly one call for each of the 43
examples in `fixtures/` (one `Score` question per query-passage pair), and no other: each example
is decided once and the stored answer is reused wherever it is shown again. That is more than the
live backend's default request budget of 25 (`JEV_COOKBOOK_LIVE_MAX_REQUESTS`,
[docs/live.md](../../docs/live.md)), so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=43` or higher before
running this notebook live, or it stops partway through with `BudgetExceeded`. Never put a key in
a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 20 `validation` and 20 `test` examples are scored, grouped into 5 queries per split (43 in
  the fixtures; the 3 `demo` examples are shown in the notebook but never scored).

The committed run replays 43 invented (query, passage) relevance judgments with hand-written
(synthetic) answers, some wrong on purpose: one `validation` passage is wrong at low confidence
(so the confidence gate this notebook selects on `validation` is a real choice, not a vacuous one),
and one `test` passage -- written to claim its own relevance without stating anything that answers
the query -- is wrong *and* confident, above the gate this notebook freezes on `validation`, so the
selective-prediction numbers on `test` show a real, non-zero risk rather than a gate that happens
to look perfect. Exact-level agreement, mean absolute error, the coverage of the frozen confidence
gate, and the nDCG and top-1 accuracy of Jev's reranking against the lexical baseline all check
that the pipeline works; they say nothing about how Jev performs, how fast it is, or what it
costs. This recipe has no recorded fixtures.

`jev_cookbook.evaluation` has `mean_ndcg` to average `ndcg` over several ranked lists, but no
equivalent average for a top-1 ranking metric (`top_k_accuracy` is for a single Choice-style
probability distribution, and `recall_at_budget` reports one ranked list at a time with no "mean
over queries" counterpart). `top1_accuracy`, added to this recipe's `helpers.py` with its own
tests in `tests/test_helpers.py`, fills that one gap by averaging
`jev_cookbook.evaluation.recall_at_budget(relevant, scores, budget=1)` over queries, so every
other rule (tie-breaking, what counts as relevant) stays inside the shared, tested helper. This is
a gap in the shared evaluation toolkit worth fixing there, not a convention this recipe invents on
its own.

## Pull request rules

This recipe's pull request changes only `recipes/17-passage-reranking/`. The root `README.md` is
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
