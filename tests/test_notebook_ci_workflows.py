"""The contracts of the two workflow files that cannot be run locally (#69).

These are text checks on the workflow files: a run on GitHub is the real test, and these keep a
later edit from quietly undoing a decision (a description edit re-runs the scope check from the
base branch, the notebook workflow does not, the sandbox cannot sudo out, the install uses the
constraints, a forced push runs everything).
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO / ".github" / "workflows"
NOTEBOOKS = (WORKFLOWS / "notebooks.yml").read_text(encoding="utf-8")
SCOPE = (WORKFLOWS / "scope.yml").read_text(encoding="utf-8")
CONSTRAINTS = (REPO / ".github" / "constraints-notebooks.txt").read_text(encoding="utf-8")


def code(text):
    """The file without comment lines, so a comment cannot satisfy or break a check."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def lines_after(text, marker, limit=20):
    """Up to ``limit`` lines following the first line containing ``marker`` (exclusive).

    A bounded, linear alternative to a regex like ``r"marker\\n(?:\\s+.*\\n)*?\\s+target"``: that
    idiom's lazy, unanchored ``(?:\\s+.*\\n)*?`` backtracks catastrophically when ``target`` is
    absent (#108 fix round 4, M2 — deleting ``max-parallel: 10`` made the test that used it hang
    for minutes instead of failing). A plain line scan with an explicit limit cannot backtrack at
    all: it is worst case O(limit), not exponential in the input size.
    """
    found = text.splitlines()
    for index, line in enumerate(found):
        if marker in line:
            return found[index + 1 : index + 1 + limit]
    return []


def test_scope_reruns_when_the_description_is_edited():
    match = re.search(r"pull_request_target:\n\s+types: \[([^\]]*)\]", code(SCOPE))
    assert match, "scope.yml must list its pull_request_target types"
    assert {t.strip() for t in match.group(1).split(",")} == {
        "opened",
        "synchronize",
        "reopened",
        "edited",
    }


def test_scope_runs_from_the_base_so_a_pull_request_cannot_edit_the_rule_that_judges_it():
    body = code(SCOPE)
    # `pull_request` would run the pull request's own copy of this file.
    assert not re.search(r"^\s*pull_request:", body, re.MULTILINE)
    assert re.search(r"^on:\n  pull_request_target:", body, re.MULTILINE)
    assert "    name: Scope (recipe pull requests)\n" in SCOPE
    # The only checkout is of the base commit, and the tool is the one in it.
    assert body.count("actions/checkout@") == 1
    assert "ref: ${{ github.event.pull_request.base.sha }}" in body
    assert "python tools/check_recipe_scope.py" in body
    assert "trusted" not in body  # no second checkout, no fallback to the pull request's copy


def test_scope_never_checks_out_or_runs_the_pull_request_head():
    body = code(SCOPE)
    assert "persist-credentials: false" in body
    assert "permissions:\n  contents: read\n" in body
    assert body.count("permissions:") == 1  # nothing widens it, at job level either
    assert "secrets." not in body
    # The head is fetched as git objects; it is never the ref of a checkout.
    assert "ref: ${{ github.event.pull_request.head" not in body
    assert "refs/pull/$PR_NUMBER/head" in body
    # The only command that runs Python runs the base's script; nothing installs or sources.
    for pattern in (r"\bpip\b", r"\bsource\b", r"\bsetup\.py\b", r"\bnpm\b", r"\bmake\b"):
        assert not re.search(pattern, body), pattern
    assert re.findall(r"^\s*python (\S+)", body, re.MULTILINE) == ["tools/check_recipe_scope.py"]


def test_notebooks_workflow_does_not_rerun_on_edits_and_has_no_scope_job():
    body = code(NOTEBOOKS)
    assert "edited" not in body
    assert "types:" not in body
    assert "Scope (recipe pull requests)" not in body
    assert not re.search(r"^  scope:", body, re.MULTILINE)


def test_required_job_names_are_unchanged():
    for name in (
        "Notebooks (discover)",
        "Notebook (${{ matrix.recipe }})",
        "Notebooks (execute)",
        "Fixtures (validate)",
    ):
        assert f"    name: {name}\n" in NOTEBOOKS, name


def test_every_sandboxed_python_runs_without_new_privileges():
    body = code(NOTEBOOKS)
    calls = re.findall(r"exec setpriv [^\n]*", body)
    assert len(calls) == 2  # the guard self-test and the notebook execution
    assert all("--no-new-privs" in call for call in calls), calls
    # #108 fix round 4: both run as the dedicated unprivileged user, not the runner's own uid.
    assert all("--reuid=nbrunner --regid=nbrunner --clear-groups" in call for call in calls), calls
    assert all(" python -s " in call for call in calls), calls
    assert "unshare --net" in body


def test_notebook_job_installs_the_ml_extra_under_the_constraints():
    assert 'pip install -e ".[ml]" -c .github/constraints-notebooks.txt' in code(NOTEBOOKS)


def pins():
    return {
        line.split("==")[0]: line.split("==")[1]
        for line in CONSTRAINTS.splitlines()
        if line and not line.startswith("#")
    }


def test_constraints_pin_the_plotting_stack_exactly():
    assert {"matplotlib", "numpy"} <= set(pins())
    assert all(re.fullmatch(r"[0-9][0-9A-Za-z.]*", version) for version in pins().values())


def test_constraints_pin_the_kernel_and_ml_stack_too():
    wanted = {
        "ipykernel",
        "ipython",
        "nbclient",
        "nbformat",
        "jupyter_client",
        "scikit-learn",
        "scipy",
    }
    assert wanted <= set(pins())


def test_main_runs_are_never_cancelled_and_pull_request_runs_are():
    body = code(NOTEBOOKS)
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in body
    assert "group: notebooks-${{ github.event.pull_request.number || github.sha }}" in body


def test_push_selection_uses_the_previous_tip_and_a_manual_run_can_force_everything():
    body = code(NOTEBOOKS)
    assert "workflow_dispatch:" in body
    following = lines_after(body, "full:", limit=5)
    assert any(re.fullmatch(r"\s+default: true", line) for line in following), following
    assert '--base "$BEFORE_SHA" --head HEAD --push' in body
    assert "BEFORE_SHA: ${{ github.event.before }}" in body


def test_a_forced_push_runs_everything_and_does_not_use_before():
    body = code(NOTEBOOKS)
    assert "FORCED: ${{ github.event.forced }}" in body
    push = re.search(
        r'elif \[ "\$EVENT" = "push" \] && \[ "\$FORCED" != "true" \]; then\n\s+(.*)\n', body
    )
    assert push and "--push" in push.group(1), "a forced push must skip the before-based branch"
    forced = re.match(
        r'\s+elif \[ "\$EVENT" = "push" \]; then\n\s+echo [^\n]*\n\s+(.*)\n', body[push.end() :]
    )
    assert forced, "the forced branch must follow"
    assert "--base" not in forced.group(1), "a forced push must not select by `before`"


def test_a_weekly_schedule_runs_every_notebook():
    body = code(NOTEBOOKS)
    assert re.search(r'schedule:\n\s+- cron: "\S+ \S+ \* \* [0-6]"', body)
    # No branch of the selection step names `schedule`, so a scheduled run reaches the final
    # `else`, which selects everything.
    assert '"$EVENT" = "schedule"' not in body
    assert re.search(r"else\n\s+python tools/notebook_ci.py matrix --github-output", body)


def test_execute_job_caps_its_own_concurrency():
    following = lines_after(code(NOTEBOOKS), "strategy:", limit=5)
    assert any(re.fullmatch(r"\s+max-parallel: \d+", line) for line in following), following


def test_kernel_runs_as_a_dedicated_unprivileged_user():
    """#108 fix round 4, M1: a copy-based defence (freezing the checks to $RUNNER_TEMP before
    execution) did not hold, because the kernel ran at the runner's own uid, which owns
    $RUNNER_TEMP, the checkout and the interpreter's site-packages, and its working directory was a
    sibling of the frozen copies reachable by a relative path. The kernel must instead run as a
    dedicated user who owns only its own recipe copy."""
    body = code(NOTEBOOKS)
    useradd = re.search(r"useradd [^\n]*", body)
    assert useradd, "no dedicated user is created for the kernel"
    assert (
        "-M" in useradd.group(0)
        and "nologin" in useradd.group(0)
        and "nbrunner" in useradd.group(0)
    )
    useradd_index = body.index(useradd.group(0))
    execute_index = body.index("Execute the notebook offline")
    assert useradd_index < execute_index, "the user must exist before the kernel runs"
    # Its own empty $HOME, not the runner's: a usercustomize.py under the runner's $HOME would
    # reach every later `python`, including the checks run after execution.
    assert 'chown nbrunner:nbrunner "$RUNNER_TEMP/nbrunner-home"' in body
    assert '"HOME=$RUNNER_TEMP/nbrunner-home"' in body
    assert '"HOME=$HOME"' not in body, "the kernel must not inherit the runner's $HOME"


def test_recipe_copy_is_nbrunners_only_writable_location():
    body = code(NOTEBOOKS)
    copy_step = re.search(
        r"Copy the recipe to nbrunner's scratch folder\n(.*?)\n\s*- ", body, re.DOTALL
    )
    assert copy_step, "no step copies the recipe to a folder nbrunner owns"
    assert "cp -R" in copy_step.group(1) and '"recipes/$RECIPE"' in copy_step.group(1)
    assert "chown -R nbrunner:nbrunner" in copy_step.group(1)
    assert "chmod -R u+rwX,go-rwx" in copy_step.group(1)
    copy_index = body.index(copy_step.group(0))
    execute_index = body.index("Execute the notebook offline")
    assert copy_index < execute_index


def test_uid_boundary_is_proved_before_execution_not_assumed():
    """The self-test must check all three routes fix round 4's review demonstrated (site-packages,
    the checkout including tools/, and the committed notebook), and that nbrunner can still write
    its own recipe copy, as the one exception."""
    body = code(NOTEBOOKS)
    probe = re.search(
        r"Prove the uid boundary - nbrunner can write only its own recipe copy\n(.*?)\n\s*- ",
        body,
        re.DOTALL,
    )
    assert probe, "no uid-boundary self-test"
    text = probe.group(1)
    assert "sysconfig.get_paths()['purelib']" in text  # site-packages, resolved, not guessed
    assert '"SITE_PACKAGES=$SITE_PACKAGES"' in text
    assert '"NOTEBOOK=$GITHUB_WORKSPACE/recipes/$RECIPE/notebook.ipynb"' in text
    assert '"CONSTRAINTS=$GITHUB_WORKSPACE/.github/constraints-notebooks.txt"' in text
    assert '"RECIPE_COPY=$RUNNER_TEMP/run/$RECIPE"' in text
    assert '-w "$path"' in text  # must-not-write loop over the read-only locations
    assert '! -w "$RECIPE_COPY"' in text  # must-write check on the one writable exception
    assert "--reuid=nbrunner --regid=nbrunner --clear-groups" in text
    probe_index = body.index(probe.group(0))
    execute_index = body.index("Execute the notebook offline")
    assert probe_index < execute_index, "the boundary must be proved before the kernel runs"


def test_kernel_runs_with_no_user_site():
    """`-s` and PYTHONNOUSERSITE keep the kernel (and the ipykernel subprocess it spawns, which
    does not inherit `-s`) off anything under nbrunner's own $HOME."""
    body = code(NOTEBOOKS)
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step
    assert '"PYTHONNOUSERSITE=1"' in execute_step.group(1)
    assert "python -s tools/execute_notebook.py" in execute_step.group(1)


def test_kernel_does_not_inherit_the_runners_xdg_directories():
    """The runner image sets its own XDG_* variables, pointing at directories under the runner's
    $HOME that nbrunner cannot write. Left alone, a library that honours them (matplotlib's config
    dir, caught live by this round's own CI run) tries to create a file under the runner's
    directory, fails, and prints a warning that lands in the notebook's stderr output and fails
    the run. Unset, each one falls back to a path under $HOME, which is nbrunner's own."""
    body = code(NOTEBOOKS)
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        assert f"-u {var}" in execute_step.group(1), var


def test_checks_run_directly_from_the_checkout_not_a_frozen_copy():
    """The checkout and tools/ are unwritable by nbrunner by construction (see the uid-boundary
    self-test), so the checks read them directly; nothing needs to be frozen into $RUNNER_TEMP
    before execution any more. The committed notebook is still read with `git show`, not from the
    working tree, as a second, independent check on top of the uid boundary (#108 fix round 4:
    reviewers reproduced the round-3 freeze being bypassed one directory further out, so the
    comparison does not rely solely on the checkout being untouched)."""
    body = code(NOTEBOOKS)
    assert "frozen" not in body
    git_show = re.search(
        r"Read the committed notebook from git, not the working tree\n\s+run: (.*)", body
    )
    assert git_show and git_show.group(1) == (
        'git show "HEAD:recipes/$RECIPE/notebook.ipynb" > "$RUNNER_TEMP/committed-notebook.ipynb"'
    )
    fresh_check = re.search(r"Committed outputs match the fresh run\n\s+run: (.*)", body)
    assert fresh_check and fresh_check.group(1) == (
        'python tools/check_notebook_fresh.py "$RUNNER_TEMP/committed-notebook.ipynb" '
        '"$RUNNER_TEMP/fresh-notebook.ipynb"'
    )
    hygiene_check = re.search(r"Hygiene of the freshly executed notebook\n\s+run: (.*)", body)
    assert hygiene_check and hygiene_check.group(1) == (
        'python tools/check_hygiene.py "$RUNNER_TEMP/fresh-notebook.ipynb"'
    )
    # The executed notebook is copied out of nbrunner's exclusive, mode-700 recipe copy as the
    # runner, only after every nbrunner process is confirmed dead, before either check reads it.
    kill_step = re.search(r"Kill any leftover nbrunner processes\n(.*?)\n\s*- ", body, re.DOTALL)
    assert kill_step and "pkill -9 -u nbrunner" in kill_step.group(1)
    assert "pgrep -u nbrunner" in kill_step.group(1)
    copy_out = re.search(
        r"Copy the executed notebook out, as the runner\n(.*?)\n\s*- ", body, re.DOTALL
    )
    assert copy_out and "sudo install" in copy_out.group(1)
    execute_index = body.index("Execute the notebook offline")
    kill_index = body.index(kill_step.group(0))
    copy_out_index = body.index(copy_out.group(0))
    git_show_index = body.index(git_show.group(0))
    fresh_check_index = body.index(fresh_check.group(0))
    assert execute_index < kill_index < copy_out_index < git_show_index < fresh_check_index


def test_a_detached_process_is_proved_killable_and_killed_before_the_notebook_is_read_back():
    """#108 fix round 4, B4 M1 route B: a cell can start a process that outlives the kernel and
    rewrite the freshly executed notebook after the executor exits. A self-test proves `pkill -u
    nbrunner` actually reaches a detached (setsid'd) grandchild, and the real step runs before the
    executed notebook is copied out (see the ordering assertion above)."""
    body = code(NOTEBOOKS)
    self_test = re.search(
        r"Prove a detached nbrunner process can be fully killed\n(.*?)\n\s*- ", body, re.DOTALL
    )
    assert self_test, "no self-test proves pkill reaches a detached process"
    text = self_test.group(1)
    assert "setsid sh -c" in text and "disown" in text
    assert "pkill -9 -u nbrunner" in text
    assert "pgrep -u nbrunner" in text
    self_test_index = body.index(self_test.group(0))
    execute_index = body.index("Execute the notebook offline")
    assert self_test_index < execute_index, (
        "the kill mechanism must be proved before it is relied on"
    )


def test_the_checkout_is_asserted_untouched_right_after_execution():
    body = code(NOTEBOOKS)
    execute_index = body.index("Execute the notebook offline")
    assertion_index = body.index("The checkout is untouched after execution")
    fresh_check_index = body.index("Committed outputs match the fresh run")
    assert execute_index < assertion_index < fresh_check_index
    assertion = body[assertion_index:fresh_check_index]
    assert "git status --porcelain" in assertion
    assert "exit 1" in assertion
