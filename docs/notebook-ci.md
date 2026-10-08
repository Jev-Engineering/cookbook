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
  selects every notebook, `docs/**` included. This is an accepted cost (see "Run time and scaling"),
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
job runs in. Fix round 2 made the matching argument for the scope check ("a pull request cannot
edit the rule that judges it"); the notebook job has the same hole, by accident as much as on
purpose (a cell that saves a file with a relative path climbing out of the recipe folder silently
rewrites whatever it lands on).

Fix round 3 tried to close it by copying `tools/check_notebook_fresh.py`, `tools/check_hygiene.py`
and the committed notebook out of the checkout before execution, and running the checks against
those copies afterwards. **That did not hold.** The kernel still ran as the runner user (`setpriv
--reuid="$(id -u)"` only drops privileges inside the network namespace, not filesystem
permissions), which owns `$RUNNER_TEMP`, the checkout and the interpreter's site-packages alike,
and the kernel's working directory was a sibling of the frozen copies under `$RUNNER_TEMP`, so a
cell could reach them with no environment variable needed — `pathlib.Path.cwd().parents[1] /
"frozen"` — and overwrite either script or heal the committed notebook before it was compared.
`git status --porcelain` only ever looked at the checkout, so none of that was visible to it. The
fix round 4 review reproduced the whole bypass end to end.

**The enforcement is a uid boundary, not a copy.** The `Notebook (<recipe>)` job creates a
dedicated, unprivileged user, `nbrunner` (`sudo useradd -M -s /usr/sbin/nologin nbrunner`), and
runs the kernel as that user inside the existing network namespace (`setpriv --no-new-privs
--reuid=nbrunner --regid=nbrunner --clear-groups`), with `python -s` (no user site-packages) and
`PYTHONNOUSERSITE=1` in its environment (belt and braces: `-s` does not reach the separate
`ipykernel` subprocess the kernel spawns, but the environment variable does). What `nbrunner` can
and cannot write:

* **Can write:** only its own copy of the recipe folder (`$RUNNER_TEMP/run/<recipe>`), created and
  `chown`-ed to it before execution, mode `700` so nothing else — the runner user included — can
  read or write it either.
* **Cannot write:** the checkout (`$GITHUB_WORKSPACE`, so neither `tools/check_notebook_fresh.py`,
  `tools/check_hygiene.py` nor the committed `recipes/<recipe>/notebook.ipynb`), the interpreter's
  site-packages (so it cannot drop a `sitecustomize.py` that every later `python` would import,
  including the checks run after it), or anything under the runner's own `$HOME` (so it cannot
  drop a `usercustomize.py` there either — its own `$HOME` is a separate, empty directory it owns,
  passed explicitly, never the runner's).

A self-test step proves this before the notebook runs, rather than assuming it: as `nbrunner`, it
asserts (`test -w`) that site-packages, the checkout (including `tools/`), the committed notebook
and the pinned constraints file are **not** writable, and that the recipe copy **is**. The checks
afterwards read the checkout directly — no copy is needed any more, because the checkout is
unwritable by the kernel by construction, not merely by a freeze step's foresight.

**A detached process is a second route to the same place, and the uid boundary alone does not
close it.** A cell can start a process that outlives the kernel (`setsid`, a double fork, `&
disown`); stray processes survive step boundaries within a job, so one could still be running after
the executor exits, free to rewrite the recipe copy's `notebook.ipynb` — the one file `nbrunner`
legitimately owns — before it is read back. Fix round 4 closed this with a `Kill any leftover
nbrunner processes` step run between execution and the read; **fix round 5's review defeated that
by timing, not by evasion**: the executor's single write to `notebook.ipynb` and the `pkill` step
that followed it were about 455 ms apart, and a `setsid`'d grandchild that *keeps rewriting* the
file in a 5 ms loop — rather than sleeping once and writing once, the only shape the fix round 4
proof exercised — holds the file at the committed bytes continuously, so it is never the fresh
copy except for the few milliseconds after each of the executor's own writes. `pkill` reaching such
a process (which it does, and still does) says nothing about whether it reaches it *before* the
next read, and the measured margin said it did not.

**The fix has two layers, and the first one alone was not enough — found by this round's own
throwaway-PR proof, not assumed.** The execute step's `unshare` already creates a network namespace
(`--net`); it now also creates a PID namespace (`--pid --fork --mount-proc`), so the sandboxed
`python` (`tools/execute_notebook.py`) becomes PID 1 of its own process tree. When PID 1 of a PID
namespace exits, the kernel reaps every other process still in that namespace — there is no step
boundary and no window of any size for a leftover process to run in *after* that exit. A self-test
(`Prove a PID namespace leaves 0 survivors, even a looping rewriter`) proves exactly this in
isolation: raise a looping, `setsid`'d rewriter inside the same shape of namespace, and nothing of
it survives once the namespace's own PID 1 exits, no `pkill` involved.

**That guarantee is about the namespace exiting, not about the executor's own write being final —
and those are different moments.** Running the fix-round-4 attack cell's upgraded form (a 5 ms
rewrite loop, not a one-shot sleep-then-write) against the namespace alone, on a real throwaway pull
request, the grandchild still won: nbclient shuts the kernel down, `execute_notebook.py` writes
`notebook.ipynb`, and *then* the Python process itself has its own interpreter shutdown to get
through before it actually exits and the namespace reaps everything — a gap of a few milliseconds
that a 5 ms loop has good odds of landing inside. The namespace closes the race *after* the
executor's process is gone; it says nothing about what else might still run in the moments before
that, during the executor's own write and shutdown.

**The second layer closes that gap from inside the executor itself.**
`tools/execute_notebook.py`'s `execute()` calls `kill_everyone_else_in_my_pid_namespace()`
immediately before writing the result: when running as PID 1 of an isolated namespace
(`os.getpid() == 1`, true only there — a no-op for a local run or any test that calls `execute()`
directly), it signals every other non-zombie process still in that namespace and confirms, by
re-checking, that none remain before returning; it raises (failing the job) rather than guessing if
one will not die in time. With both layers in place, the same attack cell's write race is: kill
everything else, confirm nothing survives, *then* write — nothing is left alive to race the write
at all, rather than merely being guaranteed dead sometime after the process exits.

**`pkill -9 -u nbrunner` stays, as a further backstop beyond both layers, not the defence.** It
still runs immediately after execution (a separate self-test, `Prove a detached nbrunner process
can be fully killed`, still proves it reaches a one-shot detached process when given one) and still
fails the job loudly if it ever finds a survivor — but by the time it runs, the notebook has already
been read back, after the executor's own kill-and-confirm step, so a survivor at that point would
mean both of the layers above are broken, not that the notebook is at risk from what this backstop
might still catch.

**The committed notebook is read with `git show HEAD:recipes/<recipe>/notebook.ipynb`, not from the
working tree**, as a second, independent layer on top of the uid boundary: even if the boundary or
the `git status --porcelain` assertion were ever wrong, the comparison still reads the actual
committed blob rather than whatever file happens to sit in the checkout at that point. `git status
--porcelain` right after execution stays as a backstop on the checkout generally, in case the uid
boundary is ever wrong; it was never the mechanism that makes the comparison itself trustworthy,
and the `git show` step above no longer depends on it being one.

**What this does and does not cover.** The uid boundary is a Linux uid: `nbrunner` cannot write the
checkout, the interpreter's site-packages or the runner's `$HOME`, under any path, however it is
reached — directly from a notebook cell or from a function called at import time from `helpers.py`.
A process that outlives the kernel is a *different* route, covered by the PID namespace above, not
by the uid boundary itself — the two sections above describe which layer closes which route; naming
only one and crediting it with both was itself fix round 4's gap. Neither covers, and nothing here
claims they cover: a vulnerability in the kernel or the Python interpreter itself that lets
`nbrunner` regain the runner's uid (`--no-new-privs` and the dropped `sudo` access narrow this, they
do not eliminate the general case); a notebook that passes a validated-looking fixtures path the
fixture validator never saw (see "`get_backend(fixtures=...)` and the fixtures gate" below); or
anything about the quality of the notebook's own logic, which review covers, not CI. Do not
describe any layer here as "unbypassable" — say what it is (a uid boundary, a PID namespace, a
process-kill backstop, a second read path) and what it stops, the way this section tries to.

**Nor does any of this reach the test jobs.** A recipe ships its own `recipes/<slug>/tests/` (and
may ship a `recipes/<slug>/conftest.py`), and `pyproject.toml`'s `testpaths` runs them in
`Tests (py3.10)`/`Tests (py3.14)` as the runner user, with network access and write access to that
job's own checkout — outside the uid boundary and the PID namespace described here entirely, which
exist only inside the `Notebook (<recipe>)` job. The blast radius is small (no secrets,
`contents: read`, an ephemeral runner, and recipe-authored tests running is the design, not an
accident), and the scope check — not this workflow — is what limits a recipe pull request to its
own `recipes/<slug>/` path in the first place.

The documented local commands in [development.md](development.md#running-ci-on-one-recipe) mirror
the real boundary where that is practical (it needs `sudo` and a spare system user) and say
plainly where the local, no-`sudo` variant is weaker.

**None of this protects `notebooks.yml` itself from the pull request it is judging.** It runs on
plain `pull_request`, so a recipe pull request supplies the very workflow file that runs this job,
and could in principle neuter the staleness step the same way the workflow file comment above
"Reviewers still reject any `.github/` change" describes for the scope check's own history. The only
automated thing that stops a recipe pull request from doing that is `Scope (recipe pull requests)`
(see "The scope check" below), which rejects any path outside `recipes/<slug>/` and `README.md`,
`.github/workflows/notebooks.yml` included — `notebooks.yml`'s own sandboxing is therefore only as
trustworthy as `Scope` being wired into branch protection and actually running (see "After this
merges"); until then, a reviewer rejecting a `.github/` change by hand is what stands behind it.

### `get_backend(fixtures=...)` and the fixtures gate

`Fixtures (validate)` validates every file under `recipes/<recipe>/fixtures/`; nothing in this
workflow or in `jev_cookbook` requires a notebook's `get_backend(fixtures=...)` call to point
inside that folder. In CI this is closed as a side effect of the boundary above, not by a rule that
checks it: `$RUNNER_TEMP/run/<recipe>` (nbrunner's writable copy) is the only place a notebook cell
could stage a file at execution time, and that is thrown away at the end of the job, so the fixtures
`Fixtures (validate)` validated are the only ones a committed, reviewable `get_backend` call can
actually reach — a path elsewhere in the checkout is read-only and points at files a reviewer can
see in the diff. **This does not hold locally**, where a notebook's author runs as their own user
and can point `fixtures=` at any file on disk they own, validated or not. The shared-code half (a
runtime check that `get_backend` refuses a fixtures path outside the recipe's own `fixtures/`)
belongs to the fixtures backend itself (#65/#66), not to this workflow.

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
  regions is rejected. **`tools/render_catalog.py` and this check disagree about what "published"
  means**: the renderer (run locally, by an integration worker) reads the working tree, this check
  reads the head commit. Running the renderer with an uncommitted second recipe folder present, then
  committing and pushing, produces a README the renderer accepted (`--check` passes locally) but
  this check rejects — as a `README.md:` diagnostic, since that is the only path difference it can
  see; committing every recipe folder before rendering avoids it (#108 fix round 5, B5 review).
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

## Run time and scaling

Jobs have timeouts, pip is cached, and a new push to a pull request cancels its older run. The
execute step prints its own elapsed seconds to the job summary.

**One recipe, measured.** From this pull request's own CI runs at the fix round 4 head
([37718584952](https://github.com/Jev-Engineering/cookbook/actions/runs/37718584952),
[37718585032](https://github.com/Jev-Engineering/cookbook/actions/runs/37718585032)):
`Notebooks (discover)` 6 s, `Notebook (_template)` 35 s (of which the notebook itself executes in
2 s; the rest is `setup-python`, install and the sandbox self-tests, which measured under 2 s
combined), `Notebooks (execute)` 3 s, `Fixtures (validate)` 17 s. The `Notebooks` workflow's wall
time for one recipe was 54 s end to end (discover, then the one notebook job, then the summary;
fixtures runs in parallel and does not add to that critical path). (#108 fix round 5, B5 review:
an earlier version of this paragraph also compared these numbers with fix round 3's run and said
"about 7 s more... despite a 3 s faster job"; checked against the two runs by job step, `Install`
was 10 s faster and the rest of the job about 4 s slower, which the dropped sentence did not say —
the comparison added no information the measurements above do not already give directly, so it is
dropped rather than restated.)

**How it scales.** The `execute` job caps itself at `max-parallel: 10` (see "Why 10" below), so a
run that selects every notebook is not one wave of N jobs in parallel but ⌈N / 10⌉ waves run one
after another. At sixty recipes that is six waves of ten: roughly 3½ minutes of execute time (six
times the one-recipe execute job's ~35 s, allowing for the fixed per-job overhead not shrinking),
plus discovery and the summary job, for a **wall time of about 4 minutes** for a full run — not the
~54 s a single uncapped wave would take. A push to a recipe pull request, or to `main` after a
recipe merges, still selects only the one or two folders that changed (see "Which notebooks run"),
so this scaling only matters for a push that selects every notebook: a foundation change outside
`recipes/`, a forced push, the weekly cron, or a manual run with `full` left `true`.

**Why 10.** Without a cap, a full run claims as many of the organisation's concurrent-job slots as
there are recipes, starving `CI`'s and `Notebooks`' other jobs. The number is a deliberate, bounded
choice rather than whatever the organisation's limit happens to be at the time; a pull request
(ordinarily at most one recipe folder changed) never notices it.

**Billed minutes (private repository), measured.** GitHub rounds each job up to a whole minute.
Counting the runs above: one push to a recipe pull request is `Notebooks` 4 billed minutes
(discover + one notebook + the summary + fixtures) + `Scope` 1, on top of 7 for the existing `CI`
and `Hygiene` workflows (`Lint` 21 s, `Catalog` 6 s, `Tests (py3.14)` 98 s, `Tests (py3.10)` 109 s,
`Hygiene` 8 s, each rounding to 1 or 2 billed minutes) — **about 12 billed minutes per push**,
unchanged from round 3 (none of fix round 4's added self-tests cross a one-minute rounding
boundary on their own job). A README-only push selects no notebook: 3 + 1 = 4 new. A push to
`main` that selects every notebook — the scaling case above — is 1 (discover) + 60 (one per
recipe) + 1 (summary) + 1 (fixtures) = 63 jobs, **about 63 billed minutes**, independent of the
`max-parallel` cap (billing is per job, not per wave); the weekly cron costs the same each time it
runs. Selecting only the recipe folders a normal recipe merge changed (see "Which notebooks run")
keeps an ordinary merge to `main` at 4 new billed minutes rather than 63. These are measured from
the runs named above, not an estimate from job counts; check the repository's usage report for
totals over time.

## Local commands

The commands that reproduce a job on one recipe, including the network guard and the scope check,
are in [development.md](development.md#running-ci-on-one-recipe).
