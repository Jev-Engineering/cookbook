# Notebook CI

What the `Notebooks` workflow (`.github/workflows/notebooks.yml`) and the `Scope` workflow
(`.github/workflows/scope.yml`) check on every pull request and every push to `main`, how, and
what they cannot see. It uses no secrets and never reaches the
TypeSafe API. Setup and the other checks are in [development.md](development.md); the recipe
contract is [CONTRIBUTING.md](../CONTRIBUTING.md).

## The checks

| Check name | Required | What it does |
| --- | :---: | --- |
| `Notebooks (execute)` | yes | One stable name that summarises the per-recipe jobs: green when discovery succeeded and every selected notebook passed (or none was selected). |
| `Notebook (<recipe>)` | no | One job per recipe folder (the names change with the recipes, so they cannot be required one by one). Executes the notebook offline, compares it with the committed one, scans the fresh copy. |
| `Notebooks (discover)` | no | Chooses the recipes to run and passes them on as a matrix. |
| `Fixtures (validate)` | yes | Every folder under `recipes/` must have a `fixtures/` folder and must pass the fixture validator. |
| `Scope (recipe pull requests)` | yes | The allowlist for recipe pull requests, in its own workflow (`scope.yml`). It runs on `pull_request_target` (opened, synchronize, reopened, edited), so the workflow file and the script both come from the base branch, and **re-runs when the description or the base branch is edited**, because it classifies a pull request by its closing references: a result that survived a later `Closes #N` would be stale. The `Notebooks` workflow does not re-run on edits. See "The scope check". |

Require all three named ones in branch protection, but they are not equivalent for a tool that also
judges current `main`: `Notebooks (execute)` and `Fixtures (validate)` have `push: branches:
[main]`, so they do appear, and must be `success`, on both a pull request head and on current
`main`. `Scope (recipe pull requests)` runs on `pull_request_target` only (see "The scope check")
and by design never appears on a commit of `main` — a commit lands on `main` only by merging a
pull request, and `pull_request_target` does not fire for a push. Treat it as required on the pull
request head only: pass `Notebooks (execute)` and `Fixtures (validate)` to
`tools/check_merge_readiness.py --require-check` (see [merge-readiness.md](merge-readiness.md)),
and never `Scope (recipe pull requests)`, because the helper demands presence on current `main` as
well as on the head and would fail forever otherwise. The helper cannot currently express "required
on the head, not on `main`"; until it can, `Scope` is verified by reading the pull request head's
own `statusCheckRollup` directly, not through `--require-check`. The other check names (`Lint
(ruff)`, `Catalog (README is current)`, `Tests (py3.10)`, `Tests (py3.14)`, `Hygiene (secrets and
notebook outputs)`) are unchanged.

### After this merges

An un-dispatched `pull_request_target` workflow is silent, not red: GitHub simply never creates a
run, so a broken trigger shows as a missing check rather than a failing one. Before any recipe pull
request relies on `Scope (recipe pull requests)`, or it is added to branch protection, the first
pull request opened after this merges must show, read directly rather than assumed:

1. a `Scope` run exists with `event: pull_request_target` (`gh run list --workflow Scope`);
2. that run's check appears on the pull request's **head commit**, under exactly the name `Scope
   (recipe pull requests)`, in `statusCheckRollup`;
3. a path outside the allowlist on that pull request is rejected (`REJECT:` with the path);
4. editing the pull request's description re-runs the check.

Until all four are observed, the allowlist is enforced by review only, exactly as it was before
this pull request: a reviewer rejects a `.github/` or out-of-scope change in a recipe pull request
by hand, the same backstop `docs/notebook-ci.md` already names for the check once it does run.

## Which notebooks run

`python tools/notebook_ci.py matrix` lists the folders with a `notebook.ipynb`, `_template`
included.

- **A push to `main`** runs the recipe folders changed since the previous tip of `main`
  (`github.event.before`) when the push touches nothing outside `recipes/<folder>/` and `README.md`
  (a recipe merge runs one notebook). It runs every notebook when anything else changed (shared
  code, tools, workflows, docs, the constraints file, anything a recipe reads). The diff is
  two-dot (`before..after`, the two trees). **A forced push is not trusted to say what changed**:
  GitHub sends the old tip as `before` (not zeros) and a three-dot diff would start from the merge
  base, so a rewound `main` selects nothing and a rewritten one selects the wrong folders. The
  workflow therefore runs every notebook when `github.event.forced` is true, and
  `matrix --push` also falls back to every notebook when `before` is not a commit in the clone (a
  first push) or is not an ancestor of the new tip (a rewind or a rewrite that `forced` somehow did
  not flag). `tests/test_notebook_ci_gates.py` pins a rewound and a rewritten `before`.
- **A weekly scheduled run** (Mondays, 04:17 UTC, on the default branch) runs every notebook. It
  exists so that a `main` run that was skipped, cancelled or lost, whose recipes the push selection
  would never revisit, is found within a week.
- **A manual run** (`workflow_dispatch`) has a `full` input. Left true (the default) it runs every
  notebook; false runs the recipe folders changed by the latest commit, by the same rule.
- **A pull request** runs only the recipe folders it changes, provided every changed path is inside
  a `recipes/<folder>/` or is exactly `README.md`. A recipe pull request is limited to that by the
  scope check, so one recipe's pull request does not re-run sixty notebooks.
- A pull request that changes anything else (shared code, tools, docs, workflows, the template's
  neighbours) runs every notebook, because shared code can change any recipe's result. **That
  includes a docs-only foundation pull request**: any path outside `recipes/` and `README.md`
  selects every notebook, `docs/**` included. This is an accepted cost (see "Run time and cost"),
  because telling which documents a notebook reads would be a second source of truth to maintain.
- A change that only regenerates `README.md` runs none, and `Notebooks (execute)` is green.

Runs on `main` are never cancelled or replaced by a newer push (each push has its own concurrency
group), because the selection is relative to the previous tip: a dropped run would leave its recipes
unverified. A new push to a pull request cancels that pull request's older run.

A folder name that is not `NN-slug` or `_template` stops discovery: names go into a matrix and a
command line.

## Offline, with no key and no network

Each job installs the package with the `ml` extra (core dependencies plus scikit-learn, for the
recipes that train a baseline; Python 3.14) under `.github/constraints-notebooks.txt`, and then runs
`tools/execute_notebook.py` on a copy of the recipe folder, so the committed file is never
rewritten. Installation is the last step that may use the network, so installing an extra does not
weaken the sandbox. The `live` extra is never installed: a recipe runs offline. A recipe whose README
names any other extra needs a foundation change to the install line first, because a recipe pull
request cannot touch `.github/`. Three layers keep the run offline, and the third is the one that
enforces it:

1. **No key, no live switch.** The executor strips every `JEV_COOKBOOK_*` and `TYPESAFE_*` variable
   from the kernel environment (case-insensitively), and CI sets none. This alone is not a network
   guard: a cell can set the variables itself.
2. **Python-level guard** (`tools/netguard/sitecustomize.py`, put on `PYTHONPATH`). Python imports
   it at start-up, in the kernel too. Any `connect`, `connect_ex` or `sendto` to a non-loopback
   address, and any name resolution of anything but `localhost` and loopback addresses, fails at
   once with `NetworkBlocked` (an `OSError`) saying that a recipe must run offline. Loopback and
   Unix sockets stay open because the kernel talks to the runner over loopback. **It is a readable
   error for an honest mistake, not a sandbox.** It is bypassable: `_socket.socket` used directly,
   `importlib.reload(socket)`, calling the unpatched method through `super()`, `sendmsg`,
   `getnameinfo`, native code that opens its own sockets, and a child process started without
   `PYTHONPATH` (or with `python -I`) all go past it. Do not rely on it for anything.
3. **OS-level guard: the enforcement.** The execute step runs inside a Linux network namespace
   (`unshare --net`) that has a loopback interface and nothing else, and drops root privileges
   inside it with `setpriv --no-new-privs`. The runner user has passwordless `sudo`, and without
   `no_new_privs` a cell could `sudo nsenter` back into the host's network namespace; with it `sudo`
   cannot gain root, so the cell has no way out. The namespace, not the Python guard, is what stops
   a cell from reaching the network: it stops every route above, `curl`, child processes and native
   code alike. The guard self-test step asserts that `no_new_privs` is set and that `sudo -n true`
   fails from inside the sandbox. The step before it runs a self-test in the same kind of namespace (an IPv4 connect, an
   IPv6 connect and a name lookup must all fail, loopback must work) and fails the job if the
   namespace is not isolating, so a guard that silently does nothing cannot pass.

The guard applies to replay, scripted and simulator recipes alike. The tests in
`tests/test_notebook_ci_netguard.py` run notebooks through the executor with the guard and show
the blocked attempts: a raw `urllib` call to `https://api.typesafe.ai/`, `socket.create_connection`
after the cell has set `JEV_COOKBOOK_LIVE=1` itself, and (when the optional SDK is installed) a
real `LiveBackend.decide` call. Each ends the executor with exit status 1 and the message
`network access is blocked while cookbook notebooks run in CI`.

The executor runs with the recipe folder as the working directory, as `execute_notebook.py` always
does.

## Protecting the checks from the notebook under test

The network guards stop a cell reaching the outside world; they say nothing about the checkout the
job runs in. The kernel is started as the runner user (`setpriv` only drops privileges inside the
network namespace, not filesystem permissions), so a cell has ordinary write access to the whole
`$GITHUB_WORKSPACE`, not only the scratch copy of the recipe it was given to run in — including
`tools/check_notebook_fresh.py`, `tools/check_hygiene.py` and the committed `notebook.ipynb` the
checks read afterwards. Fix round 2 made the matching argument for the scope check ("a pull request
cannot edit the rule that judges it"); the notebook job has the same hole, by accident as much as on
purpose (a cell that saves a file with a relative path climbing out of the recipe folder silently
rewrites whatever it lands on). Two layers close it, and the second is the one that enforces it:

1. **The checks and the committed notebook are frozen before execution runs**, not read from the
   checkout afterwards. The `Notebook (<recipe>)` job copies `tools/check_notebook_fresh.py` and
   `tools/check_hygiene.py` to `$RUNNER_TEMP`, and reads the committed notebook with
   `git show HEAD:recipes/<recipe>/notebook.ipynb` into `$RUNNER_TEMP` rather than from the working
   tree, before the execute step runs. Both checks afterwards run from those frozen copies. A cell
   that rewrites the checkout's `tools/` or `recipes/<recipe>/notebook.ipynb` therefore reaches
   nothing the checks actually use.
2. **`git status --porcelain` must be empty right after execution — the enforcement.** Freezing
   two files is not a proof that nothing else in the checkout was touched, so a step immediately
   after the execute step fails the job if the working tree changed at all. This is what turns an
   unanticipated write (a relative path that climbed out of the recipe folder, say) into a visible,
   named failure instead of a silently tampered result; it is not bypassable by writing somewhere
   the freeze step did not anticipate, the way freezing two specific files would be on its own.

The documented local commands in [development.md](development.md#running-ci-on-one-recipe) mirror
both steps, so running the sequence by hand gives the same guarantee CI does.

## The staleness check

`python tools/check_notebook_fresh.py <committed> <fresh>` compares the notebook in the repository
with the one the job just produced from scratch. Exit 0 means they agree. The rules, in order:

1. **Failures in either file.** Any output with `output_type` `error` (what a cell tagged
   `raises-exception` commits; the executor exits 0 for such a cell, so the check must catch it) and
   any `stderr` stream output are problems, in the committed notebook and in the fresh one, even
   when the two are identical. So is a cell tagged `skip-execution`: it is nbclient's own default
   for `skip_cells_with_tag`, `tools/execute_notebook.py` does not change it, and a cell with this
   tag is never executed at all, so whatever it commits (fabricated or merely stale) survives
   unchanged into the "fresh" copy and a presence-only, or an equality-only, comparison would call
   the two sides a match. The tag is rejected outright, whether or not the cell has any output.
2. **One normalisation.** Every `outputs[*].data["image/png"]` value is replaced by a marker, so a
   figure must be present on both sides in the same place. Nothing else is normalised. The rest of
   the two notebooks, parsed as JSON, must be equal: sources, ids, metadata, execution counts,
   `text/plain`, streams, tables, every other output type (including `image/jpeg` and
   `image/svg+xml`). The executor makes these byte-stable (`coalesce_streams`, no timings, fixed
   metadata, LF); differences are reported as `notebook.cells[i].outputs[j]...: committed X, fresh
   Y`, at most a dozen.
3. **The figures are compared by what they show.** PNG bytes differ with the matplotlib version, the
   platform even at one version, and the pixel size, so equal bytes are not required, but ignoring the
   images would let a changed teaching chart pass. Each pair is therefore compared as follows
   (`compare_png`):
   - equal bytes are equal;
   - otherwise both images are flattened onto white, their aspect ratios must agree within 8%, and
     both are shrunk with a box filter to a fixed grid of 64 by 48 cells, so the pixel size does not
     matter;
   - a cell is *unmatched* when no cell of the other image within one cell of it (a 3 by 3 window) is
     within 30 of 255 in every colour channel. The window forgives what rendering does: edges move by a
     pixel or two and the plot area rescales by a few percent, which leaves a thin line of unmatched
     cells along every hard edge;
   - the figures differ when a 2 by 2 block of cells is unmatched, in either direction. A line along an
     edge is never a block; a changed bar or a recoloured highlight is, and so is a changed heat-map
     cell when the cell is larger than a 2 by 2 block of the grid (a 3 by 3 confusion matrix: yes; a
     20 by 20 heat map: no).

   The constants (`GRID`, `SHIFT`, `LEVEL`, `ASPECT_TOLERANCE` in `tools/check_notebook_fresh.py`)
   were calibrated on the template's two figures drawn by two matplotlib versions (3.10.9 on Python
   3.10 and 3.11.2 on Python 3.14, whose confusion matrices differ in pixel size, 664 by 600 against 647
   by 602) and on probe charts drawn with the cookbook's own plotting functions, at two versions each.

| Probe, drawn at both versions | Unmatched 2x2 blocks | Result |
| --- | ---: | --- |
| same chart, other version (9 bar and heat-map charts, the template's two figures) | 0 | match |
| same charts at 72, 100, 131 and 200 dpi (tests) | 0 | match |
| a bar moves by 5, 8, 10, 15 percentage points | 5, 13, 19, 42 | differs |
| the highlighted option changes | 206 | differs |
| a heat-map count moves to another cell | 360 | differs |
| a diagonal heat-map count changes | 615 | differs |
| a bar moves by 2 or 4 percentage points | 0 | passes |
| one word of the title changes | 0 | passes |

**What the figure comparison cannot see.** It compares areas of colour, not text, and it forgives
anything thin by construction (the 3 by 3 window and the 2 by 2 block rule). These pass undetected:

- a changed title, axis label, tick label or in-cell number that does not change a coloured area;
- a bar that moves by a few percentage points (less than about 5% of the plot height);
- **a moved or reshaped line or curve**, such as a recall curve moved by a few hundredths;
- **a moved reference or threshold line** (`axvline`, `axhline`, the `chosen` marker of
  `plot_threshold_sweep`, the `reference_risk` line of `plot_risk_coverage`): a threshold line moved
  from 0.5 to 0.6 and a reference risk moved from 0.10 to 0.15 both pass;
- **moved markers and scatter points**: 30 of 300 points shifted by 1.5 standard deviations passes,
  and a marker moved by 10% of the axis passes;
- **a small heat-map cell**: one cell of a 20 by 20 heat map changed from v to 1-v passes;
- any change smaller than a 2 by 2 block of the grid (about 3% of the figure's width and 4% of its
  height).

A line chart is therefore guarded mainly by the exact comparison of the text outputs, not by the
picture. A recipe that draws a curve, a threshold or a reference line should also print the numbers
it plots (rounded: a full-precision `repr` of a transcendental result can differ in the last digit
between operating systems), so a stale chart arrives with stale text. A different library
version that moves things by more than a cell, or a larger change in font metrics, would show as a
difference and need a regenerated notebook. `tests/test_notebook_ci_fresh.py` pins the title, the small bar move and a threshold line
moved from 0.5 to 0.6 (`test_known_limits_small_changes_are_not_seen`,
`test_known_limits_a_moved_threshold_line_is_not_seen`); if one starts to fail the comparison got
stricter and this list needs updating. The scatter, 20 by 20 heat-map and reference-line cases above
were measured with probe charts (an independent review, across four environments), not pinned.
The check is a second line behind the text outputs: a number shown in a table or a printed line is
compared exactly, so a stale chart usually comes with stale text too.

When the check fails, run `python tools/execute_notebook.py recipes/NN-slug` and commit the result.

## Fixture validation

`python tools/notebook_ci.py fixtures` runs `python -m jev_cookbook.fixtures validate
recipes/<folder>` for every folder directly under `recipes/` and prints the mode (`replay` or
`scripted`) the validator reports. A folder with no `fixtures/` folder fails: the validator's own
`validate --all` skips such a recipe without a word. An empty `recipes/` directory fails too. A
scripted recipe, with empty `replay_keys` and no `responses.json`, validates as `scripted`, and
malformed or drifted responses files fail as the validator defines ([fixtures.md](fixtures.md)).

## The scope check

`tools/check_recipe_scope.py` is the allowlist from [CONTRIBUTING.md](../CONTRIBUTING.md),
enforced. It runs on `pull_request_target`, so GitHub runs the workflow file of the **base branch**
and the job checks out the base commit for the script: a pull request, even one that edits
`.github/workflows/scope.yml` or `tools/check_recipe_scope.py`, is judged by the base's copy. (Under
plain `pull_request` the workflow file comes from the pull request itself, so a recipe pull request
could replace the step with `exit 0` and get a green check under the required name; that is why this
is not `pull_request`.) The job is built so that the base context is safe: `permissions: contents:
read` and no secret; the pull request head is fetched as git objects (`refs/pull/N/head`), never
checked out, and the script reads only git objects of `--base` and `--head`; `persist-credentials:
false`, and the token reaches one `git fetch` only. **No step may run, install, import or source a
file of the pull request.** Because the workflow file is read from the base branch, a change to
`scope.yml` takes effect only once it is merged.

**Reviewers still reject any `.github/` change in a recipe pull request by hand.** The scope check
rejects it too (it is outside `recipes/<slug>/`), but the check is one safeguard, not the only one,
and a change to a workflow or the tooling must be a foundation pull request.

```bash
python tools/check_recipe_scope.py --base origin/main --head HEAD \
    --branch recipe/01-sentiment-classification --body-file pr-body.txt
# --repo DIR         git directory (default: current)
# --github-repo O/N  repository that issue references are matched against (default Jev-Engineering/cookbook)
```

Exit 0: accepted (a recipe pull request inside the allowlist, or a foundation pull request, which is
not subject to it). Exit 1: one `REJECT:` line per problem. Exit 2: the check could not run (an unknown
ref, an unreadable body, an unreadable diff); it fails closed.

- **Which kind.** A recipe pull request has both markers: branch `recipe/<slug>` and a closing
  reference (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`,
  with an optional colon, then `#N`, `owner/repo#N` or an issue URL; one inside a fenced code block
  or an inline code span does not count, as GitHub links nothing written in either) to an issue of
  this repository numbered 1 to 60. Neither marker: a foundation pull request. Only one: rejected.
  Closing any other issue of this repository as well, or closing two recipe issues: rejected. The
  branch must be `recipe/` plus the catalog slug of the closed issue, read from the base catalog.
- **Paths and modes**, on `git diff --raw -M -z base...head` (modes and types, not just names; both
  sides of a rename are checked). Every path must be under `recipes/<slug>/` or be exactly `README.md`.
  Inside the folder a deletion is allowed (it has no resulting mode, whatever the deleted entry was);
  an addition must be `100644`; a modification and both sides of a rename must be `100644`; a type
  change, symlink (`120000`), submodule (`160000`), mode change or any other status is rejected.
  `README.md` may only be modified from `100644` to `100644`.
- **README content**, only once no path was outside the allowlist (so a malformed catalog edit gets the
  path diagnostic, not a crash): the head `README.md` must equal
  `render(<base README.md>, <head catalog/recipes.json>)` byte for byte, using `render` from
  `tools/render_catalog.py` with the head's `recipes/` tree deciding which recipes are published.
  The base README, not the head's own, is rendered, so a prose or marker edit outside the generated
  regions is rejected.
- Everything is read from git objects of `--base` and `--head`, not from the working tree.

`tests/test_notebook_ci_scope.py` builds throwaway repositories and covers every excluded class: another
recipe's folder, a root file, `docs/`, `tests/`, `src/`, `tools/`, `catalog/` (also a malformed one),
`.github/`, `orchestration/`, `pyproject.toml`, files directly under `recipes/`, a folder that only
starts like the slug, a second recipe folder, README prose, a README marker, a generated row, an
extra newline, a README rendered from the head instead of the base, a mode-only README change, a
README type change, a README deletion or rename, a rename out of (and into) the folder, deletions
outside it, symlinks, submodules, new executables, mode and type changes inside the folder, and every
mis-tagged branch.

## Pinned plotting stack

The notebook job installs under `.github/constraints-notebooks.txt`, which pins `matplotlib` and
`numpy` (and the libraries matplotlib pulls in: `pillow`, `contourpy`, `cycler`, `fonttools`,
`kiwisolver`, `packaging`, `pyparsing`, `python-dateutil`, `six`) and the kernel and ML stack (`ipykernel`, `ipython`,
`jupyter_client`, `nbclient`, `nbformat`, `scikit-learn`, `scipy`) to the versions the committed
template outputs were produced with. Without it every job would take the latest release, and a
release that changes a `repr`, prints a warning to stderr, or moves figure geometry by more than a
grid cell would turn every notebook red at once on `main`. `pyproject.toml` stays unpinned, and the
constraints apply to the notebook execution job only.

**Authors install with the same file.** Text outputs are compared exactly against CI's pinned
stack, so a recipe author runs `pip install -e ".[dev,ml]" -c .github/constraints-notebooks.txt`
(Python 3.14) before executing a notebook and committing its outputs; the template README and
[recipe-template.md](recipe-template.md) say so. The constraints file cannot be installed on the
package floor, Python 3.10 (`numpy==2.5.3` needs Python 3.12 or newer): committable outputs are a
3.14 activity, not merely a `pip install -c` one.

**Bumping the constraints is a foundation change** that re-executes every notebook: change the
file, run `python tools/execute_notebook.py recipes/<folder>` for each folder in an environment
with the new versions, commit the regenerated notebooks in the same pull request, and read the
freshness check's output. A change to the file counts as "anything else", so it runs every notebook.

## Run time and cost

Jobs have timeouts, pip is cached, and a new push to a pull request cancels its older run. The
execute step prints its own elapsed seconds to the job summary.

**Billed minutes (private repository).** GitHub rounds each job up to a whole minute, so a recipe
costs at least one minute whatever its run time (about 30 seconds of runner time for the template,
of which execution is a few seconds). Counting jobs: a run that selects one notebook is about 4
billed minutes in `Notebooks` (discover, the notebook, the summary, fixtures) plus one for `Scope`;
a run that selects all N notebooks is about N + 3. These are estimates from job counts and the
template's measured time, not billing data; check the repository's usage report. Selecting only
the recipe folders a push to `main` changed (see "Which notebooks run") avoids re-running every
notebook on each merge, which over a sixty-recipe build would otherwise add up to well over a
thousand billed minutes. The `execute` job also caps itself at `max-parallel: 10`, so a full run is
always a deliberate, bounded set of waves rather than however many of the organisation's own
concurrent-job slots happen to be free, and the other jobs in `CI` and `Notebooks` are never
starved by one big `Notebooks (execute)` run.

## Local commands

The commands that reproduce a job on one recipe, including the network guard and the scope check,
are in [development.md](development.md#running-ci-on-one-recipe).
