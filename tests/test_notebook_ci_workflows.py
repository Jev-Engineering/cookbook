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
    assert re.search(r"inputs:\n\s+full:\n(?:\s+.*\n)*?\s+default: true", body)
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
