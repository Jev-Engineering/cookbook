"""Python's half of recipe 20: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed option set the catalog's use case names, in the order the issue's build notes list
# them. There is no separate "none of the above": UNRESOLVED is the fallback outcome the use
# case names, and it is a real class a passage can genuinely belong to, not a last resort for an
# option Python is unwilling to report (CONTRIBUTING.md section 4: an uncertain or inconsistent
# result goes to an explicit review outcome, but a low-confidence fallback option may stand on
# its own when choosing it triggers no side effect -- here every option is one Python is willing
# to report, so the only review branch this rule needs is the confidence gate below).
SUPPORTS = "supports"
CONTRADICTS = "contradicts"
UNRESOLVED = "unresolved"
OPTIONS = (SUPPORTS, CONTRADICTS, UNRESOLVED)

ACCEPTED = "accepted"
REVIEW = "review"

# The instructions and descriptions below are adapted from TypeSafe's citation-checking cookbook
# (S06, https://docs.typesafe.ai/cookbooks/citation_check.md): a Choice question named "relation"
# with instructions "How does the section relate to the claim?" and three options -- supports,
# contradicts, and a third option for a section that does not address the claim either way
# (there named "says_nothing"). This recipe keeps the question shape (one Choice, the same three-
# way split) and the wording of the first two options nearly verbatim, renaming "section" to
# "passage" to match this use case's own vocabulary; the third option is renamed to the use
# case's own fallback outcome, "unresolved", and its description is widened to also name the
# narrower/broader-claim and different-claim hard cases this recipe's fixtures exercise (the
# citation-checking pattern's own "says_nothing" wording covers only the off-topic case).
_DESCRIPTIONS = {
    SUPPORTS: (
        "The passage states the claim, or directly implies that it is true. A passage that "
        "proves a strictly stronger claim also supports a weaker claim it logically contains."
    ),
    CONTRADICTS: (
        "The passage states the opposite of the claim, or implies that it is false, including "
        "by giving a number, a date, or another concrete detail inconsistent with it."
    ),
    UNRESOLVED: (
        "The passage does not settle whether the claim is true or false. This covers a passage "
        "that is on the same topic without addressing what the claim specifically asserts, a "
        "passage that only supports a narrower or weaker version of the claim, a passage about "
        "a different claim that happens to share words with this one, and a passage that is "
        "simply about something else."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one example: the claim and the passage, and nothing else.

    ``fields`` also carries ``passage_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model, and every result
    still traces back to the passage it came from.
    """
    return {"claim": fields["claim"], "passage": fields["passage"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every claim/passage pair. The options come from ``OPTIONS``."""
    return {
        "relation": Choice(
            instructions="How does the passage relate to the claim?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided: the passage identifier carried through unchanged, the label Jev
    chose, and whether it is accepted or sent to review."""

    passage_id: str
    label: str
    outcome: str
    reason: str


def classify(passage_id: str, answer: Any, min_confidence: float) -> Classification:
    """Accept the chosen relation only when the answer is confident enough.

    Every option is a label Python is willing to report (there is no option to reject, unlike a
    router that only recognises some options as queues), so the only question is confidence: an
    answer at or above ``min_confidence`` is accepted as is; anything below it goes to an explicit
    ``review`` outcome instead of being reported as a result. The rule is code, so it holds
    whatever the model answers, and ``passage_id`` passes through unchanged on both outcomes.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        return Classification(passage_id, answer.choice, REVIEW, "confidence below the threshold")
    return Classification(passage_id, answer.choice, ACCEPTED, "confident")
