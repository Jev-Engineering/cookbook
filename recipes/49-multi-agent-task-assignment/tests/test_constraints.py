"""The central claim of this recipe: a test shows capability, dependency and budget constraints
hold for any scores.

A fuzz that runs many iterations and never checks whether any of them actually reached the
branch it claims to test is a reassuring NUMBER, not a reassuring result: a fuzz reports
differences constantly, on inputs that do not matter, so "300 cases ran" says nothing about
whether any of them reached the constraint under test. So every property test below does three
things, not one:

1. Holds the invariant for every one of 300 randomised score matrices over the fixed, real
   "sprint-1" scenario (``helpers.VALIDATION_AGENTS``/``VALIDATION_SUBTASKS``) -- the structure
   that varies is the scores, never the agents, subtasks, skills, costs or dependencies, which
   is the literal reading of "for any scores".
2. Counts the iterations where the constraint actually BINDS -- where enforcing it changed the
   outcome from what an unconstrained process would have done -- and asserts that count is
   non-zero, so "300 passed" cannot mean "300 untested".
3. Removes that one constraint's enforcement (``enforce_capability=False`` and so on -- the only
   reason those flags exist on ``assign``) and shows the SAME invariant check, run against the
   mutated scheduler, reports a violation: the mutation is proven to have taken effect first
   (``assert mutated_assignment != real_assignment``, per the "the mutation that never applied"
   fail-open shape), and the assertion that fires is named and its message is shown.
"""

import random
from pathlib import Path

import pytest

from jev_cookbook import Provenance, load_helpers
from jev_cookbook.answers import ScoreAnswer

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)

AGENTS = helpers.VALIDATION_AGENTS
SUBTASKS = helpers.VALIDATION_SUBTASKS
THRESHOLD = 0.0  # the fuzz is about capability/dependency/budget, not the confidence gate
N_TRIALS = 300


def _random_score_answer(rng: random.Random) -> ScoreAnswer:
    """A uniformly random point on the 5-level probability simplex, as a real ``ScoreAnswer``
    (so ``.score`` and ``.confidence`` come from the same published formulas the notebook's
    stored answers use) -- built from ``rng.random()`` only, the one call the ``random`` module
    documents as producing the same sequence on every platform and Python 3.10 to 3.14."""
    cuts = sorted(rng.random() for _ in range(4))
    raw = [cuts[0], cuts[1] - cuts[0], cuts[2] - cuts[1], cuts[3] - cuts[2], 1.0 - cuts[3]]
    # Round to 6 decimal places and push the rounding remainder onto the last level, so the
    # five numbers are exact binary floats that sum to exactly 1.0 (ScoreAnswer validates the
    # sum against math.fsum, which is deterministic but not forgiving of a 1e-16 drift from six
    # independent roundings). This is test-only randomisation, not a committed fixture, so there
    # is no cross-interpreter byte-identity requirement on it; the rounding is for ScoreAnswer's
    # own validation, not for that.
    rounded = [round(p, 6) for p in raw[:4]]
    total = 0.0
    for p in rounded:
        total += p
    rounded.append(round(1.0 - total, 6))
    return ScoreAnswer.from_probabilities(
        rounded, list(helpers.SUITABILITY_LEVELS), Provenance.synthetic()
    )


def _random_scores(rng: random.Random) -> dict:
    return {
        (agent.id, subtask.id): _random_score_answer(rng)
        for agent in AGENTS
        for subtask in SUBTASKS
    }


def _unconstrained_best(subtask_id: str, scores: dict):
    """The agent with the highest score for ``subtask_id`` among ALL agents, ignoring
    capability and budget entirely -- what a scheduler with no capability filter would pick."""
    return min(AGENTS, key=lambda a: (-scores[(a.id, subtask_id)].score, a.id)).id


def _capability_only_best(subtask_id: str, subtask, scores: dict):
    """The highest-scoring agent among those with the required skill, ignoring budget -- what a
    scheduler with no budget tracking would pick for this subtask in isolation."""
    capable = [a for a in AGENTS if subtask.required_skill in a.skills]
    return min(capable, key=lambda a: (-scores[(a.id, subtask_id)].score, a.id)).id


def _assert_capability_respected(result, subtasks, agents_by_id):
    sub_by_id = helpers.subtasks_by_id(subtasks)
    for subtask_id, agent_id in result.assignment().items():
        subtask = sub_by_id[subtask_id]
        assert subtask.required_skill in agents_by_id[agent_id].skills, (
            f"{subtask_id} was assigned to {agent_id}, who lacks {subtask.required_skill!r}"
        )


def _assert_budget_respected(result, subtasks, agents):
    """Recomputed independently from ``result.assignment()`` and each subtask's own cost --
    never from ``result.budget.used()``, which is the scheduler's OWN bookkeeping and would
    only tell us the scheduler agrees with itself."""
    sub_by_id = helpers.subtasks_by_id(subtasks)
    spent = {}
    for subtask_id, agent_id in result.assignment().items():
        spent[agent_id] = spent.get(agent_id, 0) + sub_by_id[subtask_id].cost
    for agent in agents:
        used = spent.get(agent.id, 0)
        assert used <= agent.capacity, (
            f"{agent.id} was used for {used} units against a capacity of {agent.capacity}"
        )


def _assert_dependency_respected(result, subtasks):
    assigned = result.assignment()
    for subtask in subtasks:
        if subtask.id in assigned:
            for dep in subtask.depends_on:
                assert dep in assigned, (
                    f"{subtask.id} was assigned even though its dependency {dep} was not"
                )


# ----------------------------------------------------------------------------------------------
# The fuzz: 300 random score matrices over the real scenario, every constraint checked on every
# one, every constraint's binding count measured and asserted non-zero.
# ----------------------------------------------------------------------------------------------


# A second, dedicated fixed scenario for measuring the dependency constraint specifically. In
# AGENTS/SUBTASKS above, resource scarcity always resolves at the deepest leaf in a dependency
# chain (every subtask upstream of it always has just enough supply, by this scenario's own
# numbers), so dependency enforcement never actually changes an outcome there -- true for any
# scores, and worth knowing, but it means a fuzz over AGENTS/SUBTASKS alone cannot witness
# dependency binding. This second scenario separates the two causes of "no eligible agent" a
# chain can have: "parent" competes with two siblings for a two-agent skill pool one wave
# earlier than it is itself processed, so it structurally never gets one (true regardless of
# scores: three code-needing subtasks and two code-capable agents cannot all succeed); "child"
# depends on "parent" but needs a different, never-scarce skill, so dependency enforcement is
# the ONLY thing standing between it and being assigned.
#
# "binds on every trial" is not 300 genuine explorations of the dependency branch: "parent"
# starves for any scores at all, so the only thing random scores can still vary here is which
# of "a1"/"a2" wins "s1" versus "s2" -- two possible outcomes, not 300. The main fuzz test below
# measures and prints that distinct-outcome count directly, rather than leaving "300 of 300"
# to be read as 300 independent trials of the thing being proven.
DEP_AGENTS = (
    helpers.Agent("a1", frozenset({"code"}), 1, ""),
    helpers.Agent("a2", frozenset({"code"}), 1, ""),
    helpers.Agent("a3", frozenset({"docs"}), 5, ""),
    helpers.Agent("a4", frozenset({"writing"}), 5, ""),
)
DEP_SUBTASKS = (
    helpers.Subtask("gate", "docs", 1, (), ""),
    helpers.Subtask("s1", "code", 1, (), ""),
    helpers.Subtask("s2", "code", 1, (), ""),
    helpers.Subtask("parent", "code", 1, ("gate",), ""),
    helpers.Subtask("child", "writing", 1, ("parent",), ""),
)


def test_constraints_hold_for_any_scores_and_each_one_actually_binds():
    rng = random.Random(20261014)
    agents_by_id = helpers.agents_by_id(AGENTS)
    dep_agents_by_id = helpers.agents_by_id(DEP_AGENTS)
    capability_binds = 0
    budget_binds = 0
    dependency_binds = 0
    distinct_dependency_outcomes = set()

    for _ in range(N_TRIALS):
        scores = _random_scores(rng)
        result = helpers.assign(AGENTS, SUBTASKS, scores, THRESHOLD)

        _assert_capability_respected(result, SUBTASKS, agents_by_id)
        _assert_budget_respected(result, SUBTASKS, AGENTS)
        _assert_dependency_respected(result, SUBTASKS)

        # Capability binds this trial if the fully unconstrained argmax, for some subtask,
        # names an agent who does not hold the required skill.
        if any(
            helpers.subtasks_by_id(SUBTASKS)[s.id].required_skill
            not in agents_by_id[_unconstrained_best(s.id, scores)].skills
            for s in SUBTASKS
        ):
            capability_binds += 1

        # Budget binds this trial if treating every subtask independently -- the best capable
        # agent for each one, with no tracking of what it was already given -- would ask some
        # agent for more total cost than its capacity allows.
        independent_cost = {}
        for s in SUBTASKS:
            winner = _capability_only_best(s.id, s, scores)
            independent_cost[winner] = independent_cost.get(winner, 0) + s.cost
        if any(independent_cost.get(a.id, 0) > a.capacity for a in AGENTS):
            budget_binds += 1

        # Dependency: same question (does disabling it change whether "child" is assigned?),
        # over the dedicated scenario above, with its own random scores drawn from the same rng.
        dep_scores = {
            (a.id, s.id): _random_score_answer(rng) for a in DEP_AGENTS for s in DEP_SUBTASKS
        }
        dep_real = helpers.assign(DEP_AGENTS, DEP_SUBTASKS, dep_scores, THRESHOLD)
        dep_mutated = helpers.assign(
            DEP_AGENTS, DEP_SUBTASKS, dep_scores, THRESHOLD, enforce_dependency=False
        )
        _assert_capability_respected(dep_real, DEP_SUBTASKS, dep_agents_by_id)
        _assert_budget_respected(dep_real, DEP_SUBTASKS, DEP_AGENTS)
        _assert_dependency_respected(dep_real, DEP_SUBTASKS)
        if "child" in dep_mutated.assignment() and "child" not in dep_real.assignment():
            dependency_binds += 1
        distinct_dependency_outcomes.add(
            (
                tuple(sorted(dep_real.assignment().items())),
                tuple(sorted(dep_mutated.assignment().items())),
            )
        )

    assert capability_binds > 0, (
        f"the capability constraint never bound across {N_TRIALS} random score matrices: "
        "the unconstrained argmax never once preferred an incapable agent"
    )
    assert budget_binds > 0, (
        f"the budget constraint never bound across {N_TRIALS} random score matrices: "
        "treating subtasks independently never once overloaded an agent's capacity"
    )
    assert dependency_binds > 0, (
        f"the dependency constraint never bound across {N_TRIALS} random score matrices: "
        "disabling it never once changed whether a dependent subtask was assigned"
    )
    print(
        f"binding counts of {N_TRIALS} trials: "
        f"capability {capability_binds}, budget {budget_binds}, dependency {dependency_binds}"
    )
    print(
        f"distinct (real, mutated) outcome pairs across those {N_TRIALS} dependency-scenario "
        f"trials: {len(distinct_dependency_outcomes)} -- 'binds on every trial' is this many "
        "distinct outcomes, not 300 independent explorations"
    )


# ----------------------------------------------------------------------------------------------
# Mutation proofs: remove one constraint's enforcement and show the invariant that constraint
# protects goes red -- naming the assertion and its message, not merely "something failed".
# ----------------------------------------------------------------------------------------------


def test_removing_capability_enforcement_reddens_the_capability_invariant():
    rng = random.Random(1)
    scores = _random_scores(rng)
    agents_by_id = helpers.agents_by_id(AGENTS)
    real = helpers.assign(AGENTS, SUBTASKS, scores, THRESHOLD)
    mutated = helpers.assign(AGENTS, SUBTASKS, scores, THRESHOLD, enforce_capability=False)
    assert mutated.assignment() != real.assignment(), (
        "the mutation did not take: disabling capability enforcement changed nothing, so this "
        "proves nothing about the guard"
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_capability_respected(mutated, SUBTASKS, agents_by_id)
    assert "lacks" in str(excinfo.value)
    # The real scheduler is unaffected: the same invariant holds on the unmutated call.
    _assert_capability_respected(real, SUBTASKS, agents_by_id)


def test_removing_budget_enforcement_reddens_the_budget_invariant():
    # A fixed, deterministic pool where every agent's stored score for every subtask it is
    # capable of is identical and maximal, so the mutated (budget-blind) scheduler assigns
    # every subtask it structurally can to agents regardless of how many they already hold --
    # overloading the single-skill agents deterministically rather than depending on luck.
    uniform_high = ScoreAnswer.from_probabilities(
        (0.01, 0.02, 0.03, 0.04, 0.90), list(helpers.SUITABILITY_LEVELS), Provenance.synthetic()
    )
    scores = {(a.id, s.id): uniform_high for a in AGENTS for s in SUBTASKS}
    real = helpers.assign(AGENTS, SUBTASKS, scores, THRESHOLD)
    mutated = helpers.assign(AGENTS, SUBTASKS, scores, THRESHOLD, enforce_budget=False)
    assert mutated.assignment() != real.assignment(), (
        "the mutation did not take: disabling budget enforcement changed nothing"
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_budget_respected(mutated, SUBTASKS, AGENTS)
    assert "against a capacity of" in str(excinfo.value)
    _assert_budget_respected(real, SUBTASKS, AGENTS)


def test_removing_dependency_enforcement_reddens_the_dependency_invariant():
    # A minimal, fully deterministic scenario, independent of any score: "blocked" has zero
    # budget, so it is never assigned regardless of what Jev answers; "downstream" depends on
    # it and has a capable agent with plenty of budget of its own, so dependency enforcement is
    # the only thing standing between it and being assigned.
    zero_budget_agent = helpers.Agent("solo", frozenset({"x"}), 0, "")
    free_agent = helpers.Agent("helper", frozenset({"y"}), 5, "")
    agents = (zero_budget_agent, free_agent)
    blocked = helpers.Subtask("blocked", "x", 1, (), "")
    downstream = helpers.Subtask("downstream", "y", 1, ("blocked",), "")
    subtasks = (blocked, downstream)
    high = ScoreAnswer.from_probabilities(
        (0.01, 0.02, 0.03, 0.04, 0.90), list(helpers.SUITABILITY_LEVELS), Provenance.synthetic()
    )
    scores = {(a.id, s.id): high for a in agents for s in subtasks}

    real = helpers.assign(agents, subtasks, scores, THRESHOLD)
    assert real.by_id()["blocked"].outcome == helpers.REVIEW  # zero budget: never assigned
    assert real.by_id()["downstream"].outcome == helpers.REVIEW
    assert real.by_id()["downstream"].reason == helpers.DEPENDENCY_NOT_ASSIGNED

    mutated = helpers.assign(agents, subtasks, scores, THRESHOLD, enforce_dependency=False)
    assert mutated.by_id() != real.by_id(), (
        "the mutation did not take: disabling dependency enforcement changed nothing"
    )
    assert mutated.assignment() != real.assignment()

    def _assert_this_scenarios_dependency_respected(result):
        assigned = result.assignment()
        if downstream.id in assigned:
            assert blocked.id in assigned, (
                f"{downstream.id} was assigned even though its dependency {blocked.id} was not"
            )

    with pytest.raises(AssertionError) as excinfo:
        _assert_this_scenarios_dependency_respected(mutated)
    assert "was not" in str(excinfo.value)
    _assert_this_scenarios_dependency_respected(real)
