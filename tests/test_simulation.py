"""Tests for jev_cookbook.simulation, including property-style invariant checks.

The property tests draw many cases from fixed seeds (``random.Random``) so every run, on every
platform and Python version, checks the same cases. ``hypothesis`` is not a dependency.
"""

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from jev_cookbook import ChoiceAnswer, Noul, Provenance, get_backend
from jev_cookbook.simulation import (
    ActionLog,
    Budget,
    BudgetExceeded,
    IllegalActionError,
    ReplayMismatch,
    ReviewQueue,
    SimulationError,
    Simulator,
    StepRecord,
    StopConditionMet,
    Store,
    StoreError,
    ToAction,
    ToReview,
    ToyGrid,
    TransactionFailed,
    Transactor,
    fill_review_queue,
    record_actions,
    replay_transactions,
    route_outcomes,
)

DOCS = Path(__file__).resolve().parent.parent / "docs" / "simulation.md"


def _answer() -> ChoiceAnswer:
    """A small synthetic typed answer to attach as provenance."""
    return ChoiceAnswer.from_probabilities({"a": 0.2, "b": 0.8}, Provenance.synthetic())


def _random_episode(seed: int, policy_seed: int, max_steps: int = 60) -> ToyGrid:
    """Run a ToyGrid with a policy that picks random legal actions from its own rng."""
    sim = ToyGrid(seed=seed)
    policy = random.Random(policy_seed)
    while not sim.done and sim.steps < max_steps:
        legal = sim.legal_actions()
        sim.step(legal[policy.randrange(len(legal))])
    return sim


# --------------------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------------------


def test_toygrid_exercises_every_method() -> None:
    sim = ToyGrid(seed=5, size=4, slip=0.0)
    first = sim.observe()
    assert first == {"position": 0, "target": sim.target, "size": 4}
    assert sim.legal_actions() == ["right"]
    record = sim.step("right")
    assert record == StepRecord(0, first, "right", "moved", False)
    assert sim.observe()["position"] == 1 and sim.steps == 1 and not sim.done
    while sim.observe()["position"] < sim.target:
        sim.step("right")
    assert "grab" in sim.legal_actions()
    last = sim.step("grab")
    assert last.done and sim.done and sim.legal_actions() == []
    assert sim.snapshot()["grabbed"] is True
    assert [r["step"] for r in sim.trajectory()] == list(range(sim.steps))
    json.dumps(sim.trajectory())
    assert sim.reset() == first and sim.log == [] and not sim.done


def test_illegal_action_changes_nothing() -> None:
    sim = ToyGrid(seed=1)
    before, log = sim.snapshot(), list(sim.log)
    for action in ("left", "grab", "jump", 3, ["right"]):
        with pytest.raises(IllegalActionError):
            sim.step(action)
    assert sim.snapshot() == before and sim.log == log
    sim = _random_episode(2, 2, 500)
    assert sim.done
    with pytest.raises(IllegalActionError, match="done"):
        sim.step("left")


def test_non_plain_action_and_bad_seed_rejected() -> None:
    sim = ToyGrid()
    with pytest.raises(TypeError):
        sim.step(object())
    with pytest.raises(TypeError):
        sim.reset(1.5)
    with pytest.raises(TypeError):
        ToyGrid(seed="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ToyGrid(size=1)
    with pytest.raises(ValueError):
        ToyGrid(slip=2.0)


def test_simulator_is_abstract() -> None:
    with pytest.raises(TypeError):
        Simulator()  # type: ignore[abstract]


def test_same_seed_same_trajectory_property() -> None:
    for seed in range(150):
        a = _random_episode(seed, seed + 1000)
        b = _random_episode(seed, seed + 1000)
        assert a.trajectory() == b.trajectory()
        assert a.snapshot() == b.snapshot()
        # Another simulator instance, created after heavy use of global randomness, agrees.
        random.seed(seed)
        c = _random_episode(seed, seed + 1000)
        assert c.trajectory() == a.trajectory()


def test_different_seeds_are_not_all_the_same() -> None:
    targets = {ToyGrid(seed=s).target for s in range(40)}
    assert len(targets) > 1


def test_replay_reproduces_final_state_property() -> None:
    for seed in range(150):
        original = _random_episode(seed, seed * 7 + 3)
        fresh = ToyGrid(seed=seed + 999)  # replay resets to the seed it is given
        final = fresh.replay(original.log, seed=seed)
        assert final == original.snapshot()
        assert fresh.log == original.log
        # The plain-dict form (what a notebook stores) replays too.
        again = ToyGrid(seed=seed).replay(json.loads(json.dumps(original.trajectory())))
        assert again == original.snapshot()


def test_replay_detects_a_different_seed_or_edited_log() -> None:
    original = _random_episode(4, 4)
    wrong_seed = next(s for s in range(5, 100) if ToyGrid(seed=s).target != ToyGrid(seed=4).target)
    with pytest.raises(ReplayMismatch):
        ToyGrid().replay(original.log, seed=wrong_seed)
    edited = original.trajectory()
    edited[0]["outcome"] = "grabbed" if edited[0]["outcome"] != "grabbed" else "moved"
    with pytest.raises(ReplayMismatch):
        ToyGrid().replay(edited, seed=4)
    with pytest.raises(ValueError):
        StepRecord.from_dict({"step": 0})


def test_golden_values_pin_cross_platform_streams() -> None:
    """Literals computed once; a platform or Python version that differs would fail here."""
    assert [ToyGrid(seed=s).target for s in range(10)] == [4, 2, 1, 2, 2, 5, 5, 3, 2, 4]
    sim = ToyGrid(seed=0, slip=0.5)
    outcomes = []
    while not sim.done and sim.steps < 40:
        action = "grab" if "grab" in sim.legal_actions() else "right"
        outcomes.append(sim.step(action).outcome)
    assert outcomes == [
        "moved",
        "slipped",
        "slipped",
        "moved",
        "slipped",
        "moved",
        "slipped",
        "slipped",
        "moved",
        "grabbed",
    ]


# --------------------------------------------------------------------------------------
# ReviewQueue and ActionLog
# --------------------------------------------------------------------------------------


def test_review_queue_keeps_reason_and_typed_answer() -> None:
    queue = ReviewQueue()
    first = queue.submit({"ticket": "t1"}, "low confidence", answer=_answer(), step=2)
    second = queue.submit("plain text", "inconsistent", answer=_answer().to_dict())
    assert (first, second) == (0, 1) and len(queue) == 2
    item = queue.get(first)
    assert item.reason == "low confidence" and item.answer["choice"] == "b" and item.step == 2
    assert queue.get(second).answer == _answer().to_dict()
    queue.resolve(first, {"decision": "keep"})
    assert [i.id for i in queue.pending()] == [1]
    with pytest.raises(SimulationError):
        queue.resolve(first, "again")
    dicts = queue.to_dicts()
    assert dicts[0]["status"] == "resolved" and dicts[0]["resolution"] == {"decision": "keep"}
    assert json.loads(json.dumps(dicts)) == dicts and len(queue) == 2


def test_review_queue_validates_input() -> None:
    queue = ReviewQueue()
    with pytest.raises(ValueError):
        queue.submit("x", "")
    with pytest.raises(TypeError):
        queue.submit(object(), "r")
    with pytest.raises(TypeError):
        queue.submit("x", "r", answer=5)
    with pytest.raises(ValueError):
        queue.submit("x", "r", step=-1)
    with pytest.raises(StoreError):
        queue.get(0)
    assert len(queue) == 0


def test_action_log_records_and_never_executes() -> None:
    log = ActionLog()
    entry = log.record("send_email", {"to": "nobody@example.invalid"}, step=1, answer=_answer())
    log.record("move", rule="legal move")
    assert entry["executed"] is False and all(e["executed"] is False for e in log.to_dicts())
    assert [e["seq"] for e in log.to_dicts()] == [0, 1] and len(log) == 2
    assert [e["kind"] for e in log.by_kind("move")] == ["move"]
    entry["payload"]["to"] = "changed"  # a returned copy; the log is unaffected
    assert log.to_dicts()[0]["payload"]["to"] == "nobody@example.invalid"
    json.dumps(log.to_dicts())
    with pytest.raises(ValueError):
        log.record("")


# --------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------


def test_store_basics_history_at_rollback() -> None:
    store = Store()
    assert store.version == 0 and store.at(0) == {} and store.keys() == []
    store.put("a", 1, writer="rule:seed", step=0)
    store.put("a", 2, writer="model:x", step=1, answer=_answer(), rule="threshold")
    store.put("b", {"n": [1, 2]}, writer="rule:seed", step=1)
    store.delete("a", writer="rule:expire", step=2)
    assert store.version == 4 and "a" not in store and store.keys() == ["b"]
    assert store.get("a", None) is None
    with pytest.raises(StoreError):
        store.get("a")
    history = store.history("a")
    assert [(h.version, h.value, h.tombstone) for h in history] == [
        (1, 1, False),
        (2, 2, False),
        (4, None, True),
    ]
    assert history[1].writer == "model:x" and history[1].answer["choice"] == "b"
    assert history[1].rule == "threshold" and history[1].step == 1
    assert store.at(2) == {"a": 2} and store.at(3) == {"a": 2, "b": {"n": [1, 2]}}
    new = store.rollback(3)
    assert new == 5 and store.snapshot() == store.at(3) == {"a": 2, "b": {"n": [1, 2]}}
    assert store.history("a")[-1].rollback_to == 3
    assert [h.version for h in store.history("a")] == [1, 2, 4, 5]
    assert store.rollback(store.version) == 5  # nothing to restore, nothing appended
    json.dumps(store.to_dicts())
    for bad in (-1, 99, "1", True):
        with pytest.raises(StoreError):
            store.at(bad)  # type: ignore[arg-type]


def test_store_copies_values_and_validates() -> None:
    store = Store()
    value = {"list": [1]}
    store.put("k", value, writer="w")
    value["list"].append(2)
    got = store.get("k")
    got["list"].append(3)
    assert store.get("k") == {"list": [1]}
    with pytest.raises(TypeError):
        store.put("k", {1: 2}, writer="w")
    with pytest.raises(ValueError):
        store.put("k", float("nan"), writer="w")
    with pytest.raises(ValueError):
        store.put("", 1, writer="w")
    with pytest.raises(ValueError):
        store.put("k", 1, writer="")
    with pytest.raises(StoreError):
        store.delete("missing", writer="w")
    assert store.version == 1
    assert str(StoreError("no live key 'x'")) == "no live key 'x'"


def _vandalize(store: Store) -> None:
    """Edit every record the store hands out, as a careless caller might."""
    for record in store.writes() + [r for k in store.keys() for r in store.history(k)]:
        if isinstance(record.value, dict):
            record.value["vandal"] = 1
        elif isinstance(record.value, list):
            record.value.append("vandal")
        if record.answer is not None:
            record.answer["choice"] = "vandal"


def test_store_never_deletes_property() -> None:
    for seed in range(200):
        rng = random.Random(seed)
        store = Store()
        ever: dict[str, int] = {}
        keys = ["a", "b", "c"]
        previous = []
        for step in range(rng.randrange(1, 40)):
            op = rng.random()
            if op < 0.5:
                key = rng.choice(keys)
                value = {"n": [rng.randrange(100)]}
                store.put(key, value, writer="gen", step=step, answer=_answer())
                ever[key] = ever.get(key, 0) + 1
            elif op < 0.75 and store.keys():
                key = rng.choice(store.keys())
                store.delete(key, writer="gen", step=step)
                ever[key] += 1
            else:
                store.rollback(rng.randrange(store.version + 1), step=step)
                ever = {k: len(store.history(k)) for k in ever}
            snapshot = json.loads(json.dumps(store.to_dicts()))  # an independent copy
            assert snapshot[: len(previous)] == previous  # existing records never change
            previous = snapshot
            _vandalize(store)  # edits to returned records must not reach the store
            writes = store.writes()
            assert [w.version for w in writes] == list(range(1, len(writes) + 1))
            for key, count in ever.items():
                assert len(store.history(key)) >= count  # a key's history only grows


def test_store_rollback_restores_state_property() -> None:
    for seed in range(200):
        rng = random.Random(seed)
        store = Store()
        for step in range(rng.randrange(1, 30)):
            key = rng.choice("abcd")
            if rng.random() < 0.7 or key not in store:
                store.put(key, rng.randrange(10), writer="gen", step=step)
            else:
                store.delete(key, writer="gen", step=step)
        target = rng.randrange(store.version + 1)
        old_versions = {v: store.at(v) for v in range(store.version + 1)}
        store.rollback(target)
        assert store.snapshot() == old_versions[target]
        for v, snap in old_versions.items():  # the past is unchanged
            assert store.at(v) == snap
        store.rollback(store.version - 1)
        for v, snap in old_versions.items():
            assert store.at(v) == snap


# --------------------------------------------------------------------------------------
# Transactor
# --------------------------------------------------------------------------------------


def _transfer(view, p):
    view.put(p["src"], view.get(p["src"]) - p["amount"])
    view.put(p["dst"], view.get(p["dst"], 0) + p["amount"])


def _no_overdraft(view, p):
    return view.get(p["src"], 0) >= p["amount"] or [f"{p['src']} would go negative"]


def test_transaction_commits_with_provenance_and_rolls_back() -> None:
    tx = Transactor()
    tx.run("open", lambda v, p: v.put("acct:a", 10), writer="rule:open", step=0)
    record = tx.run(
        "move",
        _transfer,
        params={"src": "acct:a", "dst": "acct:b", "amount": 4},
        writer="rule:transfer",
        step=1,
        answer=_answer(),
        rule="amount within limit",
        validate=_no_overdraft,
    )
    assert record.committed and (record.version_before, record.version_after) == (1, 3)
    assert tx.store.snapshot() == {"acct:a": 6, "acct:b": 4}
    write = tx.store.history("acct:b")[0]
    assert (write.writer, write.step, write.rule) == ("rule:transfer", 1, "amount within limit")
    assert write.answer["choice"] == "b"
    version = tx.store.version
    with pytest.raises(TransactionFailed, match="would go negative") as err:
        tx.run(
            "move",
            _transfer,
            params={"src": "acct:a", "dst": "acct:b", "amount": 50},
            writer="rule:transfer",
            validate=_no_overdraft,
        )
    assert err.value.record.status == "rolled_back" and tx.store.version == version
    assert tx.log[-1] == err.value.record and tx.log[-1].ops == ()


def test_transaction_failures_in_every_phase_roll_back() -> None:
    tx = Transactor()
    tx.run("seed", lambda v, p: v.put("x", 1), writer="w")

    def half_then_boom(view, p):
        view.put("x", 2)
        view.put("y", 3)
        raise RuntimeError("boom")

    def always_false(view):
        return False

    before = tx.store.to_dicts()
    cases = [
        {"apply": half_then_boom},
        {"apply": lambda v, p: v.put("x", 9), "validate": lambda v, p: False},
        {"apply": lambda v, p: v.put("x", 9), "validate": lambda v, p: ["no"]},
        {"apply": lambda v, p: v.put("x", 9), "invariant": always_false},
        {"apply": lambda v, p: v.delete("nothing")},
        {"apply": lambda v, p: v.put("x", object())},
    ]
    for kwargs in cases:
        record = tx.run("t", writer="w", raise_on_failure=False, **kwargs)
        assert record.status == "rolled_back" and record.error
        assert tx.store.to_dicts() == before
    assert [r.index for r in tx.log] == list(range(len(tx.log)))
    with pytest.raises(TypeError):
        tx.run("t", lambda v, p: None, writer="w", params=object())
    assert len(tx.log) == 1 + len(cases)


def test_staged_view_reads_its_own_writes() -> None:
    tx = Transactor()
    tx.run("seed", lambda v, p: (v.put("a", 1), v.put("b", 2)), writer="w")

    def apply(view, p):
        view.put("a", 10)
        view.delete("b")
        assert view.get("a") == 10 and "b" not in view and view.get("b", "gone") == "gone"
        assert view.snapshot() == {"a": 10}
        with pytest.raises(StoreError):
            view.get("b")
        view.put("b", 3)

    assert tx.run("t", apply, writer="w").committed
    assert tx.store.snapshot() == {"a": 10, "b": 3}


def test_transaction_log_replays_to_same_store_property() -> None:
    for seed in range(150):
        rng = random.Random(seed)
        tx = Transactor()
        tx.run("open", lambda v, p: [v.put(f"acct:{i}", 20) for i in range(3)], writer="open")
        for step in range(rng.randrange(1, 25)):
            params = {
                "src": f"acct:{rng.randrange(3)}",
                "dst": f"acct:{rng.randrange(3)}",
                "amount": rng.randrange(1, 15),
            }
            snapshot = tx.store.to_dicts()
            record = tx.run(
                "move",
                _transfer,
                params=params,
                writer="gen",
                step=step,
                answer=_answer() if rng.random() < 0.3 else None,
                validate=_no_overdraft,
                invariant=lambda v: sum(v.snapshot().values()) == 60,
                raise_on_failure=False,
            )
            if not record.committed:
                assert tx.store.to_dicts() == snapshot  # rolled back: nothing changed
            assert sum(tx.store.snapshot().values()) == 60
        for form in (tx.log, json.loads(json.dumps(tx.to_dicts()))):
            rebuilt = replay_transactions(form)
            assert rebuilt.to_dicts() == tx.store.to_dicts()
            assert rebuilt.snapshot() == tx.store.snapshot()


# --------------------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------------------


def test_budget_basics() -> None:
    budget = Budget(calls=3, retries=0)
    assert budget.remaining("calls") == 3 and budget.limit("calls") == 3
    assert budget.spend("calls") == 2 and budget.spend("calls", 2) == 0
    assert budget.exhausted("calls") and budget.used("calls") == 3
    with pytest.raises(BudgetExceeded, match="calls"):
        budget.spend("calls")
    with pytest.raises(BudgetExceeded):
        budget.spend("retries")
    assert not budget.can_spend("retries") and budget.used("calls") == 3
    assert budget.to_dict()["calls"] == {"limit": 3, "used": 3, "remaining": 0}
    with pytest.raises(KeyError):
        budget.remaining("nope")
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            Budget(calls=3).spend("calls", bad)  # type: ignore[arg-type]
    for bad_limit in (-1, 1.5, True, "3"):
        with pytest.raises(ValueError):
            Budget(calls=bad_limit)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Budget()


def test_budget_stop_conditions() -> None:
    budget = Budget(calls=5, stop_when={"done": lambda s: s["done"], "big": lambda s: s["n"] > 9})
    budget.check({"done": False, "n": 1})
    assert budget.stop_reason({"done": False, "n": 10}) == "big"
    with pytest.raises(StopConditionMet, match="done"):
        budget.check({"done": True, "n": 1})
    assert Budget(stop_when={"x": lambda s: False}).stop_reason() is None


def test_budget_never_exceeded_property() -> None:
    for seed in range(300):
        rng = random.Random(seed)
        limits = {"calls": rng.randrange(0, 15), "retries": rng.randrange(0, 5)}
        budget = Budget(**limits)
        for _ in range(60):
            name = rng.choice(sorted(limits))
            amount = rng.randrange(1, 6)
            before = budget.to_dict()
            try:
                budget.spend(name, amount)
            except BudgetExceeded:
                assert amount > before[name]["remaining"]
                assert budget.to_dict() == before  # a refused spend changes nothing
            for key, limit in limits.items():
                assert 0 <= budget.used(key) <= limit
                assert budget.used(key) + budget.remaining(key) == limit


def test_budget_holds_whatever_the_model_answers() -> None:
    """A model that always says 'retry' still cannot get past the retry limit."""

    def always_retry(state, questions, rng):
        return {"retry": 1.0}

    for seed in range(20):
        backend = get_backend(script=always_retry, seed=seed)
        budget = Budget(retries=3)
        asked = 0
        while True:
            answer = backend.decide({"asked": asked}, {"retry": Noul(instructions="Retry?")})
            if answer["retry"].noul > 0.5 and budget.can_spend("retries"):
                budget.spend("retries")
                asked += 1
            else:
                break
        assert asked == 3 and budget.exhausted("retries")


# --------------------------------------------------------------------------------------
# Documentation example
# --------------------------------------------------------------------------------------


def test_docs_example_runs_end_to_end(capsys: pytest.CaptureFixture[str]) -> None:
    text = DOCS.read_text(encoding="utf-8")
    block = re.search(r"```python\n# recipe: example\n(.*?)\n```", text, re.S).group(1)
    namespace: dict = {}
    exec(compile(block, "docs/simulation.md", "exec"), namespace)
    printed = capsys.readouterr().out
    sim, budget, queue, actions, tx = (
        namespace["sim"],
        namespace["budget"],
        namespace["queue"],
        namespace["actions"],
        namespace["tx"],
    )
    assert sim.done and printed.startswith("{")
    # A step with only one legal move is decided by Python directly (no Choice, no call: a
    # Choice needs at least two options), so it is recorded with no answer and spends no
    # budget; every other acted-on step asks the backend and carries a typed answer.
    free_moves = [a for a in actions.to_dicts() if a["answer"] is None]
    assert free_moves, "the example should exercise its own single-legal-move short-circuit"
    assert budget.used("calls") <= 40
    assert budget.used("calls") == len(queue) + len(actions) - len(free_moves)
    assert all(a["rule"] == "only legal move" for a in free_moves)
    assert len(actions) == sim.steps and all(not a["executed"] for a in actions.to_dicts())
    # The review path is taken: unsure answers are queued, with their reason and typed answer.
    assert len(queue) > 0 and len(queue.pending()) == len(queue)
    assert all(i.reason == "unsure which move" for i in queue.pending())
    assert all(i.answer["confidence"] < 0.3 for i in queue.pending())
    # The transaction validator really rejects: a revisited cell is refused and changes nothing.
    rejected = [r for r in tx.log if r.status == "rolled_back"]
    committed = [r for r in tx.log if r.committed]
    assert rejected and committed
    assert all("already visited" in r.error and r.ops == () for r in rejected)
    assert len(tx.store.writes()) == len(committed) == len(tx.store.keys())
    assert replay_transactions(tx.log).to_dicts() == tx.store.to_dicts()
    # Same seeds, same run; and the trajectory replays without the backend.
    again = namespace["run"](0, 0)
    assert again[0].trajectory() == sim.trajectory()
    assert again[2].to_dicts() == queue.to_dicts()
    assert again[4].to_dicts() == tx.to_dicts()
    assert ToyGrid().replay(sim.trajectory(), seed=0) == sim.snapshot()
    assert namespace["run"](0, 1)[0].snapshot()["target"] == sim.snapshot()["target"]


# --------------------------------------------------------------------------------------
# Fix round 1: argument checks, returned records, strict replay
# --------------------------------------------------------------------------------------


def test_bad_arguments_write_nothing_and_log_nothing() -> None:
    tx = Transactor()
    tx.run("seed", lambda v, p: v.put("x", 0), writer="w")
    store_before, log_before = tx.store.to_dicts(), tx.to_dicts()

    def put(v, p):
        v.put("x", 1)

    bad_calls = [
        {"name": ""},
        {"name": 5},
        {"writer": ""},
        {"step": -1},
        {"rule": ""},
        {"params": object()},
        {"answer": 5},
    ]
    for override in bad_calls:
        kwargs = {"name": "t", "writer": "w", **override}
        with pytest.raises((ValueError, TypeError)):
            tx.run(kwargs.pop("name"), put, **kwargs)
        assert tx.store.to_dicts() == store_before and tx.to_dicts() == log_before
    assert replay_transactions(tx.log).to_dicts() == tx.store.to_dicts()


def _deep_vandal(value: object) -> None:
    """Edit a returned dict or list in place, at every level."""
    if isinstance(value, dict):
        for item in value.values():
            _deep_vandal(item)
        value["vandal"] = 1
    elif isinstance(value, list):
        for item in value:
            _deep_vandal(item)
        value.append("vandal")


def test_returned_records_are_copies() -> None:
    # Store: history() and writes().
    store = Store()
    store.put("k", {"n": [1]}, writer="w", step=1, answer=_answer())
    for record in store.history("k") + store.writes():
        _deep_vandal(record.value)
        _deep_vandal(record.answer)
    assert store.at(1) == {"k": {"n": [1]}} and store.get("k") == {"n": [1]}
    assert store.history("k")[0].answer == _answer().to_dict()

    # Simulator: log and the record step() returns.
    sim = ToyGrid(seed=2, slip=0.0)
    returned = sim.step("right")
    _deep_vandal(returned.observation)
    _deep_vandal(returned.outcome)
    _deep_vandal(sim.log[0].observation)
    sim.log.append("junk")  # type: ignore[arg-type]
    fresh = ToyGrid(seed=2, slip=0.0)
    fresh.step("right")
    assert sim.trajectory() == fresh.trajectory() and sim.steps == 1
    assert ToyGrid(slip=0.0).replay(sim.trajectory(), seed=2) == sim.snapshot()

    # ReviewQueue: get(), pending(), and what resolve() returns.
    queue = ReviewQueue()
    queue.submit({"t": [1]}, "why", answer=_answer(), step=1)
    before = queue.to_dicts()
    for item in (queue.get(0), queue.pending()[0]):
        _deep_vandal(item.item)
        _deep_vandal(item.answer)
    resolved = queue.resolve(0, {"r": [1]})
    _deep_vandal(resolved.resolution)
    _deep_vandal(queue.get(0).resolution)
    assert queue.to_dicts()[0]["item"] == before[0]["item"]
    assert queue.to_dicts()[0]["answer"] == before[0]["answer"]
    assert queue.to_dicts()[0]["resolution"] == {"r": [1]}

    # Transactor: log and the record run() returns.
    tx = Transactor()
    record = tx.run("t", lambda v, p: v.put("a", [1]), params={"p": [1]}, writer="w")
    snapshot = json.loads(json.dumps(tx.to_dicts()))
    _deep_vandal(record.params)
    for op in record.ops:
        _deep_vandal(op)
    for entry in tx.log:
        _deep_vandal(entry.params)
        for op in entry.ops:
            _deep_vandal(op)
    assert tx.to_dicts() == snapshot
    assert replay_transactions(tx.log).to_dicts() == tx.store.to_dicts()


def _good_log() -> list[dict]:
    """A transaction log with commits and one rollback, as plain dicts."""
    tx = Transactor()
    tx.run("a", lambda v, p: (v.put("x", 1), v.put("y", 2)), writer="w", step=0)
    tx.run("b", lambda v, p: v.put("x", 3), writer="w", step=1)
    tx.run("bad", lambda v, p: v.delete("nope"), writer="w", raise_on_failure=False)
    tx.run("c", lambda v, p: v.delete("y"), writer="w", step=2, rule="r")
    return json.loads(json.dumps(tx.to_dicts()))


def test_replay_accepts_a_good_log_and_rejects_a_missing_middle_entry() -> None:
    log = _good_log()
    assert replay_transactions(log).snapshot() == {"x": 3}
    # Dropping a committed entry that is not the last leaves a gap in the versions.
    for dropped in (0, 1):
        with pytest.raises(ReplayMismatch, match="version"):
            replay_transactions(log[:dropped] + log[dropped + 1 :])
    # A rolled-back entry consumes no version, so dropping it leaves the rest consistent.
    assert replay_transactions(log[:2] + log[3:]).snapshot() == {"x": 3}
    with pytest.raises(ReplayMismatch):
        replay_transactions([log[1], log[0], *log[2:]])


def _extra_op(entry: dict, op: dict) -> None:
    """Append an operation and keep the recorded versions consistent with it."""
    entry["ops"].append(op)
    entry["version_after"] += 1


def test_replay_rejects_unknown_op_status_and_shape() -> None:
    last = len(_good_log()) - 1  # a typo on the last entry has no later entry to expose it
    mutations = (
        (last, lambda e: _extra_op(e, {"op": "purge", "key": "x"})),
        (last, lambda e: _extra_op(e, {"op": "put", "key": "z"})),
        (last, lambda e: _extra_op(e, {"op": "delete", "key": "x", "value": 1})),
        (last, lambda e: e.update(status="Committed")),
        (last, lambda e: e.update(status="done")),
        (2, lambda e: e.update(status="rolled-back")),
        (0, lambda e: e.pop("writer")),
        (0, lambda e: e.update(extra=1)),
        (0, lambda e: e.update(version_after=99)),
        (0, lambda e: e.update(writer="")),
    )
    for index, mutate in mutations:
        log = _good_log()
        mutate(log[index])
        with pytest.raises(ReplayMismatch):
            replay_transactions(log)
    log = _good_log()
    log[2]["ops"] = [{"op": "put", "key": "q", "value": 1}]  # a rolled-back entry with ops
    with pytest.raises(ReplayMismatch, match="rolled-back"):
        replay_transactions(log)
    with pytest.raises(ReplayMismatch):
        replay_transactions([{"status": "committed"}])


def test_replay_failing_entry_leaves_store_as_before_that_entry() -> None:
    log = _good_log()
    # Entry 1 becomes [put y, delete zzz]: the second operation cannot apply.
    log[1]["ops"] = [{"op": "put", "key": "y", "value": 9}, {"op": "delete", "key": "zzz"}]
    log[1]["version_after"] = log[1]["version_before"] + 2
    store = Store()
    with pytest.raises(ReplayMismatch):
        replay_transactions(log, store)
    assert store.version == 2 and store.snapshot() == {"x": 1, "y": 2}  # only entry 0 applied
    assert store.to_dicts() == replay_transactions(_good_log()[:1]).to_dicts()
    # A store passed in must start at the version the log started from.
    with pytest.raises(ReplayMismatch, match="version"):
        replay_transactions(_good_log(), store)


def test_a_64_level_payload_round_trips_through_the_log_and_the_transactor() -> None:
    """The depth limit belongs to replay_key only: values these classes accepted still read back."""
    deep = "leaf"
    for _ in range(64):
        deep = {"k": deep}
    log = ActionLog()
    log.record("send", deep)
    assert len(log) == 1
    assert log.to_dicts()[0]["payload"] == deep
    assert log.to_dicts() == log.to_dicts()

    tx = Transactor()
    record = tx.run("put", lambda v, p: v.put("k", p), params=deep, writer="rule:test")
    assert record.committed
    assert tx.store.snapshot() == {"k": deep}
    assert tx.to_dicts()[0]["ops"]
    assert tx.log[0].to_dict()["ops"]


# --------------------------------------------------------------------------------------
# Routing outcomes: fill_review_queue, record_actions, route_outcomes
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Outcome:
    """A stand-in for a recipe's own outcome record."""

    id: str
    split: str
    outcome: str
    reason: str = "confidence below the threshold"


_DEMO = _Outcome("d1", "demo", "review")
_VALIDATION = [
    _Outcome("v1", "validation", "accepted"),
    _Outcome("v2", "validation", "review"),
    _Outcome("v3", "validation", "review", "no option fits"),
]
_TEST = [
    _Outcome("t1", "test", "review"),
    _Outcome("t2", "test", "accepted"),
]


def _fill(queue: ReviewQueue, outcomes, **overrides):
    """Fill ``queue`` the way a recipe notebook would: the arguments a notebook cell supplies."""
    arguments = {
        "needs_review": lambda o: o.outcome == "review",
        "item": lambda o: {"id": o.id, "split": o.split},
        "reason": lambda o: o.reason,
        "key": lambda o: o.id,
    }
    arguments.update(overrides)
    return fill_review_queue(queue, outcomes, **arguments)


def test_fill_review_queue_pins_ids_order_count_and_both_split_membership_as_literals() -> None:
    queue = ReviewQueue()
    first = _fill(queue, _VALIDATION)
    second = _fill(queue, [_DEMO, *_TEST], exclude=lambda o: o.split == "demo")
    # Nothing below is computed from the code under test: every expectation is a literal.
    assert first.review_keys == ("v2", "v3")
    assert first.review_ids == (0, 1)
    assert first.skipped_keys == ("v1",)
    assert first.excluded_keys == ()
    assert second.review_keys == ("t1",)
    assert second.review_ids == (2,)
    assert second.skipped_keys == ("t2",)
    assert second.excluded_keys == ("d1",)
    assert len(queue) == 3
    assert [(i["id"], i["item"], i["reason"]) for i in queue.to_dicts()] == [
        (0, {"id": "v2", "split": "validation"}, "confidence below the threshold"),
        (1, {"id": "v3", "split": "validation"}, "no option fits"),
        (2, {"id": "t1", "split": "test"}, "confidence below the threshold"),
    ]


def test_fill_review_queue_defaults_the_key_to_the_position_and_passes_answer_and_step() -> None:
    queue = ReviewQueue()
    answer = _answer()
    result = fill_review_queue(
        queue,
        _VALIDATION,
        needs_review=lambda o: o.outcome == "review",
        item=lambda o: {"id": o.id},
        reason="confidence below the threshold",
        answer=lambda o: answer,
        step=lambda o: int(o.id[1:]),
    )
    assert result.review_keys == (1, 2)  # positions in the outcomes
    stored = queue.to_dicts()
    assert [i["step"] for i in stored] == [2, 3]
    assert all(i["answer"] == answer.to_dict() for i in stored)
    assert {i["reason"] for i in stored} == {"confidence below the threshold"}
    assert result.to_dicts()[0] == {"key": 0, "destination": "skipped", "id": None}


def test_fill_review_queue_accepts_any_iterable_once() -> None:
    queue = ReviewQueue()
    result = _fill(queue, iter(_VALIDATION))
    assert result.review_keys == ("v2", "v3") and len(result) == 3


def test_route_outcomes_sends_each_outcome_to_the_queue_or_the_log_in_one_pass() -> None:
    queue, log = ReviewQueue(), ActionLog()

    def route(o: _Outcome):
        if o.outcome == "review":
            return ToReview({"id": o.id}, o.reason, step=1)
        return ToAction("route_to_queue", {"id": o.id}, rule="accepted", step=1)

    result = route_outcomes(
        _VALIDATION + _TEST, route, queue=queue, actions=log, key=lambda o: o.id
    )
    assert result.review_keys == ("v2", "v3", "t1") and result.review_ids == (0, 1, 2)
    assert result.action_keys == ("v1", "t2") and result.action_seqs == (0, 1)
    assert [e["destination"] for e in result.to_dicts()] == [
        "action",
        "review",
        "review",
        "review",
        "action",
    ]
    assert [a["payload"] for a in log.to_dicts()] == [{"id": "v1"}, {"id": "t2"}]
    assert all(a["executed"] is False and a["rule"] == "accepted" for a in log.to_dicts())


def test_record_actions_records_only_the_selected_outcomes_in_order() -> None:
    log = ActionLog()
    result = record_actions(
        log,
        _VALIDATION + _TEST,
        selects=lambda o: o.outcome == "accepted",
        kind="release",
        payload=lambda o: {"id": o.id},
        rule=lambda o: f"accepted {o.split}",
        key=lambda o: o.id,
    )
    assert result.action_keys == ("v1", "t2") and result.action_seqs == (0, 1)
    assert [(a["kind"], a["payload"], a["rule"]) for a in log.to_dicts()] == [
        ("release", {"id": "v1"}, "accepted validation"),
        ("release", {"id": "t2"}, "accepted test"),
    ]


def test_a_routing_pass_is_all_or_nothing() -> None:
    queue, log = ReviewQueue(), ActionLog()
    queue.submit({"id": "earlier"}, "kept")

    def route(o: _Outcome):
        # The last outcome carries an item that is not plain JSON, which only the write detects.
        item = {"id": o} if o.id == "v3" else {"id": o.id}
        if o.outcome == "review":
            return ToReview(item, o.reason)
        return ToAction("release", {"id": o.id})

    with pytest.raises(TypeError):
        route_outcomes(_VALIDATION, route, queue=queue, actions=log)
    assert [i["item"] for i in queue.to_dicts()] == [{"id": "earlier"}]
    assert len(log) == 0  # the action recorded before the failure was removed again
    # A route function that raises changes nothing either.
    with pytest.raises(ZeroDivisionError):
        route_outcomes(_VALIDATION, lambda o: 1 / 0, queue=queue, actions=log)
    assert len(queue) == 1 and len(log) == 0


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda q, a: route_outcomes(_VALIDATION, lambda o: ToReview({}, "x")), "no queue"),
        (lambda q, a: route_outcomes(_VALIDATION, lambda o: ToAction("k"), queue=q), "no actions"),
        (lambda q, a: route_outcomes(_VALIDATION, lambda o: "review", queue=q), "ToReview"),
        (lambda q, a: route_outcomes(_VALIDATION, None, queue=q), "route must be callable"),
        (lambda q, a: route_outcomes(_VALIDATION, lambda o: None, queue=[]), "ReviewQueue"),
        (lambda q, a: route_outcomes(_VALIDATION, lambda o: None, actions=[]), "ActionLog"),
        (
            lambda q, a: route_outcomes(_VALIDATION, lambda o: None, key=lambda o: "same"),
            "more than once",
        ),
        (
            lambda q, a: route_outcomes(_VALIDATION, lambda o: None, exclude=lambda o: "yes"),
            "must return a bool",
        ),
        (
            lambda q, a: _fill(q, _VALIDATION, needs_review=lambda o: o.outcome),
            "must return a bool",
        ),
        (lambda q, a: _fill(q, _VALIDATION, needs_review=None), "callable"),
    ],
)
def test_routing_rejects_a_misuse_before_writing_anything(call, message) -> None:
    queue, log = ReviewQueue(), ActionLog()
    with pytest.raises(SimulationError, match=message):
        call(queue, log)
    assert len(queue) == 0 and len(log) == 0


def test_the_shared_helper_reproduces_the_inline_loops_recipes_wrote_by_hand() -> None:
    """The helper expresses the hand-written shapes published recipes use, entry for entry.

    The inline versions below follow what recipes 02 (demo skipped, then an ``already_queued``
    guard) and 38 (queue and log filled in one loop) do in their notebooks today; they are here
    only to show the migration path is lossless, never as the expectation for a recipe's own test.
    """
    answer = _answer()
    everything = [_DEMO, *_VALIDATION, *_TEST]

    inline = ReviewQueue()
    already = {"v2"}
    for o in everything:
        if o.split == "demo":
            continue
        if o.outcome != "accepted" and o.id not in already:
            inline.submit({"ticket_id": o.id}, o.reason, answer=answer)
    shared = ReviewQueue()
    fill_review_queue(
        shared,
        everything,
        needs_review=lambda o: o.outcome != "accepted",
        item=lambda o: {"ticket_id": o.id},
        reason=lambda o: o.reason,
        answer=lambda o: answer,
        exclude=lambda o: o.split == "demo" or o.id in already,
    )
    assert shared.to_dicts() == inline.to_dicts() and len(shared) == 2

    inline_queue, inline_log = ReviewQueue(), ActionLog()
    for o in _VALIDATION + _TEST:
        if o.outcome == "accepted":
            inline_log.record("route_to_queue", {"ticket_id": o.id}, answer=answer, rule=o.reason)
        else:
            inline_queue.submit({"ticket_id": o.id}, o.reason, answer=answer)
    shared_queue, shared_log = ReviewQueue(), ActionLog()
    route_outcomes(
        _VALIDATION + _TEST,
        lambda o: (
            ToAction("route_to_queue", {"ticket_id": o.id}, answer=answer, rule=o.reason)
            if o.outcome == "accepted"
            else ToReview({"ticket_id": o.id}, o.reason, answer=answer)
        ),
        queue=shared_queue,
        actions=shared_log,
    )
    assert shared_queue.to_dicts() == inline_queue.to_dicts()
    assert shared_log.to_dicts() == inline_log.to_dicts()


def test_the_worked_example_in_the_docs_runs_and_its_literals_hold() -> None:
    text = DOCS.read_text(encoding="utf-8")
    block = re.search(r"```python\n# recipe: fill-example\n(.*?)\n```", text, re.S).group(1)
    namespace: dict = {}
    exec(compile(block, "docs/simulation.md", "exec"), namespace)
    assert namespace["validation_fill"].review_keys == ("v2", "v3")
    assert namespace["test_fill"].review_ids == (2,)


def test_a_key_that_is_not_plain_json_is_a_simulation_error() -> None:
    queue = ReviewQueue()
    with pytest.raises(SimulationError, match="not plain JSON"):
        route_outcomes(_VALIDATION, lambda o: None, queue=queue, key=lambda o: object())
    assert len(queue) == 0


def test_routed_passes_can_be_concatenated_for_a_per_step_loop() -> None:
    queue, log = ReviewQueue(), ActionLog()
    total = route_outcomes([], lambda o: None)
    for step, outcome in enumerate(_VALIDATION):
        total += route_outcomes(
            [outcome],
            lambda o, step=step: (
                ToReview({"id": o.id}, o.reason, step=step)
                if o.outcome == "review"
                else ToAction("release", {"id": o.id}, step=step)
            ),
            queue=queue,
            actions=log,
            key=lambda o: o.id,
        )
    assert total.review_keys == ("v2", "v3") and total.review_ids == (0, 1)
    assert total.action_keys == ("v1",) and total.action_seqs == (0,)
    assert len(total) == 3
    assert [i["step"] for i in queue.to_dicts()] == [1, 2]
    with pytest.raises(TypeError):
        total + 1  # type: ignore[operator]


def test_the_decide_and_apply_example_in_the_docs_runs_and_its_literals_hold() -> None:
    text = DOCS.read_text(encoding="utf-8")
    block = re.search(r"```python\n# recipe: decide-example\n(.*?)\n```", text, re.S).group(1)
    namespace: dict = {}
    exec(compile(block, "docs/simulation.md", "exec"), namespace)
    assert namespace["outcomes"] == ["assigned", "review", "review", "assigned"]
