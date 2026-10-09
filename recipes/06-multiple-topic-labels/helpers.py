"""Python's half of recipe 06: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions, the state and the rules cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed list of topic labels the catalog's use case names ("every applicable topic").
# A dict, not a set, so the order Python builds the questions in is stable and so that each
# label carries one description, used both in the question's criteria and by build_fixtures.py.
# A piece of feedback can raise any number of these at once (zero, one, or several), which is
# exactly why this recipe is not a Choice: Choice commits to exactly one option, and these
# outcomes are not mutually exclusive (CONTRIBUTING.md section 3, "Noul propositions are written
# as statements that can be true or false. One independent question per label for multi-label
# tasks.").
LABELS: dict[str, str] = {
    "pricing": "the price, a charge, a subscription cost, or a refund tied to money",
    "reliability": "the product crashing, an error, downtime, or something not working as built",
    "usability": "how easy or hard the product is to learn, use, or navigate",
    "support": "an interaction with customer support, sales, or service staff",
    "feature_request": (
        "wanting a capability, integration, or behavior the product does not currently have"
    ),
}

# Outcomes the three-path rule in ``decide_tags`` can produce for one (example, label) pair.
# UNCERTAIN's value is the lexicon's own outcome string, "review" (docs/glossary.md#review):
# the name stays UNCERTAIN because it is the clearer word for what a low-confidence label is,
# but what the rule actually reports for it is "review", the same word every other recipe's
# confidence-gated outcome reports.
YES = "yes"
NO = "no"
UNCERTAIN = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one piece of feedback: the text, and nothing else.

    ``fields`` also carries ``feedback_id``, a bookkeeping identifier. Python keeps it and
    attaches it to the outcome, so it never needs to pass through the model.
    """
    return {"text": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """One independent ``Noul`` per label in ``LABELS``, built by Python from that fixed list.

    Each proposition is a statement that can be true or false ("The feedback is about ..."),
    not a question, as CONTRIBUTING.md requires. All of them describe the same state, so
    ``backend.decide`` sends them together in a single request: TypeSafe's primitives page
    (S02) says independent questions over the same state belong in one request. They stay
    independent questions, not one five-way Choice, because the five outcomes are not
    exclusive: a single piece of feedback can be about pricing and reliability at once, or
    about neither.
    """
    return {
        label: Noul(
            instructions=f"The feedback is about {description}.",
            criteria={
                "true": f"The feedback is about {description}.",
                "false": "The feedback does not raise this topic at all.",
            },
        )
        for label, description in LABELS.items()
    }


@dataclass(frozen=True)
class LabelDecision:
    """What Python decided for one (example, label) pair: the business-rule tag (always
    computed), and the three-path outcome a confidence gate adds on top of it."""

    label: str
    noul: float
    tag: bool
    outcome: str
    reason: str


def decide_tags(
    answers: Any,
    thresholds: dict[str, float],
    confidence_cutoff: float,
) -> dict[str, LabelDecision]:
    """Apply the per-label business rule and the shared confidence gate to one request's answers.

    ``answers`` is a mapping from label name to a Noul answer (or anything with a ``.noul``).
    For every label in ``thresholds``:

    - the business tag is ``noul >= thresholds[label]`` (the rule ``multilabel_from_noul``
      applies at evaluation time; this function applies the same comparison per label so the
      notebook can show it decision by decision);
    - the outcome is ``"review"`` whenever ``noul_confidence(noul) < confidence_cutoff``,
      whatever the business tag says, and otherwise ``"yes"`` or ``"no"`` matching the tag.

    A label routed to ``"review"`` is not reported as a tag either way: it is Python's
    explicit third path (CONTRIBUTING.md section 4, "Uncertain or inconsistent results go to
    an explicit review outcome."), alongside the two the business rule alone would give. The
    rule holds whatever the model answers: it is code, not prose, and ``tests/test_helpers.py``
    checks it for every label and every outcome.

    Args:
        answers: ``{label: NoulAnswer-like}``, one per label in ``LABELS``.
        thresholds: The frozen per-label business thresholds (chosen on ``validation``); must
            name exactly the labels in ``LABELS``, no more and no fewer.
        confidence_cutoff: The frozen shared confidence gate (chosen on ``validation``, pooled
            across labels; see the notebook's "Python's part" section for why one shared value
            is used rather than a second per-label parameter).

    Returns:
        ``{label: LabelDecision}``, one entry per label in ``LABELS``.
    """
    if not 0.0 <= float(confidence_cutoff) <= 1.0:
        raise ValueError(f"confidence_cutoff must be between 0 and 1, got {confidence_cutoff!r}")
    if set(thresholds) != set(LABELS):
        raise ValueError(
            f"thresholds must name exactly LABELS {sorted(LABELS)}, got {sorted(thresholds)}"
        )
    decisions: dict[str, LabelDecision] = {}
    for label in LABELS:
        threshold = thresholds[label]
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError(f"threshold for {label!r} must be between 0 and 1, got {threshold!r}")
        noul = float(answers[label].noul)
        tag = noul >= threshold
        # |2p - 1| per the TypeSafe confidence page (S03); jev_cookbook.evaluation.noul_confidence
        # is the shared implementation, so it is imported rather than reimplemented here.
        confidence = noul_confidence([noul])[0]
        if confidence < confidence_cutoff:
            outcome, reason = UNCERTAIN, "confidence below the threshold"
        elif tag:
            outcome, reason = YES, "at or above the label's threshold, confident enough"
        else:
            outcome, reason = NO, "below the label's threshold, confident enough"
        decisions[label] = LabelDecision(label, noul, tag, outcome, reason)
    return decisions


def tag_set(decisions: dict[str, LabelDecision]) -> frozenset[str]:
    """The labels Python is willing to report as present: every ``"yes"`` outcome, and no
    label sent to review, whatever its business tag says (a reviewed label is not reported as
    absent or present)."""
    return frozenset(label for label, d in decisions.items() if d.outcome == YES)


def uncertain_labels(decisions: dict[str, LabelDecision]) -> tuple[str, ...]:
    """The labels sent to review for this example, in ``LABELS`` order."""
    return tuple(label for label, d in decisions.items() if d.outcome == UNCERTAIN)
