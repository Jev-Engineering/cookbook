# Candidate rewrite selection

**Recipe 13** · Level 2 (Easy) · Decision type: `Choice`

Choose a supplied sentence rewrite that preserves the original meaning and requested tone, with a no-suitable-rewrite outcome when necessary.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over four fixed options Python builds: three
candidate-rewrite identifiers, `candidate_1`, `candidate_2` and `candidate_3`, and the explicit
fallback `no_suitable_rewrite` the use case names for an item where none of the three candidates
both preserves the original sentence's meaning and matches the requested tone. The three
candidates are generated ahead of time by ordinary Python, from fixed, fabricated candidate sets
-- never by calling a text model -- and Python deliberately varies which position holds the
correct rewrite (when one exists) across the fixture set, because a `Choice`'s option order is
part of its replay key and jev-1.13 is documented to lean toward whichever option comes first.
Python owns everything else: which candidate sits at which position, the rule that returns a
confident candidate's own text, keeps the original sentence unchanged whenever Jev says no
candidate fits (whatever its confidence, since there is no stored rewrite a confidence check
could protect there), and sends anything else uncertain to an explicit `review` outcome instead
of guessing. The notebook shows three typed answers up close (an item where two candidates both
keep the meaning and only one matches the tone, an item where no candidate fits, and a
`validation` item whose stored answer is simply wrong), then the rule, then an evaluation that
reports top-1 accuracy, `no_suitable_rewrite`'s own precision and recall, and a selective
coverage, accuracy and risk computed from what the rule actually did.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/13-candidate-rewrite-selection
python tools/execute_notebook.py recipes/13-candidate-rewrite-selection
pytest recipes/13-candidate-rewrite-selection
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for
the `Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`
(Python 3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to
execute the notebook -- `.[dev]` above is for `ruff` and `pytest`, which that job does not run;
see [docs/recipe-template.md](../../docs/recipe-template.md) step 6).

## Switch to live

Live calls are opt-in and change nothing but the backend; the question definition is the same in both
modes. Install the SDK (`pip install -e ".[live]"`) and set `TYPESAFE_API_KEY`, `JEV_COOKBOOK_LIVE=1`
and `JEV_COOKBOOK_LIVE_MODEL`; then open `notebook.ipynb` from this folder in Jupyter (not a dependency
of this repository), or record answers with the recorder described in
[docs/live.md](../../docs/live.md). `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome into
a committed notebook. In live mode this notebook makes exactly one call for each of the 40 examples
in `fixtures/`, and no other (each example is decided once and the stored answer is reused wherever
it is shown again). That is more than the live backend's default request budget of 25
(`JEV_COOKBOOK_LIVE_MAX_REQUESTS`, [docs/live.md](../../docs/live.md)), so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=40` or higher before running this notebook live, or it stops partway
through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo`
  examples are shown in the notebook but never scored).

The committed run replays 40 invented sentence-rewrite items with hand-written (synthetic)
answers, four of them wrong on purpose and in different ways. One is in `validation` itself: a
refund-refusal rewrite read as acceptably sympathetic when it is actually flat and neutral,
confidently enough that it is what drives the frozen confidence gate up to exclude it (two
genuinely correct but low-confidence items are swept up with it, the coverage cost of that
choice). The other three are in `test`: one wrong and confident through the gate (a late-fee
refusal read the same flat way), one wrong and not confident through the un-gated
`no_suitable_rewrite` branch (a courtesy-credit item read as having no suitable rewrite at all,
below the gate but delivered anyway because that branch is never gated), and one wrong but caught
by the gate (a setup-fee waiver with a quietly added restriction, at too low a confidence to be
reported). Its top-1 accuracy, confusion matrix, `no_suitable_rewrite`
precision and recall, and the coverage, accuracy and risk of the frozen confidence gate check
that the pipeline works; they say nothing about how Jev performs, how fast it is, or what it
costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/13-candidate-rewrite-selection/`. The root
`README.md` is generated; per the generated-README exception in
[CONTRIBUTING.md](../../CONTRIBUTING.md#the-generated-readme-exception), a designated integration
worker regenerates it **inside this same pull request**, after this branch is handed over, by
updating against current `main` and running `tools/render_catalog.py`; it is never regenerated by a
separate pull request, and this recipe's own builder never runs the renderer. While this recipe
remains unpublished and that integration step has not yet run, `Catalog (README is current)` is
expected to be red on its pull request, which is not a defect to fix here; once the catalog is
regenerated for it, the check turns green and stays that way. No sentence anywhere in this folder
states or implies Jev's real quality, latency, or cost: every number above is a synthetic pipeline
check. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
