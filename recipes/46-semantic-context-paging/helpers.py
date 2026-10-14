"""Python's half of recipe 46: the relevance rubric, the retain/page/review rule, and the
budgeted paging policy that turns per-chunk Score answers into paging decisions Python enforces.

The fixture generator, the notebook and the tests all load this file with
``jev_cookbook.load_helpers``, so the question and the state cannot disagree.

**The use case.** A context store keeps small chunks of prior material (ticket messages,
runbook steps, code comments, monitoring alerts) that an assistant might need for the task in
front of it right now. Context has a budget: only a few chunks can stay "hot" at once. Jev
judges each chunk's relevance to the current task on a four-level rubric; Python turns that
judgment, plus a fixed budget, into a retain / page-out / rehydrate decision, and never loses a
chunk's content or source link while doing it -- ``jev_cookbook.simulation.Store`` is the
primitive that makes "never loses" a property of the store itself, not a promise this file has
to keep by hand.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.evaluation import score_level
from jev_cookbook.simulation import Budget

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# The relevance rubric, lowest level first. Each level is judged on its own against the (task,
# chunk) pair ("Every level is evaluated separately. The model doesn't see a level's number or
# its neighbours, so 'worse than the previous level' means nothing to it.",
# https://docs.typesafe.ai/primitives/score), so every description stands alone: it says what
# the chunk itself states about the task, never "less relevant than the level above". None of
# the four levels says anything about when the chunk was written or added to the store --
# recency is not part of the rubric Jev judges; it is the separate, zero-request baseline this
# recipe compares against.
NOT_RELEVANT = (
    "The chunk has nothing to do with the current task: a different file, ticket, person, or "
    "topic than the task names. Nothing in it bears on the task at all."
)
BACKGROUND = (
    "The chunk is about the same file, ticket, or topic as the task, but it does not state "
    "anything the task's own answer or action depends on."
)
SUPPORTING = (
    "The chunk states something the task's answer or action depends on, but only part of it: "
    "a reader also needs another chunk to complete the task correctly."
)
NEEDED = (
    "The chunk states, on its own, the specific fact, value, or step the task's answer or "
    "action depends on. Nothing else is needed to act on it correctly."
)
RELEVANCE_LEVELS = (NOT_RELEVANT, BACKGROUND, SUPPORTING, NEEDED)  # level 0 to level 3

# The retention cutoff lives in code: a chunk whose most likely level is below SUPPORTING
# (level 2) does not state anything the task depends on, so Python never treats it as a
# retention candidate, however much budget is free. This is a fixed editorial decision, not a
# value chosen by searching validation: unlike the confidence gate below, there is no
# "selecting" step for it, which is also why it is a plain module constant and not an argument.
RETENTION_CUTOFF = 2

# The fixed number of chunks a task's context window can hold "hot" at once. A fixed editorial
# capacity, the same for every task in this recipe, not a value chosen from validation.
BUDGET_SLOTS = 3

RETAINED = "retained"
PAGED_OUT = "paged_out"
CANDIDATE = "candidate"
REVIEW = "review"  # docs/glossary.md#review: the outcome value itself is the string "review"


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (task, chunk) pair: the task description and the chunk's own
    content, and nothing else.

    ``fields`` also carries ``chunk_id``, ``source`` (the chunk's source reference, e.g.
    ``"ticket:5521#msg2"``) and ``recency_rank`` (how many chunks have been added to this
    task's pool more recently, 0 = newest), all bookkeeping Python keeps for itself. None of
    the three reaches the model; all three are reattached to the outcome afterwards, so every
    paging decision still traces back to its source and every chunk still carries its place in
    the recency baseline this recipe compares against.
    """
    return {"task": fields["task"], "chunk": fields["chunk"]}


def build_questions() -> dict[str, Score]:
    """The one question asked about every (task, chunk) pair. The levels come from
    ``RELEVANCE_LEVELS``."""
    return {
        "relevance": Score(
            instructions=(
                "How relevant is this stored chunk to completing the current task? Judge only "
                "what this chunk itself states, not what any other chunk says, not how recently "
                "it was added, and not any claim the chunk makes about its own importance."
            ),
            criteria=list(RELEVANCE_LEVELS),
        )
    }


@dataclass(frozen=True)
class Classification:
    """What Python decided about one chunk's relevance call: the level Jev's answer most
    likely holds, and the outcome of trusting it."""

    chunk_id: str
    level: int
    outcome: str
    reason: str


def classify_chunk(chunk_id: str, answer: Any, confidence_gate: float) -> Classification:
    """Act on a relevance answer: trust it only when confident enough, then apply the cutoff.

    The confidence gate decides whether the level is trustworthy at all: below
    ``confidence_gate`` the outcome is an explicit ``review``, whatever level the answer names,
    because a spread-out distribution over levels is not solid ground for a paging decision. At
    or above it, the rule applies the fixed :data:`RETENTION_CUTOFF`: a trusted answer whose
    most likely level (:func:`jev_cookbook.evaluation.score_level`, the modal level, ties going
    to the lower one) falls below ``SUPPORTING`` can never be retained, whatever budget is free,
    so its outcome is ``paged_out`` directly, not ``candidate``. The rest become ``candidate``:
    eligible for a budget slot, not yet promised one.

    This function decides only whether to *trust and consider* a chunk for retention. It does
    not decide whether the chunk actually keeps a slot: see :func:`allocate_budget`, which ranks
    every ``candidate`` by its expected score and spends the budget. The confidence gate, the
    retention cutoff and the budget allocation are three separate, explicit mechanisms, not one
    conflated rule.
    """
    if not 0.0 <= confidence_gate <= 1.0:
        raise ValueError(f"confidence_gate must be between 0 and 1, got {confidence_gate!r}")
    level = score_level(answer)
    if answer.confidence < confidence_gate:
        return Classification(chunk_id, level, REVIEW, "confidence below the threshold")
    if level < RETENTION_CUTOFF:
        return Classification(chunk_id, level, PAGED_OUT, "modal level below the retention cutoff")
    return Classification(chunk_id, level, CANDIDATE, "modal level clears the retention cutoff")


@dataclass(frozen=True)
class PagingDecision:
    """What happened to one chunk under the budget: its final status, the classification that
    led there, and whether this is a rehydration (the chunk's status one step ago was
    ``paged_out`` and it is ``retained`` now)."""

    chunk_id: str
    status: str  # RETAINED or PAGED_OUT; a "review" classification is paged out, conservatively
    classification: Classification
    rehydrated: bool


def allocate_budget(
    classifications: list[Classification],
    expected_scores: dict[str, float],
    previous_status: dict[str, str],
    slots: int = BUDGET_SLOTS,
) -> tuple[list[PagingDecision], Budget]:
    """Spend a fixed budget of ``slots`` retained chunks among this task's ``candidate`` chunks.

    Only chunks :func:`classify_chunk` already called ``candidate`` compete for a slot, ranked
    by ``expected_scores`` (Jev's expected level for that chunk, typically ``answer.score``)
    highest first, ties broken by ``chunk_id`` so the order is deterministic whatever the model
    answers. A chunk already judged ``paged_out`` is never promoted by budget slack, and a
    chunk sent to ``review`` is held back rather than risking a slot on an unconfident call --
    both page out here too, distinguished from a true ``paged_out`` classification only through
    ``classification.outcome``.

    ``jev_cookbook.simulation.Budget`` enforces the limit: this function never retains more than
    ``slots`` chunks because ``Budget.spend`` would raise ``BudgetExceeded`` first, and the
    allocation loop never calls ``spend`` past what ``can_spend`` allows. That makes "the budget
    is never exceeded" a property of the ``Budget`` object this function returns, checkable from
    outside it, whatever distribution of levels and confidences the model's answers carry.

    Args:
        classifications: One :class:`Classification` per chunk in the task's pool.
        expected_scores: ``{chunk_id: float}`` ranking score for every chunk named in
            ``classifications``.
        previous_status: ``{chunk_id: RETAINED | PAGED_OUT}`` for a chunk already known from an
            earlier turn in the same session; a chunk with no entry (new to the store, or this
            task is not part of a session) is treated as never having been retained.
        slots: The budget, at least 1.

    Returns:
        ``(decisions, budget)``, one :class:`PagingDecision` per input classification (same
        order) and the spent :class:`Budget` so a caller can inspect ``used("slots")`` directly.
    """
    if slots < 1:
        raise ValueError("slots must be at least 1")
    budget = Budget(slots=slots)
    ranked = sorted(
        (c for c in classifications if c.outcome == CANDIDATE),
        key=lambda c: (-expected_scores[c.chunk_id], c.chunk_id),
    )
    retained_ids: set[str] = set()
    for c in ranked:
        if not budget.can_spend("slots"):
            break
        budget.spend("slots")
        retained_ids.add(c.chunk_id)
    decisions = []
    for c in classifications:
        retained = c.chunk_id in retained_ids
        status = RETAINED if retained else PAGED_OUT
        rehydrated = retained and previous_status.get(c.chunk_id) == PAGED_OUT
        decisions.append(PagingDecision(c.chunk_id, status, c, rehydrated))
    return decisions, budget


def apply_to_store(
    store: Any,
    chunks_by_id: dict[str, dict[str, str]],
    decisions: list[PagingDecision],
    answers_by_id: dict[str, Any],
    *,
    writer: str,
    step: int,
) -> None:
    """Write this task's paging decisions to ``store``, one write per chunk.

    Only ``status`` changes between writes to the same key: ``content`` and ``source`` are
    copied from ``chunks_by_id`` unchanged on every call, for every chunk, whatever it was
    classified as. ``jev_cookbook.simulation.Store.delete`` is never called here, so a
    paged-out chunk's content and source stay in the store's live value (and in its full
    history) exactly as written, ready to be read back if the chunk is later rehydrated.
    """
    for d in decisions:
        chunk = chunks_by_id[d.chunk_id]
        store.put(
            d.chunk_id,
            {"content": chunk["content"], "source": chunk["source"], "status": d.status},
            writer=writer,
            step=step,
            answer=answers_by_id[d.chunk_id],
            rule=d.classification.reason,
        )


def content_preserved(history: list) -> bool:
    """True iff every write in ``history`` (a ``Store.history(key)`` result, oldest first)
    carries the same ``content`` and ``source`` as the first write: only ``status`` may change
    between writes to the same key, whatever paging decisions produced them. ``history`` must
    not be empty.
    """
    if not history:
        raise ValueError("history must not be empty")
    first = history[0].value
    return all(
        (not record.tombstone)
        and record.value["content"] == first["content"]
        and record.value["source"] == first["source"]
        for record in history
    )


def run_session(
    turns: list[list[tuple[str, dict[str, str], Any]]],
    confidence_gate: float,
    slots: int = BUDGET_SLOTS,
) -> tuple[Any, list[tuple[list[PagingDecision], Budget]]]:
    """Run a multi-turn paging session over one shared ``jev_cookbook.simulation.Store``.

    ``turns`` is one list per turn, each a list of ``(chunk_id, chunk, answer)`` triples:
    ``chunk`` is ``{"content": ..., "source": ...}`` and ``answer`` is that chunk's Score answer
    for the task in front of the engineer at this turn (a chunk already known from an earlier
    turn may reappear with a different answer, because the same chunk's relevance can change as
    the task changes). Composes :func:`classify_chunk`, :func:`allocate_budget` and
    :func:`apply_to_store` once per turn, carrying the previous turn's status forward so a
    chunk paged out on one turn can be rehydrated on a later one.

    Both the notebook and the tests call this one function for the session walkthrough, so the
    two can never silently diverge on what "running the session" means.

    Returns:
        ``(store, per_turn)``: the store after every turn, and one
        ``(decisions, budget)`` pair per turn, in order.
    """
    from jev_cookbook.simulation import Store

    store = Store()
    previous_status: dict[str, str] = {}
    per_turn: list[tuple[list[PagingDecision], Budget]] = []
    for step, turn in enumerate(turns):
        chunks_by_id = {cid: chunk for cid, chunk, _ in turn}
        answers_by_id = {cid: answer for cid, _, answer in turn}
        classifications = [
            classify_chunk(cid, answer, confidence_gate) for cid, answer in answers_by_id.items()
        ]
        expected_scores = {cid: answer.score for cid, answer in answers_by_id.items()}
        decisions, budget = allocate_budget(
            classifications, expected_scores, previous_status, slots
        )
        apply_to_store(
            store, chunks_by_id, decisions, answers_by_id, writer="paging_policy", step=step
        )
        previous_status = {d.chunk_id: d.status for d in decisions}
        per_turn.append((decisions, budget))
    return store, per_turn


def rebuild_store(write_records: list[dict]):
    """A fresh ``Store`` built by replaying ``write_records`` (``Store.to_dicts()`` output, or
    that same list carried through a JSON round trip) in order, via ``put``/``delete``.

    Used to prove a chunk's content and source survive paging losslessly *through
    serialisation*, not merely by comparing a live store object to itself: build this from the
    JSON text a store was dumped to, and compare the result's ``snapshot()`` and ``history(key)``
    against the original store's.
    """
    from jev_cookbook.simulation import Store

    store = Store()
    for record in write_records:
        if record["tombstone"]:
            store.delete(
                record["key"],
                writer=record["writer"],
                step=record["step"],
                answer=record["answer"],
                rule=record["rule"],
            )
        else:
            store.put(
                record["key"],
                record["value"],
                writer=record["writer"],
                step=record["step"],
                answer=record["answer"],
                rule=record["rule"],
            )
    return store
