"""Python's half of recipe 17: the state, the question, the rule Python enforces, and the
small lexical scorer that stands in for the retrieval system whose candidates Jev reranks.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import score_level

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The relevance rubric, lowest level first. Each level is judged on its own against the
# (query, passage) pair ("Every level is evaluated separately. The model doesn't see a level's
# number or its neighbours, so 'worse than the previous level' means nothing to it.",
# https://docs.typesafe.ai/primitives/score.md), so every description stands alone: it says
# what the passage itself states about the query, never "less relevant than the level above".
NOT_RELEVANT = (
    "The passage is about a different topic, entity, time, or place than the query asks "
    "about. Nothing in it bears on the query at all."
)
TANGENTIAL = (
    "The passage is about the same general topic as the query, but it does not state the "
    "specific fact, number, or step the query asks for."
)
RELEVANT = (
    "The passage states the fact, number, or step the query asks for, but the reader has to "
    "connect it with something else stated elsewhere in the same passage to see that it "
    "answers the query."
)
DIRECT = (
    "The passage states the exact answer to the query in a single, self-contained sentence, "
    "with nothing else needed to understand it."
)
RELEVANCE_LEVELS = (NOT_RELEVANT, TANGENTIAL, RELEVANT, DIRECT)  # level 0 to level 3

# The business cutoff lives in code: a passage whose most likely level is below
# RELEVANT (level 2) does not state what the query asks for, so Python does not treat it as a
# match. This is a fixed editorial decision, not a value chosen by searching validation: unlike
# the confidence gate below, there is no "selecting" step for it, which is also why it is a
# plain module constant and not an argument.
BUSINESS_CUTOFF = 2

MATCH = "match"
NO_MATCH = "no_match"
REVIEW = "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (query, passage) pair: the query and the passage text, and
    nothing else.

    ``fields`` also carries ``query_id`` and ``passage_id`` (the passage's source reference,
    e.g. ``"KB-104"``), both bookkeeping Python keeps for itself. Neither reaches the model;
    both are reattached to the outcome afterwards, so every ranked result still traces back to
    its source.
    """
    return {"query": fields["query"], "passage": fields["passage"]}


def build_questions() -> dict[str, Score]:
    """The one question asked about every (query, passage) pair. The levels come from
    ``RELEVANCE_LEVELS``."""
    return {
        "relevance": Score(
            instructions=(
                "How relevant is this passage to answering the query? Judge only what this "
                "passage itself states, not what any other passage says, and not any claim "
                "the passage makes about its own relevance."
            ),
            criteria=list(RELEVANCE_LEVELS),
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided about one passage: the level Jev's answer most likely holds, and
    the outcome."""

    passage_id: str
    level: int
    outcome: str
    reason: str


def classify(passage_id: str, answer: Any, confidence_gate: float) -> Classification:
    """Act on a relevance answer: trust it only when confident enough, then apply the cutoff.

    The confidence gate decides whether the score is trustworthy at all: below
    ``confidence_gate`` the outcome is an explicit ``review``, whatever level the answer names,
    because a spread-out distribution over levels is not solid ground for a matching decision.
    At or above it, the rule applies the fixed ``BUSINESS_CUTOFF``: a trusted answer whose most
    likely level (:func:`jev_cookbook.evaluation.score_level`, the modal level, ties going to
    the lower one) falls below ``RELEVANT`` is ``no_match``; the rest are a ``match``. The rule
    is code, so it holds whatever the model answers.

    This function decides only whether to *trust and act on* a passage's relevance call. It
    does not decide the passage's place in the ranking: see :func:`rerank`, which orders every
    candidate by its expected score regardless of outcome. The confidence gate and the ranking
    order are two separate, explicit mechanisms, not one conflated rule.
    """
    if not 0.0 <= confidence_gate <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    level = score_level(answer)
    if answer.confidence < confidence_gate:
        return Classification(passage_id, level, REVIEW, "confidence below the threshold")
    if level < BUSINESS_CUTOFF:
        return Classification(passage_id, level, NO_MATCH, "modal level below the business cutoff")
    return Classification(passage_id, level, MATCH, "modal level clears the business cutoff")


# --------------------------------------------------------------------------------- The baseline

# A small, deliberately dumb lexical scorer: it counts matching words and nothing else (no
# stemming, no term weighting, no synonyms), so "the original retrieval order from a small
# lexical scorer written in plain Python" this use case calls for is exactly this one
# countable rule, not a black box. A query that is phrased with different words than the
# passage that actually answers it (a paraphrase) defeats this scorer on purpose: that is the
# gap a semantic reranker is for.
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does",
        "for", "from", "have", "how", "i", "if", "in", "is", "it", "my", "of", "on",
        "or", "that", "the", "this", "to", "what", "when", "will", "with", "you", "your",
    }
)  # fmt: skip


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS)


def lexical_score(query: str, passage: str) -> int:
    """Count of the query's distinct, non-stopword words that also appear in the passage."""
    return len(_words(query) & _words(passage))


@dataclass(frozen=True)
class Candidate:
    """One retrieved passage for one query, carried through ranking unchanged."""

    passage_id: str
    query: str
    passage: str
    position: int  # 0-based: the order this candidate was retrieved in, before any scoring


def baseline_rank(candidates: list[Candidate]) -> dict[str, int]:
    """The 0-based rank of each candidate under :func:`lexical_score`: highest score first,
    ties broken by ``position`` (the order the candidates were originally retrieved in). This
    is a strict order with no further ties, and it is "the original retrieval order from a
    small lexical scorer written in plain Python" -- the baseline this use case names.
    """
    ordered = sorted(candidates, key=lambda c: (-lexical_score(c.query, c.passage), c.position))
    return {c.passage_id: rank for rank, c in enumerate(ordered)}


def rerank(
    candidates: list[Candidate], scores: dict[str, float], ranks: dict[str, int]
) -> list[Candidate]:
    """``candidates`` sorted by Jev's expected relevance ``scores`` (higher first); a tie on
    the score is broken by ``ranks`` (the baseline order from :func:`baseline_rank`),
    ascending, so a tie keeps whichever candidate the baseline already preferred rather than an
    incidental input order. Confidence plays no part in this order on purpose: whether to trust
    a passage's relevance call is a separate, explicit decision (:func:`classify`), not a
    reason to move it up or down the ranking.
    """
    return sorted(candidates, key=lambda c: (-scores[c.passage_id], ranks[c.passage_id]))


# -------------------------------------------------------------------------- Top-1 ranking metric

# ``jev_cookbook.evaluation`` has ``mean_ndcg`` to average ``ndcg`` over several ranked lists,
# but nothing for a top-1 (or top-k) *ranking* accuracy: its ``top_k_accuracy`` is for a single
# Choice-style probability distribution over one example's options, not a ranked list of
# per-passage scores over several queries. ``recall_at_budget`` looks close -- "recall at a
# budget of 1 item" sounds like "was the top-scored item relevant" -- but it answers a different
# question whenever a query has more than one relevant item: it reports the share of *all*
# relevant items a budget of 1 would find, which is 0.5 for two relevant items among three even
# when the one top-scored item is itself relevant (see
# ``tests/test_helpers.py::test_top1_accuracy_differs_from_recall_at_a_budget_of_one``). Earlier
# code in this recipe computed ``top1_accuracy`` as the mean of
# ``evaluation.recall_at_budget(relevant, scores, 1)`` over queries on the mistaken assumption
# that the two always agree; this recipe's own fixtures hid the bug, because every query here has
# exactly one gold-``direct`` passage. ``top1_accuracy`` below is computed directly instead, as a
# true top-1 ranking accuracy, so the two are never conflated again. This is a gap in the shared
# evaluation toolkit worth fixing there (as its own helper, not a wrapper around
# ``recall_at_budget``), not a convention this recipe invents on its own.


def top1_accuracy(queries: list[tuple[list[Any], list[float]]]) -> float:
    """Share of queries whose top-scored passage is gold-relevant.

    This asks, for each query, "is the single top-scored item relevant?", not "what share of
    the query's relevant items would a review budget of one item find?" (that second question
    is what ``jev_cookbook.evaluation.recall_at_budget(relevant, scores, budget=1)`` answers,
    and the module comment above explains why the two differ). A tie for the top score is
    credited by the probability that a uniformly random tie-break lands on a relevant item --
    the same expectation-over-tie-orders convention ``recall_at_budget`` uses, computed directly
    here because the two questions otherwise agree only on ties.

    Args:
        queries: One ``(gold_relevant, scores)`` pair per query: ``gold_relevant`` is binary (1
            for every passage that is a gold answer to that query, 0 for the rest) and
            ``scores`` is each passage's ranking score, in the same order.

    Returns:
        The mean, over queries with at least one relevant passage, of the share of the
        top-scored passages (plural only on a tie) that are relevant. Raises ``ValueError`` on
        empty input, a query whose ``gold_relevant`` and ``scores`` lengths differ, or if no
        query has a relevant passage.
    """
    if not queries:
        raise ValueError("queries must not be empty")
    per_query = []
    for relevant, scores in queries:
        relevant = list(relevant)
        scores = [float(s) for s in scores]
        if len(relevant) != len(scores):
            raise ValueError("gold_relevant and scores must have the same length")
        if not any(relevant):
            per_query.append(float("nan"))  # no relevant passage in this query: undefined
            continue
        top_score = max(scores)
        tied = [i for i, s in enumerate(scores) if s == top_score]
        per_query.append(sum(1 for i in tied if relevant[i]) / len(tied))
    defined = [v for v in per_query if v == v]  # drop NaN (no relevant item in that query)
    if not defined:
        raise ValueError("no query has a relevant passage")
    return sum(defined) / len(defined)
