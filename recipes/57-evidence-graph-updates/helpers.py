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

# Outcomes Python can reach for one proposal.
APPLIED = "applied"  # the transaction committed
NOT_MATCHED = "no_match"  # the mention is none of the listed people: nothing is written
REJECTED = "rejected"  # the evidence does not support the relationship: nothing is written
REVIEW = "review"  # docs/glossary.md#review: a person decides; nothing is written

# Review reasons, exact strings. The first is the cookbook's fixed confidence-gate reason.
REASON_LOW_CONFIDENCE = "confidence below the threshold"
REASON_CONFLICT = "the excerpts conflict"
REASON_ROLLED_BACK = "the transaction was rolled back"
REASON_BUDGET = "request budget spent"
REASON_NO_MATCH = "the mention matches no listed person"
REASON_UNSUPPORTED = "the evidence does not support the relationship"
REASON_COMMITTED = "the transaction committed"

# ---------------------------------------------------------------------------------------------
# The seed graph. Fabricated organisations and people; every person has exactly one current
# employer, which is the graph invariant the Transactor enforces on every update.
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


def candidates(mention: str) -> list[str]:
    """The people Python shortlists for a mention: everyone whose surname is the mention's last
    word, in id order. Jev never adds a candidate; it only chooses among these or ``no_match``."""
    surname = mention.split()[-1].lower()
    return [pid for pid, (name, _, _) in PEOPLE.items() if name.split()[-1].lower() == surname]


def option_order(example_id: str, mention: str) -> list[str]:
    """The candidates in a per-example order from the seeded permutation helper, keyed by
    ``f"{SLUG}:{example_id}"``, so the shown order comes from neither the data nor the id order;
    ``no_match`` is always last."""
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
    """Request 1: two independent questions about the same state, asked together."""
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
    current employer from the seed graph, the proposed employer, and the same excerpts. Each
    person appears at most once in a split, so the seed graph is the graph at request time."""
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


def freeze_stage_one(first: list[Any], gold: list[dict[str, Any]]) -> Settings:
    """The entity confidence gate and the conflict threshold, chosen on validation.

    The gate is the lowest observed confidence at which every validation entity answer at or
    above it is right (``target_accuracy=1.0``); every option, ``no_match`` included, is gated.
    The conflict threshold maximises F1 over the validation conflict answers."""
    correct = [a["entity"].choice == g["entity"] for a, g in zip(first, gold, strict=True)]
    confidence = [a["entity"].confidence for a in first]
    gate = select_confidence_threshold(correct, confidence, target_accuracy=1.0)
    conflict = select_threshold(
        [g["conflict"] for g in gold], [a["conflict"].noul for a in first], "f1"
    )
    return Settings(gate=gate, conflict=conflict)


def freeze_stage_two(settings: Settings, second: list[Any], gold: list[dict[str, Any]]) -> Settings:
    """The two business thresholds of request 2, each maximising F1 on validation over the rows
    that reached request 2 with the right person matched."""
    supported = select_threshold(
        [g["supported"] for g in gold], [a["supported"].noul for a in second], "f1"
    )
    ended = select_threshold([g["ended"] for g in gold], [a["ended"].noul for a in second], "f1")
    return Settings(settings.gate, settings.conflict, supported, ended)


# ---------------------------------------------------------------------------------------------
# Asking. A Budget of requests is spent before every decide() call; a request the budget cannot
# pay for is not made, and the proposal goes to review.
# ---------------------------------------------------------------------------------------------


def ask_first(backend: Any, budget: Any, examples: list[Any]) -> dict[str, Any]:
    """Request 1 for every example, in order: ``{example id: DecisionResult or None}``."""
    out = {}
    for e in examples:
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
    request 1 chose, which is why this is a separate, later request."""
    out = {}
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
    remove: str | None = None  # the current edge to delete, when the old employment ended
    answers: Any = None  # plain-JSON answers, carried into the log as provenance


PROPOSE = "propose"


def _answers_dict(first: Any, second: Any) -> dict[str, Any]:
    """Both requests' answers as plain JSON, for the log. A result is a ``DecisionResult`` or a
    plain ``{name: answer}`` mapping (the notebook's counterfactual rows use one)."""
    out = {}
    for result in (first, second):
        if result is not None:
            for name in result.keys():
                out[name] = result[name].to_dict()
    return out


def decide_first(first: Any, settings: Settings, example: str = "") -> Decision | None:
    """The rule's first stage. ``None`` means "ask request 2"; otherwise the final Decision."""
    answers = _answers_dict(first, None)
    if first is None:
        return Decision(example, REVIEW, REASON_BUDGET)
    entity = first["entity"]
    if entity.confidence < settings.gate:
        return Decision(example, REVIEW, REASON_LOW_CONFIDENCE, answers=answers)
    if entity.choice == NO_MATCH:
        return Decision(example, NOT_MATCHED, REASON_NO_MATCH, answers=answers)
    if first["conflict"].noul >= settings.conflict:
        return Decision(example, REVIEW, REASON_CONFLICT, entity.choice, answers=answers)
    return None


def decide(example: Any, first: Any, second: Any, settings: Settings) -> Decision:
    """Compose both requests into one Decision for ``example`` (an Example with ``fields``)."""
    early = decide_first(first, settings, example.id)
    if early is not None:
        return early
    person = first["entity"].choice
    answers = _answers_dict(first, second)
    if second is None:
        return Decision(example.id, REVIEW, REASON_BUDGET, person, answers=answers)
    target = example.fields["target"]
    if second["supported"].noul < settings.supported:
        return Decision(example.id, REJECTED, REASON_UNSUPPORTED, person, target, answers=answers)
    remove = None
    if second["ended"].noul >= settings.ended:
        remove = edge_key(person, PEOPLE[person][2])
    return Decision(example.id, PROPOSE, "", person, target, remove, answers)


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


def baseline_decide(example: Any) -> Decision:
    """Keyword baseline. Entity: the one candidate whose full name appears in an excerpt, else
    ``no_match``. No conflict check. Supported: the proposed organisation's name appears in an
    excerpt. Ended: the current employer's name and one of ``ENDED_CUES`` both appear."""
    fields = example.fields
    text = " ".join(e["text"] for e in fields["excerpts"]).lower()
    named = [p for p in candidates(fields["mention"]) if PEOPLE[p][0].lower() in text]
    if len(named) != 1:
        return Decision(example.id, NOT_MATCHED, REASON_NO_MATCH)
    person = named[0]
    target = fields["target"]
    if ORGANISATIONS[target].lower() not in text:
        return Decision(example.id, REJECTED, REASON_UNSUPPORTED, person, target)
    current = PEOPLE[person][2]
    remove = None
    if ORGANISATIONS[current].lower() in text and any(cue in text for cue in ENDED_CUES):
        remove = edge_key(person, current)
    return Decision(example.id, PROPOSE, "", person, target, remove)


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


def validate_update(view: Any, params: Any) -> list[str] | None:
    """Checks on the proposal itself, before it is staged."""
    problems = []
    if person_key(params["person"]) not in view:
        problems.append(f"no person {params['person']}")
    if org_key(params["org"]) not in view:
        problems.append(f"no organisation {params['org']}")
    if edge_key(params["person"], params["org"]) in view:
        problems.append("the edge is already in the graph")
    if params["remove"] is not None and params["remove"] not in view:
        problems.append(f"{params['remove']} is not in the graph")
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

    ``no_match`` and ``rejected`` write nothing. A ``review`` decision is submitted to the queue.
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
        params = {"example": d.example, "person": d.person, "org": d.target, "remove": d.remove}
        rule = "replace the employer" if d.remove else "add an employer"
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
