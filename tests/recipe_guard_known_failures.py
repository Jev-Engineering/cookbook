"""The allowlist of known `tests/test_recipe_guard.py` failures, one entry per (slug, check_id).

#165's guard mechanises the Wave 2 consistency review (issue #76 comment 6079429778) and the
PR #186 review's additions (issue #165 comments) over every published recipe at once. Running it
the day it lands finds real, pre-existing contract drift in merged recipes -- that drift is
#163's work list, not something this guard, or the recipe that happens to trip it next, may fix
by weakening the check. Each entry below marks one (recipe, check) pair ``xfail(strict=True)``
so CI stays green today without hiding the drift: the reason always names the #163 sweep.

The protocol, so later readers do not have to reconstruct it from a diff:

* **A recipe pull request may never add an entry here.** Touching this file from a recipe
  branch is itself out of scope (`tools/check_recipe_scope.py` rejects any path outside
  `recipes/<slug>/`), and the rule holds even for a sweep-shaped foundation branch: adding an
  entry to hide a check a recipe pull request newly fails is exactly the "never weaken a check to
  pass it" rule this guard exists to enforce on everyone else.
* **Only a #163 sweep pull request removes an entry**, by fixing the recipe so the check passes
  for real, never by deleting the entry while the underlying file is unchanged.
* **A new foundation pull request that adds a stricter check here may add entries** for the
  failures that check newly reveals (this file's first population, when #165 landed the guard; its
  fix round 1, which tightened four checks and added two more -- `metric_lines_carry_check` and
  `next_steps_inbound_links`; and its fix round 2, which turned `review_value_is_review`'s 06 and
  21 skips into two more entries by implementing the trace that check's docstring had sketched --
  are all exactly that). It may not add an entry for a check that already existed and already
  passed.
* Every entry's reason string names the check's own rule in one clause and ends with
  ``see #163``, so `gh issue list` or a grep for ``#163`` in CI logs finds the work list.

Keyed by ``(slug, check_id)``; `check_id` values are documented at the top of
`tests/test_recipe_guard.py`. A `strict=True` xfail turns an unexpected pass (the sweep fixed it
but forgot to remove the entry) into a hard failure, so the allowlist cannot silently go stale in
the other direction either.
"""

from __future__ import annotations

KNOWN_FAILURES: dict[tuple[str, str], str] = {
    # --- check 1: tests/test_build_fixtures.py matches the current scaffold -------------------
    # R8: these ship the pre-#162 test_build_fixtures.py (no inputs/labels regeneration
    # assertion, or an older docstring), or (02) no such file at all.
    # --- check 2: no "#NNN" issue numbers or "the issue" in a recipe file --------------------
    # R9/R10: a private issue cited by number or by "the issue" in a recipe file.
    (
        "20-claim-support-classification",
        "no_issue_citations",
    ): '"the issue" in helpers.py and build_fixtures.py (R10); see #163',
    (
        "22-cmdb-asset-matching",
        "no_issue_citations",
    ): '"the issue" in notebook:per-class-no-match-md and notebook:side-effect-md (R10); see #163',
    (
        "23-pairwise-answer-evaluation",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py and notebook:by-label-md (R10); see #163',
    # --- check 3: test_stored_answers_are_not_all_right is the strong form -------------------
    # R7, extended to the six Level 1 recipes Wave 2 never reviewed (01-10 are outside its
    # "Level 2 recipes 11-23" scope). Only 20 remains: it ships the weak "assert wrong" form,
    # which passes even when the confidence gate catches every mistake.
    (
        "20-claim-support-classification",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    # --- check 4a: a validation metric line carries both {selection} and {check} -------------
    # R1/R3: a validation metric line disclosed with {selection} alone.
    # --- check 4b: every printed metric line carries at least {check} (G1(d) clause 2) -------
    # R3 and more besides: a coverage/accuracy/risk/precision/recall/F1/nDCG line with no
    # {check} token (traced through bound variables), beyond what Wave 2 reviewed.
    # --- check 4c: a plot_confusion_matrix / plot_threshold_sweep / plot_risk_coverage title -
    #              carries {check} and not {selection} ---------------------------------------
    # R2: four different conventions across the thirteen; only {check}-only is compliant.
    # --- check 5: every plot_confusion_matrix / plot_risk_coverage / plot_threshold_sweep ----
    #              call prints the plotted object itself, in the same cell -------------------
    # R4 and more besides: a figure plotted with nothing of its own data printed (an aggregate
    # accuracy or a cosmetic line does not count), beyond what Wave 2 reviewed.
    (
        "20-claim-support-classification",
        "print_what_you_plot",
    ): "plot_confusion_matrix in eval-test prints only aggregate accuracy, not the matrix's own counts; see #163",
    (
        "23-pairwise-answer-evaluation",
        "print_what_you_plot",
    ): "plot_confusion_matrix in eval-confusion prints nothing (R4); see #163",
    # --- check 6a: every Next-steps link target exists on disk -------------------------------
    # R20: a forward link to a recipe not yet published, which docs/recipe-template.md forbids.
    (
        "21-quiz-answer-adjudication",
        "next_steps_links_exist",
    ): "next-md links ../36-card-game-action-selection/, not published on main (R20); see #163",
    # --- check 6b: every recipe is the target of some other recipe's Next steps -------------
    # R21: a published recipe no other recipe's Next steps links to.
    (
        "21-quiz-answer-adjudication",
        "next_steps_inbound_links",
    ): "no other published recipe's Next steps links ../21-quiz-answer-adjudication/ (R21); see #163",
    (
        "22-cmdb-asset-matching",
        "next_steps_inbound_links",
    ): "no other published recipe's Next steps links ../22-cmdb-asset-matching/ (R21); see #163",
    (
        "23-pairwise-answer-evaluation",
        "next_steps_inbound_links",
    ): "no other published recipe's Next steps links ../23-pairwise-answer-evaluation/ (R21); see #163",
    # --- check 7a: helpers.REVIEW == "review" where it exists, traced where it does not -----
    # PR #186 review MC3 / fix round 2 suggestion 2: 09 ships a different REVIEW value directly;
    # 06 and 21's confidence-gated outcome, traced through the reason string, is not "review"
    # either (both read as a plain rename of the review-queue outcome). 16 is a named exemption
    # in that check's own docstring (ESCALATE is a genuine domain-specific outcome), not here.
    (
        "21-quiz-answer-adjudication",
        "review_value_is_review",
    ): 'the confidence-gated outcome (NEEDS_REVIEW) is "needs_review", not "review"; see #163',
    # --- check 7b: the exact reason string "confidence below the threshold" in helpers.py ----
    # --- check 9: no ".[dev,ml]" install line in the README ---------------------------------
    # R15: the pre-#162 README install paragraph combined the two extras into one line.
}
