# Recipe template and scaffolder

Every recipe starts from [`recipes/_template/`](../recipes/_template/), a small recipe that
already satisfies the [contract](../CONTRIBUTING.md), and from the command that stamps out a new
folder for it. This page is the reference and the walkthrough; the template's own
[README](../recipes/_template/README.md) carries the same steps on one page.

```bash
python tools/new_recipe.py NN                 # create recipes/NN-slug/ from the catalog (NN is 1 to 100)
python tools/new_recipe.py NN --mode scripted # the same for a scripted or simulator recipe
python tools/execute_notebook.py recipes/X    # run X/notebook.ipynb offline, write the outputs back
```

The catalog has an original track (01–60) and a separate multimodal track (61–100). `NN` denotes
the recipe's rank, not its issue number; slugs use zero-padded prefixes through `99` and the
three-digit prefix `100`. Use the catalog's exact slug.

```python
from jev_cookbook import load_helpers

helpers = load_helpers()  # in the notebook
helpers = load_helpers(Path(__file__).resolve().parent.parent)  # in recipe/tests/test_*.py
```

## What the template is

A router for support messages: one `Choice` (`billing`, `bug`, `account`, `none`) and one rule in
Python. It is deliberately small, so that it can be read in a few minutes and adapted to a recipe.
For the multimodal track it supplies the notebook structure and offline workflow. A builder must
still write visual questions, image or frame fixtures, deterministic Python rules and an
evaluation suited to the recipe's decisions.
Scaffolding makes no live API calls, and the completed notebook remains offline by default with
live inference explicitly opt-in under the [contract](../CONTRIBUTING.md).

| File | Role |
| - | - |
| `notebook.ipynb` | The recipe, executed, with its outputs committed. Nine sections, in a fixed order. |
| `README.md` | The one-page recipe README, plus the builder's walkthrough (a real recipe's README has only the first part). |
| `helpers.py` | `build_state`, `build_questions`, and the rule Python enforces (`route`). |
| `build_fixtures.py` | Writes `fixtures/`; the replay keys come from `helpers.py`, so they cannot drift from the questions. It lives next to the notebook, outside `fixtures/` ([fixtures.md](fixtures.md)). Generating inputs and labels is separate from generating responses: `--force` is needed to overwrite a `responses.json` that already holds a `recorded` answer. |
| `assets/` | Multimodal recipes only (absent from the template): the image files the recipe sends to Jev, PNG or baseline JPEG, each at most 1 MiB, 8 MiB in all, with no metadata, and nowhere else in the recipe. The contract and the check that enforces it are in [fixtures.md](fixtures.md#image-fixtures); how a recipe loads them is in [vision.md](vision.md). |
| `assets-manifest.json` | Multimodal recipes only, beside `assets/`: one entry per image with its hash, size, generator and parameters, licence and the attestations that it is synthetic and holds no real photograph, brand, person or third-party content. Required exactly when `assets/` exists; `build_fixtures.py` should write it with the images. Format, worked example and rules: [fixtures.md](fixtures.md#image-provenance-manifest). |
| `fixtures/` | `inputs.jsonl`, `labels.jsonl`, `responses.json`: 22 examples (10 `validation`, 10 `test`, 2 `demo`), synthetic and deliberately imperfect. |
| `request_budget.json` | The recipe's declared live request count (#213, #368), the one place it is stated: one audited backend, `main`, declaring `requests: 22` and `fixtures: "fixtures/responses.json"`. The setup cell's one `get_backend(...)` is wrapped in `AuditedBackend(..., label="main")`, and a final standalone cell (nested under "What was and was not measured" as a `###` subsection, never a new `##` heading) prints `backend.audit_json()`. The README's `## Switch to live` paragraph is *rendered* from this file by `jev_cookbook.accounting.render_recipe_note`, never typed by hand, and the recipe guard's `readme_budget_note_matches_request_audit` check (#213) compares the declaration, the audited execution and the rendered paragraph against each other for every published recipe. It does not yet run against `recipes/_template` itself (#381); the template's own three were verified to agree when this file was last committed. [backends.md](backends.md#the-declared-count-request_budgetjson) is the full contract; this is the one route a recipe's live request count is stated through. |
| `tests/test_helpers.py` | Tests for the rule, a check that the stored keys match the current question, `test_stored_answers_are_not_all_right` (replay recipes only): re-derives the frozen threshold from `validation` (the `select_confidence_threshold` call written out, or `gate = helpers.<fn>(...)` through a function of the recipe's own `helpers.py` that calls it; the guard finds the test by its name, so keep `test_stored_answers_are_not_all_right` as the prefix) and requires a wrong `test` answer at or above it, so a fixture set that is merely "not all correct" (but has every mistake caught by the gate) still fails, and a test that pins the threshold-selection call's own **objective** keyword against the committed cell source (see "Pin the threshold's OBJECTIVE" above) — a value-only re-derivation does not pin which objective ran. `tools/new_recipe.py` scaffolds a working copy of the stored-answers test, so no recipe has to hand-write it from scratch; the objective pin is adapted per recipe from the template's own worked example. |
| `side_effects.json` | The recipe's statement of its simulated side effects (a `ReviewQueue`, `ActionLog`, `Store`, `Transactor` or `Simulator` write): `{"schema": 1, "sites": {"helpers.submit_reviews": 2}}`, the exact number of places the notebook calls each side-effect function or method, or `{"schema": 1, "none": "why"}`. `tools/new_recipe.py` scaffolds it as a `none` declaration whose reason is a `TODO` placeholder (the template recipe has no simulated side effect, so `none` is what it would declare): rewrite the reason, or replace the file with `sites`, before the recipe is done. The recipe guard rejects a reason that still carries the `TODO`, rejects `none` for a recipe that has a side effect or needs a simulator, and fails a notebook that calls fewer, more or none of what it declares. Schema, keys, `not_side_effects` (bookkeeping only, with a reason per entry), factory-built simulators, the guard's known limits and the two function shapes (a batch fill, a decide-and-apply function) with their test rules: [simulation.md](simulation.md). |
| `tests/test_build_fixtures.py` | Guards `build_fixtures.py` (replay recipes only): refusal without `--force`, `inputs.jsonl`/`labels.jsonl` regenerated from `ROWS` even on a refused run, and the committed `responses.json` byte-identical to what `jev_cookbook.dump_responses` returns (the public form of the serialization the recorder writes with; `jev_cookbook.live._dump` is kept only as a transitional alias, and recipes do not import it). A scripted recipe has no `responses.json` and nothing for these tests to guard, so the scaffolder does not emit this file for `--mode scripted`. |

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

- **The live request count is declared once, audited, and never hand-typed.** `request_budget.json`
  declares `requests: 22` for the one backend the setup cell builds, wrapped
  `AuditedBackend(get_backend(fixtures=responses_path()), label="main")`. A final standalone code
  cell (`### Live request audit`, a `###` subsection of "What was and was not measured", never a
  new `##` heading) prints `backend.audit_json()`, and the README's `## Switch to live` paragraph,
  between `<!-- request-budget:begin -->` and `<!-- request-budget:end -->`, is *rendered* from
  the declaration by `jev_cookbook.accounting.render_recipe_note` — never typed, never a hand-written
  count or cap. This is the one route a recipe states its live request count through; see
  [backends.md](backends.md#the-declared-count-request_budgetjson) and
  [live.md](live.md#budget-guard) for the contract and `readme_budget_note_matches_request_audit`
  (#213) in `tests/test_recipe_guard.py` for the check.
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
- **The gate comes from the shared helper, and its reason comes from a live branch.** A rule that
  compares a confidence with a bound freezes the bound with `select_confidence_threshold`, imported
  by name and used (in the notebook, or in a `helpers.py` wrapper the notebook calls), never a
  constant; the guard check `confidence_gate_from_shared_helper` fails a recipe that does not. The
  reason string `confidence below the threshold` is produced by the branch that comparison controls
  (not a comment, a docstring or an unused constant), that branch's function is reachable from the
  notebook, and a committed output shows a review the rule produced: print the result's `.reason` for
  an example the gate sends to review, not the words (words typed into the cell, or bound to a name in
  any cell and printed from another, are not evidence). Keep the reason in the comparison's own
  function, on the branch it controls or behind a flag derived from it; a private helper the branch
  calls to build the reason is not seen. A rule with no confidence-gated review at all (a margin, a
  budget, a top-k cut; validating that an argument lies between 0 and 1 is not a gate) does not add
  one to satisfy the guard; the guard's `GATE_FREE_DESIGNS` list names the recipes that have none, a
  new entry is a foundation decision, and both checks are not applicable to a recipe on it.
- **Pin the threshold's OBJECTIVE, not only the value it lands on.** `select_confidence_threshold`
  takes exactly one of `target_accuracy` or `min_coverage`; `select_threshold` takes an `objective`
  of `"f1"`, `"recall_at_precision"`, or `"precision_at_recall"`. Neither a printed f-string beside
  the call (`print(f"objective: select_confidence_threshold(..., min_coverage=0.75)")`) nor a test
  that only re-derives the resulting *value* pins which objective the notebook actually used: the
  printed literal is hand-written and nothing compares it to the call, and a value-only test pins
  the objective only if no other objective can reach that same value on this recipe's own pool —
  which is not something a value-only test checks, and two objectives have been found to coincide
  on a real recipe's data. Parse the committed cell source instead -- the template's own
  `tests/test_helpers.py` has a worked example (its last test function, named for exactly this)
  -- and tie an assertion to the keyword or objective string the call actually uses: a keyword
  swap then changes the cell's committed source, so the assertion notices regardless of what
  value the swapped-in objective happens to select on this pool. If the selection lives behind
  a `helpers.py` wrapper rather than inline in the notebook cell, pin the wrapper function's own
  source instead (`inspect.getsource(helpers.<wrapper>)`), for the same reason. The guard check
  `threshold_objective_pin` enforces this, fail closed, over every recipe with a threshold
  selection. What the check credits is what an unconditional `assert` *claims*, derived rather
  than enumerated. Three routes are credited, and only these:

  1. **A direct pin.** The assertion says the spelling is **present** in a value derived from
     the committed source: a read of the committed `notebook.ipynb` or `helpers.py` (by
     `read_text()`, `read_bytes()`, `open(...).read()`, `with open(...)`, any other `open` /
     `.open` / `.read` / `.readlines` call that names the file, or a function in the same test
     file that does one of those), or `inspect.getsource(helpers.<fn>)`, or a call to a
     `helpers.py` function whose own body makes the selection call. A path under `tmp_path` is a
     copy, not the committed file, so a read of it does not count.
  2. **An extraction.** `name = _your_helper(source, ...)`, through a function defined in the
     test file, followed by `assert name is not None`. That is the only truthiness check
     credited here: a bare `assert name`, or any other check, is not. The strings in the call
     are what is pinned.
  3. **A production tie** (recipe 28's shape, which reads no file). A `helpers.py` function
     whose body makes the real selection call is compared with `==` to a local re-derivation
     computed with an explicit keyword, and a separate `!=` assert shows that re-derivation
     differs from a sibling computed with a different objective.

  For a direct pin, `not`, `is False`, `.count(...) == 0`, an `if`/`else` branch that asserts
  nothing, and an `or` with a vacuous operand are read for what they claim, so none of them
  counts as a pin. So is a needle that is also *typed into the test function* as part of the
  value it is compared with: inline (`source + " min_coverage"`, `kws.get("objective",
  "min_coverage")`), as a `+` of adjacent literals (`"min" + "_coverage"`), through a variable
  the value was built from, or put into a container with `.append(...)`, `.extend(...)`,
  `.update(...)` or `name[key] = ...`. The check looks at text typed in the function; it does not
  follow a needle that reaches the value any other way (a module-level name, a parameter, a
  computed string). A name counts as the read only if every binding of it is the read (or wholly
  derived from it): once it is also bound by `+=`, a `for` target, unpacking, `:=` or a
  hand-typed value, it does not. `all(...)`/`any(...)`/`len([...]) > 0`/`sum(...) > 0` over the
  committed source do count (an `all(...)` needs an iterable that is visibly non-empty and bound
  once, since it is vacuously true over nothing).

  Only asserts that really run count. They are the top-level statements of a `test_` function
  that pytest collects: a module-level function, or a method of a top-level class named `Test*`
  that defines no `__init__`, none of them marked `skip`/`skipif`/`xfail` (on the function, on the
  class, or by a `pytestmark` in the class body or the module), in a file with no top-level
  `pytest.importorskip(...)` or `pytest.skip(..., allow_module_level=True)`, and not nested in
  another function. Within it they are the statements directly in the function body, those inside
  `with open(...)`, and those in a `for` over a non-empty literal tuple/list/set (no `else`, no
  `break`/`continue`/`return`), only up to the first `return`, `raise` or
  `pytest.skip`/`xfail`/`exit`/`fail` call. An assert under `if`, `try`, any other loop, or a
  context manager such as `pytest.raises` is not credited.
- **`evaluate_selective` reports the same split as the rule only when the rule's only review
  branch is that confidence gate — `route` here has three, so it is not that rule.**
  `helpers.py::route` sends a ticket to `review` for any of three reasons, in this order:
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

  **A deferral counts toward review; a complete-answer fallback counts toward coverage, even one
  that is also noted in a backlog.** The distinction is not "did this write anywhere", it is
  "did the rule answer the question it was asked, or ask a person to answer it instead". An
  `unknown` result routed to the `ReviewQueue` for a person to pick the real answer is a
  deferral — it asks the same question again — so it counts toward
  [review](glossary.md#review), never toward [coverage](glossary.md#coverage), however
  confident the answer that produced it. A rule that resolves an example to a genuine final
  answer and *separately* notes it in a backlog for an unrelated follow-up (an unmatched asset
  backlogged so someone can decide later whether a new canonical record is needed — a different
  question from "was this a match") still counts that example toward coverage: the rule already
  answered the question that was asked, and the backlog entry is not a review of that answer.
  Build `accepted[i]` from which of these the rule actually did, never from a confidence alone,
  for a rule with any branch that does not depend on `min_confidence`.
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
  additionally re-labelled as a selection step the way a printed number is. This rule covers the
  evaluation chart helpers — `plot_confusion_matrix`, `plot_risk_coverage`, `plot_threshold_sweep`
  — each of which summarises a whole split; it does not reach `plot_answer_probabilities` shown
  for one answer up close (the template's own `title="One Choice answer"`), which is neither a
  pipeline check nor a selection step on an aggregate and so need not carry one.
- **A number the selection forces says so.** A `validation` number that is fixed by how the threshold was chosen cannot come out otherwise, and labelling it "a selection step" says where it came from, not that. With `target_accuracy=1.0` the threshold is chosen so every answer that names a queue and clears it is right, so "right among those routed automatically" is all of them on `validation` by construction (and a risk of 0.0000 likewise). The template's `evaluation-md` says so in a short passage written for this template's objective; a recipe replaces it with what its own selection forces and does not copy it verbatim (under `min_coverage=x`, for example, coverage of at least x on `validation` is forced, and a different sentence is true), naming every `validation` number so forced, or saying that none is. (#222 gap 3; the published recipes that carry an undisclosed forced metric are swept separately.)
- **A confusion-matrix column is as wide as the widest label or the widest count.** The template's `evaluation-matrix` cell sizes the columns with `max(width, len(str(matrix.matrix.max())))`, because a format spec never truncates and a count with more digits than the longest label would otherwise push its row out of line with the header. `tests/test_template_matrix_alignment.py` runs that cell on counts wider than every label.
- **Nothing path-like is printed.** The hygiene scan fails notebook outputs that contain absolute
  paths, usernames or environment dumps.
- **`Noul` propositions are statements** that can be true or false. The contract is stricter than
  TypeSafe's documentation, which also shows questions. **A recipe that asks more than one `Noul`
  proposition about the same state needs its fixture set to carry three more things, beyond what
  a single proposition needs:**
  - a gold-true row **and** a gold-false row for **every** proposition, in **every** scored
    split — `validation` and `test`, the two scored splits in
    [fixtures.md](fixtures.md#splits) — not only the one used to select a threshold. Without one
    in `validation`, `select_threshold` has no example of that value to choose a threshold from;
    without one in `test`, the frozen threshold is reported on a split with no positive (or no
    negative) for that proposition. Either way the result is degenerate before any model ever
    answers, which is a fixture gap wearing the costume of a model limitation.
    `tests/test_recipe_guard.py` checks this per split and per proposition, so a `test` split
    left one-sided fails CI even when `validation` is fully covered;
  - at least one row for **every truth combination** the use case admits — both propositions
    true, both false, and each true alone — because a group of propositions only shows its own
    composition in the states that distinguish it from asking the same questions one at a time,
    and a fixture set built from complementary groups alone can never reach them;
  - at least one row, for **each** proposition, where that proposition's own tag is what changes
    the composed outcome — a proposition no committed row depends on is decorative rather than
    load-bearing, however many labels the question carries.

  The first two do not imply the third: a fixture set can carry a positive and a negative example
  of every proposition and cover every combination, and still never let one proposition's tag
  decide anything.
- **Per-item order comes from a seed key, never from `random.shuffle` or list position.** This
  template's one `Choice` lists its options in a fixed, meaningful order, so it needs none of
  this, and it prints no first-option or other position statistic either: offline, the share of
  gold answers on the first listed option measures the fixture author and not any model, so it
  is never offered as a check on a model's first-option lean (CONTRIBUTING.md section 2). A
  recipe that ranks or compares several candidates, and does not want their shown order to
  come from the data itself (which one is listed first, which side of a pairwise comparison an
  item sits on), derives it from `jev_cookbook.fixtures.stable_permutation` /
  `stable_shuffle` ([fixtures.md](fixtures.md#per-item-option-order)) instead: a seeded
  Fisher-Yates permutation built from nothing but `random()`, so the same seed key gives the same
  order on every Python version.
- **A fixture builder uses only exactly-specified float operations.** `build_fixtures.py` is
  asserted byte for byte against the committed `responses.json` (`tests/test_build_fixtures.py`),
  on Python 3.10 and 3.14. Accumulate floats with a left-to-right loop, not `sum()` (CPython 3.12
  changed `sum()` over floats to compensated summation, so the two legs can differ in the last
  bit), and build a power by repeated multiplication, not `float ** int` (the C library's
  `pow()` is not pinned across builds). Rounding the stored value also hides a difference, but
  prefer a construction that is deterministic to one that truncates its output. The measured
  example, and the other operations to avoid, are in [fixtures.md](fixtures.md#floats-in-a-generator).
  The template's own `build_fixtures.py` stores hand-typed probabilities and does neither.
- **Neighbour links are folder links, and every linked neighbour already exists on `main`.**
  "Next steps" links a neighbouring recipe as `../NN-slug/`. `tools/render_catalog.py` renders
  each catalog row as a bare `| NN | **title**<br>use_case | category | decision | status |` with
  no id or anchor, so there is no more stable target in the generated README to link to instead.
  Link only a recipe whose `notebook.ipynb` is already committed on `main`: a folder link to one
  that is not yet published would 404 on GitHub, and that forward link is not allowed — pick a
  different, already-published neighbour, or name none and say so in one sentence.
- **A "Next steps" exercise names a verified value and quotes no counterfactual number.** Tell the
  reader which parameter to change, to a value you ran and confirmed moves the quantity you ask
  them to watch (recipes 38 and 40 each shipped a floor that moved nothing), which quantity to
  watch, and which way it moves; do not quote the resulting figures, which describe a run the
  notebook never performs and so are pinned by nothing. If a figure is worth quoting, print it
  from a labelled side-computation cell or assert it in a test (no published recipe is the model
  for this yet; recipe 40's Next steps prints one illustrative figure but its prose still quotes
  others that no committed cell prints, and is being brought into line under #259), so it is in committed output or under a
  test. The direction sentence follows the helper, not the parameter's name: raising
  `select_confidence_threshold`'s `min_coverage` can only lower the threshold or leave it
  unchanged, and the response is piecewise constant, so test the exercise by running it
  ([evaluation.md](evaluation.md#selective-prediction)).
- **A Noul confidence gate is measured on your own composition, split by side.** The gate is a
  two-sided band, `(1 - g)/2 < p < (1 + g)/2` goes to review; whether it changes any outcome of
  your rule is not derivable from `t` and `g`. Run the rule's own decision function over a grid
  with and without the gate, print the count of changed outcomes at or above and below the
  business threshold, and state in prose which side the gate acts on.
  This assumes one Noul and one threshold; several gated Nouls (recipe 06), a rule with no
  threshold but 0.5, and a decision function that takes an answer object rather than `p` are
  covered by "Scope of the measurement" ([evaluation.md](evaluation.md#noul-three-path-pattern)).
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
- **A fallback option may be a final result at any confidence only when it passes a three-part
  test.** CONTRIBUTING.md section 4 states it; this is the worked contrast between the two shapes
  that split the cookbook's fallback-exempting recipes, so a reader can apply the test without
  re-deriving it.

  | | `route`'s `none` (this template) | a wrong `allowed` → `ignore` | a wrong `no_match` backlogged, not acted on |
  | - | - | - | - |
  | (a) complete answer, not a deferral? | yes — `none` is a real judgment ("no option fits") | yes — `allowed` is a real judgment | yes — `no_match` is a real judgment |
  | (b) records no action? | yes — this template simulates no container at all | **no** — recorded to the `ActionLog` | yes — printed to a backlog, labelled a note, no action taken |
  | (c) wrong leaves nothing beyond the missed item? | yes — nothing is simulated either way | **no** — a published violating message is harm beyond the missed item | yes — one item left unlinked, exactly what review would also have left pending |
  | passes all three? | yes — exemptable (gated anyway here, also compliant) | **no — must be gated** | yes — exemptable |

  `unknown` → "manual triage" and `needs_review` fail part (a) outright: each asks a person to
  decide the same question again, so each is a deferral, always a review outcome in the
  `ReviewQueue`, never final at any confidence, and each counts toward review rather than
  coverage. A fallback with no simulated container at all (`no_suitable_rewrite`, `not_stated`,
  `insufficient_evidence`, `no_clarification_needed` → `proceed`) passes (b) trivially, the same
  as `none` here. `route`'s own fallback, `none`, passes all three parts, but this template still
  sends it to `review` like every other unconfident or unrecognized case rather than claim the
  exemption — the test names when the exemption is *available*, not when it is required; gating a
  qualifying fallback anyway is always compliant. A fallback that fails any part goes through the
  same confidence gate as every other option before whatever it does runs. A recipe that does
  claim the exemption prints the gated counterfactual — what `evaluate_outcomes` would report, on
  the split it is reporting (`test`), with the fallback gated too — beside the numbers it actually
  reports, so a reader can see what the exemption costs or buys; see the
  `evaluate_selective`/`evaluate_outcomes` bullet above for where that counterfactual comes from.

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
  `TODO` in each markdown cell. The setup cell's one `get_backend(...)` is already wrapped
  `AuditedBackend(..., label="main")`, and a final standalone cell, already complete and
  needing no `TODO`, prints `backend.audit_json()`.
- `README.md`: the recipe README with the same fields, the run commands for this slug, and a `TODO`
  where you write what it teaches. Its `## Switch to live` section already holds the rendered
  budget paragraph for `request_budget.json`'s declaration, between the
  `<!-- request-budget:begin -->` / `<!-- request-budget:end -->` markers, plus a `TODO` that says
  how to keep the two in step as you add `decide()` calls while writing Evaluation (step 5).
- `helpers.py`, `build_fixtures.py`: skeletons that raise `NotImplementedError("TODO ...")` until
  you write them.
- `request_budget.json`: declares exactly the one `decide()` call the skeleton notebook's own
  `answer` cell makes (`requests: 1`, `fixtures: "fixtures/responses.json"`, or `fixtures: null`
  for `--mode scripted`) — already self-consistent with the audited setup cell and the rendered
  README paragraph above, with nothing to edit yet. As `decide()` calls are added while writing
  Evaluation (step 5), update this file's declared count (and `distinct`/`at_most` where they
  apply) to match, then regenerate the README paragraph the same way
  ([backends.md](backends.md#the-declared-count-request_budgetjson)); step 8's checks fail a
  mismatch, so this cannot be forgotten.
- `side_effects.json`: a `none` declaration whose reason is a `TODO` placeholder. A recipe with no
  simulated side effect rewrites the reason; a recipe that writes to a `ReviewQueue`, `ActionLog`,
  `Store`, `Transactor` or `Simulator` (every recipe flagged `needs: simulator`) replaces the file
  with `sites`. See the `side_effects.json` row of the table above and [simulation.md](simulation.md).
- `tests/test_helpers.py`: a `TODO` skeleton for the rule's own test, plus two guards that already
  work once `helpers.py`, `build_fixtures.py` and the fixtures exist, with no `TODO` of their own:
  the replay-key test (which assumes one request per example — `example.replay_keys` holds a
  single key — adapt it when an example needs a dependent second request, a later request with
  its own key) and, for a replay recipe, `test_stored_answers_are_not_all_right` (re-derives the
  frozen threshold and requires a wrong `test` answer at or above it).
- `tests/test_build_fixtures.py`, for a replay recipe only: the three guard tests already working
  against your `build_fixtures.py` once you have filled in `ROWS` and `answers_for` (step 4);
  nothing here is a `TODO`. A `--mode scripted` scaffold does not get this file.

Every place you must write is marked `TODO`, so `grep -rn TODO recipes/NN-slug` lists what remains;
a finished recipe prints nothing. The command validates that `NN` is a whole number from 1 to 100
(exit status 2 otherwise), exits with status 1 and a message when the recipe is not in the catalog,
and **never overwrites**: if `recipes/<slug>/` exists it changes nothing and exits with status 1.
`--catalog` and `--recipes-dir` point it elsewhere; the tests use them with temporary copies.

An entry with `issue: null` can be scaffolded locally. The command prints a notice that a real
issue must be assigned in the trusted base catalog before opening a recipe pull request. It does
not invent an issue link: ranks 61–100 are multimodal recipe positions, while repository issues
61–100 already serve foundation and tracking work. Assigning an issue in a recipe branch's head
catalog is insufficient; the scope guard reads assignments from the base.

## From scaffold to a running notebook

1. Create `recipe/NN-slug` from `main`; `python -m venv .venv`, activate, `pip install -e ".[dev]"`.
2. `python tools/new_recipe.py NN`.
3. Write `helpers.py`: the state, the questions (options built by Python), and the rules Python
   enforces. Write a test for each rule in `tests/test_helpers.py`; run `pytest recipes/NN-slug`.
   If `helpers.py` trains a baseline with scikit-learn (the `ml` extra), install the extra too
   (`pip install -e ".[dev,ml]"`): the `Tests` jobs install it, so it is available in `helpers.py`,
   `build_fixtures.py` and `tests/`, as well as in notebook cells. Those jobs do not use the
   notebook constraints (Python 3.10 cannot install them), so a test asserts properties of the
   trained model, never numbers that depend on the scikit-learn version
   ([development.md](development.md#continuous-integration)).
4. Fill `ROWS` and `answers_for` in `build_fixtures.py`, run
   `python recipes/NN-slug/build_fixtures.py`, then
   `python -m jev_cookbook.fixtures validate recipes/NN-slug`. Generating `inputs.jsonl` and
   `labels.jsonl` is separate from generating `responses.json`: once a response is `recorded`,
   rerunning the script refuses to overwrite it unless you pass `--force`.
5. Work through `notebook.ipynb` section by section. The scaffold's setup, state, question and
   answer cells already run once steps 3 and 4 are done; replace each `TODO` and fill the
   `# TODO` code cells. Copy the template's evaluation cells as a starting point. As Evaluation
   adds more `decide()` calls, update `request_budget.json`'s declared `requests` (and `distinct`
   or `at_most` where they apply) to match, then regenerate the README's rendered paragraph:
   `python -c "from jev_cookbook.accounting import render_recipe_note as r;
   print(r('recipes/NN-slug'), end='')"` and paste its output between the
   `<!-- request-budget:begin -->` / `<!-- request-budget:end -->` markers
   ([backends.md](backends.md#the-declared-count-request_budgetjson)). Leave the final
   `print(backend.audit_json())` cell as the scaffold wrote it.
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
9. Once the slug has a real assigned issue in the trusted base catalog, open the pull request
   with `Closes #N` naming that issue, not the recipe rank. If `issue` is still `null`, keep the
   work local until the assignment is available. Do not run `tools/render_catalog.py` or edit
   the root `README.md`: the `Catalog (README is current)` check is expected to be red until the
   integration worker has run
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
| setup cell | `AuditedBackend(get_backend(fixtures=responses_path()), label="main")` | `AuditedBackend(get_backend(script=helpers.script, seed=helpers.SEED), label="main")`; `run_header(..., backend=backend, n_examples=len(scored))` is the same |
| `request_budget.json` | `"fixtures": "fixtures/responses.json"` | `"fixtures": null` (nothing to replay); `requests: 1` either way at scaffold time |
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
  "Address in use" error, so the tool starts a fresh kernel again when one does not start (never
  when a cell fails): up to four starts for a kernel that exits at once, two for one that is alive
  but silent, which is waited for up to 180 seconds. Each retry prints a line to stderr, and a start
  that keeps failing fails the run. A shell that is set up for live calls still runs offline.
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
