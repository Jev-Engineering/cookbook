# File organization

**Recipe 09** · Level 1 (Beginner) · Decision type: `Choice`

Recommend a destination folder from a fixed catalog using a file's name and text excerpt so Python can preview the proposed organization.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over five fixed options Python builds: the four
real destination folders `invoices`, `contracts`, `reports`, `correspondence`, and `unsorted`, the
fallback for a file that matches none of them. Python owns everything else: the state Jev sees, the
identifier that never reaches the model, and the rule that places the chosen folder only when Jev
did not itself answer `unsorted` and the answer's `confidence` clears a threshold chosen on
`validation` and then frozen. No file is moved, created, or read from disk outside the fixtures;
Python only renders a dry-run preview table of proposed destinations, with a low-confidence or
no-match proposal left in an `unsorted` row. The notebook shows three typed answers up close (a
file with conflicting signal, a nearly textless one, and one whose file name is misleading), then
the rule, then an evaluation that reports accuracy against the gold folder, a confusion matrix
across all five options, per-option precision and recall, and the coverage, accuracy and risk the
frozen threshold produces.

## Run it offline

From the repository root, in an environment with
`pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14; this is the install
the `Notebook (<recipe>)` CI job uses, and the one that reproduces the committed notebook outputs
byte for byte, see [docs/recipe-template.md](../../docs/recipe-template.md) step 6; `".[dev]"`
alone is enough for the fixture and test commands below, which do not re-execute the notebook):

```bash
python -m jev_cookbook.fixtures validate recipes/09-file-organization
python tools/execute_notebook.py recipes/09-file-organization
pytest recipes/09-file-organization
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

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
- **N:** 19 `validation` and 19 `test` examples are scored (40 in the fixtures; the 2 `demo` examples
  are shown in the notebook but never scored).

The committed run replays 40 invented files with hand-written (synthetic) answers, one wrong on
purpose and at low confidence on `validation` and one wrong *and* confident on `test` (a lease
renewal whose restated balance pulls the stored answer toward `invoices` even though the document's
main content is the signed renewal itself). Its accuracy, confusion matrix, per-option metrics and
the coverage of the frozen confidence threshold check that the pipeline works; they say nothing about
how Jev performs, how fast it is, or what it costs. This recipe has no recorded fixtures.

## Pull request rules

This recipe's pull request changes only `recipes/09-file-organization/`; the root `README.md` is
generated and is regenerated inside this same pull request by a separate integration worker after
this branch is handed over, never by this recipe's own pull request. While this recipe remains
unpublished and that has not yet happened, `Catalog (README is current)` is expected to be red on
its pull request, which is not a defect to fix here; once the catalog is regenerated for it, the
check turns green and stays that way. No sentence anywhere in this folder states or implies Jev's
real quality, latency, or cost: every number above is a synthetic pipeline check, and every
proposed move is a preview only. The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Sources

- S02: [TypeSafe AI: Primitives (Questions)](https://docs.typesafe.ai/primitives)
- S03: [TypeSafe AI: Confidence](https://docs.typesafe.ai/confidence)
- S04: [TypeSafe AI: How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one)
