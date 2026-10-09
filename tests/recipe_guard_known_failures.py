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
  failures that check newly reveals (this file's own first population, below, is exactly that:
  #165 landing the guard). It may not add an entry for a check that already existed and already
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
    # recipes/_template/tests/test_build_fixtures.py (R8): these ship the pre-#162 file (no
    # inputs/labels regeneration assertion) or an older docstring; see #163.
    (
        "01-sentiment-classification",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "02-refund-intent-detection",
        "build_fixtures_scaffold",
    ): "no tests/test_build_fixtures.py at all, despite a replay fixtures/responses.json; see #163",
    (
        "03-response-clarity-scoring",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "04-support-ticket-routing",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "05-document-classification",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "06-multiple-topic-labels",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "07-word-sense-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "08-faq-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "09-file-organization",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "10-answer-relevance-check",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "11-clarification-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "12-thesaurus-word-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "13-candidate-rewrite-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "14-source-span-selection",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "15-sensitive-text-triage",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "16-discord-moderation-triage",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "17-passage-reranking",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    (
        "18-duplicate-incident-matching",
        "build_fixtures_scaffold",
    ): "pre-#162 test_build_fixtures.py (R8); see #163",
    # --- check 2: no "#NNN" issue numbers or "the issue" in a recipe file --------------------
    # R9/R10: a private issue cited by number or by "the issue" in a recipe file.
    (
        "01-sentiment-classification",
        "no_issue_citations",
    ): 'issue numbers/"the issue" in build_fixtures.py and tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "02-refund-intent-detection",
        "no_issue_citations",
    ): '"Issue #2" cited in notebook:queue-md, "the issue" in build_fixtures.py (R10); see #163',
    (
        "03-response-clarity-scoring",
        "no_issue_citations",
    ): '"the issue" in helpers.py and notebook prose, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "04-support-ticket-routing",
        "no_issue_citations",
    ): '"the issue" in helpers.py, build_fixtures.py and notebook:python-md, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "06-multiple-topic-labels",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "07-word-sense-selection",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "08-faq-selection",
        "no_issue_citations",
    ): '"issue #8" in helpers.py, "the issue" in helpers.py/build_fixtures.py/notebook, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "09-file-organization",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py and notebook:evaluation-md, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "10-answer-relevance-check",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py, issue numbers in tests/test_build_fixtures.py (R9/R10); see #163',
    (
        "11-clarification-selection",
        "no_issue_citations",
    ): '"the issue" in helpers.py, build_fixtures.py and notebook:python-md (R10); see #163',
    (
        "12-thesaurus-word-selection",
        "no_issue_citations",
    ): '"the issue"/"The issue" in notebook:evaluation-md and notebook:keep-original-md (R10); see #163',
    (
        "13-candidate-rewrite-selection",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py (R10); see #163',
    (
        "16-discord-moderation-triage",
        "no_issue_citations",
    ): '"The issue"/"the issue" in helpers.py, build_fixtures.py, README.md and notebook (R9/R10); see #163',
    (
        "17-passage-reranking",
        "no_issue_citations",
    ): '"the issue" (x3) in helpers.py (R10, R11 business-cutoff recipe); see #163',
    (
        "18-duplicate-incident-matching",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py (R10); see #163',
    (
        "19-ci-failure-classification",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py (R10); see #163',
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
    (
        "05-document-classification",
        "no_issue_citations",
    ): '"#124"/"#129" in tests/test_build_fixtures.py (R9, pre-#162 copy); see #163',
    (
        "15-sensitive-text-triage",
        "no_issue_citations",
    ): '"the issue" in build_fixtures.py (R10); see #163',
    # --- check 3: test_stored_answers_are_not_all_right is the strong form -------------------
    # R7, extended to the six Level 1 recipes Wave 2 never reviewed (01-10 are outside its
    # "Level 2 recipes 11-23" scope): 01, 02, 03, 04, 06, 08, 09 and 10 have no
    # test_stored_answers_are_not_all_right at all, replay recipe or not; 07, 12, 13, 16, 19 and
    # 20 ship only the weak "assert wrong" form, which passes even when the confidence gate
    # catches every mistake.
    (
        "01-sentiment-classification",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "02-refund-intent-detection",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "03-response-clarity-scoring",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "04-support-ticket-routing",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "05-document-classification",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "06-multiple-topic-labels",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "07-word-sense-selection",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    (
        "08-faq-selection",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "09-file-organization",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "10-answer-relevance-check",
        "stored_answers_strong_form",
    ): "no test_stored_answers_are_not_all_right in tests/ at all; see #163",
    (
        "12-thesaurus-word-selection",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    (
        "13-candidate-rewrite-selection",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    (
        "16-discord-moderation-triage",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    (
        "19-ci-failure-classification",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    (
        "20-claim-support-classification",
        "stored_answers_strong_form",
    ): "weak assert-wrong form, not re-derived from the frozen threshold (R7); see #163",
    # --- check 4a: a validation metric line carries both {selection} and {check} -------------
    # R1/R3: a validation metric line disclosed with {check} alone, or with neither label.
    (
        "08-faq-selection",
        "validation_lines_carry_selection_and_check",
    ): "a validation metric line prints {selection} without {check}; see #163",
    (
        "18-duplicate-incident-matching",
        "validation_lines_carry_selection_and_check",
    ): "validation metric lines print {selection} without {check} (R1, 14 lines across 5 cells); see #163",
    # --- check 4b: a plot_confusion_matrix / plot_threshold_sweep / plot_risk_coverage title -
    #              carries {check} and not {selection} ---------------------------------------
    # R2: four different conventions across the thirteen; only {check}-only is compliant.
    (
        "02-refund-intent-detection",
        "figure_titles_check_only",
    ): "validation figure titles carry {selection} without {check} (R2); see #163",
    (
        "06-multiple-topic-labels",
        "figure_titles_check_only",
    ): "validation figure titles carry {selection} without {check} (R2); see #163",
    (
        "10-answer-relevance-check",
        "figure_titles_check_only",
    ): "validation figure titles carry {selection} without {check} (R2); see #163",
    (
        "12-thesaurus-word-selection",
        "figure_titles_check_only",
    ): 'validation figure title has no disclosure label at all, "Validation confidence sweep" (R2); see #163',
    (
        "14-source-span-selection",
        "figure_titles_check_only",
    ): "validation figure title carries {selection}{check} rather than {check} alone (R2); see #163",
    (
        "15-sensitive-text-triage",
        "figure_titles_check_only",
    ): "validation figure titles carry {selection} without {check} (R2); see #163",
    (
        "18-duplicate-incident-matching",
        "figure_titles_check_only",
    ): "validation figure title carries {selection} without {check} (R2); see #163",
    # --- check 5: every plot_confusion_matrix / plot_risk_coverage call has a printed table --
    # R4: a confusion-matrix figure plotted with no printed table in the same or preceding cell.
    (
        "09-file-organization",
        "print_what_you_plot",
    ): "plot_confusion_matrix in test-matrix prints nothing; see #163",
    (
        "23-pairwise-answer-evaluation",
        "print_what_you_plot",
    ): "plot_confusion_matrix in eval-confusion prints nothing (R4); see #163",
    # --- check 6: every Next-steps link target exists on disk -------------------------------
    # R20: a forward link to a recipe not yet published, which docs/recipe-template.md forbids.
    (
        "21-quiz-answer-adjudication",
        "next_steps_links_exist",
    ): "next-md links ../36-card-game-action-selection/, not published on main (R20); see #163",
    # --- check 7a: helpers.REVIEW == "review" where a REVIEW constant exists ----------------
    # PR #186 review MC3: 09 ships a different review-outcome value. (21 names its outcome
    # NEEDS_REVIEW, not REVIEW, so it has no module-level REVIEW constant for this check to
    # compare -- the check is correctly a no-op there, not a pass or a failure.)
    (
        "09-file-organization",
        "review_value_is_review",
    ): 'REVIEW = "unsorted", not "review" (PR #186 review MC3); see #163',
    # --- check 7b: the exact reason string "confidence below the threshold" in helpers.py ----
    (
        "02-refund-intent-detection",
        "review_reason_string",
    ): '"too close to an even split to trust either way: needs a person" instead of the lexicon reason string; see #163',
    (
        "06-multiple-topic-labels",
        "review_reason_string",
    ): '"confidence below the review cutoff" instead of the lexicon reason string; see #163',
    (
        "10-answer-relevance-check",
        "review_reason_string",
    ): "helpers.py does not use the lexicon's exact reason string; see #163",
    # --- check 9: no ".[dev,ml]" install line in the README ---------------------------------
    # R15: the pre-#162 README install paragraph combined the two extras into one line.
    (
        "02-refund-intent-detection",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "03-response-clarity-scoring",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "04-support-ticket-routing",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "06-multiple-topic-labels",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "07-word-sense-selection",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "08-faq-selection",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
    (
        "09-file-organization",
        "readme_no_dev_ml_install",
    ): 'README quotes `pip install -e ".[dev,ml]"` for reproducing outputs (R15); see #163',
}
