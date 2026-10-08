# Response clarity scoring

**Recipe 03** · Level 1 (Beginner) · Decision type: `Score`

Score a support response against a clearly defined clarity rubric to identify examples that need editing.

## What it teaches

Jev supplies one narrow judgment, a typed `Score` over a four-level clarity rubric Python builds:
`confusing`, `needs_work`, `clear`, `exemplary`. Python owns everything else: the state Jev sees,
the identifier that never reaches the model, the fixed cutoff that decides which levels count as
needing an edit, and the confidence threshold, chosen on `validation` and then frozen, that
decides whether an answer is trustworthy enough to act on at all. An answer too uncertain to act
on goes to an explicit `review` outcome instead of being reported as a result. The notebook shows
three typed answers up close (process-speak that names no outcome, a response written to try to
steer its own score, and an immediately clear one), then the rule, then an evaluation that reports
exact-level agreement and mean absolute error against the human rubric, the distribution over
levels for a couple of `test` responses, and the coverage, accuracy and risk the frozen threshold
buys.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
that reproduces the committed notebook outputs byte for byte, see
[docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"` alone is enough for the
fixture and test commands below):

```bash
python -m jev_cookbook.fixtures validate recipes/03-response-clarity-scoring
python tools/execute_notebook.py recipes/03-response-clarity-scoring
pytest recipes/03-response-clarity-scoring
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
into a committed notebook. In live mode this notebook makes exactly one call for each of the 40
examples in `fixtures/`, and no other (each example is decided once and the stored answer is reused
wherever it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed
file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 40 invented support responses with hand-written (synthetic) answers,
some wrong on purpose (a self-contradicting response, a response written to try to steer its own
score, and others). One `test` response (`t14-contradiction`) is scored wrong *and* confidently, at
a confidence above the threshold this notebook freezes on `validation`, so the selective-prediction
numbers show a real, non-zero risk on `test` rather than a guarantee that happens to hold. Its
exact-level agreement, mean absolute error, and the coverage of the frozen confidence threshold
check that the pipeline works; they say nothing about how Jev performs, how fast it is, or what it
costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's builder never runs `tools/render_catalog.py` and never hand-edits the root
`README.md`. A designated integration worker updates this branch against current `main` and
commits only the generated regions of the root `README.md`, **in this same pull request**,
before the final review and the final CI run (`CONTRIBUTING.md`, "The generated-README
exception"). Until that integration step has run, `Catalog (README is current)` is expected to be
red on this pull request, which is not a defect to fix here. No sentence anywhere in this folder
states or implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline
check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
