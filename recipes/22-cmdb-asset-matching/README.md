# CMDB asset matching

**Recipe 22** · Level 2 (Easy) · Decision type: `Choice`

Link differently worded software asset descriptions to a canonical configuration-management record from a bounded candidate list or a no-match outcome.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over options Python builds fresh for each observed software asset: a bounded list of canonical CMDB records retrieved by normalized vendor/product word overlap (no fixed size -- some assets retrieve several candidates, some exactly one, some none at all), plus the explicit fallback `no_match` the use case names for an asset that matches none of them. Python owns everything else: the retrieval, the candidate descriptions, the rule that writes a link for a confident real match (the one outcome with a simulated side effect), reports `no_match` as a final result whatever its confidence -- or, for an asset with no candidates at all, without ever asking Jev, since a single-option `Choice` is never sent -- and sends anything else uncertain to an explicit `review` outcome. The notebook shows typed answers across this recipe's hard cases (a lexical look-alike that is a genuinely different product, an asset retrieving four candidates, an asset retrieving none, and a `validation` asset whose stored answer falls into the look-alike trap), then the rule and its one simulated side effect, a confidence-gate sweep, a printed table of where the gold match sits in its own shortlist, two trivial Jev-free baselines the rule's own accuracy must clearly beat, and an evaluation that reports link accuracy, the false-link rate, coverage, risk and `no_match`'s own precision and recall.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/22-cmdb-asset-matching
python tools/execute_notebook.py recipes/22-cmdb-asset-matching
pytest recipes/22-cmdb-asset-matching
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
each of the 35 examples whose retrieved candidate list is non-empty, and no other (each asset is
decided once and the stored answer is reused wherever it is shown again); the 5 remaining examples
(4 scored, 1 demo) retrieve no candidate at all, so no request is ever made for them. 35 is more
than the live backend's default request budget of 25, so set `JEV_COOKBOOK_LIVE_MAX_REQUESTS=35`
or higher before running this notebook live, or it stops partway through with `BudgetExceeded`.
Never put a key in a notebook or a fixture.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (38 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored). Of those 38, 4 retrieve no candidate at
  all and so are decided by Python without ever asking Jev.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

The committed run replays 40 invented software assets against a pool of 15 canonical CMDB
records, with hand-written (synthetic) answers, four wrong on purpose and in four different ways:
one in `validation` itself (a lexical look-alike -- a different, free product that shares enough
wording with a paid one to be retrieved as a candidate -- named confidently instead of `no_match`,
which is exactly the error the confidence gate chosen there excludes), and three in `test` (an
asset with no reported version, where this recipe's policy makes the gold label `no_match`,
confidently misnamed with a specific version instead -- a false link the gate does not catch; a
real match reported as `no_match`, confidently, and never checked by any confidence gate at all;
and a real match named with the wrong same-vendor-and-product sibling at a low confidence, caught
and sent to review). Its link accuracy, two trivial Jev-free baselines, `no_match`'s own precision and recall, and the coverage,
accuracy, risk and false-link rate taken from the rule's own outcomes check that the pipeline
works; they say nothing about how Jev performs, how fast it is, or what it costs. This recipe has
no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/22-cmdb-asset-matching/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. Until that
integration step has run, `Catalog (README is current)` is expected to be red on this pull
request, which is not a defect to fix here. No sentence anywhere in this folder states or implies
Jev's real quality, latency, or cost: every number above is a synthetic pipeline check. The full
contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
