"""Python's half of recipe 08: the state, the question and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed FAQ catalog this recipe answers from. Each id is a Choice option; Python, not Jev,
# holds the stored answer text for it, and returns that text unchanged when a question matches
# it with enough confidence: Python returns the stored FAQ answer by identifier, never a
# model-written one.
PASSWORD_RESET = "password_reset"
CHANGE_EMAIL = "change_email"
CANCEL_SUBSCRIPTION = "cancel_subscription"
BILLING_CYCLE = "billing_cycle"
EXPORT_DATA = "export_data"
DELETE_ACCOUNT = "delete_account"
# The explicit fallback outcome the use case names, for a question none of the six FAQs above
# addresses. It is a Choice option like the others, built by Python, not a separate code path
# Jev reaches by failing to answer (CONTRIBUTING.md section 3: "Include none, other, no_match,
# or uncertain outcomes when the use case calls for them.").
NO_MATCH = "no_match"

OPTIONS = (
    PASSWORD_RESET,
    CHANGE_EMAIL,
    CANCEL_SUBSCRIPTION,
    BILLING_CYCLE,
    EXPORT_DATA,
    DELETE_ACCOUNT,
    NO_MATCH,
)

# The stored answer Python returns for a confident match. Jev never sees this text and never
# writes it; it only picks the identifier.
ANSWERS = {
    PASSWORD_RESET: (
        "Open the sign-in page, select 'Forgot password', and follow the link we email you to "
        "set a new one. The link expires after 30 minutes."
    ),
    CHANGE_EMAIL: (
        "Go to Account settings > Profile, enter the new email address, and confirm it from the "
        "verification link we send there."
    ),
    CANCEL_SUBSCRIPTION: (
        "Go to Account settings > Subscription > Cancel plan. Cancelling takes effect at the end "
        "of the current billing period; you keep access until then."
    ),
    BILLING_CYCLE: (
        "Your plan renews every 30 days from the date you subscribed. The next charge date is "
        "shown on the Billing page under Account settings."
    ),
    EXPORT_DATA: (
        "Go to Account settings > Data > Export, choose a format, and we will email a download "
        "link within 24 hours."
    ),
    DELETE_ACCOUNT: (
        "Go to Account settings > Delete account, confirm by email, and the account and its data "
        "are permanently removed after a 14-day grace period."
    ),
}

# Descriptions say what belongs to each FAQ and, for the three pairs that are easiest to
# confuse (password_reset vs. change_email; cancel_subscription vs. billing_cycle;
# cancel_subscription vs. delete_account), what belongs to the other option instead
# (TypeSafe's guidance for options that are easy to confuse: say what doesn't belong to a
# neighbouring option).
_DESCRIPTIONS = {
    PASSWORD_RESET: (
        "The question asks how to reset a forgotten password or sign back in after being "
        "locked out by a wrong password. A request to change the email address on the account "
        "instead belongs to change_email."
    ),
    CHANGE_EMAIL: (
        "The question asks how to change the email address on the account, for example after "
        "switching jobs or email providers. A request to recover a forgotten password instead "
        "belongs to password_reset."
    ),
    CANCEL_SUBSCRIPTION: (
        "The question asks how to cancel a paid subscription so it does not renew again, or "
        "asks to stop being charged, with the account itself left open. A question only about "
        "when the next charge happens, with no request to stop anything, belongs to "
        "billing_cycle instead; a request to remove the account itself, not just stop paying, "
        "belongs to delete_account instead."
    ),
    BILLING_CYCLE: (
        "The question asks when the account will next be charged or how often billing repeats, "
        "without asking to cancel or stop anything. A request to stop future charges belongs to "
        "cancel_subscription instead."
    ),
    EXPORT_DATA: "The question asks how to download or export the data stored in the account.",
    DELETE_ACCOUNT: (
        "The question asks to permanently delete the account and its data, not merely to stop "
        "future charges. A request only to stop being billed, with the account itself left "
        "open, belongs to cancel_subscription instead."
    ),
    NO_MATCH: (
        "None of the other options addresses the question: it is about something this FAQ list "
        "does not cover, such as a feature request, a bug report, pricing for a plan that does "
        "not exist, or a topic unrelated to the account, billing, password, email, data or "
        "cancellation."
    ),
}

# Outcomes the rule below can produce.
MATCHED = "matched"
NO_MATCH_OUTCOME = "no_match"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one question: the customer's text, and nothing else.

    ``fields`` also carries ``question_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"question": fields["text"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every customer message. The options come from ``OPTIONS``:
    the six FAQ identifiers plus the fallback ``no_match``, all built by Python."""
    return {
        "faq": Choice(
            instructions=("Which one of these FAQs, if any, best answers the customer's question?"),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


@dataclass(frozen=True)
class Selection:
    """What Python decided: the option Jev chose, the outcome, the stored FAQ answer (only when
    the outcome is ``matched``), and why."""

    question_id: str
    label: str
    outcome: str
    answer: str | None
    reason: str


def select_faq(question_id: str, answer: Any, min_confidence: float) -> Selection:
    """Return the stored FAQ answer only when Jev names a real FAQ and is confident enough.

    ``no_match`` is never run past the confidence gate, whatever its confidence: the option
    itself already says no FAQ addresses the question, so there is no stored answer a
    confidence check could protect (the options are FAQ identifiers from a short candidate list
    plus ``no_match``, and Python returns the stored FAQ answer by identifier, never a
    model-written one). Any other answer that is not confident enough goes to an explicit
    ``review`` outcome instead of returning a possibly wrong FAQ. The rule is code, so it holds
    whatever the model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NO_MATCH:
        return Selection(
            question_id, NO_MATCH, NO_MATCH_OUTCOME, None, "no FAQ addresses the question"
        )
    if answer.confidence < min_confidence:
        return Selection(question_id, answer.choice, REVIEW, None, "confidence below the threshold")
    return Selection(question_id, answer.choice, MATCHED, ANSWERS[answer.choice], "confident match")
