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
    # #122 (A9 S2 on #108, folding in A6 S4): the auth header is scoped to github.com, not every
    # host the fetch might talk to, and `--config-env` -- which takes the scoped key unchanged --
    # is what actually reads it, not a literal `-c "...=..."` that would put the token in argv.
    assert "--config-env=http.https://github.com/.extraheader=AUTH_HEADER" in body
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
    """Four steps drop into nbrunner inside a namespace: the network-isolation self-test, the
    netguard self-test, the PID-namespace self-test (#108 fix round 5) and the real execution.
    Every one must drop privileges the same safe way; only the two that run a notebook-adjacent
    Python (the guard self-test and the real execution) need `-s` (no user site-packages) — the
    network probe only needs `socket`, and the PID-namespace self-test does not run Python at all."""
    body = code(NOTEBOOKS)
    calls = re.findall(r"exec setpriv [^\n]*", body)
    assert len(calls) == 4, calls
    assert all("--no-new-privs" in call for call in calls), calls
    # #108 fix round 4: all four run as the dedicated unprivileged user, not the runner's own uid.
    assert all("--reuid=nbrunner --regid=nbrunner --clear-groups" in call for call in calls), calls
    assert sum(" python -s " in call for call in calls) == 2, calls
    assert "unshare --net" in body
    # #108 fix round 5, M1: the executor's own PID namespace, not the pkill backstop, is what
    # stops a leftover process from outliving execution; proved by its own self-test below.
    assert body.count("unshare --net --pid --fork --mount-proc") == 2


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
    # reach every later `python`, including the checks run after execution. #108 fix round 5: the
    # scratch tree (nbrunner's $HOME included) moved to /srv/nbrun, outside the runner's own $HOME.
    assert "chown nbrunner:nbrunner /srv/nbrun/nbrunner-home" in body
    assert '"HOME=/srv/nbrun/nbrunner-home"' in body
    assert '"HOME=$HOME"' not in body, "the kernel must not inherit the runner's $HOME"


def test_sandbox_scratch_lives_outside_the_runners_home():
    """#108 fix round 5, A5 suggestion: the scratch tree used to sit under $RUNNER_TEMP, a child
    of the runner's $HOME, which bought nbrunner traversal into $HOME with a `chmod o+x "$HOME"`
    justified only by reaching this one subdirectory. /srv/nbrun sits outside $HOME, so that chmod
    is no longer needed for the scratch tree (it is still needed, and kept, so nbrunner can read
    the checkout, which remains a child of $HOME on a hosted runner)."""
    body = code(NOTEBOOKS)
    assert "/srv/nbrun" in body
    assert "$RUNNER_TEMP/nbrunner-home" not in body
    assert "$RUNNER_TEMP/run" not in body
    assert 'chmod o+x "$HOME"' in body  # kept, for checkout read-traversal, not the scratch
    assert (
        'chmod o+rx "$RUNNER_TEMP"' not in body
    )  # no longer needed: nothing nbrunner reads is here


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
    """The self-test must check all six routes fix round 4's review and A5's fix round 5 review
    demonstrated or asked for (site-packages, the checkout, tools/ inside it, the committed
    notebook, the pinned constraints file, the runner's own $HOME), plus the three files a step
    uses to talk to later steps (`$GITHUB_ENV`, `$GITHUB_OUTPUT`, `$GITHUB_PATH` — #108 fix round
    5, A5 suggestion: an attacker-controlled `$GITHUB_PATH` entry would put a fake `python` ahead
    of the real one for every later step, the checks included), and that nbrunner can still write
    its own recipe copy, as the one exception.

    #108 fix round 5, M2: the previous version of this test pinned the `sudo env` assignments
    (`SITE_PACKAGES=...`, `NOTEBOOK=...`, etc.) and the generic `-w "$path"` loop shape, but never
    looked at the probe script's own `for path in ...` line — so removing a variable from that
    loop (dropping site-package coverage entirely, the exact route fix round 4 found live) left
    every assignment and every other assertion here intact and the whole module still passed. This
    version reads the `for path in ...` line itself and asserts the full, exact set of variable
    names in it, so dropping any one of them fails this test directly."""
    body = code(NOTEBOOKS)
    probe = re.search(
        r"Prove the uid boundary - nbrunner can write only its own recipe copy\n(.*?)\n\s*- ",
        body,
        re.DOTALL,
    )
    assert probe, "no uid-boundary self-test"
    text = probe.group(1)
    assert "sysconfig.get_paths()['purelib']" in text  # site-packages, resolved, not guessed
    for_line = next((line for line in text.splitlines() if "for path in" in line), None)
    assert for_line, "no `for path in ...` line in the probe script"
    assert re.findall(r'"\$([A-Z_]+)(?:/[^"]*)?"', for_line) == [
        "SITE_PACKAGES",
        "WORKSPACE",
        "WORKSPACE",  # "$WORKSPACE/tools"
        "NOTEBOOK",
        "CONSTRAINTS",
        "RUNNER_HOME",
        "GH_ENV",
        "GH_OUTPUT",
        "GH_PATH",
    ], for_line
    assert '"$WORKSPACE/tools"' in for_line
    assert '"SITE_PACKAGES=$SITE_PACKAGES"' in text
    assert '"NOTEBOOK=$GITHUB_WORKSPACE/recipes/$RECIPE/notebook.ipynb"' in text
    assert '"CONSTRAINTS=$GITHUB_WORKSPACE/.github/constraints-notebooks.txt"' in text
    assert '"GH_ENV=$GITHUB_ENV"' in text
    assert '"GH_OUTPUT=$GITHUB_OUTPUT"' in text
    assert '"GH_PATH=$GITHUB_PATH"' in text
    assert '"RECIPE_COPY=/srv/nbrun/run/$RECIPE"' in text
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
    # #108 fix round 5, M1: the executed notebook is copied out of nbrunner's exclusive, mode-700
    # recipe copy as the runner, inside the "Execute the notebook offline" step itself, immediately
    # after the sandboxed run and before any step boundary (see test_execute_closes_the_pid_
    # namespace_and_reads_back_in_the_same_step below) — not as a separate step gated by the kill
    # step any more, since the PID namespace already guarantees nothing is left to race by the time
    # that copy runs. `Kill any leftover nbrunner processes` is a backstop that runs after.
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step and "sudo install" in execute_step.group(1)
    assert '"/srv/nbrun/run/$RECIPE/notebook.ipynb" "$RUNNER_TEMP/fresh-notebook.ipynb"' in (
        execute_step.group(1)
    )
    assert "Copy the executed notebook out, as the runner" not in body
    kill_step = re.search(r"Kill any leftover nbrunner processes\n(.*?)\n\s*- ", body, re.DOTALL)
    assert kill_step and "pkill -9 -u nbrunner" in kill_step.group(1)
    assert "pgrep -u nbrunner" in kill_step.group(1)
    execute_index = body.index("Execute the notebook offline")
    kill_index = body.index(kill_step.group(0))
    git_show_index = body.index(git_show.group(0))
    fresh_check_index = body.index(fresh_check.group(0))
    assert execute_index < kill_index < git_show_index < fresh_check_index


def test_execute_closes_the_pid_namespace_and_reads_back_in_the_same_step():
    """#108 fix round 5, M1: A5 reproduced a detached, tight-loop `setsid` rewriter beating the old
    `pkill`-after-execution defence by about two orders of magnitude of margin (a one-shot
    sleep-then-write, the only shape fix round 4's own proof used, does not exercise this at all).
    The workflow-level half of the fix is a PID namespace around the executor
    (`unshare ... --pid --fork --mount-proc`, on top of the existing `--net`), so nothing it spawns
    can outlive it once it is gone, plus reading the result back inside that same step, immediately,
    before any step boundary a surviving process could still exploit. The namespace alone was not
    enough against the same attack on a real throwaway pull request (it says nothing about what
    runs *before* the executor's process exits); the other half, inside
    tools/execute_notebook.py itself, is covered by tests/test_notebook_ci_sandbox.py instead,
    since it runs in the Python process the namespace wraps, not in this shell."""
    body = code(NOTEBOOKS)
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step
    text = execute_step.group(1)
    assert "unshare --net --pid --fork --mount-proc" in text
    install_index = text.index("sudo install")
    unshare_index = text.index("unshare --net --pid --fork --mount-proc")
    assert unshare_index < install_index, "the copy must come after the sandboxed run returns"


def test_execute_step_requires_and_confirms_the_pid_namespace():
    """#108 fix round 6, B6 M1: ``kill_everyone_else_in_my_pid_namespace`` (tools/
    execute_notebook.py) only ran because this step's shell `exec`s straight into `python`, which
    is PID 1 only as a result -- nothing asserted that, so an edit that stops it (wrapping the
    command in something that forks instead of `exec`ing, a `timeout 600` added after a hung job,
    say) silently disabled the one layer that stops the demonstrated attack, with every other test
    and check in this pull request still green. ``JEV_COOKBOOK_REQUIRE_PID_NAMESPACE`` turns the
    inference into a demand (the executor raises if it is not actually PID 1 of a
    procfs-mounted namespace, see tests/test_notebook_ci_sandbox.py), and the grep below fails this
    step if the executor's own one-line confirmation is ever missing, not just if its exit code
    is bad."""
    body = code(NOTEBOOKS)
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step
    text = execute_step.group(1)
    assert 'JEV_COOKBOOK_REQUIRE_PID_NAMESPACE: "1"' in text
    # Declaring it under the step's own `env:` is not enough: `sudo` wipes the environment unless a
    # variable is passed through explicitly, exactly as PATH, HOME, PYTHONPATH and
    # PYTHONNOUSERSITE already are.
    assert '"JEV_COOKBOOK_REQUIRE_PID_NAMESPACE=$JEV_COOKBOOK_REQUIRE_PID_NAMESPACE"' in text
    assert 'grep -qx "pid namespace: active"' in text
    # `python` must be the thing `exec setpriv` hands off to directly: anything interposed between
    # the final `--` and `python` (a `timeout 600` added after a hung job, say) forks rather than
    # `exec`s, so `python` lands on PID 2, not PID 1 -- the exact scenario the variable above
    # exists to catch at runtime. Pinning the literal invocation here catches it statically too.
    assert '--clear-groups -- python -s tools/execute_notebook.py --timeout 300 "$1"\'' in text, (
        "python must be exec'd directly after setpriv; nothing may sit between them and steal PID 1"
    )
    sandbox_index = text.index("unshare --net --pid --fork --mount-proc")
    pass_env_index = text.index(
        '"JEV_COOKBOOK_REQUIRE_PID_NAMESPACE=$JEV_COOKBOOK_REQUIRE_PID_NAMESPACE"'
    )
    grep_index = text.index('grep -qx "pid namespace: active"')
    assert pass_env_index < sandbox_index, "the variable must reach the sandboxed process"
    assert sandbox_index < grep_index, "the confirmation must be read after the sandboxed run"


def test_execute_step_sets_pipefail_shell():
    """#108 fix round 7, A8 M1 / B8 M1 (the same finding from both review seats): round 6 turned
    this step's single command into a pipeline (``... | tee "$RUNNER_TEMP/execute-notebook.log"``)
    so the grep right after it would have something to read, but GitHub's default shell for a
    `run:` block with no `shell:` key is `bash -e {0}` -- with no `pipefail` -- and a pipeline's
    exit status is its *last* command's, which is `tee`'s, always 0, regardless of what the
    executor did. An executor that raised (``kill_everyone_else_in_my_pid_namespace`` refusing to
    write the result, tools/execute_notebook.py) *after* printing "pid namespace: active" left
    this step green on the still-committed, never-executed notebook: the grep for that
    confirmation line still passed, and the executor's own nonzero exit reached nothing else.
    `shell: bash` makes GitHub run the block as `bash --noprofile --norc -eo pipefail {0}`
    instead, so the pipeline -- and so the step -- fails if either side of it does, restoring the
    property the plain, unpiped command had before round 6 (#108 fix round 6, B6 M1) added the
    pipe. B8's own mutation for this finding was different from A8's: appending `|| true` to the
    pipeline, which forces the *whole* pipeline's exit status to 0 regardless of `pipefail` -- a
    second way to defeat the same property, not caught by only checking for `shell: bash`, so this
    test also rejects it."""
    body = code(NOTEBOOKS)
    execute_step = re.search(r"Execute the notebook offline\n(.*?)\n\s*- ", body, re.DOTALL)
    assert execute_step
    text = execute_step.group(1)
    assert "| tee" in text, "the step must still pipe to the log the grep below reads"
    assert "shell: bash" in text, (
        "the step needs `shell: bash` (or an equivalent pipefail) so the executor's exit code "
        "is not swallowed by `tee` under GitHub's default `bash -e {0}`"
    )
    assert "|| true" not in text, (
        "an `|| true` appended to the pipeline (B8's own mutation for this finding) forces the "
        "whole pipeline's exit status to 0 regardless of `pipefail`, the same bypass as the "
        "missing `shell: bash` with a different spelling"
    )
    # #108 fix round 8, A9 S3 / B9 suggestion 1: `|| true` is one spelling of "force the
    # pipeline's exit status to 0 regardless of `pipefail`"; `|| :` is another (the same effect
    # through the `:` builtin instead of `true`), and `set +o pipefail` is a different route to
    # the same place -- turning `pipefail` back off for the rest of the step without touching
    # `shell: bash` or the pipeline at all. Each is rejected on its own rather than folded into
    # one regex, in the same style as the assertion above (see the docstring's reasoning for not
    # generalising further).
    assert "|| :" not in text, (
        "a trailing `|| :` after the pipeline is the `|| true` bypass spelled with the `:` "
        "builtin instead of `true`, which also always exits 0"
    )
    assert "set +o pipefail" not in text, (
        "`set +o pipefail` turns pipefail back off for the rest of the step, defeating "
        "`shell: bash` without changing the `shell:` line or the pipeline itself"
    )
    # #122 (A9 re-review of round 8, comment 6057665444, and B9's comment 6057581690; corrected
    # per the #125 review, comment 6060303924, M2): putting the failing pipeline into an `&&`
    # list exempts it from `set -e` entirely (the rule applies to the list as a whole, not to a
    # non-last command inside it) -- but NOT by running `true`/`:` and taking their exit status:
    # `&&` short-circuits on the pipeline's nonzero status, so `true`/`:` never execute at all.
    # What actually happens is the step simply continues past the failed list to the commands
    # after it (the grep, the echo, the `sudo install` that copies the stale notebook out), and
    # the step's exit status becomes whichever of *those* ran last -- 0, since none of them fails
    # on a never-executed notebook. Measured end to end on #108/#125: appending `&& true` or
    # `&& :` to the real execute step left it at `STEP EXIT=0` with the stale, never-executed
    # notebook copied out and certified fresh -- the same outcome as `|| true`, by a different
    # route.
    assert "&& true" not in text, (
        "a trailing `&& true` after the pipeline is a real bypass: the `&&` list exempts the "
        "failing pipeline from `set -e` (its own nonzero status is discarded, and `true` never "
        "runs -- `&&` short-circuits on it), so the step continues to the commands after the "
        "list and exits with whichever of those ran last, 0"
    )
    assert "&& :" not in text, (
        "a trailing `&& :` is the same `&&`-list bypass as `&& true`, spelled with the `:` "
        "builtin instead of `true` (which, like `true`, never runs -- `&&` short-circuits on "
        "the pipeline's nonzero status)"
    )
    # #122, same source: `set +e` is a different route to the same place as `set +o pipefail` --
    # it turns off `-e` (not `pipefail`) for the rest of the step, so the failing pipeline no
    # longer aborts anything and the step again exits with its last command's status, 0. Measured
    # on #108: injecting `set +e` as the block's first line left the step at `STEP EXIT=0` on a
    # failing executor.
    assert "set +e" not in text, (
        "`set +e` turns off `-e` for the rest of the step, the same bypass as `set +o pipefail` "
        "reached through the other switch -- it also leaves the step exit 0 on a failing executor"
    )
    # A trailing `; true`, by contrast, is NOT a bypass: the pipeline is a standalone command (not
    # part of an `&&`/`||` list), so `set -e` aborts the step at the pipeline itself, before
    # `; true` is ever reached -- measured on #108: `; true` appended to the real step left it at
    # `STEP EXIT=1`, identical to the unmodified step. The assertion below is kept anyway, as
    # harmless over-strictness in the same defensive style as the others (rejecting a spelling
    # that was never a bypass costs nothing), but -- per the #108 round-8 re-review -- its message
    # no longer claims the pipeline's exit status is discarded, which is not what happens.
    assert "; true" not in text, (
        "a trailing `; true` after the pipeline is not a bypass (`set -e` aborts the step at the "
        "standalone pipeline before `; true` is ever reached); rejected anyway as harmless "
        "over-strictness, in the same style as the other spellings here"
    )
    shell_index = text.index("shell: bash")
    pipe_index = text.index("| tee")
    grep_index = text.index('grep -qx "pid namespace: active"')
    assert shell_index < pipe_index < grep_index, (
        "pipefail must be in force before the pipeline it protects, which must run before the "
        "confirmation is read"
    )


def test_a_detached_process_is_proved_killable_by_the_backstop():
    """#108 fix round 4, B4 M1 route B, narrowed by #108 fix round 5, M1: a cell can start a
    process that outlives the kernel. The PID namespace plus execute_notebook.py's own
    kill-before-write (see the tests above and tests/test_notebook_ci_sandbox.py) are what actually
    close this route now; `pkill -u nbrunner` afterward is kept only as a further backstop, and
    this self-test proves only that it reaches a detached (setsid'd) grandchild when given one —
    not that it would reach one in time on its own, which is no longer the property being relied
    on."""
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
        "the backstop mechanism must be proved before it is relied on"
    )


def test_pid_namespace_leaves_no_survivors_even_a_looping_rewriter():
    """#108 fix round 5, M1's own self-test for the namespace's half of the fix: unlike the pkill
    backstop's self-test (a one-shot `sleep 300 & disown`), this one raises a `setsid`'d process
    that loops forever, inside the same kind of `--pid --fork --mount-proc` namespace the real
    execute step uses, and asserts nothing of it survives *the namespace's own PID 1 exiting* —
    with no `pkill` involved in reaching that conclusion at all. This is a necessary property, not
    a sufficient one on its own: a real attack still won against the namespace alone, in the gap
    before PID 1 actually exits, which is why execute_notebook.py also gets its own
    kill-before-write (tests/test_notebook_ci_sandbox.py)."""
    body = code(NOTEBOOKS)
    self_test = re.search(
        r"Prove a PID namespace leaves 0 survivors, even a looping rewriter\n(.*?)\n\s*- ",
        body,
        re.DOTALL,
    )
    assert self_test, "no self-test proves the PID namespace itself leaves no survivors"
    text = self_test.group(1)
    assert "unshare --net --pid --fork --mount-proc" in text
    assert "setsid sh -c" in text
    assert "while :; do :; done" in text  # a looping rewriter, not a one-shot sleep-then-write
    assert "pkill" not in text, "this self-test must not rely on pkill to reach its conclusion"
    assert "pgrep -u nbrunner" in text
    self_test_index = body.index(self_test.group(0))
    execute_index = body.index("Execute the notebook offline")
    assert self_test_index < execute_index, "the namespace must be proved before it is relied on"


def test_the_checkout_is_asserted_untouched_right_after_execution():
    body = code(NOTEBOOKS)
    execute_index = body.index("Execute the notebook offline")
    assertion_index = body.index("The checkout is untouched after execution")
    fresh_check_index = body.index("Committed outputs match the fresh run")
    assert execute_index < assertion_index < fresh_check_index
    assertion = body[assertion_index:fresh_check_index]
    assert "git status --porcelain" in assertion
    assert "exit 1" in assertion
