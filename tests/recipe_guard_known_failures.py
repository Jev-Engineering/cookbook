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

KNOWN_FAILURES: dict[tuple[str, str], str] = {}
