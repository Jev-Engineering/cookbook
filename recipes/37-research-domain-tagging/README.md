# Research domain tagging

**Recipe 37** · Level 3 (Intermediate) · Decision type: `Noul`

Assign independently judged research-domain labels to evidence passages while Python preserves provenance and enforces access controls.

## What it teaches

Jev answers three independent `Noul` propositions over one evidence passage, one per research domain in a fixed list Python builds (`biomedical`, `computational`, `economics`), all sent together in a single request because they share the same state. Python filters passages by access control before any request is built, so a passage marked `restricted` is never sent: no state is built for it, no request is made, and no tag, review-queue entry, or printed line in the committed notebook ever names its id. For every accessible passage, Python turns the three yes-or-no answers into a tagged domain set with a threshold chosen separately for each domain, gates every domain behind a shared confidence gate, and sends anything it is not confident enough about to an explicit review outcome instead of guessing. The notebook shows a passage that raises all three domains at once, a benign look-alike that raises none, and one that fools a stored answer into a confident, wrong domain tag, then evaluates the frozen rule per domain (precision, recall, F1) and at task level (the share of passages tagged exactly right), alongside a direct proof that the access-control filter is load-bearing. The filter itself is a deterministic Python rule of this recipe's own fabricated access scheme, not a security feature or an access-control system in its own right.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/37-research-domain-tagging
python tools/execute_notebook.py recipes/37-research-domain-tagging
pytest recipes/37-research-domain-tagging
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
and always runs offline. In live mode this notebook makes exactly one request for each of the 37
accessible examples in `fixtures/` (each example is decided once, through a cache every decide
call shares, and the stored answer is reused wherever it is shown again); every request carries
all three domains' propositions together, so it answers 111 individual yes-or-no decisions (37
passages times three domains) in those 37 requests, not 111 requests. The five `restricted`
passages in `fixtures/` (four `validation`/`test`, one `demo`) are never sent, in any mode, and
so never count against this budget at all. 37 is more than the live backend's default request
budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=37` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Every attempt counts against that budget, including each
retry. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names
  the model the API returned and the date or dates the answers were captured.
- **N:** 18 `validation` and 18 `test` examples are scored and accessible (36 in total; 2 `demo`
  examples are shown in the notebook but never scored, and 4 further `validation`/`test`
  examples are `restricted` and so counted, but never decided or scored). Each scored example
  carries three domain decisions, so the per-domain and pooled numbers in the notebook cover 54
  (passage, domain) pairs per split.

A recorded recipe states the model version the API returned, the capture date and N for every number
it reports, here and in the notebook.

`fixtures/` holds 42 invented research passages in total; 37 of them are actually decided
(replayed) with hand-written (synthetic) answers, several wrong on purpose, and the remaining 5
are `restricted` and never decided at all (see "Switch to live" above). Among the 37 decided
passages: six benign look-alikes that use a domain's vocabulary ("cost",
"algorithm", "patient") without a passage actually raising that domain's research question
(`v04-biomedical-lookalike`, `t04-biomedical-lookalike`, `v19-economics-biomedical-wrong`,
`v20-economics-computational-wrong`, `t19-economics-biomedical-wrong`,
`t20-economics-computational-wrong`). `t19` and `t20` are wrong *and* confident on `test`
(stored 0.84 against thresholds of 0.80 and 0.79), and the frozen confidence gate, 0.6400,
does not catch either one: both clear it with room to spare. The per-domain precision and
recall, the micro and macro F1, the exact domain-set match, and the coverage, accuracy and risk
of the confidence gate check that the pipeline works; they say nothing about how Jev performs,
how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/37-research-domain-tagging/`. The root `README.md` is generated; per
the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by
a separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this
folder states or implies Jev's real quality, latency, or cost: every number above is a synthetic
pipeline check. The full contract is
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S06: [TypeSafe AI: Cookbooks](https://docs.typesafe.ai/cookbooks)
