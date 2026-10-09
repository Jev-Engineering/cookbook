"""Python's half of recipe 09: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed destination catalog a small office's shared drive uses. Jev never sees these as
# folders it may write to: it only names one of them, and Python decides what that answer may
# do (CONTRIBUTING.md, "Python owns every side effect"). ``UNSORTED`` is not a destination; it
# is the option for a file whose name and excerpt do not clearly belong to any of the other
# four, the fallback outcome this use case names.
INVOICES = "invoices"
CONTRACTS = "contracts"
REPORTS = "reports"
CORRESPONDENCE = "correspondence"
UNSORTED = "unsorted"
FOLDERS = (INVOICES, CONTRACTS, REPORTS, CORRESPONDENCE)
OPTIONS = (*FOLDERS, UNSORTED)

PLACED = "placed"
REVIEW = "unsorted"

# Descriptions that say what each folder covers and, for the pair most often confused
# (an invoice that also carries contract language, or the reverse), what belongs to the
# other one instead.
_DESCRIPTIONS = {
    INVOICES: (
        "Billing paperwork: invoices, receipts, purchase orders and payment confirmations. "
        "A document that is mostly an amount due, a payment term or a receipt number is an "
        "invoice even if it also references an existing contract; it is a contract only when "
        "its main content is the agreement itself, such as new or changed terms to sign."
    ),
    CONTRACTS: (
        "Legal agreements: signed contracts, non-disclosure agreements, vendor terms and "
        "lease or service renewals. A renewal notice that states a price is still a contract "
        "when what it asks for is a signature accepting new terms, not payment of a bill."
    ),
    REPORTS: (
        "Internal reporting: status updates, sales or analytics summaries, and performance or "
        "project reviews written for people inside the company, not sent to a specific person."
    ),
    CORRESPONDENCE: (
        "Letters and message threads written to or from a specific person: emails, meeting "
        "notes and replies, even one whose file name was given a generic label such as "
        "'report' or 'summary' by whoever saved it."
    ),
    UNSORTED: (
        "The file name and excerpt do not clearly match any of the folders above: the "
        "content is unrelated to the office's billing, legal, reporting or correspondence "
        "work, or there is too little text in the excerpt to tell."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one file: its name and a short text excerpt, nothing else.

    ``fields`` also carries ``file_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the proposal, so it never needs to pass through the model.
    """
    return {"filename": fields["filename"], "excerpt": fields["excerpt"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every file. The options come from ``OPTIONS``."""
    return {
        "destination": Choice(
            instructions=(
                "Which folder should this file be organized into, based on its name and the "
                "excerpt of its text?"
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Proposal:
    """One row of the dry-run preview: the proposed destination, or ``unsorted`` with why.

    ``destination`` is one of ``FOLDERS`` when the proposal is placed, and ``None`` when it is
    left unsorted (no file is moved either way: this is a preview, built by Python, never a
    real move, create or read of anything outside the fixtures)."""

    file_id: str
    destination: str | None
    outcome: str
    reason: str


def propose_destination(file_id: str, answer: Any, min_confidence: float) -> Proposal:
    """Propose a destination only when Jev named a real folder confidently enough.

    Two things send a file to the ``unsorted`` row of the preview, whatever the file: Jev
    itself naming the ``unsorted`` option (its own fallback, used when the excerpt does not
    clearly match a folder), and a confidence below ``min_confidence`` even for a real folder.
    Every real folder is one Python is willing to propose, so once ``unsorted`` is ruled out,
    confidence is the only remaining check. The rule is code, so it holds whatever the model
    answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == UNSORTED:
        return Proposal(file_id, None, REVIEW, "no folder matches")
    if answer.confidence < min_confidence:
        return Proposal(file_id, None, REVIEW, "confidence below the threshold")
    return Proposal(file_id, answer.choice, PLACED, "confident match")


def placement_confidence(answer: Any) -> float:
    """A confidence signal ``jev_cookbook.evaluation``'s selective-prediction helpers
    (``select_confidence_threshold``, ``evaluate_selective``) can select a threshold on.

    Those helpers assume one confidence number gates everything, which fits a rule with a
    single cutoff (the pattern ``docs/fixtures.md`` and recipe 01 use) but not this recipe's
    two-part rule: an answer of ``unsorted`` is never placed, however confident Jev is that
    nothing else fits. Reporting ``answer.confidence`` unchanged would let a confident
    ``unsorted`` answer count as "answered" in the selective-prediction curve, which does not
    match what ``propose_destination`` actually does with it. This mirrors the documented
    precedent for a Noul recipe that wants a confidence signal independent of the one field its
    answer type has (``noul_confidence(noul) = max(p, 1 - p)``, docs/evaluation.md): ``-1.0``
    sits below every real confidence (which is always in ``[0, 1]``), so an ``unsorted`` answer
    is never selected by any non-negative threshold, exactly like ``propose_destination``.
    """
    return -1.0 if answer.choice == UNSORTED else answer.confidence
