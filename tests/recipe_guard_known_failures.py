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
* **Only a sweep pull request removes an entry**, by fixing the recipe so the check passes for
  real, never by deleting the entry while the underlying file is unchanged. For the entries below
  that trace to #163, that sweep is a #163 sweep; for entries that trace to a different issue (see
  the next bullet), it is a sweep against *that* issue's own work list instead -- the owning issue
  is exactly what the reason string names, so there is never a need to guess which sweep clears
  which entry.
* **A new foundation pull request that adds a stricter check here may add entries** for the
  failures that check newly reveals (this file's first population, when #165 landed the guard; its
  fix round 1, which tightened four checks and added two more -- `metric_lines_carry_check` and
  `next_steps_inbound_links`; its fix round 2, which turned `review_value_is_review`'s 06 and
  21 skips into two more entries by implementing the trace that check's docstring had sketched;
  and #244's `threshold_objective_pin`, added below -- are all exactly that). It may not add an
  entry for a check that already existed and already passed.
* **Every entry's reason string names the check's own rule in one clause and ends with
  ``see #NNN``**, where ``#NNN`` is the issue whose work list actually owns clearing the entry --
  not necessarily #163. Every entry here before #244 traces to the #163 sweep (`issue #76` /
  `#165`'s own consistency-review debt) and says ``see #163``, so `gh issue list` or a grep for
  ``#163`` in CI logs finds that work list. The `threshold_objective_pin` entries below say
  ``see #244`` instead: that check is #244's own addition, the drift it reveals is #244's own
  scope (its acceptance criteria ask for exactly this per-recipe audit), and #163's sweep has no
  mandate over a check #163 never named -- grepping for ``#163`` must not silently swallow
  another issue's work list, and grepping for ``#244`` must find these 35 entries. (A corollary,
  not yet exercised: `tests/test_recipe_guard.py::guarded`'s xfail `reason=` no longer prepends a
  hardcoded ``"#163: "`` to every entry regardless of which issue it names -- it now shows the
  reason string's own citation unchanged, since that assumption stopped being true the moment a
  check other than #165's own could add entries.)

Keyed by ``(slug, check_id)``; `check_id` values are documented at the top of
`tests/test_recipe_guard.py`. A `strict=True` xfail turns an unexpected pass (the sweep fixed it
but forgot to remove the entry) into a hard failure, so the allowlist cannot silently go stale in
the other direction either.
"""

from __future__ import annotations

_THRESHOLD_OBJECTIVE_PIN_REASON = (
    "threshold_objective_pin (#244): the recipe's threshold-selection objective keyword is not "
    "asserted present against a real read of the committed notebook/helpers.py source; see #244"
)

KNOWN_FAILURES: dict[tuple[str, str], str] = {
    (slug, "threshold_objective_pin"): _THRESHOLD_OBJECTIVE_PIN_REASON
    for slug in (
        "01-sentiment-classification",
        "02-refund-intent-detection",
        "03-response-clarity-scoring",
        "04-support-ticket-routing",
        "05-document-classification",
        "06-multiple-topic-labels",
        "07-word-sense-selection",
        "08-faq-selection",
        "09-file-organization",
        "10-answer-relevance-check",
        "11-clarification-selection",
        "12-thesaurus-word-selection",
        "13-candidate-rewrite-selection",
        "14-source-span-selection",
        "15-sensitive-text-triage",
        "16-discord-moderation-triage",
        "17-passage-reranking",
        "18-duplicate-incident-matching",
        "19-ci-failure-classification",
        "20-claim-support-classification",
        "21-quiz-answer-adjudication",
        "22-cmdb-asset-matching",
        "23-pairwise-answer-evaluation",
        "24-incident-priority-composition",
        "25-change-evidence-review",
        "26-prompt-injection-screening",
        "27-function-selection",
        "28-skill-selection",
        "29-tool-outcome-verification",
        "30-citation-verification",
        "33-schema-field-mapping",
        "35-semantic-feature-extraction",
        "41-approval-scope-review",
        "42-outbound-disclosure-screening",
        "44-plan-constraint-assessment",
    )
}
