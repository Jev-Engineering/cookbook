"""Python's half of recipe 50: the state, the two requests, and the triage rule.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.

Two requests make up one task. Request A is always sent: three independent judgments about
one vendor compliance statement, asked together (a ``Choice`` category, and two ``Noul``
propositions). Request B is sent only when request A's own ``category`` answer says the
statement is not ``OTHER`` -- a ``Score`` rubric rating how specific the statement is. Python,
not Jev, decides whether request B is worth asking, and that decision depends only on the
earlier answer: see ``needs_followup``.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice, Noul, Score, replay_key
from jev_cookbook.evaluation import score_level

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed compliance categories this use case names, plus the explicit fallback option
# (CONTRIBUTING.md section 3: "Include none, other, no_match, or uncertain outcomes when the
# use case calls for them."). Order here is the order every stored Choice answer's
# probabilities are written in.
DATA_HANDLING = "data_handling"
SECURITY_CONTROLS = "security_controls"
BUSINESS_CONTINUITY = "business_continuity"
OTHER = "other"
CATEGORIES = (DATA_HANDLING, SECURITY_CONTROLS, BUSINESS_CONTINUITY, OTHER)

_CATEGORY_DESCRIPTIONS = {
    DATA_HANDLING: (
        "The statement is about how personal or customer data is collected, stored, shared, "
        "or deleted -- data residency, access limits, retention, or pseudonymization."
    ),
    SECURITY_CONTROLS: (
        "The statement is about protecting systems from unauthorized access or tampering -- "
        "encryption, authentication, firewalls, audits, or penetration testing."
    ),
    BUSINESS_CONTINUITY: (
        "The statement is about keeping the business or its services running through a "
        "disruption -- backups, failover, disaster recovery, or redundancy."
    ),
    OTHER: "The statement is not about any compliance category above, or does not say enough to tell.",
}

# Outcomes the triage rule can produce. Two are reviews (REVIEW itself, and the stateful
# variant ESCALATE_REVIEW a resubmission still failing the gate produces); CLEARED and
# NEEDS_DETAIL are complete answers, gated on confidence like any other result (CONTRIBUTING.md
# section 4); FLAGGED is the one outcome a human compliance reviewer actually has to act on.
REVIEW = "review"
ESCALATE_REVIEW = "escalate_review"
CLEARED = "cleared"
NEEDS_DETAIL = "needs_detail"
FLAGGED = "flagged"

# docs/glossary.md#review: a confidence-gated review always carries this exact reason string.
CONFIDENCE_REASON = "confidence below the threshold"

# The specificity rubric (request B): every level described in words, in order, from least to
# most specific. Mapping, weighting and the business cutoff below are plain Python; Jev only
# ever returns a distribution over these four described levels.
SPECIFICITY_LEVELS = (
    "No concrete detail: a general claim with nothing a reviewer could check.",
    "Names a general policy area, but no specific control or standard.",
    "Names a specific control or standard, with no detail on how it is verified.",
    "Names a specific control or standard and says how it is verified or audited.",
)
# A plain Python business rule, not calibrated from data: a statement scores FLAGGED only once
# it clears this level. Changing the rubric's wording would change what "specific enough" means;
# changing this constant would not need new fixtures, which is why it is a bare constant here
# rather than something select_confidence_threshold or select_threshold chooses.
SPECIFICITY_CUTOFF = 2


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one statement: its text, nothing else.

    ``fields`` also carries ``resubmission``, which Python keeps for itself (the stateful rule
    in ``triage`` below) and never sends to the model.
    """
    return {"statement": fields["statement"]}


def build_questions_a() -> dict[str, Any]:
    """Request A: three independent judgments about one statement, asked together."""
    return {
        "category": Choice(
            instructions="Which compliance category does this statement belong to?",
            criteria={name: _CATEGORY_DESCRIPTIONS[name] for name in CATEGORIES},
        ),
        "verifiable": Noul(
            instructions="This statement makes a claim that could be checked against evidence.",
        ),
        "names_control": Noul(
            instructions="This statement names a specific control, standard, or policy by name.",
        ),
    }


def build_questions_b() -> dict[str, Any]:
    """Request B: how specific the statement is. Sent only when ``needs_followup`` says so."""
    return {
        "specificity": Score(
            instructions="How specific is this statement, from the levels described?",
            criteria=list(SPECIFICITY_LEVELS),
        )
    }


def needs_followup(category_answer: Any) -> bool:
    """Whether request B is worth asking, from request A's own answer alone.

    Depends only on the earlier answer (CONTRIBUTING.md section 3), never on the gold label:
    a statement Jev itself calls ``OTHER`` is not worth rating for specificity, whatever the
    gold category says. Backends can disagree with each other and with gold here, and the
    notebook shows that disagreement rather than papering over it.
    """
    return category_answer.choice != OTHER


class MemoisingBackend:
    """One backend, wrapped so that an identical request is sent once and then reused.

    Two different quantities get confused whenever a recipe says what a live run of it costs,
    so this wrapper counts both and the notebook prints both:

    * ``requests`` -- distinct ``(state, questions)`` pairs asked, keyed by ``replay_key``, the
      same key a stored responses file is keyed on. ``fixtures/responses.json`` holds exactly
      one entry per distinct request, so this is the quantity that file's length measures.
    * ``calls`` -- ``decide()`` calls actually forwarded to the wrapped backend. A live backend
      bills one request per forwarded call and caches nothing: ``LiveBackend.decide`` spends
      budget on every attempt it makes (its own budget error says "retries and timed-out
      requests count"), and the skip-what-is-already-stored deduplication in
      ``jev_cookbook.live.record_responses`` applies to a recorder run, which running this
      notebook is not. So a notebook that decides the same row again to fill a second table
      pays for it again, and this count -- not ``requests`` -- is the one a reader needs to
      size ``JEV_COOKBOOK_LIVE_MAX_REQUESTS``, as a floor, since each retried attempt bills on
      top of it.

    ``repeats`` is the requests answered from this wrapper's own memo instead of being
    forwarded; without the memo each would have been another forwarded call. Memoising cannot
    change what a request means (the key is the whole request), and it makes every table in
    this notebook read the same answer for the same request rather than a fresh sample of it.

    Every other attribute (``mode``, ``model``, ``recorded_dates``) is forwarded to the wrapped
    backend, so this reads as the backend it wraps everywhere else in the harness.
    """

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.calls = 0
        self.repeats = 0
        self._answers: dict[str, Any] = {}

    @property
    def requests(self) -> int:
        """Distinct requests asked through this wrapper (one per ``replay_key``)."""
        return len(self._answers)

    def decide(self, state: Any, questions: dict[str, Any]) -> Any:
        key = replay_key(state, questions)
        if key in self._answers:
            self.repeats += 1
            return self._answers[key]
        self.calls += 1
        self._answers[key] = self.backend.decide(state, questions)
        return self._answers[key]

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes this wrapper does not define itself; ``backend`` is set
        # first in __init__, so this never recurses on it.
        return getattr(self.backend, name)


def noul_gate(probability: float, width: float) -> str:
    """Where ``probability`` (a Noul's probability of yes) falls in the two-sided confidence
    band of half-width ``width``, ``width`` in ``[0, 1]``.

    ``confidence = |2p - 1|`` is symmetric about 0.5 (docs/glossary.md#confidence), so the band
    accepts a confident answer on EITHER side::

        "true"   if probability >= (1 + width) / 2    (confidently yes)
        "false"  if probability <= (1 - width) / 2    (confidently no)
        "review" otherwise

    ``width`` is chosen on ``validation`` with ``select_confidence_threshold`` and frozen (the
    notebook's "Calibrating each backend separately" names the same function); whether a given
    ``width`` ever changes an outcome is not derivable from ``width`` and a business threshold
    alone -- it depends on how a rule wires the gate into its own composition, so it has to be
    measured against this module's own ``triage``, not assumed (see the notebook's "Where the
    Noul gate bends" section).
    """
    if not 0.0 <= width <= 1.0:
        raise ValueError(f"width must be between 0 and 1, got {width!r}")
    if probability >= (1.0 + width) / 2.0:
        return "true"
    if probability <= (1.0 - width) / 2.0:
        return "false"
    return "review"


@dataclass(frozen=True)
class TriageResult:
    """What Python decided for one statement: an outcome, and why."""

    statement_id: str
    outcome: str
    reason: str


def triage(
    statement_id: str,
    category_answer: Any,
    verifiable_answer: Any,
    names_control_answer: Any,
    specificity_answer: Any,
    *,
    choice_threshold: float,
    gate_width: float,
    resubmission: bool,
) -> TriageResult:
    """Combine one backend's answers into one outcome. Holds whatever the model answers.

    ``specificity_answer`` is the request-B answer, or ``None`` when ``needs_followup`` said
    request B was not worth asking for this backend's own ``category`` answer.

    Order of checks: the confidence gate on ``category`` first (CONTRIBUTING.md section 4:
    permissions and gates are enforced in code, whatever the model answers); then the complete
    fallback answer ``OTHER``, itself gated by having passed that same confidence check; then
    the two-sided Noul gate on both propositions; only once both are confidently "true" does
    the specificity cutoff (plain Python arithmetic) decide between ``FLAGGED`` and
    ``NEEDS_DETAIL``. A resubmission (state Python keeps outside the model) that still lands on
    ``REVIEW`` escalates instead, because it has already failed this gate once before.
    """
    if not 0.0 <= choice_threshold <= 1.0:
        raise ValueError(f"choice_threshold must be between 0 and 1, got {choice_threshold!r}")
    if category_answer.confidence < choice_threshold:
        outcome, reason = REVIEW, CONFIDENCE_REASON
    elif not needs_followup(category_answer):
        outcome, reason = CLEARED, "no compliance category applies"
    else:
        verifiable_gate = noul_gate(verifiable_answer.noul, gate_width)
        names_gate = noul_gate(names_control_answer.noul, gate_width)
        if verifiable_gate == "review" or names_gate == "review":
            outcome, reason = REVIEW, CONFIDENCE_REASON
        elif verifiable_gate == "true" and names_gate == "true":
            if (
                specificity_answer is not None
                and score_level(specificity_answer) >= SPECIFICITY_CUTOFF
            ):
                outcome, reason = FLAGGED, "substantive and specific"
            else:
                outcome, reason = NEEDS_DETAIL, "substantive claim lacks verification detail"
        else:
            outcome, reason = CLEARED, "not a verifiable, specific claim"
    if resubmission and outcome == REVIEW:
        outcome, reason = ESCALATE_REVIEW, "resubmission still below the threshold"
    return TriageResult(statement_id, outcome, reason)
