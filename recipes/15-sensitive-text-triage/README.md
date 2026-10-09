# Sensitive text triage

**Recipe 15** · Level 2 (Easy) · Decision type: `Noul`

Flag synthetic documents that may contain personal information so a simulated review queue can prioritize redaction checks.

## What it teaches

Jev supplies one narrow judgment, a typed `Noul` over a single proposition Python writes: "this document may contain personal information about a real, identifiable person." Python owns everything else: a deterministic candidate-span scan for email-, phone-, and street-address-shaped substrings (shown to the reader, never sent to Jev), the business threshold that turns a probability into a flagged/cleared decision (chosen on `validation` with `select_threshold`, then frozen), a separate confidence gate (`noul_confidence`, distance from an even split, chosen on `validation` with a coverage floor) that sends a document to an explicit `review` outcome instead of a forced guess, and a simulated `ReviewQueue` that Python orders by the stored probability so the documents most likely to contain personal information surface first. The notebook shows four typed answers up close -- a document that clearly contains personal information, one that clearly does not, one that is genuinely ambiguous, and one that embeds an instruction trying to steer the triage into clearing it despite containing a fabricated name, phone number and address -- then the rule, the queue, and an evaluation that reports precision and recall at the business threshold, the confidence gate's own coverage-versus-accuracy curve, and the recall a fixed review budget would reach working the queue in probability order. This recipe prioritizes review; it does not guarantee detection, and nothing in it redacts anything.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/15-sensitive-text-triage
python tools/execute_notebook.py recipes/15-sensitive-text-triage
pytest recipes/15-sensitive-text-triage
```

The notebook runs from this folder with no network and no API key, replaying `fixtures/`.

Reproducing the committed notebook outputs byte for byte needs the exact stack CI installs for
the `Notebook (<recipe>)` job: `pip install -e ".[ml]" -c .github/constraints-notebooks.txt`
(Python 3.14; `nbclient` and `ipykernel` are core dependencies, so this alone is enough to execute
the notebook -- `.[dev]` above is for `ruff` and `pytest`, which that job does not run; see
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
each of the 52 documents in `fixtures/`, and no other (each document is decided once and the
stored answer is reused wherever it is shown again). That is more than the default budget, so set
`JEV_COOKBOOK_LIVE_MAX_REQUESTS=52` or higher before running this notebook live, or it stops
partway through with `BudgetExceeded`. Never put a key in a notebook, a fixture, or any other
committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 25 `validation` and 25 `test` documents are scored (52 in the fixtures; the 2 `demo`
  documents are shown in the notebook but never scored).

The committed run replays 52 invented documents with hand-written (synthetic) answers, some wrong
on purpose: a document that embeds an instruction trying to steer the triage into clearing it
despite containing a fabricated name, phone number and address (one per split, stored well clear
of the confidence gate, so the gate cannot catch it), a tracking or order reference formatted like
a phone number that the stored answer mistakes for one (one per split, close enough to an even
split that the gate does catch it), and several documents held close to an even split with gold
labels not all one way. Its precision, recall, the threshold sweep, the confidence gate's own
coverage-versus-accuracy curve, and the recall a fixed review budget would reach check that the
pipeline works; they say nothing about how Jev performs, how fast it is, or what it costs. This
recipe has no recorded fixtures. Clearing a document means this rule did not flag it for a person
to check; it is not a guarantee that the document contains no personal information, and nothing
in this recipe performs redaction.

## Pull request rules

This recipe's pull request changes only `recipes/15-sensitive-text-triage/`. The root `README.md`
is generated; per the generated-README exception in
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
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
- S07: [TypeSafe AI: Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
