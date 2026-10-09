# Simulation and state primitives

Shared building blocks for recipes that keep state or run a loop. Import them from
`jev_cookbook.simulation` (they are not re-exported from the package root):

```python
from jev_cookbook.simulation import (
    ActionLog,
    Budget,
    ReviewQueue,
    Simulator,
    Store,
    ToyGrid,
    Transactor,
)
```

Everything is plain Python with the standard library. Nothing touches the network, a key, or
global randomness, and actions are simulated: they are recorded, never executed. Every record
is plain JSON, so `to_dicts()` output can be displayed in a notebook as it is. This is the
"Python owns every side effect" rule of `CONTRIBUTING.md`, made reusable. Nothing here says
anything about how Jev performs.

## Simulator

`Simulator(seed=0)` is an abstract base with `reset(seed=None)`, `observe()`,
`legal_actions()`, `step(action)`, `replay(log, seed=None)`, `snapshot()`, `trajectory()`,
the `log` (a list of `StepRecord(step, observation, action, outcome, done)`) and the
properties `done` and `steps`. A subclass fills in `_reset(rng)`, `_observe()`,
`_legal_actions()`, `_apply(action, rng)`, `_snapshot()` and optionally `_is_done()`.

- Randomness comes only from the `random.Random(seed)` the base class passes in. Prefer
  `rng.random()`: the `random` module's own docs commit only `random.Random.random()` to
  producing the same sequence for the same seed across Python versions ([backends.md](backends.md),
  "Scripted backend"). `ToyGrid._reset` already calls `rng.randrange(n)` for its target cell, and
  that call stays — its output is pinned byte for byte by
  `test_golden_values_pin_cross_platform_streams` in `tests/test_simulation.py`, so a change to
  CPython's generator would be caught here, not merely assumed away — but a *new* `_reset` or
  `_apply` should derive any discrete choice from `rng.random()` (for example
  `int(rng.random() * n)`) rather than add another call to `rng.randrange`, `rng.choice`,
  `rng.shuffle` or anything else that draws from `_randbelow()`/`getrandbits()`: the `random`
  module names no cross-version guarantee for any of those, only for `random()` itself. Never call
  the global `random` or `numpy.random` functions in `_apply`.
- `step` rejects an action that is not in `legal_actions()` with `IllegalActionError`, and
  leaves the state and log unchanged. Python enumerates the legal actions, so a recipe can offer
  them as the fixed options of a `Choice` question and a model answer can never pick an
  action outside them.
- `replay(log)` resets to the seed, re-applies the logged actions, checks each observation and
  outcome against the log (`ReplayMismatch` otherwise), and returns the final `snapshot()`. The
  log is only valid for the seed that produced it.
- Actions, observations and outcomes are plain JSON (a string, a number, a list or a dict).

`ToyGrid(seed=0, size=6, slip=0.25)` is the small concrete example: walk a line to a target and
`grab` it, with a seeded chance that a move slips.

## ReviewQueue and ActionLog

```python
queue = ReviewQueue()
item_id = queue.submit({"ticket": 7}, "low confidence", answer=result["tone"], step=3)
queue.pending()  # [ReviewItem(...)]
queue.resolve(item_id, "kept as is")  # marks it resolved, deletes nothing
queue.to_dicts()

actions = ActionLog()
actions.record("move", {"to": "right"}, step=3, answer=result["tone"], rule="legal move")
actions.to_dicts()  # every entry has "executed": False
```

An `answer` is a typed answer object or its `to_dict()`, kept next to the reason so the notebook
can show what triggered the review. `ActionLog` never executes anything.

## Store

`Store` is a versioned key-value store. Version 0 is empty and every write adds one version.

```python
store = Store()
store.put("a", 1, writer="rule:seed", step=0)
store.put("a", 2, writer="model:tone", step=1, answer=result["tone"], rule="threshold 0.8")
store.delete("a", writer="rule:expire", step=2)  # a tombstone, not a removal
store.history("a")  # three WriteRecords, each with writer, step, answer, rule
store.at(2)  # {"a": 2}, the live state as of version 2
store.rollback(1)  # appends writes restoring version 1; history keeps everything
```

- Nothing is ever deleted: `delete` appends a tombstone, and `rollback(v)` appends writes
  (marked `rollback_to=v`) rather than truncating, so a rollback can itself be rolled back.
- `get(key, default)`, `key in store`, `keys()` and `snapshot()` see live keys only; `at(version)`
  gives any earlier live state; `writes()` and `to_dicts()` give the whole history.
- Values are plain JSON and are copied in and out. Every record an accessor returns
  (`history`, `writes`, `Simulator.log` and the record from `step`, `ReviewQueue.get` and
  `pending`, `Transactor.log` and the record from `run`) is a deep copy, so editing what you
  received never changes the history; to change history you must go through `put`, `delete` or
  `rollback`.

## Transactor

```python
def assign(view, p):
    view.put(p["ticket"], p["owner"])


def not_assigned(view, p):
    return None if p["ticket"] not in view else [f"{p['ticket']} is already assigned"]


tx = Transactor(Store())
tx.run(
    "assign",
    assign,
    params={"ticket": "t7", "owner": "ana"},
    writer="rule:assign",
    step=4,
    validate=not_assigned,
)
tx.run(
    "assign",
    assign,
    params={"ticket": "t7", "owner": "bo"},
    writer="rule:assign",
    step=5,
    validate=not_assigned,
    raise_on_failure=False,
)  # rolled back: t7 is already assigned
```

`run` stages the changes on a view (`view.put`, `view.delete`, `view.get`, `key in view`,
`view.snapshot()`), so `validate` (first), `apply` and `invariant` (after `apply`, on the staged
state) can fail without the store changing. A validator passes by returning `None` or `True` and fails by returning anything else (for
example a list of problems) or raising, so `p["x"] not in view or None` would never reject. On success the changes commit as one batch with
provenance. On failure the record has status `"rolled_back"` and the reason, and
`TransactionFailed` is raised (`raise_on_failure=False` returns the record instead). Both outcomes
are in `tx.log`. `replay_transactions(tx.log)` rebuilds a fresh store from the committed entries
alone, with identical history and provenance, so the log can be shown, saved and replayed.
Replay is strict and raises `ReplayMismatch` rather than build a different store: an unknown
status or operation, a malformed entry, or versions that do not follow on (for example a missing
middle entry) are all errors, and a bad entry leaves the store as it was before that entry.
`Transactor.run` checks every argument (name, writer, params, ...) before it stages anything.

## Budget

```python
budget = Budget(calls=12, retries=2, stop_when={"goal": lambda state: state["done"]})
budget.spend("calls")  # returns what remains; BudgetExceeded when it would pass the limit
budget.remaining("calls")  # 11
budget.check(state)  # raises StopConditionMet when a stop condition is true
```

A failed `spend` changes nothing, so used never passes the limit. `Budget` never reads a model
answer: the recipe decides what to spend and the limit holds whatever the model says.

## Running a closed loop offline with `ScriptedBackend`

In a closed loop the next request depends on earlier answers (the state it asks about is the
result of the previous action), so a fixed set of replay fixtures does not fit: you would have to
record every path the loop might take. Use `ScriptedBackend` instead. It answers any request
from a seeded function of `(state, questions, rng)`, so the same request gives the same answer on
every platform, and the whole loop is reproducible from `(simulator seed, backend seed)`. Scripted
answers are always `synthetic`: they check that the loop's plumbing and its rules work, and say
nothing about Jev. When a recipe needs real answers it records them separately (see
`docs/backends.md`).

The example below runs `ToyGrid` for up to 40 model calls. Each step asks one `Choice` question
whose options Python built from `legal_actions()` -- except when there is only one legal move
(the agent's starting cell, or either end of the line): a `Choice` needs at least two options
(see "Single-option Choice" in [docs/backends.md](backends.md)), so Python takes that one move
directly and spends no call. The script stands in for the model: it prefers
the move toward the target but is unsure about a third of the time. Python enforces the rules:
the call budget and the done condition stop the loop, an unsure answer goes to the review queue
and the step is skipped rather than acted on, the chosen action is only recorded and then
passed to the simulator, and a `Transactor` keeps a visited-cell register whose validator
refuses to record a cell twice (a rejected transaction is logged and changes nothing). Because a scripted answer depends only on the request, the request
carries an `attempt` counter, otherwise asking again about the same state would repeat the same
unsure answer.

```python
# recipe: example
from jev_cookbook import Choice, get_backend
from jev_cookbook.simulation import ActionLog, Budget, ReviewQueue, Store, ToyGrid, Transactor


def script(state, questions, rng):
    obs = state["observation"]
    legal = list(questions["move"].criteria)
    toward = "grab" if "grab" in legal else ("right" if obs["target"] > obs["position"] else "left")
    if rng.random() < 0.33:
        return {"move": {name: 1.0 for name in legal}}  # unsure: equal weight everywhere
    return {"move": {toward: 0.9, **{n: 0.1 / len(legal) for n in legal if n != toward}}}


def visit(view, p):
    view.put(f"cell:{p['cell']}", p["step"])


def not_visited(view, p):
    return None if f"cell:{p['cell']}" not in view else [f"cell {p['cell']} already visited"]


def run(sim_seed, backend_seed):
    sim = ToyGrid(seed=sim_seed)
    backend = get_backend(script=script, seed=backend_seed)
    budget = Budget(calls=40)
    queue, actions, tx = ReviewQueue(), ActionLog(), Transactor(Store())
    while not sim.done and budget.can_spend("calls"):
        legal = sim.legal_actions()
        if len(legal) == 1:
            # A Choice needs at least two options (docs/backends.md, "Single-option Choice"):
            # with only one legal move, Python already has the answer, so it takes the move
            # directly and never builds the question or spends a call.
            move = legal[0]
            actions.record(move, step=sim.steps, rule="only legal move")
        else:
            question = Choice(
                instructions="Which move gets the agent closer to the target?",
                criteria={name: None for name in legal},
            )
            request = {"observation": sim.observe(), "attempt": budget.used("calls")}
            budget.spend("calls")
            answer = backend.decide(request, {"move": question})["move"]
            if answer.confidence < 0.3:
                queue.submit(sim.observe(), "unsure which move", answer=answer, step=sim.steps)
                continue
            move = answer.choice
            actions.record(move, step=sim.steps, answer=answer, rule="chosen from legal")
        sim.step(move)
        cell = sim.observe()["position"]
        params = {"cell": cell, "step": sim.steps}
        tx.run(
            "visit",
            visit,
            params=params,
            writer="rule:visit",
            step=sim.steps,
            validate=not_visited,
            raise_on_failure=False,
        )
    return sim, budget, queue, actions, tx


sim, budget, queue, actions, tx = run(sim_seed=0, backend_seed=0)
print(sim.snapshot(), budget.to_dict()["calls"], len(queue), len(actions), len(tx.log))
```

The observation after each step goes into the next request, which is why replay fixtures cannot
cover this loop. Replaying `sim.trajectory()` on a fresh `ToyGrid(seed=0)` with `replay`
reproduces the final state without the backend at all.
