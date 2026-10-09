"""Python's half of recipe 13: the state, the question and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The three candidate-rewrite identifiers are always these fixed names, whatever the three
# rewrites under them say: Python assigns the position, never the model. The fourth option is
# the explicit fallback the use case names, for an item where none of the three candidates both
# preserves the original sentence's meaning and matches the requested tone.
CANDIDATE_1 = "candidate_1"
CANDIDATE_2 = "candidate_2"
CANDIDATE_3 = "candidate_3"
NO_SUITABLE_REWRITE = "no_suitable_rewrite"
CANDIDATES = (CANDIDATE_1, CANDIDATE_2, CANDIDATE_3)
OPTIONS = (*CANDIDATES, NO_SUITABLE_REWRITE)

# Outcomes the rule below can produce.
ACCEPTED = "accepted"
KEPT_ORIGINAL = "kept_original"
REVIEW = "review"

# Every candidate option carries the same description, naming the position it sits at in the
# state: there is nothing else stable to describe ahead of time, because the text under each
# identifier changes from one item to the next. Each description also says what does *not*
# belong to it (TypeSafe's guidance for options that are easy to confuse: say what belongs to a
# neighbouring option instead), since a candidate that is well written but wrong in one of two
# specific ways -- a changed meaning, or a missed tone -- is exactly what this recipe's hard
# cases test.
_CANDIDATE_DESCRIPTION = (
    "The text under '{name}' in the state is a faithful rewrite of the original sentence: it "
    "keeps every fact, request and commitment the original makes, changing none of them, and "
    "its tone matches the requested tone. A rewrite that changes what the original says, or "
    "that reads in a different tone than the one requested, does not belong to this option "
    "even if it is otherwise well written -- it belongs to no_suitable_rewrite instead, "
    "together with the other two candidates, unless one of the other two candidates is the "
    "faithful, correctly toned one."
)
_NO_SUITABLE_DESCRIPTION = (
    "None of candidate_1, candidate_2 or candidate_3 both preserves the original sentence's "
    "meaning and matches the requested tone: each one either changes what the original says, "
    "misses the requested tone, or both. Choose this option instead of picking the "
    "least-wrong candidate."
)


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one rewrite choice: the original sentence, the requested tone,
    and the three candidate rewrites, each under its own fixed identifier.

    ``fields`` also carries ``item_id`` (bookkeeping) and ``candidates`` as a tuple Python keeps
    for itself, so it can resolve whichever identifier Jev picks back to that candidate's own
    text. Neither passes through the model.
    """
    candidate_1, candidate_2, candidate_3 = fields["candidates"]
    return {
        "original": fields["original"],
        "requested_tone": fields["requested_tone"],
        CANDIDATE_1: candidate_1,
        CANDIDATE_2: candidate_2,
        CANDIDATE_3: candidate_3,
    }


def build_questions() -> dict[str, Choice]:
    """The one question asked about every item. The option set is always the same four names:
    the three candidate identifiers, built by Python every time from the same fixed labels, and
    the explicit fallback ``no_suitable_rewrite``."""
    criteria = {name: _CANDIDATE_DESCRIPTION.format(name=name) for name in CANDIDATES}
    criteria[NO_SUITABLE_REWRITE] = _NO_SUITABLE_DESCRIPTION
    return {
        "rewrite": Choice(
            instructions=(
                "The state gives the original sentence, the requested tone, and three candidate "
                "rewrites of it under candidate_1, candidate_2 and candidate_3. Choose the "
                "identifier of the one candidate that both keeps the original sentence's "
                "meaning intact and matches the requested tone. If none of the three candidates "
                "does both, choose no_suitable_rewrite instead of picking the closest wrong one."
            ),
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class Selection:
    """What Python decided: the option Jev chose, the outcome, the text to use (the chosen
    candidate's own text when accepted, the original sentence unchanged when no candidate fit,
    or ``None`` when the item is sent for review instead of being resolved), and why."""

    item_id: str
    label: str
    outcome: str
    text: str | None
    reason: str


def select_rewrite(
    item_id: str,
    answer: Any,
    original: str,
    candidates: dict[str, str],
    min_confidence: float,
) -> Selection:
    """Return the chosen candidate's own text for a confident match, keep the original sentence
    unchanged whenever Jev names ``no_suitable_rewrite`` (whatever its confidence), and send
    anything else uncertain to an explicit ``review`` outcome instead of reporting a possibly
    wrong rewrite.

    ``no_suitable_rewrite`` is never run past the confidence gate: choosing it already means
    keeping the sentence exactly as written, which is a side-effect-free outcome a confidence
    check has nothing to protect -- unlike reporting one of the three candidates' own (possibly
    wrong) rewritten text, which the gate exists to guard. The rule is code, so it holds
    whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NO_SUITABLE_REWRITE:
        return Selection(
            item_id, NO_SUITABLE_REWRITE, KEPT_ORIGINAL, original, "no candidate rewrite fits"
        )
    if answer.confidence < min_confidence:
        return Selection(item_id, answer.choice, REVIEW, None, "confidence below the threshold")
    return Selection(item_id, answer.choice, ACCEPTED, candidates[answer.choice], "confident match")
