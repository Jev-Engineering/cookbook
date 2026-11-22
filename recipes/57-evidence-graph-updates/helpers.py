"""Python's half of recipe 57: the graph, the two requests, the rule, and the transactional apply.

The fixture generator, the notebook and the tests all load this one file with
``jev_cookbook.load_helpers``, so the questions, the state, the rule and the store cannot disagree.

**The use case.** An upstream extractor proposes graph updates of one shape: "this mention now
works at this organisation". Before anything is written, Jev answers narrow questions about the
proposal, in two requests:

1. **Request 1** (independent questions about the mention and its excerpts): a ``Choice`` naming
   which person in the graph the mention is (or ``no_match``), and a ``Noul`` on whether the
   excerpts contradict each other.
2. **Request 2** (depends on request 1's choice, so it is a later request): the state shows the
   matched person's graph record and current employer, and two ``Noul`` propositions ask whether
   the excerpts state that the person now works at the proposed organisation, and whether they
   state that the person no longer works at the current one.

Python composes the answers into one proposed update and applies it with a ``Transactor``: the
validator and the graph invariant (a person works at one organisation at most) run on staged
writes, so a failing update is rolled back and leaves the store untouched. Every attempt is in
``tx.log`` with its provenance, and ``replay_transactions(tx.log)`` rebuilds the graph.
"""

import ast
import inspect
import math
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from jev_cookbook import Choice, Noul
from jev_cookbook.evaluation import select_confidence_threshold, select_threshold
from jev_cookbook.fixtures import stable_permutation
from jev_cookbook.simulation import ReviewQueue, Store, Transactor

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

SLUG = "57-evidence-graph-updates"
RELATION = "works_at"
NO_MATCH = "no_match"
UNMATCHED = "unmatched"  # what ask_first stores when the mention has no candidate

# Outcomes Python can reach for one proposal.
APPLIED = "applied"  # the transaction committed
NOT_MATCHED = "not_matched"  # the mention is none of the listed people: nothing is written
REJECTED = "rejected"  # the evidence does not support the relationship: nothing is written
REVIEW = "review"  # docs/glossary.md#review: a person decides; nothing is written

# Review reasons, exact strings. The first is the cookbook's fixed confidence-gate reason.
REASON_LOW_CONFIDENCE = "confidence below the threshold"
REASON_CONFLICT = "the excerpts conflict"
REASON_ROLLED_BACK = "the transaction was rolled back"
REASON_BUDGET = "request budget spent"
REASON_NO_MATCH = "the mention matches no listed person"
REASON_NO_CANDIDATE = "no candidate in the shortlist"
REASON_UNSUPPORTED = "the evidence does not support the relationship"
REASON_COMMITTED = "the transaction committed"
REASON_NOT_FITTED = "a request-2 threshold is not fitted"

# ---------------------------------------------------------------------------------------------
# The seed graph. Fabricated organisations and people; every person starts with exactly one
# current employer. The graph invariant the Transactor enforces on every update is "at most
# one": it rejects a second employer, but not a person left with none.
# ---------------------------------------------------------------------------------------------

ORGANISATIONS = {
    "O1": "Brightwater Labs",
    "O2": "Halden Institute",
    "O3": "Quillmoor Analytics",
    "O4": "Tessaly Foundry",
    "O5": "Orrin Bay Observatory",
    "O6": "Vantrell Clinic",
}

# id: (name, role, current employer)
PEOPLE = {
    "P01": ("Mira Okafor", "chemist", "O1"),
    "P02": ("Marcus Okafor", "engineer", "O3"),
    "P03": ("Ines Varga", "astronomer", "O5"),
    "P04": ("Tomas Varga", "accountant", "O4"),
    "P05": ("Ada Lindqvist", "physician", "O6"),
    "P06": ("Jonah Pell", "data analyst", "O3"),
    "P07": ("Ruth Pell", "metallurgist", "O4"),
    "P08": ("Sami Ekwueme", "biologist", "O2"),
    "P09": ("Noor Haddad", "statistician", "O2"),
    "P10": ("Leo Haddad", "lab technician", "O1"),
    "P11": ("Clara Moss", "nurse", "O6"),
    "P12": ("Felix Moss", "software developer", "O3"),
    "P13": ("Yara Sato", "geologist", "O4"),
    "P14": ("Owen Sato", "optician", "O6"),
    "P15": ("Hana Brekke", "physicist", "O5"),
    "P16": ("Dev Brekke", "radiographer", "O2"),
    "P17": ("Iris Calloway", "architect", "O1"),
    "P18": ("Basil Calloway", "telescope engineer", "O5"),
    "P19": ("Edda Rhee", "archivist", "O2"),
    "P20": ("Milo Rhee", "pharmacist", "O3"),
    "P21": ("Gwen Tallis", "safety officer", "O4"),
    "P22": ("Petra Lund", "survey designer", "O2"),
    "P23": ("Ansel Lund", "microscope builder", "O6"),
}


def org_key(org: str) -> str:
    return f"org:{org}"


def person_key(person: str) -> str:
    return f"person:{person}"


def edge_key(person: str, org: str) -> str:
    return f"edge:{person}|{RELATION}|{org}"


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd"}
_PUNCTUATION = ".,;:!?\"'()"
_PARENTHETICALS = re.compile(r"\([^()]*\)")


def _bare(word: str) -> str:
    """One word without the punctuation around it or a trailing possessive (``'s``)."""
    return word.strip(_PUNCTUATION).lower().removesuffix("'s").strip(_PUNCTUATION)


def _without_suffixes(words: list[str]) -> list[str]:
    """``words`` without trailing name suffixes (``Jr.``, ``Jr.'s``, ``III``, ``PhD``)."""
    while words and _bare(words[-1]) in _NAME_SUFFIXES:
        words = words[:-1]
    return words


def candidates(mention: str) -> list[str]:
    """The people Python shortlists for a mention: everyone whose surname is the mention's
    surname, in id order. The surname is the last word, after dropping every parenthetical
    (``(chemist)``, wherever it stands), punctuation around the word, a trailing possessive
    (``'s`` or ``\u2019s``) and a name suffix (``Jr.`` or ``PhD``, possessive or not). A known
    surname before a comma handles "Surname, Given" and trailing appositives; a descriptor
    starting with "the " before a comma allows the surname after it ("the architect, Iris
    Calloway"). Conflicting known surnames and unrecognised comma prefixes have no candidates.
    An empty or blank mention has no candidates, and ``ask_first`` sends no request for it. Jev
    never adds a candidate; it only chooses among these or ``no_match``."""
    text = _PARENTHETICALS.sub(" ", mention.replace("\u2019", "'"))
    words = _without_suffixes(text.split())
    text = " ".join(words).rstrip(",;: ")
    if "," in text:
        before, after = text.split(",", 1)
        left, right = _without_suffixes(before.split()), _without_suffixes(after.split())
        surnames = {name.split()[-1].lower() for name, _, _ in PEOPLE.values()}
        left_name = _bare(left[-1]) if left else ""
        right_name = _bare(right[-1]) if right else ""
        if left_name in surnames:
            if right_name in surnames and right_name != left_name:
                return []
            words = left
        elif before.lower().startswith("the ") and "," not in after:
            words = right
        else:
            return []
    surname = _bare(words[-1]) if words else ""
    if not surname:
        return []
    return [pid for pid, (name, _, _) in PEOPLE.items() if name.split()[-1].lower() == surname]


def option_order(example_id: str, mention: str) -> list[str]:
    """The candidates in a per-example order from the seeded permutation helper, keyed by
    ``f"{SLUG}:{example_id}"``, so the shown order comes from neither the data nor the id order.
    It holds only the shortlisted people: ``build_first_questions`` appends ``no_match`` after
    them, and ``ask_first`` sends no request at all when the shortlist is empty."""
    pool = candidates(mention)
    order = stable_permutation(f"{SLUG}:{example_id}", len(pool))
    return [pool[i] for i in order]


def describe(person: str) -> str:
    name, role, org = PEOPLE[person]
    return f"{name}, {role}, currently works at {ORGANISATIONS[org]}"


def _excerpts(fields: dict[str, Any]) -> list[str]:
    return [f"{e['source']}: {e['text']}" for e in fields["excerpts"]]


def build_first_state(fields: dict[str, Any]) -> dict[str, Any]:
    """Request 1's state: the mention, the proposal in words, and the excerpts. The example id
    and the organisation id stay in Python."""
    target = ORGANISATIONS[fields["target"]]
    return {
        "mention": fields["mention"],
        "proposed_update": f"{fields['mention']} now works at {target}",
        "excerpts": _excerpts(fields),
    }


def build_first_questions(example_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Request 1: two independent questions about the same state, asked together. The mention
    must have at least one candidate: a ``Choice`` needs two options (a person and ``no_match``)."""
    options = {pid: describe(pid) for pid in option_order(example_id, fields["mention"])}
    options[NO_MATCH] = (
        "None of the people listed above: the excerpts describe someone else who shares the name."
    )
    return {
        "entity": Choice(
            instructions=(
                "Which person in the graph is the mention in the excerpts? Read the roles and "
                "employers in the excerpts. Choose no_match when the excerpts describe a person "
                "who is none of the listed people."
            ),
            criteria=options,
        ),
        "conflict": Noul(
            instructions=(
                "Two of the excerpts contradict each other about where the mentioned person "
                "works now."
            )
        ),
    }


def build_second_state(fields: dict[str, Any], person: str) -> dict[str, Any]:
    """Request 2's state, built from request 1's choice: the matched person's graph record, the
    current employer from the seed graph, the proposed employer, and the same excerpts. Every
    request is asked before any update is applied, so this state shows the seed graph, and the
    answers about "the current employer" are about that seed edge. ``decide`` records that edge in
    the Decision (``judged``); ``validate_update`` rolls back a replacement whose live edge is no
    longer the one judged, for instance after an earlier update to the same person committed."""
    name, role, org = PEOPLE[person]
    return {
        "person": f"{name}, {role}",
        "current_employer": ORGANISATIONS[org],
        "proposed_employer": ORGANISATIONS[fields["target"]],
        "excerpts": _excerpts(fields),
    }


def build_second_questions() -> dict[str, Noul]:
    """Request 2: two Noul propositions about the same state, asked together."""
    return {
        "supported": Noul(
            instructions="The excerpts state that the person now works at the proposed employer."
        ),
        "ended": Noul(
            instructions=(
                "The excerpts state that the person no longer works at the current employer."
            )
        ),
    }


# ---------------------------------------------------------------------------------------------
# Settings, frozen on validation with the shared selectors.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """Every frozen setting of the rule. ``supported`` and ``ended`` are ``None`` until the
    second stage is frozen; ``decide_first`` reads only ``gate`` and ``conflict``."""

    gate: float
    conflict: float
    supported: float | None = None
    ended: float | None = None


def _is_answered(answer: Any) -> bool:
    """Whether a request was actually answered: a request the budget could not pay for (``None``)
    or a mention with no candidate (``UNMATCHED``) has no probability."""
    return answer is not None and answer != UNMATCHED


def _answered(first: list[Any], gold: list[dict[str, Any]]) -> tuple[list[Any], list[Any]]:
    """The (answer, gold) pairs whose request was actually answered."""
    pairs = [(a, g) for a, g in zip(first, gold, strict=True) if _is_answered(a)]
    return [a for a, _ in pairs], [g for _, g in pairs]


def reaches_conflict_check(first: Any, gate: float) -> bool:
    """Whether ``decide_first`` reads this request-1 answer's ``conflict`` probability: the
    request was answered, its entity confidence is at or above the gate, and it is not
    ``no_match``. The conflict threshold is fitted, and reported, on exactly these rows."""
    return (
        _is_answered(first)
        and first["entity"].confidence >= gate
        and first["entity"].choice != NO_MATCH
    )


def conflict_rows(examples: list[Any], first: dict[str, Any], gate: float) -> list[Any]:
    """The examples whose request-1 answer reaches the conflict check, in order."""
    return [e for e in examples if reaches_conflict_check(first[e.id], gate)]


def freeze_stage_one(first: list[Any], gold: list[dict[str, Any]]) -> Settings:
    """The entity confidence gate and the conflict threshold, chosen on validation.

    The gate is the lowest observed confidence at which every validation entity answer at or
    above it is right (``target_accuracy=1.0``); every option, ``no_match`` included, is gated.
    The conflict threshold maximises F1 over the validation conflict answers of the rows that
    reach the conflict check in ``decide_first`` (``reaches_conflict_check``): answered, at or
    above the gate, and not ``no_match``. Unanswered requests are left out. Both thresholds fail
    closed, so every proposal goes to review. When no request is answered, or no gate reaches the
    target accuracy (the selector raises ``ValueError``), the gate is infinite, so no answer
    passes it. When no row reaches the conflict check, none of those rows is a gold conflict (F1
    is 0 at every threshold, so no threshold is chosen by it), or the selector raises
    ``ValueError``, the conflict threshold is minus infinity, so every probability reaches it
    and the proposal goes to review."""
    first, gold = _answered(first, gold)
    if not first:
        return Settings(gate=math.inf, conflict=-math.inf)
    correct = [a["entity"].choice == g["entity"] for a, g in zip(first, gold, strict=True)]
    confidence = [a["entity"].confidence for a in first]
    try:
        gate = select_confidence_threshold(correct, confidence, target_accuracy=1.0)
    except ValueError:
        gate = math.inf
    checked = [(a, g) for a, g in zip(first, gold, strict=True) if reaches_conflict_check(a, gate)]
    try:
        if not checked:
            raise ValueError("no validation row reaches the conflict check")
        if not any(g["conflict"] for _, g in checked):
            raise ValueError("no validation row that reaches the conflict check is a conflict")
        conflict = select_threshold(
            [g["conflict"] for _, g in checked],
            [a["conflict"].noul for a, _ in checked],
            "f1",
        )
    except ValueError:
        conflict = -math.inf
    return Settings(gate=gate, conflict=conflict)


def freeze_stage_two(settings: Settings, second: list[Any], gold: list[dict[str, Any]]) -> Settings:
    """The two business thresholds of request 2, each maximising F1 on validation over the rows
    that reached request 2 with the right person matched. Unanswered requests are left out; with
    no row left, no row that is gold-true for that proposition (F1 is 0 at every threshold, so no
    threshold is chosen by it), or a selector that raises ``ValueError`` (no threshold satisfies
    the objective), that threshold is infinite: it is not fitted, and ``decide`` sends every
    proposal that reaches request 2 to review."""
    second, gold = _answered(second, gold)
    if not second:
        return Settings(settings.gate, settings.conflict, math.inf, math.inf)
    try:
        if not any(g["supported"] for g in gold):
            raise ValueError("no validation row that reached request 2 is gold-supported")
        supported = select_threshold(
            [g["supported"] for g in gold],
            [a["supported"].noul for a in second],
            "f1",
        )
    except ValueError:
        supported = math.inf
    try:
        if not any(g["ended"] for g in gold):
            raise ValueError("no validation row that reached request 2 is gold-ended")
        ended = select_threshold(
            [g["ended"] for g in gold], [a["ended"].noul for a in second], "f1"
        )
    except ValueError:
        ended = math.inf
    return Settings(settings.gate, settings.conflict, supported, ended)


def objective_in(source: str, name: str) -> str | None:
    """The objective of the ``select_threshold`` call in ``source`` whose gold is ``g["<name>"]``,
    spelled as the notebook prints it, or ``None`` when ``source`` has no such call or its
    objective or target is not a literal. The call may be by name or by attribute
    (``evaluation.select_threshold``). Each argument is read by position or by keyword, in
    ``select_threshold``'s own parameter order, and a missing objective is that signature's
    default."""
    signature = inspect.signature(select_threshold).parameters
    params = list(signature)
    for node in ast.walk(ast.parse(textwrap.dedent(source))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if called != "select_threshold":
            continue
        args = dict(zip(params, node.args, strict=False))
        args.update({k.arg: k.value for k in node.keywords if k.arg in params})
        if "gold" not in args or f"g['{name}']" not in ast.unparse(args["gold"]):
            continue
        try:
            objective = (
                ast.literal_eval(args["objective"])
                if "objective" in args
                else signature["objective"].default
            )
            target = ast.literal_eval(args["target"]) if "target" in args else None
        except ValueError:
            return None
        label = "F1" if objective == "f1" else objective
        if target is not None:
            label += f", target {target}"
        return label
    return None


def objective_label(name: str) -> str:
    """The objective the ``name`` threshold is chosen with, read from the ``select_threshold``
    call in ``freeze_stage_one`` / ``freeze_stage_two`` itself, so the notebook prints what the
    committed call uses (and not a string typed beside it)."""
    for freeze in (freeze_stage_one, freeze_stage_two):
        label = objective_in(inspect.getsource(freeze), name)
        if label is not None:
            return label
    raise KeyError(name)


def reached_second(
    examples: list[Any], first: dict[str, Any], second: dict[str, Any], labels: dict[str, Any]
) -> list[Any]:
    """The examples whose request 2 was actually answered (not refused by the budget, so not
    ``None``), whose request 1 named the gold person, and whose gold has request-2 labels. A
    refused row has no probabilities, so it is left out here and goes to review in ``decide``."""
    return [
        e
        for e in examples
        if second.get(e.id) is not None
        and first[e.id]["entity"].choice == labels[e.id]["entity"]
        and "supported" in labels[e.id]
    ]


def entity_hits(first: list[Any], gold: list[dict[str, Any]], floor: float = 0.0) -> list[bool]:
    """Whether each answered request 1 named the gold entity, for the answers whose confidence is
    at least ``floor``. Unanswered requests are left out, so the list can be empty."""
    first, gold = _answered(first, gold)
    return [
        a["entity"].choice == g["entity"]
        for a, g in zip(first, gold, strict=True)
        if a["entity"].confidence >= floor
    ]


# ---------------------------------------------------------------------------------------------
# Asking. A Budget of requests is spent before every decide() call; a request the budget cannot
# pay for is not made, and the proposal goes to review.
# ---------------------------------------------------------------------------------------------


def ask_first(backend: Any, budget: Any, examples: list[Any]) -> dict[str, Any]:
    """Request 1 for every example, in order: ``{example id: DecisionResult, None or UNMATCHED}``.
    ``None`` is a request the budget could not pay for; ``UNMATCHED`` is a mention with no
    candidate in the graph: no request is sent, and the rule sends it to review."""
    out = {}
    for e in examples:
        if not candidates(e.fields["mention"]):
            out[e.id] = UNMATCHED
            continue
        if not budget.can_spend("requests"):
            out[e.id] = None
            continue
        budget.spend("requests")
        out[e.id] = backend.decide(
            build_first_state(e.fields), build_first_questions(e.id, e.fields)
        )
    return out


def ask_second(
    backend: Any, budget: Any, examples: list[Any], first: dict[str, Any], settings: Settings
) -> dict[str, Any]:
    """Request 2 for every example whose request 1 the rule lets through (``decide_first``
    returns ``None``): ``{example id: DecisionResult or None}``. The state names the person
    request 1 chose, which is why this is a separate, later request. ``None`` thresholds allow
    calibration; a final nonfinite request-2 threshold skips the request without spending."""
    out = {}
    if any(t is not None and not math.isfinite(t) for t in (settings.supported, settings.ended)):
        return out
    for e in examples:
        if decide_first(first[e.id], settings) is not None:
            continue
        if not budget.can_spend("requests"):
            out[e.id] = None
            continue
        budget.spend("requests")
        person = first[e.id]["entity"].choice
        out[e.id] = backend.decide(build_second_state(e.fields, person), build_second_questions())
    return out


# ---------------------------------------------------------------------------------------------
# The rule. Pure: it reads answers and settings and returns a Decision; it writes nothing.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """What the rule decided for one proposal, before anything is written."""

    example: str
    outcome: str  # "propose", NOT_MATCHED, REJECTED or REVIEW
    reason: str
    person: str | None = None
    target: str | None = None
    replace: bool = False  # the old employment ended: delete the person's current edge
    answers: Any = None  # plain-JSON answers, carried into the log as provenance
    judged: str | None = None  # the edge request 2 judged "ended" about (set with ``replace``)


PROPOSE = "propose"


def _answers_dict(first: Any, second: Any) -> dict[str, Any]:
    """Both requests' answers as plain JSON, for the log. A result is a ``DecisionResult`` or a
    plain ``{name: answer}`` mapping (the notebook's counterfactual rows use one)."""
    out = {}
    for result in (first, second):
        if result is not None and result != UNMATCHED:
            for name in result.keys():
                out[name] = result[name].to_dict()
    return out


def decide_first(
    first: Any, settings: Settings, example: str = "", target: str | None = None
) -> Decision | None:
    """The rule's first stage. ``None`` means "ask request 2"; otherwise the final Decision. The
    answers are serialised for the log only when a Decision is returned. A review Decision
    carries ``target`` (the proposed organisation) and, once request 1 named a person (not
    ``no_match``), that person, so the review item shows the update it would write."""
    if first is None:
        return Decision(example, REVIEW, REASON_BUDGET, target=target)
    if first == UNMATCHED:
        return Decision(example, REVIEW, REASON_NO_CANDIDATE, target=target, answers={})
    entity = first["entity"]
    person = None if entity.choice == NO_MATCH else entity.choice
    if entity.confidence < settings.gate:
        answers = _answers_dict(first, None)
        return Decision(example, REVIEW, REASON_LOW_CONFIDENCE, person, target, answers=answers)
    if entity.choice == NO_MATCH:
        return Decision(example, NOT_MATCHED, REASON_NO_MATCH, answers=_answers_dict(first, None))
    if first["conflict"].noul >= settings.conflict:
        answers = _answers_dict(first, None)
        return Decision(example, REVIEW, REASON_CONFLICT, person, target, answers=answers)
    return None


def decide(example: Any, first: Any, second: Any, settings: Settings) -> Decision:
    """Compose both requests into one Decision for ``example`` (an Example with ``fields``).
    ``settings`` must hold both stages (``freeze_stage_two``). A request-2 threshold that is not
    fitted (infinite) fails closed: the proposal goes to review, never to a reject or a write."""
    if settings.supported is None or settings.ended is None:
        raise ValueError("decide needs settings with supported and ended; call freeze_stage_two")
    target = example.fields["target"]
    early = decide_first(first, settings, example.id, target)
    if early is not None:
        return early
    person = first["entity"].choice
    answers = _answers_dict(first, second)
    if not (math.isfinite(settings.supported) and math.isfinite(settings.ended)):
        return Decision(example.id, REVIEW, REASON_NOT_FITTED, person, target, answers=answers)
    if second is None:
        return Decision(example.id, REVIEW, REASON_BUDGET, person, target, answers=answers)
    if second["supported"].noul < settings.supported:
        return Decision(example.id, REJECTED, REASON_UNSUPPORTED, person, target, answers=answers)
    replace = second["ended"].noul >= settings.ended
    judged = edge_key(person, PEOPLE[person][2]) if replace else None
    return Decision(example.id, PROPOSE, "", person, target, replace, answers, judged)


# ---------------------------------------------------------------------------------------------
# The baseline: a deterministic keyword rule over the same fields, no request at all.
# ---------------------------------------------------------------------------------------------

ENDED_CUES = (
    "left ",
    "leaving",
    "departed",
    "former ",
    "last day",
    "moved from",
    "transferred from",
    "retired",
)
# A cue starts at a word boundary; one written with a trailing space must be followed by
# whitespace (so ``left `` matches "left Tessaly" but not "cleft" or the sentence-final "left.").
_ENDED_PATTERN = re.compile(
    "|".join(
        r"\b" + re.escape(cue.rstrip()) + (r"\s" if cue.endswith(" ") else r"\b")
        for cue in ENDED_CUES
    )
)


def _names(name: str, excerpt: str) -> bool:
    """Whether ``name`` appears in one excerpt as whole words (so ``Leo Haddad`` is not found in
    ``Cleo Haddad``, and a name cannot be assembled across two excerpts)."""
    return re.search(r"\b" + re.escape(name.lower()) + r"\b", excerpt.lower()) is not None


def baseline_decide(example: Any) -> Decision:
    """Keyword baseline. Entity: the one candidate whose full name appears as whole words in one
    excerpt, else ``not_matched``. No conflict check. Supported: the proposed organisation's name
    appears as whole words in one excerpt. Ended: the current employer's name and one of
    ``ENDED_CUES`` (from a word boundary) both appear in the same excerpt, with the employer
    matched as whole words."""
    fields = example.fields
    named = [
        p
        for p in candidates(fields["mention"])
        if any(_names(PEOPLE[p][0], e["text"]) for e in fields["excerpts"])
    ]
    if len(named) != 1:
        return Decision(example.id, NOT_MATCHED, REASON_NO_MATCH)
    person = named[0]
    target = fields["target"]
    if not any(_names(ORGANISATIONS[target], e["text"]) for e in fields["excerpts"]):
        return Decision(example.id, REJECTED, REASON_UNSUPPORTED, person, target)
    current = PEOPLE[person][2]
    employer = ORGANISATIONS[current]
    replace = any(
        _names(employer, e["text"]) and _ENDED_PATTERN.search(e["text"].lower())
        for e in fields["excerpts"]
    )
    judged = edge_key(person, current) if replace else None
    return Decision(example.id, PROPOSE, "", person, target, replace, judged=judged)


# ---------------------------------------------------------------------------------------------
# The store, the transaction and the run. Shape 2 of docs/simulation.md: where a proposal ends
# up (committed, or rolled back and sent to review) depends on the transaction's own result.
# ---------------------------------------------------------------------------------------------


def graph_invariant(view: Any) -> list[str] | None:
    """The graph invariant, checked on staged writes: every edge joins a live person to a live
    organisation, and nobody works at more than one organisation."""
    state = view.snapshot()
    employers: dict[str, list[str]] = {}
    problems = []
    for key, value in sorted(state.items()):
        if not key.startswith("edge:"):
            continue
        if person_key(value["person"]) not in state or org_key(value["org"]) not in state:
            problems.append(f"{key} joins an entity that is not in the graph")
        employers.setdefault(value["person"], []).append(value["org"])
    for person, orgs in sorted(employers.items()):
        if len(orgs) > 1:
            problems.append(f"{person} would work at {len(orgs)} organisations: {', '.join(orgs)}")
    return problems or None


def current_edges(state: dict[str, Any], person: str) -> list[str]:
    """The keys of ``person``'s employment edges in ``state``, a graph snapshot."""
    return [
        key
        for key, value in sorted(state.items())
        if key.startswith("edge:") and value["person"] == person
    ]


def validate_update(view: Any, params: Any) -> list[str] | None:
    """Checks on the proposal itself, before it is staged."""
    problems = []
    if person_key(params["person"]) not in view:
        problems.append(f"no person {params['person']}")
    if org_key(params["org"]) not in view:
        problems.append(f"no organisation {params['org']}")
    if edge_key(params["person"], params["org"]) in view:
        problems.append("the edge is already in the graph")
    if params["replace"] and params["remove"] is None:
        problems.append(f"{params['person']} has no current employment to replace")
    if params["remove"] is not None:
        if params["remove"] not in current_edges(view.snapshot(), params["person"]):
            problems.append(f"{params['remove']} is not {params['person']}'s current employment")
        if params["remove"] != params["judged"]:
            problems.append(
                f"{params['remove']} is not the employment the evidence was judged against "
                f"({params['judged']})"
            )
    return problems or None


@dataclass(frozen=True)
class Outcome:
    """What happened to one proposal: the outcome, why, and the operations committed."""

    example: str
    outcome: str
    reason: str
    ops: tuple[tuple[str, str], ...] = ()
    error: str | None = None


def run_updates(
    decisions: list[Decision], writer: str
) -> tuple[Transactor, ReviewQueue, list[Outcome]]:
    """Seed a fresh graph, then act on every Decision in order; return the Transactor (its store
    and log), the review queue and one Outcome per Decision.

    ``not_matched`` and ``rejected`` write nothing. A ``review`` decision is submitted to the queue.
    A ``propose`` decision runs one transaction (``validate_update`` first, then the staged
    writes, then ``graph_invariant``); if it commits, the outcome is ``applied`` with the
    committed operations, and if it is rolled back, the store is unchanged and the proposal goes
    to review with the rollback error beside it."""

    # The two staging functions live inside run_updates, the one side-effect function the
    # notebook calls: they write only to the Transactor's staged view.
    def _seed(view: Any, params: Any) -> None:
        for org, name in ORGANISATIONS.items():
            view.put(org_key(org), {"name": name})
        for person, (name, role, org) in PEOPLE.items():
            view.put(person_key(person), {"name": name, "role": role})
            view.put(edge_key(person, org), {"person": person, "relation": RELATION, "org": org})

    def _apply_update(view: Any, params: Any) -> None:
        if params["remove"] is not None:
            view.delete(params["remove"])
        view.put(
            edge_key(params["person"], params["org"]),
            {"person": params["person"], "relation": RELATION, "org": params["org"]},
        )

    tx = Transactor(Store())
    queue = ReviewQueue()
    tx.run("seed_graph", _seed, writer="rule:seed", step=0, invariant=graph_invariant)
    outcomes = []
    for step, d in enumerate(decisions, start=1):
        item = {"example": d.example, "person": d.person, "target": d.target}
        if d.outcome == REVIEW:
            queue.submit(item, d.reason, answer=d.answers, step=step)
            outcomes.append(Outcome(d.example, REVIEW, d.reason))
            continue
        if d.outcome != PROPOSE:
            outcomes.append(Outcome(d.example, d.outcome, d.reason))
            continue
        # The edge to delete is read from the live store now; validate_update rolls the update
        # back unless it is the edge request 2 judged (an earlier committed update to the same
        # person changes it).
        edges = current_edges(tx.store.snapshot(), d.person) if d.replace else []
        params = {
            "example": d.example,
            "person": d.person,
            "org": d.target,
            "replace": d.replace,
            "remove": edges[0] if edges else None,
            "judged": d.judged,
        }
        rule = "replace the employer" if d.replace else "add an employer"
        record = tx.run(
            f"{RELATION}:{d.example}",
            _apply_update,
            params=params,
            writer=writer,
            step=step,
            answer=d.answers,
            rule=rule,
            validate=validate_update,
            invariant=graph_invariant,
            raise_on_failure=False,
        )
        if record.committed:
            ops = tuple((op["op"], op["key"]) for op in record.ops)
            outcomes.append(Outcome(d.example, APPLIED, REASON_COMMITTED, ops))
        else:
            queue.submit(
                {**item, "error": record.error}, REASON_ROLLED_BACK, answer=d.answers, step=step
            )
            outcomes.append(Outcome(d.example, REVIEW, REASON_ROLLED_BACK, (), record.error))
    return tx, queue, outcomes


def gold_ops(label: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """The operations the gold label says the update should commit (empty: write nothing)."""
    return tuple((op, key) for op, key in label["update"])
