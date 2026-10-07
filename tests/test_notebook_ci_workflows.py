"""The contracts of the two workflow files that cannot be run locally (#69).

These are text checks on the workflow files: a run on GitHub is the real test, and these keep a
later edit from quietly undoing a decision (a description edit re-runs the scope check, the
notebook workflow does not, the sandbox cannot sudo out, the install uses the constraints).
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
    match = re.search(r"pull_request:\n\s+types: \[([^\]]*)\]", code(SCOPE))
    assert match, "scope.yml must list its pull_request types"
    assert {t.strip() for t in match.group(1).split(",")} == {
        "opened",
        "synchronize",
        "reopened",
        "edited",
    }


def test_scope_job_keeps_its_required_name_and_runs_the_base_copy():
    assert "    name: Scope (recipe pull requests)\n" in SCOPE
    assert "trusted/tools/check_recipe_scope.py" in SCOPE
    assert "github.event.pull_request.base.sha" in SCOPE


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


def test_constraints_pin_the_plotting_stack_exactly():
    pins = {
        line.split("==")[0]: line.split("==")[1]
        for line in CONSTRAINTS.splitlines()
        if line and not line.startswith("#")
    }
    assert {"matplotlib", "numpy"} <= set(pins)
    assert all(re.fullmatch(r"[0-9][0-9A-Za-z.]*", version) for version in pins.values())


def test_main_runs_are_never_cancelled_and_pull_request_runs_are():
    body = code(NOTEBOOKS)
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in body
    assert "group: notebooks-${{ github.event.pull_request.number || github.sha }}" in body


def test_push_selection_uses_the_previous_tip_and_a_manual_run_can_force_everything():
    body = code(NOTEBOOKS)
    assert "workflow_dispatch:" in body
    assert re.search(r"inputs:\n\s+full:\n(?:\s+.*\n)*?\s+default: true", body)
    assert '--base "$BEFORE_SHA" --head HEAD --lenient' in body
    assert "BEFORE_SHA: ${{ github.event.before }}" in body
