"""Python's half of recipe 49: the state, the question, the structured scenario data, and the
deterministic scheduler.

Jev answers one question: how suitable is this agent for this subtask, given each one's plain
track record? Everything else -- which agents may even be considered for a subtask (capability),
in what order a subtask may be attempted (dependency), and how much work an agent may be given
before it is out of room (budget) -- is structured data Python already has, and the scheduler
below enforces it regardless of what Jev answers. The fixture generator, the notebook and the
tests all load this file with ``jev_cookbook.load_helpers``, so the question, the scenario data
and the rule cannot disagree.
"""

from dataclasses import dataclass
from typing import Any

from jev_cookbook import Score
from jev_cookbook.simulation import ActionLog, Budget, ReviewQueue

# No ``from __future__ import annotations`` here: load_helpers removes this module from
# ``sys.modules``, so typing.get_type_hints cannot resolve postponed annotations on a dataclass.

# --------------------------------------------------------------------------------------------
# The suitability rubric, lowest level first. Score evaluates every level independently against
# the state (https://docs.typesafe.ai/primitives/score: "Every level is evaluated separately."),
# so each description stands on its own rather than naming the level above or below it.
# --------------------------------------------------------------------------------------------
UNSUITABLE = (
    "Nothing in the agent's track record resembles this kind of work; attempting the subtask "
    "would very likely fail."
)
TANGENTIAL = (
    "The agent's track record is in a related area but does not cover the specific kind of "
    "outcome this subtask needs; completing it would take substantial unsupported effort."
)
UNPROVEN_FIT = (
    "The agent's track record covers the general skill this subtask needs, without a completed "
    "example of this particular kind of outcome; a workable fit that is not yet demonstrated."
)
STRONG_FIT = (
    "The agent's track record includes a directly comparable completed example of this "
    "subtask's kind of outcome; a strong, demonstrated fit."
)
IDEAL_FIT = (
    "The agent's track record shows multiple successful completions of exactly this kind of "
    "outcome; the best possible fit."
)
SUITABILITY_LEVELS = (UNSUITABLE, TANGENTIAL, UNPROVEN_FIT, STRONG_FIT, IDEAL_FIT)  # level 0 to 4

REVIEW = "review"
ASSIGNED = "assigned"

# Review reasons. "confidence below the threshold" is the exact string every confidence-gated
# recipe in this cookbook uses (docs/glossary.md#review); the other two name a different,
# unconditional review branch that has nothing to do with confidence.
NO_ELIGIBLE_AGENT = "no eligible agent"
DEPENDENCY_NOT_ASSIGNED = "a dependency was not assigned"
BELOW_CONFIDENCE_THRESHOLD = "confidence below the threshold"


# --------------------------------------------------------------------------------------------
# The structured scenario: agents, subtasks, capability, dependency and budget. None of this
# comes from Jev; the fixture generator and the scheduler both read it from here so the two
# halves of each recipe (the question and the enforcement) cannot drift apart.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Agent:
    """One agent: its id, the skills it holds (capability), its remaining-work budget, and the
    plain-text track record Jev reads. ``profile`` never mentions a skill tag by name."""

    id: str
    skills: frozenset
    capacity: int
    profile: str


@dataclass(frozen=True)
class Subtask:
    """One subtask: its id, the single skill it requires, its cost against an agent's budget,
    the subtasks it depends on, and the plain-text description Jev reads."""

    id: str
    required_skill: str
    cost: int
    depends_on: tuple = ()
    description: str = ""


def _agent(id_, skills, capacity, profile):
    return Agent(id_, frozenset(skills), capacity, profile)


def _subtask(id_, required_skill, cost, depends_on, description):
    return Subtask(id_, required_skill, cost, tuple(depends_on), description)


# "sprint-1": a tight scenario where one agent (zephyr) is the only one who can do both kinds of
# work, so whichever subtask gets zephyr's one unit of budget changes what is still possible for
# the rest of the sprint -- the scheduler's state (what budget is left, what has been assigned)
# carries from one subtask to the next.
VALIDATION_AGENTS = (
    _agent(
        "nova",
        {"code"},
        1,
        "Nova has spent the last two years writing backend services and database schemas, "
        "including three API redesigns that shipped without a rollback.",
    ),
    _agent(
        "iris",
        {"code"},
        1,
        "Iris implements backend features end to end and has closed out more implementation "
        "tickets than anyone else on the team this quarter.",
    ),
    _agent(
        "orin",
        {"code"},
        1,
        "Orin joined the backend team six months ago and has so far handled small, well-scoped "
        "bug fixes rather than anything that started from a blank page.",
    ),
    _agent(
        "wren",
        {"docs"},
        1,
        "Wren writes release notes and user-facing documentation, and has a reputation for "
        "documentation that the support team can actually use.",
    ),
    _agent(
        "sable",
        {"docs"},
        1,
        "Sable edits documentation others have drafted but has not yet written a release note "
        "or a guide from a blank page.",
    ),
    _agent(
        "zephyr",
        {"code", "docs"},
        1,
        "Zephyr moves between backend work and documentation as needed, with recent wins in "
        "both performance tuning and onboarding material.",
    ),
)
VALIDATION_SUBTASKS = (
    _subtask(
        "s1-api-schema",
        "code",
        1,
        (),
        "Define the schema the new API will expose, including field names and types, before "
        "any implementation starts.",
    ),
    _subtask(
        "s2-api-implementation",
        "code",
        1,
        ("s1-api-schema",),
        "Implement the backend service against the schema that was just defined.",
    ),
    _subtask(
        "s3-release-notes",
        "docs",
        1,
        ("s2-api-implementation",),
        "Write the release notes describing what changed in this version, for an audience of "
        "existing customers.",
    ),
    _subtask(
        "s4-onboarding-guide",
        "docs",
        1,
        (),
        "Write the onboarding guide that walks a brand-new user through their first use of the "
        "product.",
    ),
    _subtask(
        "s5-perf-tuning",
        "code",
        1,
        ("s2-api-implementation",),
        "Profile and tune the backend service's response time under load.",
    ),
    _subtask(
        "s6-load-test",
        "code",
        1,
        ("s5-perf-tuning",),
        "Run a load test against the tuned service and record the results.",
    ),
)

# "sprint-2": a second, independently shaped project. Two code subtasks have no dependency at
# all, the docs chain has its own internal dependency, and the last subtask depends on two
# earlier subtasks from different skill chains at once -- a shape validation does not have, so
# applying the frozen threshold here is not simply replaying the same scenario with new names.
TEST_AGENTS = (
    _agent(
        "cora",
        {"code"},
        1,
        "Cora has built backend services for two internal tools and recently fixed a "
        "long-standing database migration bug.",
    ),
    _agent(
        "juno",
        {"code"},
        1,
        "Juno has the broadest backend experience on the team, having implemented integrations "
        "with three external services.",
    ),
    _agent(
        "milo",
        {"code"},
        1,
        "Milo is new to backend work and has only shadowed migrations and integrations so far, "
        "without owning one end to end.",
    ),
    _agent(
        "astra",
        {"docs"},
        1,
        "Astra writes user guides and FAQ content, and keeps the support team's documentation "
        "up to date.",
    ),
    _agent(
        "reed",
        {"docs"},
        1,
        "Reed proofreads documentation others have written but has not yet drafted a guide or "
        "an FAQ section from scratch.",
    ),
    _agent(
        "pike",
        {"code", "docs"},
        1,
        "Pike splits time between backend integration work and documentation, picking up "
        "whichever is short-staffed.",
    ),
)
TEST_SUBTASKS = (
    _subtask(
        "u1-db-migration",
        "code",
        1,
        (),
        "Write and run the database migration this release depends on.",
    ),
    _subtask(
        "u2-service-integration",
        "code",
        1,
        ("u1-db-migration",),
        "Integrate the new external service once the migration above has run.",
    ),
    _subtask(
        "u3-metrics-dashboard",
        "code",
        1,
        (),
        "Build a small dashboard that reports the service's request metrics.",
    ),
    _subtask(
        "u4-user-guide",
        "docs",
        1,
        (),
        "Write the user guide section covering this release's new feature.",
    ),
    _subtask(
        "u5-faq-update",
        "docs",
        1,
        ("u4-user-guide",),
        "Update the FAQ to answer the questions this release will raise, based on the new "
        "guide section.",
    ),
    _subtask(
        "u6-launch-checklist",
        "docs",
        1,
        ("u2-service-integration", "u5-faq-update"),
        "Write the launch checklist that depends on both the integration and the FAQ work "
        "being done.",
    ),
)

# The demo subtask asks for a skill ("security") no agent on either roster holds. Jev is still
# asked to score two agents against it, to show that a confident answer from Jev about a subtask
# nobody is capable of still cannot result in an assignment: Python's capability filter runs
# before any score is looked at.
DEMO_SUBTASK = _subtask(
    "d1-security-review",
    "security",
    1,
    (),
    "Review the new integration for a security vulnerability before it ships.",
)

_ALL_SUBTASKS = VALIDATION_SUBTASKS + TEST_SUBTASKS + (DEMO_SUBTASK,)
_SKILL_BY_SUBTASK = {s.id: s.required_skill for s in _ALL_SUBTASKS}


def agents_by_id(agents) -> dict:
    return {a.id: a for a in agents}


def subtasks_by_id(subtasks) -> dict:
    return {s.id: s for s in subtasks}


# --------------------------------------------------------------------------------------------
# The question
# --------------------------------------------------------------------------------------------


def build_state(fields: dict[str, Any]) -> dict[str, str]:
    """The state Jev sees for one (agent, subtask) pair: the agent's plain-text track record and
    the subtask's plain-text description, nothing else. ``fields`` also carries the scenario,
    agent id and subtask id; Python keeps those and attaches them to the outcome, so they never
    pass through the model."""
    return {
        "agent_profile": fields["agent_profile"],
        "subtask_description": fields["subtask_description"],
    }


def build_questions() -> dict[str, Score]:
    """The one question asked about every (agent, subtask) pair. Levels come from
    ``SUITABILITY_LEVELS``; capability, dependency and budget are never mentioned here, because
    Jev is never asked to judge them -- Python already knows them from structured data."""
    return {
        "suitability": Score(
            instructions=(
                "How suitable is this agent for this subtask, based only on the agent's track "
                "record and what the subtask needs?"
            ),
            criteria=list(SUITABILITY_LEVELS),
        )
    }


# --------------------------------------------------------------------------------------------
# The deterministic scheduler
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """What the scheduler decided for one subtask: the outcome, the reason, which agent (if
    any) was assigned, and the confidence of the agent that was actually compared to the gate
    (``None`` when no agent was ever eligible to compare)."""

    subtask_id: str
    outcome: str
    reason: str
    agent_id: Any
    confidence: Any


@dataclass(frozen=True)
class ScheduleResult:
    """Every subtask's ``Decision``, in the order they were processed, plus the budget and the
    simulated action log and review queue that produced them."""

    decisions: tuple
    budget: Budget
    action_log: ActionLog
    review_queue: ReviewQueue

    def assignment(self) -> dict:
        """``{subtask_id: agent_id}`` for every subtask that was actually assigned."""
        return {d.subtask_id: d.agent_id for d in self.decisions if d.outcome == ASSIGNED}

    def by_id(self) -> dict:
        """``{subtask_id: Decision}``."""
        return {d.subtask_id: d for d in self.decisions}


def topological_order(subtasks) -> list:
    """Kahn's algorithm, ties broken by subtask id: the processing order the scheduler uses, so
    a subtask is only ever attempted after everything it depends on has been attempted.

    Raises ``ValueError`` on a dependency cycle or a dependency naming a subtask not present.
    """
    by_id = subtasks_by_id(subtasks)
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in by_id:
                raise ValueError(f"{s.id} depends on unknown subtask {dep!r}")
    remaining = {s.id: set(s.depends_on) for s in subtasks}
    order = []
    while remaining:
        ready = sorted(sid for sid, deps in remaining.items() if not deps)
        if not ready:
            raise ValueError(f"dependency cycle among {sorted(remaining)}")
        for sid in ready:
            order.append(by_id[sid])
            del remaining[sid]
        for deps in remaining.values():
            deps.difference_update(ready)
    return order


def _eligible(agents, subtask, budget, enforce_capability, enforce_budget):
    """Agents still allowed to take ``subtask`` right now: capable (unless disabled) and with
    enough budget left (unless disabled)."""
    out = []
    for agent in agents:
        if enforce_capability and subtask.required_skill not in agent.skills:
            continue
        if enforce_budget and not budget.can_spend(agent.id, subtask.cost):
            continue
        out.append(agent)
    return out


def _best(eligible, subtask_id, scores):
    """The eligible agent with the highest ``.score`` for this subtask; ties go to the lowest
    agent id. Returns ``None`` if ``eligible`` is empty."""
    if not eligible:
        return None
    return min(eligible, key=lambda a: (-scores[(a.id, subtask_id)].score, a.id))


def assign(
    agents,
    subtasks,
    scores: dict,
    confidence_threshold: float,
    *,
    enforce_capability: bool = True,
    enforce_dependency: bool = True,
    enforce_budget: bool = True,
) -> ScheduleResult:
    """Assign every subtask to at most one agent, deterministically.

    For each subtask, in dependency order: if ``enforce_dependency`` and a dependency was not
    itself assigned, the subtask goes to ``review`` ("a dependency was not assigned") without
    looking at any score. Otherwise the agent with the highest suitability score among those
    currently eligible (capable, per ``enforce_capability``, and with enough budget left, per
    ``enforce_budget``) is compared to ``confidence_threshold``: below it, the subtask goes to
    ``review`` ("confidence below the threshold"); at or above it, the subtask is ``assigned``
    and that agent's budget is spent. A subtask with no eligible agent at all goes to ``review``
    ("no eligible agent"), with no agent and no confidence to report.

    The three ``enforce_*`` flags exist for exactly one purpose: proving, by removing one guard
    at a time and nothing else, that the invariant it protects can actually be violated without
    it (see ``tests/test_constraints.py``). The real scheduler Jev's answers feed into (the
    notebook and the fixtures below) never calls this with any of them set to ``False``.

    ``scores`` maps ``(agent_id, subtask_id)`` to an answer with ``.score`` and ``.confidence``
    (a stored ``ScoreAnswer``, or anything with those two attributes). Every pair this function
    ever needs to compare must have an entry; a missing one raises ``KeyError`` naming the pair.
    """
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError(f"confidence_threshold must be in [0, 1], got {confidence_threshold!r}")
    order = topological_order(subtasks)
    budget = Budget(**{a.id: a.capacity for a in agents})
    action_log = ActionLog()
    review_queue = ReviewQueue()
    decisions = []
    assigned_ids: set = set()
    for subtask in order:
        if enforce_dependency and any(dep not in assigned_ids for dep in subtask.depends_on):
            decisions.append(Decision(subtask.id, REVIEW, DEPENDENCY_NOT_ASSIGNED, None, None))
            review_queue.submit(
                {"subtask": subtask.id}, DEPENDENCY_NOT_ASSIGNED, step=len(decisions)
            )
            continue
        eligible = _eligible(agents, subtask, budget, enforce_capability, enforce_budget)
        best = _best(eligible, subtask.id, scores)
        if best is None:
            decisions.append(Decision(subtask.id, REVIEW, NO_ELIGIBLE_AGENT, None, None))
            review_queue.submit({"subtask": subtask.id}, NO_ELIGIBLE_AGENT, step=len(decisions))
            continue
        answer = scores[(best.id, subtask.id)]
        if answer.confidence < confidence_threshold:
            decisions.append(
                Decision(subtask.id, REVIEW, BELOW_CONFIDENCE_THRESHOLD, best.id, answer.confidence)
            )
            review_queue.submit(
                {"subtask": subtask.id, "would_be_agent": best.id},
                BELOW_CONFIDENCE_THRESHOLD,
                answer=answer,
                step=len(decisions),
            )
            continue
        # When enforce_budget is False, _eligible already stopped checking can_spend, so best
        # may not actually have room; spend only what the real Budget object can accept without
        # raising, so the mutation (meant to show the invariant breaks) does not itself crash.
        if enforce_budget or budget.can_spend(best.id, subtask.cost):
            budget.spend(best.id, subtask.cost)
        assigned_ids.add(subtask.id)
        decisions.append(
            Decision(
                subtask.id, ASSIGNED, "highest confident suitability", best.id, answer.confidence
            )
        )
        action_log.record(
            "assign", {"subtask": subtask.id, "agent": best.id}, answer=answer, rule="assign"
        )
    return ScheduleResult(tuple(decisions), budget, action_log, review_queue)


def assign_by_capacity(agents, subtasks) -> dict:
    """A zero-request baseline scheduler: never asks Jev anything.

    For each subtask, in the same dependency order :func:`assign` uses, pick the capable agent
    (structured skill match) with the most budget remaining, ties broken by the lowest agent
    id; spend that budget. Capability and budget are still enforced exactly as in :func:`assign`
    (there is no model answer to gate on, so there is no confidence gate and no dependency
    check: every subtask is attempted, and this function makes no claim about whether an
    earlier subtask's assignment was itself a good one). Returns ``{subtask_id: agent_id or
    None}``; ``None`` means no agent was capable and had budget left.
    """
    budget = Budget(**{a.id: a.capacity for a in agents})
    out = {}
    for subtask in topological_order(subtasks):
        eligible = [
            a
            for a in agents
            if subtask.required_skill in a.skills and budget.can_spend(a.id, subtask.cost)
        ]
        if not eligible:
            out[subtask.id] = None
            continue
        best = min(eligible, key=lambda a: (-budget.remaining(a.id), a.id))
        budget.spend(best.id, subtask.cost)
        out[subtask.id] = best.id
    return out


def gold_best_agent(subtask_id: str, agents, gold_levels: dict):
    """The capable agent with the highest gold suitability level for ``subtask_id``; ties go to
    the lowest agent id. ``gold_levels`` maps ``(agent_id, subtask_id)`` to the gold level
    (0-4). This is Python arithmetic over the labels; it never asks Jev anything and is used
    only for evaluation, never by :func:`assign`.

    Returns ``None`` if no agent in ``agents`` is capable of ``subtask_id``.
    """
    skill = _SKILL_BY_SUBTASK[subtask_id]
    capable = [a for a in agents if skill in a.skills]
    if not capable:
        return None
    return min(capable, key=lambda a: (-gold_levels[(a.id, subtask_id)], a.id)).id
