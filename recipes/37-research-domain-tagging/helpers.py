"""Python's half of recipe 37: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions, the state and the rules cannot disagree.

Design in one paragraph: an evidence passage (a fabricated research abstract or excerpt) carries
an access classification Python decides on before any request is built. A passage marked
``"restricted"`` is filtered out by :func:`accessible_examples` before anything downstream ever
sees it: no state is built for it, no question is asked about it, and nothing it says reaches
Jev. For every passage that *is* accessible, Jev answers one independent ``Noul`` proposition
per research domain -- all sent together in one request per passage, never one request per
domain -- and :func:`tag_domains` turns each probability into a business tag against that
domain's own frozen threshold, with a shared confidence gate sending an unconfident label to
review rather than reporting it either way. :func:`compose` is the one function that turns those
independent per-domain decisions into Python's task-level result for the passage: the domain set
it tags, the domains it sends to review, and the provenance of every one of those decisions, kept
and carried through rather than discarded once the tag is assigned.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Noul
from jev_cookbook.evaluation import noul_confidence

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The fixed list of research domains the catalog's use case names ("research-domain labels").
# A dict, not a set, so Python's own build order (and so the request's option order) is stable.
# Each passage can belong to any number of these domains at once (an interdisciplinary passage
# raises two or three; an unrelated passage raises none), which is exactly why this is three
# independent Noul propositions and not one three-way Choice: Choice commits to exactly one
# option, and these outcomes are not mutually exclusive (CONTRIBUTING.md section 3, "One
# independent question per label for multi-label tasks.").
DOMAINS: dict[str, str] = {
    "biomedical": (
        "biomedical or life-sciences research: a clinical, biological, or health-related "
        "finding, method, trial, or dataset"
    ),
    "computational": (
        "computer-science or computational research: an algorithm, software system, model "
        "architecture, or computational method presented as the work's own subject"
    ),
    "economics": (
        "economics or policy research: an economic model, market analysis, cost or welfare "
        "estimate, or policy evaluation"
    ),
}

# Outcomes the three-path rule in ``tag_domains`` can produce for one (passage, domain) pair.
# REVIEW is the lexicon's own outcome string (docs/glossary.md#review), the same word every
# other recipe's confidence-gated outcome reports.
YES = "yes"
NO = "no"
REVIEW = "review"

# The access classification Python decides on before any request. This is a fabricated access
# scheme of this recipe's own, not a real embargo or permission system, and the recipe is not an
# access-control system: Python's filter is a plain, deterministic rule over a field the fixtures
# carry, applied once, before any passage's text ever reaches a question. It is independent of
# which research domains a passage happens to raise (CONTRIBUTING.md section 3's "never derive
# one gold label from another" extends to this: access is a third, separately-authored fact, not
# a function of the domain labels, and the domain labels are not a function of it either).
ACCESS_OPEN = "open"
ACCESS_RESTRICTED = "restricted"
ACCESS_LEVELS: tuple[str, ...] = (ACCESS_OPEN, ACCESS_RESTRICTED)


def is_accessible(access: str) -> bool:
    """True if Python is willing to send this passage's text in a request at all.

    Raises on anything other than the two known access classifications, so a typo in a
    fixture's ``access`` field is a loud error here rather than a silent "treat as open".
    """
    if access not in ACCESS_LEVELS:
        raise ValueError(f"access must be one of {ACCESS_LEVELS}, got {access!r}")
    return access == ACCESS_OPEN


def accessible_examples(examples: Any) -> tuple[Any, ...]:
    """The access-control filter: the subset of ``examples`` Python is willing to send in a
    request, in their given order.

    ``examples`` is anything whose items carry a ``.fields`` mapping with an ``"access"`` key
    (the notebook's ``Example`` objects from ``jev_cookbook.fixtures``, or anything shaped like
    one); this function reads nothing else from an item, so it has no way to notice an item's
    research-domain content and cannot be made to depend on it by accident. This is the one place
    this recipe decides which passages may be sent at all, and it runs before any state is built,
    before any question exists, and before ``backend.decide`` is ever called: nothing downstream
    of this function's return value can see a restricted passage, because a restricted passage is
    never in it.
    """
    return tuple(e for e in examples if is_accessible(e.fields["access"]))


def restricted_examples(examples: Any) -> tuple[Any, ...]:
    """The complement of :func:`accessible_examples`: every example this recipe declines to send,
    in their given order. Used only to report how many were withheld and to prove none of them
    leaked through, never to build a request."""
    return tuple(e for e in examples if not is_accessible(e.fields["access"]))


class CountingBackend:
    """Wraps a backend and records the state of every request it is actually asked to decide,
    so a reader can verify what was sent rather than inferring it from where a filter happens
    to sit in the code.

    Every attribute other than ``decide`` is forwarded to the wrapped backend (``mode``,
    ``model``, and, for a recorded backend, ``recorded_dates``), so this wrapper is transparent
    to ``run_header`` and to anything else that reads a backend's own attributes -- it can wrap
    the single backend a notebook builds in "Setup and run mode" and be used everywhere that
    backend is, rather than becoming a second backend of its own. ``sent_states`` grows across
    every call this wrapper ever makes, for as long as the wrapper lives, so wrapping the one
    real backend once, early, turns on a running count for the whole notebook rather than a
    one-off snapshot taken later.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.sent_states: list[Any] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def decide(self, state: Any, questions: Any) -> Any:
        self.sent_states.append(state)
        return self._inner.decide(state, questions)


def decide_passages(
    examples: Any,
    backend: Any,
    questions: dict[str, Noul],
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decide every accessible example in ``examples`` and nothing else.

    The access-control filter (:func:`accessible_examples`) runs first, so a restricted
    example's state never reaches ``backend.decide``: this is the one place in this recipe that
    turns a list of examples into actual requests, and it is deliberately the single function a
    test can delete the filter from to prove the filter is load-bearing (removing the
    ``accessible_examples(...)`` call below and replacing it with ``examples`` makes
    ``tests/test_helpers.py``'s access-control tests fail, naming the restricted passage that
    leaked through).

    ``cache``, if given, is a ``{example.id: DecisionResult}`` dict this call reuses and
    extends: an accessible example already present in it (because the notebook decided it
    individually earlier, for "One answer up close") is not asked again, so a passage shown
    once and scored later is still decided exactly once in total. The default, ``None``, decides
    every accessible example in this call, as if the cache started empty.

    Returns:
        ``{example.id: DecisionResult}``, one entry per accessible example, in
        :func:`accessible_examples`'s order. A restricted example's id is never a key here.
    """
    store: dict[str, Any] = cache if cache is not None else {}
    result: dict[str, Any] = {}
    for example in accessible_examples(examples):
        if example.id not in store:
            store[example.id] = backend.decide(build_state(example.fields), questions)
        result[example.id] = store[example.id]
    return result


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one accessible passage: its text, and nothing else.

    ``fields`` also carries ``passage_id`` (bookkeeping) and ``access`` (the classification
    :func:`is_accessible` reads); neither crosses into the state. Calling this on a restricted
    passage builds a perfectly good state dict -- this function has no opinion about access on
    its own -- which is exactly why the filter has to run before this function is ever reached,
    not inside it: a restricted passage must never reach ``build_state`` at all, so the recipe
    does not depend on this function refusing to cooperate.
    """
    return {"passage": fields["text"]}


def build_questions() -> dict[str, Noul]:
    """One independent ``Noul`` per domain in :data:`DOMAINS`, built by Python from that fixed
    list.

    Each proposition is a statement that can be true or false ("The passage reports ..."), not a
    question, as CONTRIBUTING.md requires. All three describe the same passage, so
    ``backend.decide`` sends them together in a single request per passage: TypeSafe's primitives
    page (S02) says independent questions over the same state belong in one request. They stay
    three independent propositions rather than one three-way Choice because the three outcomes
    are not exclusive: a passage can report work that is biomedical and computational and
    economic at once (or none of the three), which rules out a Choice built to commit to one.
    """
    return {
        domain: Noul(
            instructions=f"The passage reports {description}.",
            criteria={
                "true": f"The passage reports {description}.",
                "false": "The passage does not report this at all, whatever words it uses.",
            },
        )
        for domain, description in DOMAINS.items()
    }


@dataclass(frozen=True)
class DomainTag:
    """What Python decided for one (passage, domain) pair: the business tag (always computed
    against that domain's own frozen threshold), the three-path outcome a shared confidence gate
    adds on top of it, and the provenance of the answer that produced it."""

    domain: str
    noul: float
    tag: bool
    outcome: str
    reason: str
    provenance: str


def tag_domains(
    answers: Any,
    thresholds: dict[str, float],
    confidence_gate: float,
) -> dict[str, DomainTag]:
    """Apply each domain's own business threshold and the shared confidence gate to one
    passage's three answers.

    ``answers`` is a mapping from domain name to a Noul answer (or anything with ``.noul`` and
    ``.provenance``). For every domain in :data:`DOMAINS`:

    - the business tag is ``noul >= thresholds[domain]`` (``jev_cookbook.evaluation.
      multilabel_from_noul`` applies the same comparison at evaluation time; this function
      applies it per domain so the notebook can show the decision domain by domain);
    - the outcome is ``"review"`` whenever ``noul_confidence(noul) < confidence_gate``, whatever
      the business tag says, and otherwise ``"yes"`` or ``"no"`` matching the tag;
    - the provenance is carried straight from the answer, unchanged, so it survives into
      :class:`DomainTag` and from there into :class:`PassageResult`.

    A domain routed to ``"review"`` is not reported as tagged either way: it is Python's explicit
    third path (CONTRIBUTING.md section 4, "Uncertain or inconsistent results go to an explicit
    review outcome."), alongside the two the business rule alone would give. The rule holds
    whatever the model answers: it is code, not prose, and ``tests/test_helpers.py`` checks it
    for every domain and every outcome.

    Args:
        answers: ``{domain: NoulAnswer-like}``, one per domain in :data:`DOMAINS`.
        thresholds: The frozen per-domain business thresholds (chosen on ``validation``); must
            name exactly the domains in :data:`DOMAINS`, no more and no fewer.
        confidence_gate: The frozen shared confidence gate (chosen on ``validation``, pooled
            across all three domains; see the notebook's "Python's part" section for why one
            shared value is used rather than a separate gate per domain).

    Returns:
        ``{domain: DomainTag}``, one entry per domain in :data:`DOMAINS`.
    """
    if not 0.0 <= float(confidence_gate) <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    if set(thresholds) != set(DOMAINS):
        raise ValueError(
            f"thresholds must name exactly DOMAINS {sorted(DOMAINS)}, got {sorted(thresholds)}"
        )
    decisions: dict[str, DomainTag] = {}
    for domain in DOMAINS:
        threshold = thresholds[domain]
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError(f"threshold for {domain!r} must be between 0 and 1, got {threshold!r}")
        answer = answers[domain]
        noul = float(answer.noul)
        tag = noul >= threshold
        # |2p - 1| per the TypeSafe confidence page (S03); jev_cookbook.evaluation.noul_confidence
        # is the shared implementation, so it is imported rather than reimplemented here.
        confidence = noul_confidence([noul])[0]
        if confidence < confidence_gate:
            outcome, reason = REVIEW, "confidence below the threshold"
        elif tag:
            outcome, reason = YES, "at or above the domain's threshold, confident enough"
        else:
            outcome, reason = NO, "below the domain's threshold, confident enough"
        decisions[domain] = DomainTag(domain, noul, tag, outcome, reason, answer.provenance.source)
    return decisions


@dataclass(frozen=True)
class PassageResult:
    """Python's composed, task-level decision for one passage: the domain set it tags, the
    domains it sends to review instead, and the provenance of every one of those decisions kept
    alongside the tag, not discarded once computed."""

    passage_id: str
    tags: frozenset[str]
    review: tuple[str, ...]
    provenance: dict[str, str]


def compose(passage_id: str, decisions: dict[str, DomainTag]) -> PassageResult:
    """The deterministic composition: turn one passage's three independent per-domain decisions
    into Python's one task-level result for that passage.

    This is the function CONTRIBUTING.md's Level 3 scope calls "deterministic composition":
    whatever the three Noul answers say, this function combines them the same way every time,
    with no further call to Jev. A domain's provenance rides along in :class:`PassageResult`
    whether it was tagged, left untagged, or sent to review, so a reader of the composed result
    can trace every domain's decision back to where it came from, never only the ones that made
    it into the tag set.

    Args:
        passage_id: The passage's own id, carried through so the result is traceable.
        decisions: ``{domain: DomainTag}`` as returned by :func:`tag_domains`, naming exactly
            the domains in :data:`DOMAINS`.

    Returns:
        A :class:`PassageResult`.
    """
    if set(decisions) != set(DOMAINS):
        raise ValueError(
            f"decisions must name exactly DOMAINS {sorted(DOMAINS)}, got {sorted(decisions)}"
        )
    tags = frozenset(d.domain for d in decisions.values() if d.outcome == YES)
    review = tuple(d.domain for d in decisions.values() if d.outcome == REVIEW)
    provenance = {d.domain: d.provenance for d in decisions.values()}
    return PassageResult(passage_id, tags, review, provenance)


def task_correct(result: PassageResult, gold: Any) -> bool:
    """The task-level outcome CONTRIBUTING.md's Level 3 scope asks for: does this passage's
    *whole* composed domain set exactly match its gold set? Two empty sets match. A domain sent
    to review is not reported as present or absent, so a passage with any domain still in review
    cannot be scored exactly right or wrong by this function alone -- the caller excludes such
    passages from this count the same way any other undelivered answer is excluded from coverage
    (``jev_cookbook.evaluation``'s "coverage counts delivered answers" rule), and reports them
    separately instead."""
    return result.tags == frozenset(gold)
