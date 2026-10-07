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
| `Scope (recipe pull requests)` | yes | The allowlist for recipe pull requests, in its own workflow (`scope.yml`). It runs on pull requests only and **re-runs when the description or the base branch is edited** (`edited`), because it classifies a pull request by its closing references: a result that survived a later `Closes #N` would be stale. The `Notebooks` workflow does not re-run on edits. |

Require the three named ones in branch protection. The other check names (`Lint (ruff)`,
`Catalog (README is current)`, `Tests (py3.10)`, `Tests (py3.14)`, `Hygiene (secrets and notebook
outputs)`) are unchanged.

## Which notebooks run

`python tools/notebook_ci.py matrix` lists the folders with a `notebook.ipynb`, `_template`
included.

- **A push to `main`** runs the recipe folders changed since the previous tip of `main`
  (`github.event.before`) when the push touches nothing outside `recipes/<folder>/` and `README.md`
  (a recipe merge runs one notebook). It runs every notebook when anything else changed (shared
  code, tools, workflows, docs, the constraints file, anything a recipe reads), and when `before`
  is not available (a first or forced push: `matrix --lenient` falls back to everything).
- **A manual run** (`workflow_dispatch`) has a `full` input. Left true (the default) it runs every
  notebook; false runs the recipe folders changed by the latest commit, by the same rule.
- **A pull request** runs only the recipe folders it changes, provided every changed path is inside
  a `recipes/<folder>/` or is exactly `README.md`. A recipe pull request is limited to that by the
  scope check, so one recipe's pull request does not re-run sixty notebooks.
- A pull request that changes anything else (shared code, tools, docs, workflows, the template's
  neighbours) runs every notebook, because shared code can change any recipe's result.
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

## The staleness check

`python tools/check_notebook_fresh.py <committed> <fresh>` compares the notebook in the repository
with the one the job just produced from scratch. Exit 0 means they agree. The rules, in order:

1. **Failures in either file.** Any output with `output_type` `error` (what a cell tagged
   `raises-exception` commits; the executor exits 0 for such a cell, so the check must catch it) and
   any `stderr` stream output are problems, in the committed notebook and in the fresh one, even
   when the two are identical.
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
enforced. It runs on pull requests, from the base branch's copy of the script (so a pull request
cannot change the rule that judges it; the pull request that introduces the script runs its own).

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
  with an optional colon, then `#N`, `owner/repo#N` or an issue URL) to an issue of this repository
  numbered 1 to 60. Neither marker: a foundation pull request. Only one: rejected. Closing any other
  issue of this repository as well, or closing two recipe issues: rejected. The branch must be
  `recipe/` plus the catalog slug of the closed issue, read from the base catalog.
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
`kiwisolver`, `packaging`, `pyparsing`, `python-dateutil`, `six`) to the versions the committed
template outputs were produced with. Without it every job would take the latest release, and a
release that changes a `repr`, prints a warning to stderr, or moves figure geometry by more than a
grid cell would turn every notebook red at once on `main`. `pyproject.toml` stays unpinned, and the
constraints apply to the notebook execution job only.

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
thousand billed minutes. The organisation's concurrent-job limit turns a full run into waves.

## Local commands

The commands that reproduce a job on one recipe, including the network guard and the scope check,
are in [development.md](development.md#running-ci-on-one-recipe).
