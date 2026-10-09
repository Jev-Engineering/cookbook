"""Python's half of recipe 05: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed option set the catalog's use case names, in the order the use case lists them, plus
# the fallback outcome it names explicitly ("... or other document type"). There is no sixth
# option: every document gets exactly one of these five, because OTHER already covers "none of
# the first four fit".
INVOICE = "invoice"
MEETING_NOTE = "meeting_note"
POLICY = "policy"
TECHNICAL_GUIDE = "technical_guide"
OTHER = "other"
OPTIONS = (INVOICE, MEETING_NOTE, POLICY, TECHNICAL_GUIDE, OTHER)

ACCEPTED = "accepted"
REVIEW = "review"

# Each description says what belongs to its option and, for the pairs that are easiest to
# confuse (invoice/other, meeting_note/policy, policy/technical_guide), what belongs to the
# other option instead (TypeSafe's guidance for options that are easy to confuse). "The
# questions" cell below shows a document where leaving that second sentence out would make the
# answer genuinely ambiguous.
_DESCRIPTIONS = {
    INVOICE: (
        "A bill requesting payment for specific goods or services: it names an amount owed and, "
        "usually, a due date or an invoice number. A receipt confirming a payment already made "
        "is not an invoice; nothing further is being requested, so that belongs to other."
    ),
    MEETING_NOTE: (
        "A record of one specific meeting that took place: who attended or spoke, and what was "
        "discussed, decided, or assigned there. A document whose main content is a standing rule "
        "that merely mentions being approved at a meeting belongs to policy, not here."
    ),
    POLICY: (
        "A standing rule or requirement that governs behavior or process going forward, stated "
        "as an obligation ('must', 'is required to', 'will not be permitted to'), independent of "
        "any single meeting or event. Minutes that report a decision as something that happened "
        "belong to meeting_note; a document whose main content is the rule itself, even if it "
        "says when or where it was approved, belongs here."
    ),
    TECHNICAL_GUIDE: (
        "Step-by-step instructions for carrying out a technical task, such as installing, "
        "configuring, or troubleshooting something, addressed to whoever performs the task. A "
        "rule that something must always be done a certain way, with no steps to follow, "
        "belongs to policy instead."
    ),
    OTHER: (
        "Does not satisfy any of the above: a personal message, a marketing or informational "
        "blurb, or any other text, including one too short to contain the signals the first "
        "four look for."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one document: its text, and nothing else.

    ``fields`` also carries ``doc_id``, a bookkeeping identifier. Python keeps it and attaches
    it to the outcome, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every document. The options come from ``OPTIONS``."""
    return {
        "doc_type": Choice(
            instructions="What type of document is this?",
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided: the type Jev chose, and whether it is accepted or sent to review."""

    doc_id: str
    label: str
    outcome: str
    reason: str


def classify(doc_id: str, answer: Any, min_confidence: float) -> Classification:
    """Accept the chosen document type only when the answer is confident enough.

    Every option is a type Python is willing to report (there is no option to reject, unlike a
    router that only recognises some options as queues), so the only question is confidence: an
    answer at or above ``min_confidence`` is accepted as is; anything below it goes to an
    explicit ``review`` outcome instead of being reported as a result. The rule is code, so it
    holds whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.confidence < min_confidence:
        return Classification(doc_id, answer.choice, REVIEW, "confidence below the threshold")
    return Classification(doc_id, answer.choice, ACCEPTED, "confident")
