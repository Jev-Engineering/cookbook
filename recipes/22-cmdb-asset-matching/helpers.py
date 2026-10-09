"""Python's half of recipe 22: the state, the questions and the rules.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the questions and the state cannot disagree.
"""

import re
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The fixed pool of canonical CMDB records. An observed asset is matched against this pool,
# never invented by Jev: every option the question can ever offer comes from here (plus the
# fallback below). CMDB-01/02/03 are the same vendor and product, differing only by major
# version -- the use case's build note ("include two records that differ only by major
# version"); keeping three instead of two means the version family also exercises every
# shortlist rank (see the notebook's candidate-rank table). CMDB-11 to CMDB-15 are each a
# same-vendor sibling of one of CMDB-06 to CMDB-10, so that an observed asset for any of those
# five also retrieves a real second candidate instead of standing alone against no_match --
# without them, half this catalog would always offer exactly one real candidate, which does not
# exercise genuine discrimination between options the way the use case's "bounded candidate
# list" build note intends. CMDB-16 is a second sibling of CMDB-08: same vendor, product and
# major version, differing only by edition (Workstation, not Server) -- the instructions'
# "a different edition ... is not a match" clause has no fixture to exercise it otherwise.
# --------------------------------------------------------------------------------------------

CMDB_RECORDS: dict[str, dict[str, str]] = {
    "CMDB-01": {"vendor": "Northcastle", "product": "LedgerStack Server", "major_version": "2017", "edition": "Standard"},
    "CMDB-02": {"vendor": "Northcastle", "product": "LedgerStack Server", "major_version": "2020", "edition": "Standard"},
    "CMDB-03": {"vendor": "Northcastle", "product": "LedgerStack Server", "major_version": "2023", "edition": "Standard"},
    "CMDB-04": {"vendor": "Candlewood", "product": "InkPress", "major_version": "12", "edition": "Pro"},
    "CMDB-05": {"vendor": "Candlewood", "product": "PixelForge", "major_version": "27", "edition": "Standard"},
    "CMDB-06": {"vendor": "Thornfield", "product": "VaultDB", "major_version": "21q", "edition": "Enterprise"},
    "CMDB-07": {"vendor": "Ashgrove", "product": "Processwell Core", "major_version": "7.0", "edition": "Enterprise"},
    "CMDB-08": {"vendor": "Redfern", "product": "Enterprise OS", "major_version": "9", "edition": "Server"},
    "CMDB-09": {"vendor": "Bluequill", "product": "TicketForge", "major_version": "11", "edition": "Data Center"},
    "CMDB-10": {"vendor": "Meridian", "product": "Pipeline Cloud", "major_version": "2026", "edition": "Enterprise"},
    "CMDB-11": {"vendor": "Thornfield", "product": "CoreRun SE", "major_version": "19", "edition": "Enterprise"},
    "CMDB-12": {"vendor": "Ashgrove", "product": "N4VISTA", "major_version": "2025", "edition": "Enterprise"},
    "CMDB-13": {"vendor": "Redfern", "product": "Containerflow", "major_version": "6", "edition": "Server"},
    "CMDB-14": {"vendor": "Bluequill", "product": "WikiSpring", "major_version": "10", "edition": "Data Center"},
    "CMDB-15": {"vendor": "Meridian", "product": "Support Cloud", "major_version": "2026", "edition": "Enterprise"},
    "CMDB-16": {"vendor": "Redfern", "product": "Enterprise OS", "major_version": "9", "edition": "Workstation"},
}  # fmt: skip

# The explicit fallback the use case names, for an observed asset that matches none of the
# retrieved candidates. It is a Choice option like the others, built by Python, not a separate
# code path Jev reaches by failing to answer.
NO_MATCH = "no_match"

# The most candidates Python ever retrieves for one observed asset (plus NO_MATCH, so a question
# never offers more than this many plus one options). Unlike a fixed shortlist size, retrieval
# below keeps only candidates that actually share normalized vendor/product wording with the
# asset, so the real count varies per asset from zero up to this cap.
MAX_CANDIDATES = 5

# A record counts as a candidate only once its normalized vendor/product overlap clears this
# floor; chosen so that an asset sharing no real wording with any canonical record (score 0.0)
# never retrieves one just to pad a list out to some fixed size.
_CANDIDATE_FLOOR = 0.0

# The fixed cut-off `baseline_overlap_cutoff` uses: a record is proposed only when its
# normalized vendor/product overlap with the observed asset is at least this. A plausible,
# hand-picked word-overlap threshold, not a value that happens to separate every genuine match
# from every decoy in this recipe's own fixtures: it does not. An asset whose vendor and product
# abbreviate or drop a word from the canonical spelling (for example "TicketForge Platform"
# against "TicketForge", or "NCS Corp" against "Northcastle") can score as low as 0.5, the same
# as this recipe's own lexical look-alike (the notebook derives and prints the actual overlap for
# every asset, rather than this comment asserting one). The point this baseline makes does not
# depend on 0.6 being a clean separator: whatever cut-off is chosen, it still reads only vendor
# and product, so it is exactly as unable to tell CMDB-01/02/03 (or CMDB-08/CMDB-16) apart by
# version or edition as `baseline_always_top` is.
OVERLAP_CUTOFF = 0.6

# Outcomes the rule below can produce.
LINKED = "linked"
NO_MATCH_OUTCOME = "no_match"
REVIEW = "review"

# A discovery scan reports vendor and product names in whatever style its own catalog uses,
# never the CMDB's own spelling. These phrase-level aliases fold the common abbreviations and
# corporate suffixes this recipe's fixtures use down to the same wording the canonical records
# use, so retrieval (below) still finds the right candidates despite the wording difference.
# Applied to BOTH an observed asset's text and a canonical record's own text, so the two sides
# of every comparison are normalized the same way.
_PHRASE_ALIASES = {
    "northcastle corporation": "northcastle",
    "northcastle corp": "northcastle",
    "nstl": "northcastle",
    "redfern, inc.": "redfern",
    "redfern inc": "redfern",
    "rfos": "redfern enterprise os",
    "thornfield corporation": "thornfield",
    "thornfield corp": "thornfield",
    "candlewood systems incorporated": "candlewood",
    "candlewood systems": "candlewood",
    "candlewood inc.": "candlewood",
    "ashgrove se": "ashgrove",
    "ashgrove ag": "ashgrove",
    "pwcr": "processwell core",
    "meridiancloud.com, inc.": "meridian",
    "meridiancloud.com": "meridian",
    "mrdn": "meridian",
    "bluequill corporation": "bluequill",
}
# "nstl" and "mrdn" look like they could be dropped (the family they resolve into always ties
# its own siblings regardless of the exact score, so `shortlist`'s result does not depend on
# them): but `baseline_overlap_cutoff` (below) picks a record only when its *absolute* overlap
# clears `OVERLAP_CUTOFF`, and without either alias "NSTL"/"LedgerStack Server" and
# "MRDN"/"Pipeline Cloud" score only 0.5 -- below the 0.6 cutoff -- so the baseline would report
# `no_match` instead of the right record, moving a published evaluation number. Both aliases are
# load-bearing for that reason, and `tests/test_helpers.py` pins it directly.
# Corporate-suffix and filler tokens dropped after splitting into words, so they never count as
# shared vocabulary between two otherwise unrelated vendors or products.
_STOPWORDS = {"inc", "incorporated", "corp", "corporation", "ltd", "llc", "co"}


def _normalize(text: str) -> str:
    """Lowercase ``text`` and apply the phrase aliases above, longest phrase first so a longer
    match (for example ``"redfern, inc."``) is not partly consumed by a shorter one first."""
    text = text.lower()
    for phrase in sorted(_PHRASE_ALIASES, key=len, reverse=True):
        text = text.replace(phrase, _PHRASE_ALIASES[phrase])
    return text


def _tokens(vendor: str, product: str) -> set[str]:
    """The normalized, stopword-free word set of ``vendor`` and ``product`` together -- what
    retrieval compares. Version and edition are deliberately excluded: this recipe's retrieval
    rule is vendor/product overlap only, exactly the build note's "normalised vendor/product
    token overlap"; telling two same-vendor-and-product records apart by version or edition is
    left to the question, not pre-filtered away by Python's retrieval."""
    text = _normalize(f"{vendor} {product}")
    return {w for w in re.findall(r"[a-z0-9]+", text) if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets: shared words over the union. 0.0 if either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity_scores(vendor: str, product: str) -> dict[str, float]:
    """The normalized vendor/product token overlap between an observed asset and every
    canonical record -- the raw numbers ``shortlist`` ranks by, exposed so a reader can see the
    retrieval step work rather than only its result, and what both baselines below read from."""
    observed = _tokens(vendor, product)
    return {
        record_id: _jaccard(observed, _tokens(record["vendor"], record["product"]))
        for record_id, record in CMDB_RECORDS.items()
    }


def shortlist(vendor: str, product: str, k: int = MAX_CANDIDATES) -> list[str]:
    """Python's retrieval step: every canonical record whose normalized vendor/product overlap
    with the observed asset clears ``_CANDIDATE_FLOOR``, ranked by that overlap and capped at
    ``k`` -- no model call, no learned embedding. Ties (including a tie at the floor itself)
    break on the record id, so the result is deterministic; this is also why CMDB-01/02/03
    (identical vendor and product, so they always tie each other exactly) always rank in that
    order relative to one another, whatever the observed version says -- version plays no part
    in retrieval at all. Unlike a fixed-size shortlist, the length of the result varies with the
    asset: an asset sharing no wording with anything in the pool gets an empty list back, not a
    list padded with unrelated records, and ``no_candidate_resolution`` below is how Python
    handles that case without ever asking Jev.
    """
    scores = similarity_scores(vendor, product)
    ranked = sorted(
        (record_id for record_id, score in scores.items() if score > _CANDIDATE_FLOOR),
        key=lambda record_id: (-scores[record_id], record_id),
    )
    return ranked[:k]


def baseline_always_top(candidates: list[str]) -> str:
    """A trivial pipeline-check baseline: always link to the first (highest-overlap) retrieved
    candidate, or ``no_match`` when retrieval found none. It never chooses ``no_match`` while any
    candidate exists, so it cannot ever be right about an asset whose true record is outside the
    candidate list, and it cannot tell CMDB-01/02/03 apart (they tie in overlap, so this baseline
    always names the lowest id among them, CMDB-01, whatever the observed version says). This
    recipe's own rule has to clearly beat this to be worth Jev's judgment at all."""
    return candidates[0] if candidates else NO_MATCH


def baseline_overlap_cutoff(vendor: str, product: str, cutoff: float = OVERLAP_CUTOFF) -> str:
    """A second trivial pipeline-check baseline: the single best-overlap record (ties broken by
    id, as in ``shortlist``), but only when its overlap clears ``cutoff``; otherwise ``no_match``.
    Unlike ``baseline_always_top``, this one can answer ``no_match`` on its own -- but, reading
    only normalized vendor/product wording, it is exactly as unable to tell CMDB-01/02/03 apart
    as the first baseline is, since version and edition play no part in either."""
    scores = similarity_scores(vendor, product)
    best = max(CMDB_RECORDS, key=lambda record_id: (scores[record_id], -_id_rank(record_id)))
    return best if scores[best] >= cutoff else NO_MATCH


def _id_rank(record_id: str) -> int:
    """Sortable rank for a record id (``"CMDB-01"`` -> ``1``), used only to break a tie toward
    the lowest id without relying on string comparison twice in one sort key."""
    return int(record_id.rsplit("-", 1)[-1])


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one observed asset: its vendor, product, version and edition,
    exactly as a discovery scan reported them, and nothing else.

    ``fields`` also carries ``asset_id``, a bookkeeping identifier. Python keeps it and attaches
    it to the outcome, so it never needs to pass through the model. The shortlist Python
    retrieved is not stored here: ``shortlist(fields["vendor"], fields["product"])`` is a
    deterministic function of those two fields alone, so it is recomputed wherever it is needed
    rather than carried as a second piece of state that could drift out of sync with it.
    """
    return {
        "vendor": fields["vendor"],
        "product": fields["product"],
        "version": fields["version"],
        "edition": fields["edition"],
    }


def _candidate_description(record_id: str) -> str:
    record = CMDB_RECORDS[record_id]
    return (
        f"Canonical CMDB record {record_id}: vendor {record['vendor']}, product "
        f"{record['product']}, major version {record['major_version']}, {record['edition']} "
        f"edition."
    )


def build_questions(candidates: list[str]) -> dict[str, Choice]:
    """The one question asked about an observed asset, given the ``candidates`` Python
    retrieved.

    ``candidates`` must be non-empty: a Choice with zero real candidates would offer exactly one
    option (the fallback alone), and a single-option Choice is never sent (see
    ``no_candidate_resolution``): a forced answer belongs to Python, not a request. Every observed asset shares one question
    shape (which canonical record, if any, is this the same software as), but the option list is
    built fresh per asset from its own shortlist, so a Candlewood asset is never asked to choose a
    Meridian candidate's identifier, and the replay key changes with the shortlist as a result.
    """
    if not candidates:
        raise ValueError(
            "build_questions needs at least one real candidate; an asset with none is resolved "
            "directly by no_candidate_resolution and never reaches this function"
        )
    criteria = {record_id: _candidate_description(record_id) for record_id in candidates}
    criteria[NO_MATCH] = (
        "None of the candidate canonical records above is the same software as the observed "
        "asset: the vendor, product, major version or edition differ, the asset is a different "
        "product from the same vendor, or the asset's true canonical record is not among the "
        "candidates at all. Choose this also when the version needed to tell two "
        "same-vendor-and-product candidates apart is not reported."
    )
    return {
        "match": Choice(
            instructions=(
                "An observed software asset, found by a discovery scan, is described below by "
                "its vendor, product, version and edition, exactly as the scan reported them: "
                "vendor names, version formats and edition names are not standardized across "
                "discovery tools and vary from the canonical record's own spelling. Does this "
                "asset match any of the candidate canonical CMDB records below, or none of "
                "them? Two records describe the same asset only when the vendor, product, "
                "major version and edition all refer to the same canonical software. A "
                "different major version, a different edition, or a different product from the "
                "same vendor is not a match, even when the wording looks similar."
            ),
            criteria=criteria,
        )
    }


@dataclass(frozen=True)
class Resolution:
    """What Python decided: the option Jev chose (or, with no candidates, the forced label), the
    outcome, and why.

    ``candidates`` is the shortlist this asset was actually offered, kept alongside the decision
    so a review item or a backlog entry can show what was on the table (empty when no candidate
    was ever retrieved).
    """

    asset_id: str
    candidates: tuple[str, ...]
    label: str
    outcome: str
    reason: str


def no_candidate_resolution(asset_id: str) -> Resolution:
    """The forced resolution for an asset whose retrieved candidate list is empty: with no real
    candidate, the only possible Choice option would be the fallback alone, a single-option
    Choice ``build_questions`` refuses to build at all, so no request is ever sent to Jev for
    this asset. This is a forced answer, not a confident one: CONTRIBUTING.md section 4 still
    applies (no side effect -- see ``record_resolution``), so ``no_match`` is final here exactly
    as it is when Jev itself names it."""
    return Resolution(
        asset_id,
        (),
        NO_MATCH,
        NO_MATCH_OUTCOME,
        "no candidate record shares any vendor or product wording with this asset",
    )


def match_record(
    asset_id: str, candidates: list[str], answer: Any, min_confidence: float
) -> Resolution:
    """Decide what to do with one typed answer: link, call it unmatched, or hold it for review.

    ``no_match`` is never run past the confidence gate, whatever its confidence: the option
    itself already says no candidate is the same asset, and there is no side effect (no link
    written to the CMDB) a confidence check could protect -- CONTRIBUTING.md section 4 allows a
    low-confidence fallback option to be a final result exactly when choosing it triggers no
    side effect, and here it triggers only a backlog entry (see ``record_resolution``), never a
    write. Choosing anything that is not one of the retrieved candidates and not ``no_match``
    goes to review (defensive: ``build_questions`` never offers such an option, but the rule
    does not trust that silently, the same guard recipe 07's word-sense rule and recipe 18's
    incident-matching rule keep). A real candidate below ``min_confidence`` also goes to review,
    instead of linking on a guess. Only a real candidate named with enough confidence is linked
    -- the one outcome that writes a link. The rule is code, so it holds whatever the model
    answers. ``candidates`` must be non-empty here: an empty shortlist never reaches Jev at all
    (see ``no_candidate_resolution``), so this function does not special-case it.
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(f"min_confidence must be between 0 and 1, got {min_confidence!r}")
    if answer.choice == NO_MATCH:
        return Resolution(
            asset_id, tuple(candidates), NO_MATCH, NO_MATCH_OUTCOME, "no canonical record matches"
        )
    if answer.choice not in candidates:
        return Resolution(
            asset_id,
            tuple(candidates),
            answer.choice,
            REVIEW,
            "not one of the retrieved candidates",
        )
    if answer.confidence < min_confidence:
        return Resolution(
            asset_id, tuple(candidates), answer.choice, REVIEW, "confidence below the threshold"
        )
    return Resolution(asset_id, tuple(candidates), answer.choice, LINKED, "confident match")


def record_resolution(
    resolution: Resolution, answer: Any, actions: Any, backlog: Any, queue: Any
) -> None:
    """Carry out Python's simulated side effect for one resolution.

    A ``linked`` resolution is recorded in ``actions`` (a ``jev_cookbook.simulation.ActionLog``):
    simulated, never executed, the only outcome of this recipe that writes anything resembling a
    change to the CMDB. A ``no_match`` resolution is recorded in ``backlog`` (a
    ``jev_cookbook.simulation.ReviewQueue``, reused here for an "unmatched asset" backlog rather
    than a person's review queue): the asset is noted for someone to later decide whether a new
    canonical record is needed, but nothing is written to the CMDB and no canonical record is
    linked or created -- this is exactly the "no side effect" CONTRIBUTING.md section 4 requires
    before a low-confidence (or, for ``no_candidate_resolution``, forced) fallback may be a final
    result, and it is why ``no_match`` bypasses the confidence gate above: there is no write to
    protect against. ``answer`` is ``None`` for a forced, request-free resolution, and the queue
    entry simply carries no answer. A ``review`` resolution is queued in ``queue`` (a second,
    separate ``ReviewQueue``) with the candidates it was offered, so a person can see what Jev
    was choosing between.
    """
    if resolution.outcome == LINKED:
        actions.record(
            "link_asset",
            {"asset": resolution.asset_id, "linked_to": resolution.label},
            answer=answer,
            rule=resolution.reason,
        )
    elif resolution.outcome == NO_MATCH_OUTCOME:
        backlog.submit(
            {"asset": resolution.asset_id, "candidates": list(resolution.candidates)},
            resolution.reason,
            answer=answer,
        )
    elif resolution.outcome == REVIEW:
        queue.submit(
            {"asset": resolution.asset_id, "candidates": list(resolution.candidates)},
            resolution.reason,
            answer=answer,
        )


def accepted_and_correct(
    results: list[Resolution], gold: dict[str, Any]
) -> tuple[list[bool], list[bool]]:
    """``(accepted, correct)`` for ``jev_cookbook.evaluation.evaluate_outcomes``: ``accepted[i]``
    is whether the resolution answered (``linked`` or ``no_match``) rather than being sent to
    ``review``, and ``correct[i]`` is whether that result's label is the gold match (ignored,
    but still computed, where ``accepted[i]`` is False, exactly as ``evaluate_outcomes``
    documents). ``evaluate_outcomes`` is the shared helper for a rule like this one, whose review
    branch is more than a single confidence gate (see "Selective prediction" in
    ``docs/evaluation.md``); it reports coverage, accuracy and risk. It has no notion of a
    second, narrower outcome inside "accepted" (``linked`` versus ``no_match``), which is what
    :func:`false_link_rate` below computes instead.
    """
    accepted = [r.outcome != REVIEW for r in results]
    correct = [r.label == gold[r.asset_id] for r in results]
    return accepted, correct


def false_link_rate(results: list[Resolution], gold: dict[str, Any]) -> float:
    """The share of ``linked`` resolutions whose chosen record is not the gold match -- the only
    way this recipe's simulated side effect (writing a link from an asset to a canonical record)
    can be wrong. A false link is an accepted link to the wrong record; reporting ``no_match``
    for an asset that really does have a canonical record is not a false link (nothing was
    linked), even though it does cost accuracy via ``evaluate_outcomes``.

    This is narrower than the risk ``jev_cookbook.evaluation.evaluate_outcomes`` reports: a wrong
    ``no_match`` call (missing a real match) is accepted and wrong, so it raises that risk too,
    but it is not a false link, because ``no_match`` triggers no side effect at all -- nothing
    was ever linked to anything. NaN when nothing was linked, matching
    ``jev_cookbook.evaluation``'s own convention (undefined is NaN, never 0.0).
    """
    if not results:
        raise ValueError("false_link_rate needs at least one result")
    linked = [r for r in results if r.outcome == LINKED]
    if not linked:
        return float("nan")
    wrong = sum(1 for r in linked if r.label != gold[r.asset_id])
    return wrong / len(linked)
