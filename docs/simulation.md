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
    fill_review_queue,
    record_actions,
    route_outcomes,
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
  "Scripted backend"). `ToyGrid._reset` already calls `rng.randrange(1, n)` for its target cell, and
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

## Writing to the queue, the log and the store from a recipe

A recipe that uses a `ReviewQueue`, an `ActionLog`, a `Store`, a `Transactor` or a `Simulator`
performs simulated side effects, and two things must be true of them: a test can state what they
should have been without re-typing the code that produced them, and the committed notebook really
executes them (a notebook that quietly stopped doing so is fresh and wrong, and nothing else
notices). Both are handled by naming the code that performs the side effect, in one function in the
recipe's `helpers.py` that the notebook and the test both call, and by declaring the notebook's
calls to it (below). Which function shape fits depends on whether each outcome is final before
anything is written.

### Shape 1: batch fill, when every outcome is final before the first write

Recipes 02, 10, 24, 33, 34 and 38 are of this kind: the confidence gate has already produced an
outcome per example, and the queue or log is filled from the list of outcomes. Use the shared
helpers instead of a loop:

- `fill_review_queue(queue, outcomes, needs_review=, item=, reason=, answer=, step=, key=, exclude=)`
  submits every outcome that `needs_review` accepts.
- `record_actions(actions, outcomes, selects=, kind=, payload=, answer=, rule=, step=, key=, exclude=)`
  is the same for the action log.
- `route_outcomes(outcomes, route, queue=, actions=, key=, exclude=)` is the general form when one
  pass sends some outcomes to the queue and others to the log (the two helpers above are thin
  wrappers over it). `route(outcome)` returns `ToReview(item, reason, answer, step)`,
  `ToAction(kind, payload, answer, rule, step)` or `None`. Two `Routed` results can be added
  (`first + second`) when the same list is filled in several calls.

What they accept and return, decided once so that recipes do not decide it again:

- **Outcomes** are any iterable of whatever record the recipe already has (a dataclass, a dict, a
  tuple). The helper never inspects them; the callables you pass read what they need.
- **Order** is the iteration order of the outcomes and nothing else, for both the queue ids
  (0, 1, 2, ...) and the log `seq` values. To queue highest-first, sort before calling. To put two
  splits into one queue, call once per split, in the order the ids should run.
- **The reason** is the string the recipe's own outcome carries (`reason=lambda o: o.reason`), or
  one constant string. The helper invents none, so the exact-reason rule in [glossary](glossary.md)
  stays the recipe's.
- **A demo or held-out case** is removed with `exclude=lambda o: o.split == "demo"`. An excluded
  outcome never reaches the route function and is listed in `excluded_keys`, so the exclusion is
  visible in the result instead of being a silent `continue`. Use the same `exclude` to keep a
  second call from queueing what the first already queued.
- **The return value** is a `Routed`: one entry per outcome in input order, with `review_keys`,
  `review_ids`, `action_keys`, `action_seqs`, `skipped_keys` and `excluded_keys`. `key=` chooses
  what names an outcome (the example id; default its position) and must be unique in the call.
- **The callbacks must be free of side effects.** `route`, `key`, `exclude` and the callables of
  `fill_review_queue` / `record_actions` all run for every outcome before the first write, so they
  see the queue and log as they were before the call: a rule such as "queue at most three" or "skip
  what is already queued" that reads the queue is wrong in a batch, and anything else they do (a
  `Budget.spend`, a `Store.put`) is not undone if the pass fails. A decision that depends on earlier
  writes belongs in shape 2.
- **Mistakes fail before anything is written.** Predicates must return a real `bool`, a
  destination you did not supply is an error, and a write that still fails (an item that is not
  plain JSON) removes what the call had already added, so a queue is never half filled.

The convention: put the call in a named `helpers.py` function (`helpers.queue_reviews(queue,
results)`) so the item shape and the reason live in one place; the notebook calls it and does not
loop over `queue.submit` itself; the recipe's test calls the same function on fixture outcomes and
states the expected ids, count, order and split membership as **literals** typed from the
fixtures, plus `queue.to_dicts()` (ids, reasons, items) as literals.

```python
# recipe: fill-example
from dataclasses import dataclass

from jev_cookbook.simulation import ReviewQueue, fill_review_queue


@dataclass(frozen=True)
class Result:
    id: str
    split: str
    outcome: str
    reason: str


def queue_reviews(queue, results):
    """The recipe's helper: what is queued, and why, in one place."""
    return fill_review_queue(
        queue,
        results,
        needs_review=lambda r: r.outcome == "review",
        item=lambda r: {"ticket_id": r.id, "split": r.split},
        reason=lambda r: r.reason,
        key=lambda r: r.id,
        exclude=lambda r: r.split == "demo",
    )


validation = [
    Result("v1", "validation", "accepted", "confident"),
    Result("v2", "validation", "review", "confidence below the threshold"),
    Result("v3", "validation", "review", "confidence below the threshold"),
]
test = [
    Result("d1", "demo", "review", "confidence below the threshold"),
    Result("t1", "test", "accepted", "confident"),
    Result("t2", "test", "review", "confidence below the threshold"),
]

# The notebook cell: one queue, one call per split.
queue = ReviewQueue()
validation_fill = queue_reviews(queue, validation)
test_fill = queue_reviews(queue, test)

# The recipe's test: the expected values are typed in, not derived from the helper.
assert validation_fill.review_keys == ("v2", "v3")
assert test_fill.review_keys == ("t2",)
assert test_fill.review_ids == (2,)
assert test_fill.excluded_keys == ("d1",)
assert [(i["id"], i["item"]["ticket_id"]) for i in queue.to_dicts()] == [
    (0, "v2"),
    (1, "v3"),
    (2, "t2"),
]
print(len(queue), "queued:", [i["item"]["ticket_id"] for i in queue.to_dicts()])
```

### Shape 2: decide-and-apply, when the destination depends on state or on a write's result

Recipes 18, 19, 22, 27, 29, 30, 43, 45, 48 and 49 do not have a list of final outcomes. Each answer
is gated, and then, depending on state that earlier answers changed (a budget that ran out, a
register that already holds the key, an agent whose capacity is used) or on the result of the write
itself (a transaction the validator rejected), it goes to the queue, the log or the store, and the
function returns the recipe's own outcome record. That is the sanctioned form for stateful,
step-dependent recipes, and recipes 57 to 60 (a transactional graph update, interlocks with a
separate controller, game steps, factory steps) are expected to be of this kind. Do not force them
into shape 1: the shared helpers cannot see a write's result and run before any write.

The convention is the same, with the function holding the writes: one named function in
`helpers.py` (`helpers.decide(...)`, `helpers.classify(...)`, `helpers.reconcile(...)`) takes the
answer and the sinks (`queue=`, `actions=`, `store=` or a `Transactor`), writes with the primitives
directly (`queue.submit`, `actions.record`, `store.put`, `tx.run`, or `route_outcomes([outcome],
...)` for the queue and log part), and returns the outcome. The notebook calls it for every example
or step; it does not repeat the branching inline.

The test rule: call the function on fixture answers, in the order the notebook does, and state the
expected `queue.to_dicts()`, `actions.to_dicts()`, `store.history(key)`, `tx.log` or
`sim.trajectory()` as literals typed from the fixtures. Include the cases where the destination
changes with state (the second ticket for a full owner, the retry after the budget is spent). Do
not compute the expectation by calling the function or by re-typing its branches.

```python
# recipe: decide-example
from jev_cookbook.simulation import ActionLog, ReviewQueue, Store


def assign(ticket, owner, confidence, threshold, *, store, queue, actions):
    """Gate one answer, then act on state the earlier tickets left behind; return the outcome."""
    if confidence < threshold:
        queue.submit({"ticket": ticket}, "confidence below the threshold")
        return "review"
    if f"owner:{owner}" in store:
        queue.submit({"ticket": ticket, "owner": owner}, "owner already has a ticket")
        return "review"
    store.put(f"owner:{owner}", ticket, writer="rule:assign")
    actions.record("assign", {"ticket": ticket, "owner": owner}, rule="owner free")
    return "assigned"


# The notebook cell: one call per answer, in order.
store, queue, actions = Store(), ReviewQueue(), ActionLog()
answers = [("t1", "ana", 0.9), ("t2", "ana", 0.9), ("t3", "bo", 0.4), ("t4", "bo", 0.8)]
outcomes = [assign(t, o, c, 0.5, store=store, queue=queue, actions=actions) for t, o, c in answers]

# The recipe's test: literals typed from the fixtures, including the state-dependent case (t2).
assert outcomes == ["assigned", "review", "review", "assigned"]
assert [(i["id"], i["item"]["ticket"], i["reason"]) for i in queue.to_dicts()] == [
    (0, "t2", "owner already has a ticket"),
    (1, "t3", "confidence below the threshold"),
]
assert [a["payload"]["ticket"] for a in actions.to_dicts()] == ["t1", "t4"]
assert store.snapshot() == {"owner:ana": "t1", "owner:bo": "t4"}
print(outcomes)
```

### Other primitives

`Store.put`, `Store.delete`, `Transactor.run` and `Simulator.step` are already single calls that
return the record they wrote, and the loops that drive them differ by recipe (a transaction's
validator, a write's writer and step, a policy choosing the next action), so there is no shared
loop to extract and a wrapper would only hide the argument that matters. They follow shape 2: the
loop lives in one named function (or a `Simulator` subclass whose `_apply` performs the effect) in
`helpers.py`, the notebook calls it, the test calls it and pins `store.history(...)`, `tx.log` or
`sim.trajectory()` as literals.

### Declaring the side effect, and what the recipe guard enforces

A recipe that has a simulated side effect says so in `recipes/NN-slug/side_effects.json`, which its
own pull request writes and its reviewer reads:

```json
{"schema": 1, "sites": {"helpers.submit_reviews": 2}}
```

```json
{"schema": 1, "none": "returns typed outcomes only; nothing is queued, logged or stored"}
```

`sites` maps each key to the exact number of places in the notebook's executable code that call it
(a loop body is one place, and so is a function body the notebook calls). The keys are
`helpers.<function>` for a side-effect function of `helpers.py`, `helpers.<Class>.<method>` for a
side-effect method of a `helpers.py` class (a `Simulator` subclass counts through `step`),
`<Sink>.<method>` for a call on a `ReviewQueue`, `ActionLog`, `Store`, `Transactor`, `ToyGrid` or
notebook-defined `Simulator` subclass the notebook built (`ReviewQueue.submit`, `ToyGrid.step`), and
the names of the shared helpers above. A simulator you get from a factory counts under the class the
factory returns: after `sim = helpers.new_game(seed)`, where `new_game` returns `Game(...)` (a
`Simulator` subclass in `helpers.py`), the calls on `sim` are `helpers.Game.step`. The same holds
for a classmethod, a staticmethod or a function the notebook defines, as long as every `return` of
the factory builds the same one thing: a sink, a simulator or a `helpers.py` class.

`helpers.py` functions that write to module-level state (`STATE[key] = value`, `STATE.append(...)`,
`QUEUE.submit(...)` on a module-level object, or a `global` rebinding; the name may be bound
anywhere in the module's own scope, also inside `try:` or `if:`) are side-effect functions and are
declared under `helpers.<function>`. A write to a module-level container can also be listed under
`not_side_effects` with a reason, like a class's own container (below); a mutating method of a
sink on a module-level object (`QUEUE.submit(...)`) cannot.

An optional `"not_side_effects"` object lists `helpers.py` functions or classes that only keep
bookkeeping (a cache, a request counter) and that the analysis would otherwise take for a side
effect, each with the reason:

```json
{"schema": 1, "none": "returns typed outcomes only", "not_side_effects": {"MemoisingBackend": "keeps its own dict of answers and a call counter; writes to no queue, log, store or simulator"}}
```

It is an exemption for bookkeeping only, and the guard refuses an entry that is not: a name whose
code writes to a `ReviewQueue`, `ActionLog`, `Store`, `Transactor` or `Simulator` (a call of
`submit`, `record`, `put`, `run`, `step` and the other mutating methods on a parameter, a local,
`self` or a module-level object, a shared fill helper, directly or through other `helpers.py`
code), or that subclasses `Simulator` or `ToyGrid`, is a side effect and is declared under `sites`.
A reason is required for every entry. What an entry can still hide is a write to a container the
class or function keeps for itself (`self.memo[key] = value`) or to module-level state
(`CACHE[key] = value`, `LOG.append(x)`), because the guard cannot tell a cache from a graph held in
a dict, so a reviewer reads every `not_side_effects` entry and its reason as a claim.

The guard (`simulated_side_effect_invoked` in `tests/test_recipe_guard.py`) parses the notebook,
walks only code that can run, and compares what it finds with the declaration in both directions:
fewer calls than declared is the case where someone deleted the side effect and re-executed the
notebook, and more calls than declared is an undeclared side effect. It fails, rather than skips,
when a recipe that has a side effect or needs a simulator has no declaration, when a
`needs: simulator` recipe declares none or detects nothing, when `helpers.py` defines side-effect
code the notebook never uses, when the notebook builds a sink or simulator (directly, or through a
factory that only constructs it) and never mutates it, and when a code cell does not parse. The one
exemption from that last rule is a name bound to the result of a side-effect function that returns
the object (`sim = helpers.run_episode(...)`, or a function the notebook defines whose body already
executed a side effect), which may already have done the work and is only read. It cannot see a call made through an alias (`f =
helpers.submit_reviews; f(...)`, which makes the count smaller and so fails), through a container of
callables, or through an attribute chain on an object it does not know, and it assumes a condition
it cannot evaluate is taken. It checks that the side effect is executed, not that you used the
shared batch helpers: a hand-rolled loop in a named function is accepted, and the convention above
is what a reviewer asks for.

Known limits, which a reviewer covers by reading `side_effects.json` against the notebook:

- A write the analysis cannot see is not counted: an assignment into a container passed as a
  parameter (`def f(graph, k, v): graph[k] = v`) or reached through a local alias
  (`g = GRAPH; g[k] = v`), `setattr`, `globals()`, a write to a file or to the environment (which
  is not a simulated side effect). Module-level state written under its own name inside a
  `helpers.py` function is seen; the same state reached through an alias is not.
- A recipe that needs a simulator must declare and execute at least one side effect; the guard does
  not know which declared key is the one the recipe is about. The reviewer checks that the declared
  sites include the trajectory, transaction or actuation the recipe is built around (the `step`
  loop, the `Transactor.run`, the controller's actuation), and that the counts match the number of
  runs and splits the notebook describes (a baseline and a Jev run, validation and test).
- A `not_side_effects` entry can name a class or a function that keeps its real state in a
  container of its own or in module-level state (`GRAPH[key] = value` in an exempted
  `apply_update`): the exemption then passes with the write loop deleted. The entry and its reason
  are in the pull request's diff; a reviewer reads them, and does not accept an exemption for the
  function or class that applies the trajectory, transaction or actuation the recipe is about.
- A name bound to the result of a `helpers.py` side-effect function that returns the object
  (`sim = helpers.run_episode(...)`) is exempt from "builds a sink or simulator and never mutates
  it", because the function may already have done the work. If that function does not in fact
  step the simulator it returns, the guard does not notice that the notebook never steps it; the
  declared sites are what bind it. A factory that only constructs (`return ToyGrid(...)`) is not
  exempt.

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
