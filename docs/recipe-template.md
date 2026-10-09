# Recipe template and scaffolder

Every recipe starts from [`recipes/_template/`](../recipes/_template/), a small recipe that
already satisfies the [contract](../CONTRIBUTING.md), and from the command that stamps out a new
folder for it. This page is the reference and the walkthrough; the template's own
[README](../recipes/_template/README.md) carries the same steps on one page.

```bash
python tools/new_recipe.py NN                 # create recipes/NN-slug/ from the catalog (NN is 1 to 60)
python tools/new_recipe.py NN --mode scripted # the same for a scripted or simulator recipe
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
| `build_fixtures.py` | Writes `fixtures/`; the replay keys come from `helpers.py`, so they cannot drift from the questions. It lives next to the notebook, outside `fixtures/` ([fixtures.md](fixtures.md)). Generating inputs and labels is separate from generating responses: `--force` is needed to overwrite a `responses.json` that already holds a `recorded` answer. |
| `fixtures/` | `inputs.jsonl`, `labels.jsonl`, `responses.json`: 22 examples (10 `validation`, 10 `test`, 2 `demo`), synthetic and deliberately imperfect. |
| `tests/test_helpers.py` | Tests for the rule, a check that the stored keys match the current question, and `test_stored_answers_are_not_all_right` (replay recipes only): re-derives the frozen threshold from `validation` and requires a wrong `test` answer at or above it, so a fixture set that is merely "not all correct" (but has every mistake caught by the gate) still fails. `tools/new_recipe.py` scaffolds a working copy of this test too, so no recipe has to hand-write it from scratch. |
| `tests/test_build_fixtures.py` | Guards `build_fixtures.py` (replay recipes only): refusal without `--force`, `inputs.jsonl`/`labels.jsonl` regenerated from `ROWS` even on a refused run, and the committed `responses.json` byte-identical to `jev_cookbook.live`'s recorder. A scripted recipe has no `responses.json` and nothing for these tests to guard, so the scaffolder does not emit this file for `--mode scripted`. |

The notebook sections, in order: **What you will build**, **Setup and run mode**, **The state**,
**The questions**, **One answer up close**, **Python's part**, **Evaluation**, **What was and was not
measured**, **Next steps**. A recipe keeps these headings. A recipe that needs a section beyond
these nine (a second baseline, a closer look at one hard case) adds it as a `###` subsection
nested under whichever of the nine it belongs to, never as a new `##` heading: the nine stay the
one fixed table of contents every recipe shares, so a reader can jump between recipes by heading
alone.

**Cell ids follow one suffix convention.** A markdown (discussion) cell's id ends `-md`
(`setup-md`, `evaluation-md`, `next-md`, ...); a code cell's id names what it does, with no
suffix when it is the only code cell for its section (`setup`, `answer`) or a plain qualifier when
a section has more than one (`evaluation-validation`, `evaluation-test`, `evaluation-matrix`,
`evaluation-wrong`). Every id stays semantic either way, so this is cosmetic, not a correctness
rule — but it is the first thing a reader comparing two recipes' cells notices, and `-md` for
prose, no suffix or a plain qualifier for code, is the one this template uses throughout.

### The lexicon

A recipe borrows a small, fixed vocabulary for the ideas every evaluation uses: business
threshold, confidence gate, review, gold label, coverage, risk, selective prediction (and the
metrics in [glossary.md](glossary.md), accuracy, precision, recall, F1, support). Define a term
the first time a recipe's own prose uses it — in a sentence, not a code comment — and link the
matching entry in [glossary.md](glossary.md) there; a recipe that never uses a term need not
define or link it. This template links the glossary where its own first lexicon term appears
(`gold label`, in "Evaluation"); a recipe that reaches for more of the lexicon links each on its
own first use the same way.

### Choices the template makes for you

- **Mode-neutral cells.** The notebook prints `check`, a suffix that says "a pipeline check, not a
  Jev result" in an offline run and is empty otherwise. `run_header(..., backend=backend)` states
  the mode, and the setup cell passes `n_examples=len(scored)` in every mode.
- **The "What was and was not measured" markdown must not promise an N its code cell does not
  print, in any mode.** The markdown states once what the cell below gives: the mode, and (for a
  recorded or live run) the model and capture date, and, in every mode, N — the number of examples
  a reported number covers. The code cell's `measured` branches must each actually print N, so an
  offline run's branch prints it too, not only the recorded/live branch: a markdown promise one
  branch of its own code does not keep is a defect in the cell, not something to soften in the
  prose.
- **Validation chooses, test reports.** The one setting (a confidence threshold) is selected on
  `validation` with `select_confidence_threshold` and frozen before `test` is touched.
- **`evaluate_selective` reports the same split as the rule only when the rule's only review
  branch is that confidence gate — `route` here has three, so it is not that rule.**
  `helpers.py::route` sends a ticket to `human_review` for any of three reasons, in this order:
  `answer.choice == NONE` ("no option fits"), `answer.choice not in QUEUES` ("not a queue Python
  may use"), or `answer.confidence < min_confidence` ("confidence below the threshold"). Only
  the third is a confidence gate; the first two are unconditional, so `evaluate_selective`
  — which only ever compares a confidence against a threshold — can disagree with `route` about
  which tickets were answered. It does, on the template's own `test` fixtures, at the threshold
  the template's own evaluation section computes (`0.6933`):

  ```
  evaluate_selective(test_correct, test_confidence, threshold)
  # n_answered=7  coverage=0.7000  accuracy=0.8571  risk=0.1429
  evaluate_outcomes(accepted, test_correct)   # accepted = [r.outcome != REVIEW for r in routings]
  # n_answered=6  coverage=0.6000  accuracy=0.8333  risk=0.1667
  ```

  The one ticket they disagree on, `t07`, names `none` at confidence 0.80 — well above the
  threshold, so `evaluate_selective` would count it as answered, but `route` sends it to review
  outright because `none` is never a queue, whatever its confidence. (The template's own
  evaluation section does not call either function; this is the illustration for recipes that
  do, not a claim about what the template prints.)

  A rule with any unconditional review branch like `route`'s first two — an explicit fallback
  option it never confidence-checks (`unsorted`, `no_match`, `unclear`), a check that the chosen
  option is really a member of some set, or anything else that does not depend on
  `min_confidence` — can diverge from `evaluate_selective` the same way. Do not paper over this
  by handing the rejected examples a sentinel confidence (`0.0`, `-1.0`, ...) so the two "happen"
  to agree: that construction is one-directional (it cannot follow a later change to the rule's
  own confidence comparison) and an out-of-range sentinel can be selected as a threshold outright.
  Build selective coverage/accuracy/risk from the rule's own accept/review decisions instead, with
  `jev_cookbook.evaluation.evaluate_outcomes(accepted, correct)` — see "Selective prediction" in
  [evaluation.md](evaluation.md), which also proves the two agree exactly when the rule really is
  confidence-only (which `route` is not, but recipes 01 and 05's rules are).

  **A sentinel is not the same thing as a disclosed stand-in.** A rule can genuinely lack a
  confidence for some of the answers it reports on — for example, a case Python resolves entirely
  on its own before any `Choice` is ever built, so there is no answer object to read `.confidence`
  from. Handing `evaluate_selective` a fixed, in-range stand-in for exactly that case (`1.0` to
  mean "always counted as answered", say) is not the forbidden sentinel above as long as the
  notebook discloses it is a stand-in and quantifies what it costs: how many examples it affects,
  and how the resulting coverage compares to the narrower denominator a confidence gate could
  actually have applied to (the examples that really were asked). An undisclosed or out-of-range
  stand-in is still forbidden, whatever the reason for using one.

  **An "answered" outcome that still goes to a person is review, not coverage.** A rule can accept
  an answer into one of its outcomes and still route that outcome to the `ReviewQueue` for a
  person to confirm (an `unknown` result that is nonetheless logged for someone to check, say).
  That example counts toward [review](glossary.md#review), never toward
  [coverage](glossary.md#coverage): coverage means answered **and** not sent to anyone, so a rule
  with any branch like this is not confidence-only and needs `evaluate_outcomes`, built from
  `accepted[i]` that is `True` only when the rule neither reviewed nor queued example `i`.
- **Figures** are the last expression of a cell. They draw after `apply_style()`; the notebook
  needs no `%matplotlib inline` line.
- **Print what you plot.** Every `plot_*` call is paired with a `print` of the same numbers,
  rounded, in the same cell: the figure comparison in CI is loose (a moved line or marker still
  passes), so the printed numbers are what actually pins the plotted data. The template's own
  confusion-matrix cell (`evaluation-matrix`) prints the gold-by-predicted table immediately
  before drawing it from the same `matrix` object; a sweep figure (`plot_threshold_sweep`,
  `plot_risk_coverage`) prints the swept rows (threshold, coverage, accuracy, risk, ...) the same
  way.
- **A figure's title carries `{check}` only; a `validation` print line carries `{selection}{check}`.**
  These are two different things: the printed *lines* a `validation` cell prints need both labels
  (below), but a figure's *title* is always drawn from one split's numbers after that split's
  selection is already done, so it carries only `{check}` — the pipeline-check disclosure — never
  `{selection}` as well. The template's own confusion-matrix figure, `title=f"Test split, ... {check}"`,
  is drawn from `test`, which is never a selection step, so this does not arise there; a recipe
  that plots a `validation` figure (a threshold sweep used to justify the choice, say) still gives
  its title only `{check}`, because the figure is read as a pipeline check in that run, not
  additionally re-labelled as a selection step the way a printed number is.
- **Nothing path-like is printed.** The hygiene scan fails notebook outputs that contain absolute
  paths, usernames or environment dumps.
- **`Noul` propositions are statements** that can be true or false. The contract is stricter than
  TypeSafe's documentation, which also shows questions.
- **Per-item order comes from a seed key, never from `random.shuffle` or list position.** This
  template's one `Choice` lists its options in a fixed, meaningful order, so it needs none of
  this. A recipe that ranks or compares several candidates, and does not want their shown order to
  come from the data itself (which one is listed first, which side of a pairwise comparison an
  item sits on), derives it from `jev_cookbook.fixtures.stable_permutation` /
  `stable_shuffle` ([fixtures.md](fixtures.md#per-item-option-order)) instead.
- **Neighbour links are folder links, and every linked neighbour already exists on `main`.**
  "Next steps" links a neighbouring recipe as `../NN-slug/`. `tools/render_catalog.py` renders
  each catalog row as a bare `| NN | **title**<br>use_case | category | decision | status |` with
  no id or anchor, so there is no more stable target in the generated README to link to instead.
  Link only a recipe whose `notebook.ipynb` is already committed on `main`: a folder link to one
  that is not yet published would 404 on GitHub, and that forward link is not allowed — pick a
  different, already-published neighbour, or name none and say so in one sentence.
- **Every validation number in an offline run carries both labels, `{selection}{check}`.**
  CONTRIBUTING.md section 2 requires the pipeline-check disclosure beside every synthetic or
  scripted number, and separately requires the selection-step label on every `validation` number
  in every run mode; in a synthetic or scripted run a `validation` number needs both, so it
  prints `{selection}{check}`, never `{selection}` alone.
  `tests/test_template.py::test_every_metric_line_of_the_evaluation_carries_the_pipeline_check_label`
  enforces this for the template.
- **The foreign-option membership check is defensive, not required.** A backend's `_check_fits`
  already rejects an answer whose `choice` is outside the question's own option set at the
  boundary, before any rule sees it (see [backends.md](backends.md)). The template's `route`
  keeps an explicit `not in QUEUES` branch anyway, with its own review reason, because naming the
  boundary for a reader is worth the one extra branch; a rule that instead indexes a dict of
  known options directly (`QUEUES[answer.choice]`) and lets an impossible case raise `KeyError`
  is relying on the same backend guarantee, not skipping a required step. Either layer owning the
  check is acceptable.
- **A low-confidence fallback option may be a final result at any confidence only when it passes
  a two-part test.** CONTRIBUTING.md section 4 requires an uncertain or inconsistent result to go
  to an explicit review outcome, and states the test for the one exception: a fallback option
  such as `none`, `unclear_request` or `no_match` may skip the confidence gate and still stand as
  a final result, but only when choosing it (1) writes nothing to any container (`ActionLog`,
  `ReviewQueue`, or any other record a later step reads) **and** (2) leaves no harm standing —
  nothing a person would otherwise have caught goes uncaught because the rule said nothing
  happened. `route`'s fallback, `none`, passes the first part (choosing it writes nothing) but the
  template does not claim the exemption: `route` sends `none` to `human_review` like every other
  unconfident or unrecognized case, which is also compliant — the two-part test names when the
  exemption is *available*, not when it is required. A fallback that instead names a review-like
  action ("manual triage", "escalate") is a review outcome, not a final one, and never qualifies.
  A recipe that does claim the exemption prints the gated counterfactual (what `evaluate_outcomes`
  would report with the fallback gated too) beside the numbers it actually reports, so a reader
  can see what the exemption costs or buys — see the `evaluate_selective`/`evaluate_outcomes`
  bullet above for where that counterfactual comes from. A fallback that itself triggers a side
  effect (sends a message, closes a ticket, writes a record) fails part (1) outright and is never
  exempt on the strength of its name: it goes through the same confidence gate as every other
  option before that side effect runs.

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
- `tests/test_build_fixtures.py`, for a replay recipe only: the three guard tests already working
  against your `build_fixtures.py` once you have filled in `ROWS` and `answers_for` (step 4);
  nothing here is a `TODO`. A `--mode scripted` scaffold does not get this file.

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
   `python -m jev_cookbook.fixtures validate recipes/NN-slug`. Generating `inputs.jsonl` and
   `labels.jsonl` is separate from generating `responses.json`: once a response is `recorded`,
   rerunning the script refuses to overwrite it unless you pass `--force`.
5. Work through `notebook.ipynb` section by section. The scaffold's setup, state, question and
   answer cells already run once steps 3 and 4 are done; replace each `TODO` and fill the
   `# TODO` code cells. Copy the template's evaluation cells as a starting point.
6. Committable outputs require Python 3.14 with the constraints file: the floor, Python 3.10,
   cannot even install it (`numpy==2.5.3` needs Python 3.12 or newer), and CI compares text output
   byte for byte against its pinned stack. Install the way the `Notebook (<recipe>)` job does,
   `pip install -e ".[ml]" -c .github/constraints-notebooks.txt` (Python 3.14; `nbclient` and
   `ipykernel` are core dependencies, so this alone is enough to execute a notebook — `.[dev]`
   from step 1 is for `ruff` and `pytest`, which that job does not run), so the outputs you commit
   come from the same library versions; then `python tools/execute_notebook.py recipes/NN-slug`,
   and read the outputs.
7. Run it twice: the second run must change nothing (`git diff --stat` empty after `git add`).
8. `ruff check .`, `ruff format --check .`, `pytest`, `python tools/check_hygiene.py`.
9. Open the pull request. Do not run `tools/render_catalog.py` or edit the root `README.md`: the
   `Catalog (README is current)` check is expected to be red until the integration worker has run
   (see "The generated-README exception" in [CONTRIBUTING.md](../CONTRIBUTING.md)).

## Scripted and simulator recipes

Replay is the default. A recipe built on `ScriptedBackend` or a simulator (for example #36, #43,
#45, #46, #48, #57, #58, #59 and #60) has nothing to replay: `docs/fixtures.md` ("Replay and
scripted recipes") allows empty `replay_keys` and no `responses.json`. Scaffold it with:

```bash
python tools/new_recipe.py NN --mode scripted
```

The command is the same otherwise (`--mode replay` is the default and changes nothing). What the
scripted scaffold changes:

| File | Replay (default) | Scripted |
| - | - | - |
| `helpers.py` | `build_state`, `build_questions` | also `SEED` and `script(state, questions, rng)`, a `TODO` that returns `{question name: spec}` (see `Spec` in [backends.md](backends.md)) |
| `build_fixtures.py` | `ROWS` of 5 fields, `answers_for`; `--force` is needed to overwrite a `recorded` `responses.json` | `ROWS` of 4 fields (no spec), no `answers_for`; writes `inputs.jsonl` and `labels.jsonl` with `"replay_keys": []`, and removes a stale `responses.json`; no `responses.json` ever exists, so there is nothing `--force` would protect |
| setup cell | `get_backend(fixtures=responses_path())` | `get_backend(script=helpers.script, seed=helpers.SEED)`; `run_header(..., backend=backend, n_examples=len(scored))` is the same |
| `measured` cell | follows `backend.mode` | the same line: `Provenance: scripted. Not measured live: a pipeline check, not a Jev result.` |
| `tests/test_helpers.py` | asserts every example's keys equal `replay_key(state, questions)` | asserts the keys are empty and that a fresh `ScriptedBackend(helpers.script, helpers.SEED)` answers the same request identically twice; the scaffolder writes the one test file that fits `--mode`, so neither carries the other's machinery |
| `tests/test_build_fixtures.py` | emitted: guards the refusal, inputs/labels regeneration and the writer | not emitted: no `responses.json` and no refusal logic for these tests to guard |
| validator | `fixtures valid (mode replay)` | `fixtures valid (mode scripted)` |

Write `script` with `rng.random()` only for chance and no clock, global `random` or environment
reads: a script that varies between calls fails the generated test. A closed loop (the state of the
next request depends on the previous action) is built the way [simulation.md](simulation.md)
describes, with the simulator owning the state and the script standing in for the model. The run is
a pipeline check, not a Jev result; the README and notebook say so under their `TODO`s. A scripted
recipe that later records real answers becomes a replay recipe: add the keys and `responses.json`.

## Executing a notebook

`tools/execute_notebook.py <recipe-dir>` runs `notebook.ipynb` with `nbclient` in a fresh kernel and
the recipe folder as working directory, and writes the outputs back in place.

- It builds a copy of the environment without any `JEV_COOKBOOK_*` or `TYPESAFE_*` variable and
  passes it to the kernel explicitly; this process's own environment is never changed, so notebooks
  can be executed in parallel. Starting several kernels at once on Windows can fail with a ZMQ
  "Address in use" error, so the tool starts a fresh kernel once more when the first one does not
  start (never when a cell fails) and waits up to 180 seconds for a kernel to answer. A shell that
  is set up for live calls still runs offline.
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
  - 2: usage error (for example no `notebook.ipynb` in the folder, or `--timeout` below 1: nbclient
    treats 0 as no limit, so the tool refuses it).

  **Known limitation.** "The kernel never started" is recognised by one `jupyter_client` message
  (`Kernel didn't respond`). A kernel that exits at start-up (a broken ipykernel) raises a different
  `RuntimeError`, which prints as a traceback rather than one line. The exit status (1) and the
  unchanged file are the same in both cases, so judge by those.

  Judge success by the exit status, not by an empty stderr: on Windows the tool and the kernel
  print harmless warnings of their own.

**Running live.** The executor never runs live, on purpose, so a committed notebook cannot
contain a live outcome by accident. To run a notebook live, set `TYPESAFE_API_KEY`,
`JEV_COOKBOOK_LIVE=1` and `JEV_COOKBOOK_LIVE_MODEL` in the shell, install the SDK
(`pip install -e ".[live]"`) and Jupyter (not a dependency), and open the notebook from its folder;
or capture answers with the recorder in [live.md](live.md). A recorded recipe states the model
version the API returned, the capture date and N for every number it reports.

The executor itself adds no network guard and no staleness check; the `Notebooks` workflow does
(#69): it re-executes the notebook offline in a network namespace and compares the result with the
committed one, text exactly and figures by what they show, because PNG bytes differ across
platforms and matplotlib or FreeType versions. What that comparison cannot see is in
[notebook-ci.md](notebook-ci.md).

## The template in the catalog

`recipes/_template` is not a catalog slug. `tools/render_catalog.py` only looks up folders named by
catalog slugs, so the template is never counted as published and needs no special case;
`tests/test_template_render.py` pins that. `python -m jev_cookbook.fixtures validate --all` does
include it, which is intended.
