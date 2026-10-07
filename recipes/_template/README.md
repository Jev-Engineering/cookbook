# Recipe template: route a support message

**Level 1 (Beginner)** · Decision type: `Choice` · Not a catalog recipe

This folder is a complete, working recipe, and the one every recipe is copied from. It routes a short
support message to `billing`, `bug`, `account`, or `none`, and lets Python decide what that answer may
do. The first half of this page is the README a recipe has. The second half, from "Build a recipe from
this template", is for the person building one.

## What it teaches

Jev supplies one narrow judgment, a typed `Choice` over options that Python builds. Python owns
everything else: the state Jev sees, the identifiers that never reach the model, and a rule that sends a
ticket to a queue only when the answer is a known queue and confident enough. Anything uncertain goes to
an explicit `human_review` outcome. The notebook shows the typed answer first, then the rule, then an
evaluation that picks its one setting (a confidence threshold) on `validation` and reports on `test`.

## Run it offline

From the repository root, in an environment with `pip install -e ".[dev]"`:

```bash
python -m jev_cookbook.fixtures validate recipes/_template   # the fixtures are valid
pytest recipes/_template                                      # the rule in helpers.py holds
python tools/execute_notebook.py recipes/_template            # run notebook.ipynb, outputs written back
```

The notebook needs no network and no API key. It runs with this folder as its working directory,
replays the stored answers in `fixtures/responses.json`, and imports only the standard library and
`jev_cookbook`. Its first output says which mode ran.

## Switch to live

Live calls change the backend and nothing else; the questions and the rule are the same. You need the
SDK (`pip install -e ".[live]"`) and three environment variables: `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL`. To run the notebook live, set them in the shell,
install Jupyter (`pip install jupyterlab`, which is not a dependency of this repository) and open
`notebook.ipynb` from this folder. `tools/execute_notebook.py` always removes `JEV_COOKBOOK_*` and
`TYPESAFE_*` from the kernel's environment, so it never runs live and never writes a live outcome into
a committed notebook; the recorder captures answers into `fixtures/` instead. In live mode this
notebook makes one call for each of the 22 examples it uses, and no other. The setup, the budget
limit and the recorder are in [docs/live.md](../../docs/live.md). Never put a key in a notebook,
fixture or committed file.

## What was and was not measured

- **Mode:** synthetic (offline replay of hand-written answers). Not measured live.
- **Model, capture date:** not applicable; no answer came from a model. A recorded recipe names the
  model the API returned and the date or dates the answers were captured.
- **N:** 10 `validation` and 10 `test` examples are scored (22 in the fixtures; the 2 `demo` examples
  are not scored). A recorded recipe states N beside every reported metric.

The committed run replays 22 invented messages with hand-written (synthetic) answers, some wrong on
purpose. Its accuracy, the routing counts and the confusion matrix check that the pipeline works; they
say nothing about how Jev performs, how fast it is, or what it costs. This template has no recorded
fixtures.

## What is in this folder

```text
_template/
├── notebook.ipynb        the recipe, executed, outputs committed
├── README.md             this page
├── helpers.py            the state, the question, and the rule Python enforces
├── build_fixtures.py     writes fixtures/ (the keys come from helpers.py, so they cannot drift)
├── fixtures/
│   ├── inputs.jsonl      22 examples: 10 validation, 10 test, 2 demo
│   ├── labels.jsonl      gold labels for the 20 scored examples
│   └── responses.json    synthetic answers, keyed by request
└── tests/test_helpers.py tests for the rule, and that the fixture keys match the question
```

The notebook's sections, in the order every recipe follows: What you will build, Setup and run mode, The
state, The questions, One answer up close, Python's part, Evaluation, What was and was not measured, Next
steps.

## Build a recipe from this template

Needs only this page and the repository. Recipe `NN` is issue `NN` and its slug is in
[`catalog/recipes.json`](../../catalog/recipes.json). The same walkthrough, with the reasons, is in
[docs/recipe-template.md](../../docs/recipe-template.md).

1. **Branch and install.** Create a branch `recipe/NN-slug` from `main`, a fresh virtual environment, and
   `pip install -e ".[dev]"` ([docs/development.md](../../docs/development.md)).
2. **Scaffold.** `python tools/new_recipe.py NN` creates `recipes/NN-slug/` with the title, level,
   decision types, use case and sources filled in, and a `TODO` wherever you must write. It stops with an
   error if the folder already exists. `grep -rn TODO recipes/NN-slug` lists what is left.
3. **Write `helpers.py`.** `build_state(fields)` returns what Jev sees; `build_questions()` returns the
   typed questions, with the options built by Python; the rule Python enforces goes here too. The
   notebook, `build_fixtures.py` and the tests all load this file the same way:

   ```python
   from jev_cookbook import load_helpers

   helpers = load_helpers()  # in the notebook, whose working directory is the recipe folder
   helpers = load_helpers(Path(__file__).resolve().parent.parent)  # in tests/test_*.py
   ```

   Never `import helpers`: every recipe has a `helpers` module, pytest runs them all in one process, and
   the second would silently get the first. `load_helpers` loads the file by path under a name taken from
   the folder (`recipe_01_sentiment_classification_helpers`), so recipes cannot collide.
4. **Write the fixtures.** Fill `ROWS` in `build_fixtures.py`: about
   twenty invented examples (this template has 22; more at levels 3 to 5 when the hard cases need
   it) across `validation` and `test`, plus a couple of `demo` ones, gold labels, and stored answers that are
   deliberately imperfect (some wrong, one hard case). Then write `answers_for`, which turns each row's
   spec into typed answers (for example `ChoiceAnswer.from_probabilities`); until you do it stops with a
   `TODO` error. Run `python recipes/NN-slug/build_fixtures.py`, then
   `python -m jev_cookbook.fixtures validate recipes/NN-slug`. Rules: [docs/fixtures.md](../../docs/fixtures.md).
5. **Write the notebook.** Replace each `TODO` in `notebook.ipynb`, section by section, keeping the
   headings. Prose goes in markdown cells, one sentence per design choice; charts use
   `jev_cookbook.style` ([docs/notebook-style.md](../../docs/notebook-style.md)); metrics use
   `jev_cookbook.evaluation` ([docs/evaluation.md](../../docs/evaluation.md)) and are printed with `check`
   beside them in an offline run. A threshold or option is chosen on `validation`, never on `test`.
6. **Test the rule.** Put a test in `tests/test_helpers.py` for every rule `helpers.py` enforces, so the
   claim "it holds whatever the model answers" is checked, not asserted.
7. **Execute and commit the outputs.** Re-execute before every commit that changes the notebook, its
   helpers or its fixtures:

   ```bash
   python tools/execute_notebook.py recipes/NN-slug
   ```

   It runs the notebook in a fresh kernel with this folder as the working directory, with
   every `JEV_COOKBOOK_*` and `TYPESAFE_*` variable removed from its environment, and writes the outputs back. A
   second run changes nothing; if yours does, something in an output is unstable (a time, an object id,
   an unordered set) and should not be printed. Outputs must not contain absolute paths, usernames or
   environment dumps: print nothing path-like.
8. **Check everything.** From the repository root: `ruff check .`, `ruff format --check .`, `pytest`,
   `python tools/check_hygiene.py`, and `grep -rn TODO recipes/NN-slug` (it must print nothing).

### Scripted or simulator recipes

A recipe built on `ScriptedBackend` or a simulator (the closed-loop and scripted catalog entries)
has nothing to replay, so its fixtures hold no responses. Scaffold it with `--mode scripted`:

```bash
python tools/new_recipe.py NN --mode scripted
```

What changes, and nothing else does:

- `helpers.py` also has `SEED` and `script(state, questions, rng)`, which stands in for the model and
  returns `{question name: spec}`. Use only `rng.random()` for chance; the same request must give the
  same answer. Write it in step 3, next to `build_state` and `build_questions`.
- `build_fixtures.py` writes `inputs.jsonl` and `labels.jsonl` only: every example has empty
  `replay_keys`, there is no `responses.json` and no `answers_for`. `ROWS` has four fields per row
  (id, split, fields, label).
- The notebook's setup cell uses `get_backend(script=helpers.script, seed=helpers.SEED)`, and
  `run_header(..., backend=backend, ...)` states `scripted`. The "measured" cell follows `backend.mode`.
- The validator reports `fixtures valid (mode scripted)`.
- The generated replay-key test checks the mode: for a scripted recipe it asserts the keys are empty
  and that the script gives the same answer to the same request twice.

How to drive a closed loop from the script is in [docs/simulation.md](../../docs/simulation.md).

### Pull request rules

The full contract is [CONTRIBUTING.md](../../CONTRIBUTING.md); in short:

- **Scope.** A recipe pull request changes only `recipes/NN-slug/`. It does not edit the catalog, shared
  code in `src/`, `tools/`, `docs/`, workflows, or any hand-written part of the root `README.md`. A change
  to shared code goes through its own issue and pull request.
- **The root README is generated.** Do not run `python tools/render_catalog.py` and do not edit
  `README.md`. Adding a notebook makes its catalog tables stale; a separate integration worker
  regenerates them in your pull request after you hand the branch over. Until then the `Catalog (README is
  current)` check is expected to be red, and that is not yours to fix.
- **Branch and description.** Branch `recipe/NN-slug`, description `Closes #NN`, the checklist from the pull
  request template filled in, commits signed, and no key, token or `Authorization` header anywhere.
- **No claims about Jev.** Nothing about its quality, speed or cost unless it comes from recorded live
  inference on a held-out set. A recorded recipe states the model version the API returned, the capture
  date and the sample size N for every number it reports, in the README and in the notebook. If you made
  no live run, the README says "not measured live".

### Notes on the contract this template follows

- A `Noul` proposition is a statement that can be true or false ("The message is about a refund."), not a
  question. The cookbook is deliberately stricter here than TypeSafe's documentation, which also shows
  questions. This template has no `Noul`, but a recipe that uses one follows the cookbook rule.
- A `Noul` has no confidence field, so a threshold on it is chosen on `validation` from examples. A
  `Choice` has one: the top probability rescaled by the number of options, `(p_max - 1/n) / (1 - 1/n)`
  (see [the confidence page](https://docs.typesafe.ai/confidence)); it is not the raw top probability.
- A fixture miss is an error (`ReplayMiss`); nothing invents an answer to keep a notebook running.
