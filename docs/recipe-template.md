# Recipe template and scaffolder

Every recipe starts from [`recipes/_template/`](../recipes/_template/), a small recipe that
already satisfies the [contract](../CONTRIBUTING.md), and from the command that stamps out a new
folder for it. This page is the reference and the walkthrough; the template's own
[README](../recipes/_template/README.md) carries the same steps on one page.

```bash
python tools/new_recipe.py NN                 # create recipes/NN-slug/ from the catalog (NN is 1 to 60)
python tools/execute_notebook.py recipes/X    # run X/notebook.ipynb offline, write the outputs back
```

```python
from jev_cookbook import load_helpers

helpers = load_helpers()  # in the notebook
helpers = load_helpers(Path(__file__).resolve().parent.parent)  # in recipe/tests/test_*.py
```

## What the template is

A router for support messages: one `Choice` (`billing`, `bug`, `account`, `none`) and one rule in
Python. It is deliberately small, so that it can be read in a few minutes and copied sixty times.

| File | Role |
| - | - |
| `notebook.ipynb` | The recipe, executed, with its outputs committed. Nine sections, in a fixed order. |
| `README.md` | The one-page recipe README, plus the builder's walkthrough (a real recipe's README has only the first part). |
| `helpers.py` | `build_state`, `build_questions`, and the rule Python enforces (`route`). |
| `build_fixtures.py` | Writes `fixtures/`; the replay keys come from `helpers.py`, so they cannot drift from the questions. It lives next to the notebook, outside `fixtures/` ([fixtures.md](fixtures.md)). |
| `fixtures/` | `inputs.jsonl`, `labels.jsonl`, `responses.json`: 22 examples (10 `validation`, 10 `test`, 2 `demo`), synthetic and deliberately imperfect. |
| `tests/test_helpers.py` | Tests for the rule, and a check that the stored keys match the current question. |

The notebook sections, in order: **What you will build**, **Setup and run mode**, **The state**,
**The questions**, **One answer up close**, **Python's part**, **Evaluation**, **What was and was not
measured**, **Next steps**. A recipe keeps these headings.

### Choices the template makes for you

- **Mode-neutral cells.** The notebook prints `check`, a suffix that says "a pipeline check, not a
  Jev result" in an offline run and is empty otherwise. `run_header(..., backend=backend)` states
  the mode, and the setup cell passes `n_examples=len(scored)` in every mode.
- **Validation chooses, test reports.** The one setting (a confidence threshold) is selected on
  `validation` with `select_confidence_threshold` and frozen before `test` is touched.
- **Figures** are the last expression of a cell. They draw after `apply_style()`; the notebook
  needs no `%matplotlib inline` line.
- **Nothing path-like is printed.** The hygiene scan fails notebook outputs that contain absolute
  paths, usernames or environment dumps.
- **`Noul` propositions are statements** that can be true or false. The contract is stricter than
  TypeSafe's documentation, which also shows questions.

## How `load_helpers` works

Every recipe may have a `helpers.py`, and pytest runs all recipe tests in one process with
`--import-mode=importlib`, so `import helpers` would give the second recipe the first one's module.
`load_helpers(recipe_dir=None)` loads `recipe_dir/helpers.py` by file path (default: the current
directory) under a name made from the folder name, such as
`recipe_01_sentiment_classification_helpers`, and caches the module per resolved path and file
contents (a SHA-256 of the bytes): an unchanged file returns the same module object, and an
edited `helpers.py` is executed again, so re-running a setup cell after an edit never serves
stale code. The file is read as bytes, so a UTF-8 byte order mark (which Windows PowerShell
writes) is accepted.

- The module is in `sys.modules` only while its file executes (`dataclasses` needs that) and is
  removed afterwards; `sys.path` is never changed. A test run leaves no trace.
- A missing file is a `FileNotFoundError` naming the folder; an error inside `helpers.py`
  propagates and nothing is cached. `reload=True` executes the file again.
- Objects from helpers cannot be pickled by module name. Keep them out of anything pickled.
- The file is compiled with `dont_inherit=True`, so it gets the semantics `import` would give it:
  postponed annotations only if the file itself says `from __future__ import annotations`. Because
  the module is removed from `sys.modules`, `typing.get_type_hints` on a helper dataclass then
  fails (`NameError`: the module cannot be found to resolve the names). Do not use postponed
  annotations in `helpers.py`; neither the template's nor the scaffold's `helpers.py` does.
- **Keep `helpers.py` a single, self-contained file.** A `helpers.py` that does `import sibling`
  appears to work in the notebook, because the kernel can import from the recipe folder (and it
  then writes `__pycache__/` there), but it raises `ModuleNotFoundError` under pytest and in
  `build_fixtures.py`, where the folder is not on `sys.path`; `from . import x` fails everywhere.
  Nothing in the cookbook supports helpers split across files.

## The scaffolder

`python tools/new_recipe.py NN` reads `catalog/recipes.json`, finds the recipe whose `rank` is
`NN`, and creates `recipes/<slug>/` with:

- `notebook.ipynb`: no outputs; the first cell has the title, recipe number, level and difficulty,
  decision types, use case and sources from the catalog, and the nine sections follow with a
  `TODO` in each markdown cell;
- `README.md`: the recipe README with the same fields, the run commands for this slug, and a `TODO`
  where you write what it teaches;
- `helpers.py`, `build_fixtures.py`, `tests/test_helpers.py`: skeletons that raise
  `NotImplementedError("TODO ...")` until you write them. The test file's replay-key test assumes
  one request per example (`example.replay_keys` holds a single key); adapt it when an example
  needs a dependent second request, which is a later request with its own key.

Every place you must write is marked `TODO`, so `grep -rn TODO recipes/NN-slug` lists what remains;
a finished recipe prints nothing. The command validates that `NN` is a whole number from 1 to 60
(exit status 2 otherwise), exits with status 1 and a message when the recipe is not in the catalog,
and **never overwrites**: if `recipes/<slug>/` exists it changes nothing and exits with status 1.
`--catalog` and `--recipes-dir` point it elsewhere; the tests use them with temporary copies.

## From scaffold to a running notebook

1. Create `recipe/NN-slug` from `main`; `python -m venv .venv`, activate, `pip install -e ".[dev]"`.
2. `python tools/new_recipe.py NN`.
3. Write `helpers.py`: the state, the questions (options built by Python), and the rules Python
   enforces. Write a test for each rule in `tests/test_helpers.py`; run `pytest recipes/NN-slug`.
4. Fill `ROWS` and `answers_for` in `build_fixtures.py`, run
   `python recipes/NN-slug/build_fixtures.py`, then
   `python -m jev_cookbook.fixtures validate recipes/NN-slug`.
5. Work through `notebook.ipynb` section by section. The scaffold's setup, state, question and
   answer cells already run once steps 3 and 4 are done; replace each `TODO` and fill the
   `# TODO` code cells. Copy the template's evaluation cells as a starting point.
6. `python tools/execute_notebook.py recipes/NN-slug`, then read the outputs.
7. Run it twice: the second run must change nothing (`git diff --stat` empty after `git add`).
8. `ruff check .`, `ruff format --check .`, `pytest`, `python tools/check_hygiene.py`.
9. Open the pull request. Do not run `tools/render_catalog.py` or edit the root `README.md`: the
   `Catalog (README is current)` check is expected to be red until the integration worker has run
   (see "The generated-README exception" in [CONTRIBUTING.md](../CONTRIBUTING.md)).

## Executing a notebook

`tools/execute_notebook.py <recipe-dir>` runs `notebook.ipynb` with `nbclient` in a fresh kernel and
the recipe folder as working directory, and writes the outputs back in place.

- It builds a copy of the environment without any `JEV_COOKBOOK_*` or `TYPESAFE_*` variable and
  passes it to the kernel explicitly; this process's own environment is never changed, so notebooks
  can be executed in parallel. Starting several kernels at once on Windows can fail with a ZMQ
  "Address in use" error, so run executions one after another, or retry once. A shell that is set up for live calls still runs offline.
- The kernel is the interpreter running the tool (`sys.executable`). The name `python3` is
  resolved to that interpreter, not to whichever `python3` kernelspec Jupyter finds first, so a
  user-level kernelspec cannot change what the committed outputs were made with. The tool needs
  `ipykernel` installed in that interpreter, which `pip install -e ".[dev]"` provides.
- Stream output is coalesced, so a printed line is never split into two outputs by a flush that
  lands between its text and its newline; without that, re-execution was not byte-identical under
  load. A kernel that dies (a crash, `os._exit`) fails the run with exit status 1 and leaves the
  file unchanged.
- It records no timings, writes LF line endings on every platform, and resets the notebook
  metadata to the interpreter-independent minimum (kernel `python3`, language `python`), so the
  file does not change with the Python version that ran it. `tests/test_new_recipe.py` and
  `tests/test_template.py` pin each of these, including that two executions of the template give
  byte-identical files.
- A cell that writes to stderr (a warning, a traceback printed by hand) fails the run: stderr
  carries absolute paths. Fix the cause; do not filter the output.
- Exit status, with the file left unchanged in every failing case and one line (or the cell's
  error) on stderr:
  - 0: the notebook ran to the end;
  - 1: a cell raised; a cell ran longer than the timeout (`--timeout SECONDS`, default 300); the
    kernel died (`os._exit`, a crash); the kernel never started; or a cell wrote to stderr;
  - 2: usage error (for example no `notebook.ipynb` in the folder).

  Judge success by the exit status, not by an empty stderr: on Windows the tool and the kernel
  print harmless warnings of their own.

**Running live.** The executor never runs live, on purpose, so a committed notebook cannot
contain a live outcome by accident. To run a notebook live, set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL` in the shell, install the SDK
(`pip install -e ".[live]"`) and Jupyter (not a dependency), and open the notebook from its folder;
or capture answers with the recorder in [live.md](live.md). A recorded recipe states the model
version the API returned, the capture date and N for every number it reports.

It adds no network guard and no staleness check. Those are #69's. Two things for that work: figure
outputs are PNG images whose bytes may differ across platforms and matplotlib or FreeType
versions, and text outputs are stable. A staleness check that compares whole files should be run in
the CI environment the committed outputs were made in, or compare outputs other than image data.

## The template in the catalog

`recipes/_template` is not a catalog slug. `tools/render_catalog.py` only looks up folders named by
catalog slugs, so the template is never counted as published and needs no special case;
`tests/test_template_render.py` pins that. `python -m jev_cookbook.fixtures validate --all` does
include it, which is intended.
