# Source span selection

**Recipe 14** · Level 2 (Easy) · Decision type: `Choice`

Select the supplier name from text spans already extracted by Python, with a not-stated outcome when the document lacks that field.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over candidate spans a real, deterministic extractor (`helpers.extract_spans`: sentence splitting plus an organisation-name cue) finds in a document, plus a shared `not_stated` fallback. Python owns everything else: the document, the extractor, the span offsets, and a rule that returns a confident pick's exact source text by slicing the document at those offsets, or sends it to an explicit `review` outcome, with `not_stated` reported as final whatever its confidence (and no question built at all for a document with no candidate span). The supplier is not always in the same position among a document's candidates, and three model-free baselines (last span, first span, a disclosure-word cue) each score well below the stored answers. The notebook shows five typed answers up close, then the rule, then an evaluation that picks its one setting (a confidence gate) on `validation`, reports exact-match accuracy and `not_stated` handling on `test`, and shows what the gate costs and buys against answering every document unconditionally.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/14-source-span-selection
python tools/execute_notebook.py recipes/14-source-span-selection
pytest recipes/14-source-span-selection
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
each of the 40 documents that have at least one candidate span, and no other: each such document
is decided once (cached by id) and the stored answer is reused wherever it is shown again. The
other 3 of the 43 documents have no candidate span at all, so Python reports `not_stated` for
them directly and spends no request. 40 is above the default budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`), so set it to 40 or higher before running this notebook live,
or it stops partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or
any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 20 `validation` and 21 `test` documents are scored (43 in the fixtures; the 2 `demo`
  documents are shown in the notebook but never scored).

The committed run replays 43 invented purchase documents (40 of them asking a question; 3 with no
candidate span at all) with hand-written (synthetic) answers, several wrong on purpose and spread
across different span positions and branches: one in `validation` (`v20`, picking the first of
two spans), and three in `test` (`t18`, a confident near-miss decoy the gate does not catch;
`t19`/`t20`, each caught by the gate; `t21`, a wrong `not_stated` pick the gate is never applied
to at all). Its exact-match accuracy, three model-free baselines, the coverage/accuracy/risk the
rule's own outcomes produce next to what answering everything would have scored, and the
`not_stated`-versus-named precision and recall check that the pipeline works; they say nothing
about how Jev performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/14-source-span-selection/`. The root `README.md`
is generated; per the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by a
separate pull request, and this recipe's own builder never runs the renderer. Until that
integration step has run, `Catalog (README is current)` is expected to be red on this pull request,
which is not a defect to fix here. No sentence anywhere in this folder states or implies Jev's real
quality, latency, or cost: every number above is a synthetic pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
