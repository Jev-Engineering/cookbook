"""Python's half of recipe 16: the state, the question and the rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The community rule every message is checked against. The rule text is supplied in the state;
# every message in this recipe is checked against this one rule (a fabricated server's conduct
# rule, not a real server's), so it is a module constant rather than a per-example field, and
# ``build_state`` below attaches it to every request.
RULE_TEXT = (
    "Lumen Games Community conduct rule: be respectful. Do not harass, threaten, demean, or "
    "target a member for who they are. No hate speech, no threats of violence or self-harm, and "
    "no sharing someone else's private information. Friendly joking between members who both "
    "enjoy it is fine; it stops being fine the moment it singles someone out or makes them a "
    "target."
)

# The three fixed outcomes the use case names (CONTRIBUTING.md section 3: "Choice options are a
# fixed, supplied set. Include none, other, no_match, or uncertain outcomes when the use case
# calls for them."). ``REVIEW_NEEDED`` is the explicit uncertain outcome Level 2 scope asks for
# ("explicit uncertain or no-match outcomes"): a message Jev itself reads as needing a person,
# not a confidence artifact Python adds on top of a two-way choice.
ALLOWED = "allowed"
REVIEW_NEEDED = "review_needed"
POTENTIALLY_VIOLATING = "potentially_violating"
# jev-1.13's documented option-order lean (S07 item 8) favours whichever option is listed
# first. Listing ``allowed`` last, rather than first, points that lean away from the option a
# confidently wrong answer would leave standing with nobody warned, not toward it.
OPTIONS = (REVIEW_NEEDED, POTENTIALLY_VIOLATING, ALLOWED)

# Descriptions say what belongs to each category and, for the pair that is easiest to confuse
# (review_needed vs. potentially_violating, over a message that quotes or reports someone
# else's abusive words), what belongs to the other option instead (TypeSafe's guidance for
# options that are easy to confuse: say what doesn't belong to a neighbouring option). S07 item
# 6 ("adversarial content") is exactly the risk this pair guards against: Jev does not treat the
# state as hostile by default, so a message that merely *carries* hostile words -- by quoting or
# reporting them -- can read as hostile itself unless the instructions say otherwise.
_DESCRIPTIONS = {
    ALLOWED: (
        "The message does not violate the rule above. This includes a message that merely uses "
        "a word the rule's examples mention (for instance 'kill', 'die', 'hate') in a way that "
        "plainly has nothing to do with a person: a game, a sport, or ordinary hyperbole. It "
        "also includes friendly joking between members that does not single anyone out, and a "
        "heated but respectful disagreement."
    ),
    REVIEW_NEEDED: (
        "The message does not clearly fit allowed or potentially_violating: its tone depends on "
        "context a reader cannot be sure of (sarcasm that could be read either way, banter that "
        "might or might not be welcome to the person on the other end, a vague message that "
        "could be about someone specific), or it quotes or describes someone else's abusive "
        "words -- for example reporting what another member said -- rather than being abusive "
        "in its own words. A person should look at it."
    ),
    POTENTIALLY_VIOLATING: (
        "The message's own words harass, threaten, demean, or target a member for who they are, "
        "share someone's private information, or otherwise cross the rule above. This is about "
        "what the message itself says, not about a word it merely contains or a quotation it "
        "carries: a message that reports or quotes someone else's abusive words belongs to "
        "review_needed instead, even when those quoted words are harsh."
    ),
}


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one message: the community rule and the message text, nothing
    else.

    ``fields`` also carries ``message_id`` and ``author``, bookkeeping Python keeps to itself;
    neither passes through the model, and both are attached to the outcome afterwards.
    """
    return {"rule": RULE_TEXT, "message": fields["message"]}


def build_questions() -> dict[str, Choice]:
    """The one question asked about every message. The options come from ``OPTIONS``."""
    return {
        "triage": Choice(
            instructions=(
                "Given the community rule above, which of these three categories does the "
                "message belong to?"
            ),
            criteria={name: _DESCRIPTIONS[name] for name in OPTIONS},
        )
    }


# The simulated moderation actions Python's rule can take, through ``jev_cookbook.simulation``
# (``ActionLog`` for ``ignore``/``warn``/``hide``, ``ReviewQueue`` for ``escalate``): nothing is
# ever posted, deleted, or sent to Discord. Every action but ``escalate`` is reached only once
# the confidence gate clears. Reaching ``ignore`` still writes an ``ActionLog`` entry, the same
# as ``warn`` and ``hide`` -- nothing is posted or deleted in the real world, but a record of the
# decision is kept -- which is one reason, below, that ``allowed`` is gated like every other
# category rather than let through on its own.
IGNORE = "ignore"
WARN = "warn"
HIDE = "hide"
ESCALATE = "escalate"


@dataclass(frozen=True)
class Moderation:
    """What Python decided: the category Jev chose, the simulated action, and why."""

    message_id: str
    label: str
    action: str
    reason: str


def moderate(message_id: str, answer: Any, min_confidence: float) -> Moderation:
    """Decide the simulated action for one message: the standard three-path pattern, applied to
    every category alike.

    A defensive membership check comes first, since the backend already rejects an option
    outside the fixed set (CONTRIBUTING.md section 3: "Choice options are a fixed, supplied
    set."). After that, **every** category -- ``allowed`` included -- goes through the same
    confidence gate before anything else is decided: below ``min_confidence`` the message is
    always escalated to a person, whatever category Jev named, because acting on *any* category
    without confidence is what the gate exists to prevent, and leaving a message that is really
    ``potentially_violating`` standing because it was confidently misread as ``allowed`` is
    exactly the kind of consequence CONTRIBUTING.md section 4 asks a review outcome to catch.

    Neither category this gate catches would even qualify for section 4's no-gate exemption, and
    each fails a different one of its three parts. ``allowed`` is a complete answer, not a
    deferral -- part (a) holds -- but it fails the other two: resolving it to ``ignore`` still
    writes an ``ActionLog`` entry, so choosing it does not record "no action" (part (b)); and
    when a confidently wrong ``allowed`` answer is really ``potentially_violating``, the message
    stays live with nobody warned at all, which is harm beyond the missed item itself (part (c)).
    ``review_needed`` fails the earlier part instead: naming it is itself asking a person to
    decide the same question again, so it is a deferral, not a complete answer, and a deferral
    never qualifies for this exemption whatever its confidence (part (a)). Both are gated here
    for these reasons, the same way ``potentially_violating`` is, not because gating is merely
    the cautious default. Only once a category clears the gate does it decide the action:
    ``allowed`` resolves to ``ignore``, a confident ``review_needed`` is warned rather than
    hidden -- the category itself already says the message's violation is not clear-cut -- and a
    confident ``potentially_violating`` is hidden. The rule is code, so it holds whatever the
    model answers.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice not in OPTIONS:
        return Moderation(message_id, answer.choice, ESCALATE, "not one of the fixed categories")
    if answer.confidence < min_confidence:
        return Moderation(message_id, answer.choice, ESCALATE, "confidence below the threshold")
    if answer.choice == ALLOWED:
        return Moderation(message_id, ALLOWED, IGNORE, "confident allowed: no action")
    if answer.choice == REVIEW_NEEDED:
        return Moderation(
            message_id, REVIEW_NEEDED, WARN, "confident review_needed: warn, do not hide"
        )
    return Moderation(
        message_id, POTENTIALLY_VIOLATING, HIDE, "confident potentially_violating: hide"
    )
