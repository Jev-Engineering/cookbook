"""Simulation and state primitives for recipes that keep state or run a loop.

Everything here is plain Python with no network, no key and no global randomness. Actions are
simulated: they are recorded, never executed. See ``docs/simulation.md``.

* ``Simulator``: a seeded environment with ``reset / observe / legal_actions / step`` and a
  replayable trajectory log; ``ToyGrid`` is the small concrete example.
* ``ReviewQueue`` and ``ActionLog``: where "send to review" and "simulated action" land.
* ``Store``: a versioned key-value store with provenance that never deletes.
* ``Transactor``: ``validate -> apply -> commit`` over a ``Store``, with rollback and a replayable log.
* ``Budget``: retry limits, call budgets and stop conditions enforced in code.

Every record is plain JSON (``str``, ``int``, ``float``, ``bool``, ``None``, ``list``, ``dict``
with ``str`` keys), so ``to_dicts()`` output can be shown in a notebook or written to a fixture.
"""

from __future__ import annotations

import abc
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from typing import Any

from ._canonical import plain_json

__all__ = [
    "ActionLog",
    "Budget",
    "BudgetExceeded",
    "IllegalActionError",
    "ReplayMismatch",
    "ReviewItem",
    "ReviewQueue",
    "SimulationError",
    "Simulator",
    "StepRecord",
    "StopConditionMet",
    "Store",
    "StoreError",
    "ToyGrid",
    "TransactionFailed",
    "TransactionRecord",
    "Transactor",
    "WriteRecord",
    "replay_transactions",
]


class SimulationError(Exception):
    """Base class of every error raised by this module."""


class IllegalActionError(SimulationError, ValueError):
    """An action was not in ``legal_actions()`` (or the episode is over)."""


class ReplayMismatch(SimulationError):
    """A replayed log did not reproduce the recorded observations or outcomes."""


class BudgetExceeded(SimulationError, RuntimeError):
    """A spend would pass a limit. The budget is left unchanged."""


class StopConditionMet(SimulationError, RuntimeError):
    """A registered stop condition is true, so the loop must stop."""


class StoreError(SimulationError, KeyError):
    """A store lookup or rollback named something that does not exist."""

    def __str__(self) -> str:
        """Return the message without the quoting ``KeyError`` adds."""
        return str(self.args[0]) if self.args else ""


class TransactionFailed(SimulationError):
    """A transaction was rolled back; ``record`` is its entry in the transaction log."""

    def __init__(self, message: str, record: TransactionRecord) -> None:
        """Keep the log record next to the message."""
        super().__init__(message)
        self.record = record


def _detach(record: Any) -> Any:
    """Return a copy of a frozen record whose nested dicts and lists are all new objects.

    Every accessor that hands out a record returns such a copy, so a caller can edit what it
    received without changing the history the owner keeps.
    """
    changes = {}
    for f in fields(record):
        value = getattr(record, f.name)
        changes[f.name] = (
            tuple(plain_json(v) for v in value) if isinstance(value, tuple) else plain_json(value)
        )
    return replace(record, **changes)


def _answer_dict(answer: Any) -> dict[str, Any] | None:
    """Return a typed answer as a plain dict (``None`` stays ``None``)."""
    if answer is None:
        return None
    if hasattr(answer, "to_dict"):
        answer = answer.to_dict()
    if not isinstance(answer, Mapping):
        raise TypeError("answer must be a typed answer object, a dict, or None")
    return plain_json(dict(answer), "answer")


def _check_int(value: Any, what: str, minimum: int = 0) -> int:
    """Return ``value`` if it is a real ``int`` (not ``bool``) of at least ``minimum``."""
    if type(value) is not int or value < minimum:
        raise ValueError(f"{what} must be an int >= {minimum}, got {value!r}")
    return value


def _check_step(step: Any) -> int | None:
    """Validate an optional step index."""
    return None if step is None else _check_int(step, "step")


def _check_text(value: Any, what: str) -> str:
    """Return ``value`` if it is non-empty text."""
    if type(value) is not str or not value:
        raise ValueError(f"{what} must be non-empty text, got {value!r}")
    return value


# --------------------------------------------------------------------------------------
# Simulator
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StepRecord:
    """One trajectory entry: the observation before the action, the action, and its outcome."""

    step: int
    observation: Any
    action: Any
    outcome: Any
    done: bool

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict."""
        return {
            "step": self.step,
            "observation": plain_json(self.observation),
            "action": plain_json(self.action),
            "outcome": plain_json(self.outcome),
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StepRecord:
        """Build a record from ``to_dict()`` output."""
        if set(data) != {"step", "observation", "action", "outcome", "done"}:
            raise ValueError(f"step record has unexpected keys {sorted(data)}")
        return cls(
            _check_int(data["step"], "step"),
            plain_json(data["observation"]),
            plain_json(data["action"]),
            plain_json(data["outcome"]),
            bool(data["done"]),
        )


class Simulator(abc.ABC):
    """Deterministic, seeded environment with a replayable trajectory log.

    Subclasses implement five hooks and never touch global randomness:

    * ``_reset(rng)`` build the initial state (``rng`` is ``random.Random(seed)``),
    * ``_observe()`` what the agent may see now (plain JSON),
    * ``_legal_actions()`` the actions allowed now (a list of plain JSON values),
    * ``_apply(action, rng)`` change the state and return the outcome (plain JSON),
    * ``_snapshot()`` the full hidden state (plain JSON), used to compare replays,

    and optionally ``_is_done()``. Draw randomness only from the ``rng`` passed in, and prefer
    ``rng.random()``: it is the one call the ``random`` module's own docs commit to producing the
    same sequence for the same seed across platforms and Python 3.10 to 3.14 (see
    ``docs/backends.md``, "Scripted backend"). ``ToyGrid._reset`` calls ``rng.randrange(1, n)``
    for its target cell; that call's output is pinned, byte for byte, by
    ``test_golden_values_pin_cross_platform_streams`` in ``tests/test_simulation.py`` rather than
    assumed stable, and a *new* ``_reset``/``_apply`` should derive a discrete choice from
    ``rng.random()`` instead of adding another call to ``rng.randrange``, ``rng.choice`` or
    ``rng.shuffle``, none of which carry the same documented guarantee. The legal actions are
    enumerated by Python, never by the model, so a recipe can offer them as the fixed options of
    a ``Choice`` question.
    """

    def __init__(self, seed: int = 0) -> None:
        """Create the simulator and ``reset`` it with ``seed``."""
        self.seed = 0
        self._log: list[StepRecord] = []
        self._rng = random.Random(0)
        self.reset(seed)

    @abc.abstractmethod
    def _reset(self, rng: random.Random) -> None:
        """Build the initial state, drawing only from ``rng``."""

    @abc.abstractmethod
    def _observe(self) -> Any:
        """Return what the agent can see now, as plain JSON."""

    @abc.abstractmethod
    def _legal_actions(self) -> Sequence[Any]:
        """Return the actions allowed in the current state (plain JSON values)."""

    @abc.abstractmethod
    def _apply(self, action: Any, rng: random.Random) -> Any:
        """Apply a legal ``action``, drawing only from ``rng``, and return its outcome."""

    @abc.abstractmethod
    def _snapshot(self) -> Any:
        """Return the complete state as plain JSON."""

    def _is_done(self) -> bool:
        """Return True when the episode is over (default: never)."""
        return False

    def reset(self, seed: int | None = None) -> Any:
        """Start a new episode with ``seed`` (default: keep the current seed); clear the log.

        Returns the first observation. The same seed always gives the same episode.
        """
        if seed is not None:
            if type(seed) is not int:
                raise TypeError("seed must be an int")
            self.seed = seed
        self._rng = random.Random(self.seed)
        self._log = []
        self._reset(self._rng)
        return self.observe()

    def observe(self) -> Any:
        """Return the current observation as a fresh plain-JSON copy."""
        return plain_json(self._observe(), "observation")

    def legal_actions(self) -> list[Any]:
        """Return the actions allowed now (empty once the episode is done)."""
        if self.done:
            return []
        return [plain_json(a, "action") for a in self._legal_actions()]

    @property
    def done(self) -> bool:
        """True when the episode is over."""
        return bool(self._is_done())

    @property
    def log(self) -> list[StepRecord]:
        """The trajectory so far, as copies: editing the result never changes the simulator."""
        return [_detach(r) for r in self._log]

    @property
    def steps(self) -> int:
        """Number of steps taken since the last reset."""
        return len(self._log)

    def snapshot(self) -> Any:
        """Return the complete state as a fresh plain-JSON copy."""
        return plain_json(self._snapshot(), "snapshot")

    def step(self, action: Any) -> StepRecord:
        """Apply ``action`` if it is legal, append a ``StepRecord`` to the log, and return it.

        Raises ``IllegalActionError`` for an action outside ``legal_actions()`` or after the
        episode is done; the state and the log are then unchanged.
        """
        action = plain_json(action, "action")
        legal = self.legal_actions()
        if action not in legal:
            why = "the episode is done" if self.done else f"legal actions are {legal!r}"
            raise IllegalActionError(f"illegal action {action!r}: {why}")
        observation = self.observe()
        outcome = plain_json(self._apply(action, self._rng), "outcome")
        record = StepRecord(len(self._log), observation, action, outcome, self.done)
        self._log.append(record)
        return _detach(record)

    def trajectory(self) -> list[dict[str, Any]]:
        """Return the log as plain dicts, for display or storage."""
        return [r.to_dict() for r in self._log]

    def replay(self, log: Iterable[StepRecord | Mapping[str, Any]], seed: int | None = None) -> Any:
        """Reset to ``seed`` (default: the current seed), re-apply the logged actions, return the state.

        Every replayed observation and outcome must equal the recorded one, otherwise
        ``ReplayMismatch`` is raised. On success ``self.log`` equals the replayed log and the
        returned snapshot equals the snapshot of the run that produced it. After a
        ``ReplayMismatch`` (or an ``IllegalActionError`` from a tampered action) the simulator
        is left part-way through the replay: ``reset`` it before reuse.
        """
        records = [r if isinstance(r, StepRecord) else StepRecord.from_dict(r) for r in log]
        self.reset(seed)
        for expected in records:
            got = self.step(expected.action)
            if got != expected:
                raise ReplayMismatch(
                    f"replay diverged at step {expected.step}: recorded {expected.to_dict()!r}, "
                    f"replayed {got.to_dict()!r}"
                )
        return self.snapshot()


class ToyGrid(Simulator):
    """A tiny concrete simulator: walk a line to a hidden target and ``grab`` it.

    The agent stands on cells ``0 .. size - 1``; the target cell is drawn from the seed and is
    visible in the observation. ``left`` and ``right`` move (blocked at the ends); with
    probability ``slip`` a move is ignored and the outcome says ``"slipped"``. ``grab`` is legal
    only on the target and ends the episode. It exercises every ``Simulator`` method.
    """

    def __init__(self, seed: int = 0, size: int = 6, slip: float = 0.25) -> None:
        """Set the line length and slip probability, then reset with ``seed``."""
        if type(size) is not int or size < 2:
            raise ValueError("size must be an int >= 2")
        if not 0.0 <= slip <= 1.0:
            raise ValueError("slip must be between 0 and 1")
        self.size = size
        self.slip = slip
        self.position = 0
        self.target = 0
        self.grabbed = False
        super().__init__(seed)

    def _reset(self, rng: random.Random) -> None:
        """Place the agent at 0 and draw the target from ``rng``."""
        self.position = 0
        self.target = rng.randrange(1, self.size)
        self.grabbed = False

    def _observe(self) -> Any:
        """Show position, target and size."""
        return {"position": self.position, "target": self.target, "size": self.size}

    def _legal_actions(self) -> Sequence[Any]:
        """Allow moves that stay on the line, and ``grab`` only on the target."""
        actions = []
        if self.position > 0:
            actions.append("left")
        if self.position < self.size - 1:
            actions.append("right")
        if self.position == self.target:
            actions.append("grab")
        return actions

    def _apply(self, action: Any, rng: random.Random) -> Any:
        """Move (or slip) or grab."""
        if action == "grab":
            self.grabbed = True
            return "grabbed"
        if rng.random() < self.slip:
            return "slipped"
        self.position += -1 if action == "left" else 1
        return "moved"

    def _snapshot(self) -> Any:
        """Return the whole state."""
        return {
            "position": self.position,
            "target": self.target,
            "grabbed": self.grabbed,
            "size": self.size,
        }

    def _is_done(self) -> bool:
        """The episode ends when the target is grabbed."""
        return self.grabbed


# --------------------------------------------------------------------------------------
# Review queue and action log
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewItem:
    """An item sent to review, with the reason and the typed answer that triggered it."""

    id: int
    item: Any
    reason: str
    answer: dict[str, Any] | None
    step: int | None
    status: str = "pending"
    resolution: Any = None

    def to_dict(self) -> dict[str, Any]:
        """Return the item as a plain dict."""
        return {
            "id": self.id,
            "item": plain_json(self.item),
            "reason": self.reason,
            "answer": plain_json(self.answer),
            "step": self.step,
            "status": self.status,
            "resolution": plain_json(self.resolution),
        }


class ReviewQueue:
    """A simulated human-review queue: items wait here, and nothing happens to them.

    ``submit`` keeps the reason and the typed answer (an answer object or its ``to_dict()``)
    that sent the item to review, so a notebook can show why. ``resolve`` marks an item
    handled with a recorded decision; it never deletes anything.
    """

    def __init__(self) -> None:
        """Create an empty queue."""
        self._items: list[ReviewItem] = []

    def submit(self, item: Any, reason: str, *, answer: Any = None, step: int | None = None) -> int:
        """Queue ``item`` (plain JSON) for review and return its id (0, 1, 2, ...)."""
        entry = ReviewItem(
            len(self._items),
            plain_json(item, "item"),
            _check_text(reason, "reason"),
            _answer_dict(answer),
            _check_step(step),
        )
        self._items.append(entry)
        return entry.id

    def resolve(self, item_id: int, resolution: Any) -> ReviewItem:
        """Mark a pending item resolved with ``resolution`` (plain JSON) and return it."""
        old = self._items[self.get(item_id).id]
        if old.status != "pending":
            raise SimulationError(f"review item {item_id} is already {old.status}")
        new = ReviewItem(
            old.id,
            old.item,
            old.reason,
            old.answer,
            old.step,
            "resolved",
            plain_json(resolution, "resolution"),
        )
        self._items[item_id] = new
        return _detach(new)

    def get(self, item_id: int) -> ReviewItem:
        """Return one item by id."""
        if type(item_id) is not int or not 0 <= item_id < len(self._items):
            raise StoreError(f"no review item {item_id!r}")
        return _detach(self._items[item_id])

    def pending(self) -> list[ReviewItem]:
        """Return the items still waiting, oldest first."""
        return [_detach(i) for i in self._items if i.status == "pending"]

    def __len__(self) -> int:
        """Return the number of items ever submitted."""
        return len(self._items)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return every item as a plain dict, oldest first."""
        return [i.to_dict() for i in self._items]


class ActionLog:
    """A record of simulated actions. Nothing is executed; ``executed`` is always False."""

    def __init__(self) -> None:
        """Create an empty log."""
        self._entries: list[dict[str, Any]] = []

    def record(
        self,
        kind: str,
        payload: Any = None,
        *,
        step: int | None = None,
        answer: Any = None,
        rule: str | None = None,
    ) -> dict[str, Any]:
        """Record that action ``kind`` with ``payload`` was chosen, and return a copy of the entry.

        ``answer`` is the typed answer behind it and ``rule`` the Python rule that allowed it.
        """
        entry = {
            "seq": len(self._entries),
            "kind": _check_text(kind, "kind"),
            "payload": plain_json(payload, "payload"),
            "step": _check_step(step),
            "answer": _answer_dict(answer),
            "rule": None if rule is None else _check_text(rule, "rule"),
            "executed": False,
        }
        self._entries.append(entry)
        return plain_json(entry)

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        """Return copies of the entries with this ``kind``."""
        return [plain_json(e) for e in self._entries if e["kind"] == kind]

    def __len__(self) -> int:
        """Return the number of recorded actions."""
        return len(self._entries)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return every entry as a plain dict, oldest first."""
        return [plain_json(e) for e in self._entries]


# --------------------------------------------------------------------------------------
# Versioned store
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteRecord:
    """One write with its provenance. ``tombstone`` marks a delete (``value`` is then None)."""

    version: int
    key: str
    value: Any
    tombstone: bool
    writer: str
    step: int | None
    answer: dict[str, Any] | None
    rule: str | None
    rollback_to: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict."""
        return {
            "version": self.version,
            "key": self.key,
            "value": plain_json(self.value),
            "tombstone": self.tombstone,
            "writer": self.writer,
            "step": self.step,
            "answer": plain_json(self.answer),
            "rule": self.rule,
            "rollback_to": self.rollback_to,
        }


_MISSING: Any = object()


class Store:
    """Versioned key-value store with per-write provenance that never deletes.

    Version 0 is the empty store; every write (put, delete, or one rollback write) adds one
    version. ``delete`` writes a tombstone and keeps the history. ``rollback(v)`` does not
    rewrite the past: it appends writes that restore the state of version ``v``, marked
    ``rollback_to=v``, so the rollback itself is in the history and can be rolled back.
    Values are plain JSON and are copied in and out.
    """

    def __init__(self) -> None:
        """Create an empty store at version 0."""
        self._writes: list[WriteRecord] = []

    @property
    def version(self) -> int:
        """The current version (the number of writes so far)."""
        return len(self._writes)

    def _append(
        self,
        key: str,
        value: Any,
        tombstone: bool,
        writer: str,
        step: int | None,
        answer: Any,
        rule: str | None,
        rollback_to: int | None = None,
    ) -> int:
        """Validate and append one write; return the new version."""
        record = WriteRecord(
            len(self._writes) + 1,
            _check_text(key, "key"),
            None if tombstone else plain_json(value, "value"),
            tombstone,
            _check_text(writer, "writer"),
            _check_step(step),
            _answer_dict(answer),
            None if rule is None else _check_text(rule, "rule"),
            rollback_to,
        )
        self._writes.append(record)
        return record.version

    def put(
        self,
        key: str,
        value: Any,
        *,
        writer: str,
        step: int | None = None,
        answer: Any = None,
        rule: str | None = None,
    ) -> int:
        """Write ``value`` under ``key`` with provenance; return the new version.

        ``writer`` says who or what wrote it, ``step`` when, ``answer`` the typed answer and
        ``rule`` the Python rule behind it.
        """
        return self._append(key, value, False, writer, step, answer, rule)

    def delete(
        self,
        key: str,
        *,
        writer: str,
        step: int | None = None,
        answer: Any = None,
        rule: str | None = None,
    ) -> int:
        """Tombstone ``key`` (it must be live); history is kept. Return the new version."""
        if key not in self:
            raise StoreError(f"cannot delete {key!r}: no such live key")
        return self._append(key, None, True, writer, step, answer, rule)

    def _state_at(self, version: int) -> dict[str, WriteRecord]:
        """Return the last write per key up to ``version`` (tombstones included)."""
        if type(version) is not int or not 0 <= version <= self.version:
            raise StoreError(f"no version {version!r}; the store is at version {self.version}")
        latest: dict[str, WriteRecord] = {}
        for record in self._writes[:version]:
            latest[record.key] = record
        return latest

    def at(self, version: int) -> dict[str, Any]:
        """Return the live ``{key: value}`` snapshot as of ``version`` (0 is empty)."""
        return {
            k: plain_json(r.value) for k, r in self._state_at(version).items() if not r.tombstone
        }

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Return the live value of ``key``; ``default`` if given, else ``StoreError``."""
        record = self._state_at(self.version).get(key)
        if record is None or record.tombstone:
            if default is _MISSING:
                raise StoreError(f"no live key {key!r}")
            return default
        return plain_json(record.value)

    def __contains__(self, key: object) -> bool:
        """Return True when ``key`` is live (written and not tombstoned)."""
        record = self._state_at(self.version).get(key) if isinstance(key, str) else None
        return record is not None and not record.tombstone

    def keys(self) -> list[str]:
        """Return the live keys in sorted order."""
        return sorted(self.at(self.version))

    def snapshot(self) -> dict[str, Any]:
        """Return the live ``{key: value}`` state now."""
        return self.at(self.version)

    def history(self, key: str) -> list[WriteRecord]:
        """Return copies of every write to ``key``, oldest first (tombstones, rollbacks too).

        Records are copies: editing one never changes the store.
        """
        return [_detach(r) for r in self._writes if r.key == key]

    def writes(self) -> list[WriteRecord]:
        """Return every write in the store, oldest first."""
        return [_detach(r) for r in self._writes]

    def rollback(self, version: int, *, writer: str = "rollback", step: int | None = None) -> int:
        """Restore the live state of ``version`` by appending writes; return the new version.

        Keys changed since ``version`` get their old value back (or a tombstone if they were
        not live then). Nothing is removed from the history. Rolling back to the current
        version appends nothing.
        """
        then = self._state_at(version)
        now = self._state_at(self.version)
        for key in sorted(set(then) | set(now)):
            old, cur = then.get(key), now.get(key)
            old_live = old is not None and not old.tombstone
            cur_live = cur is not None and not cur.tombstone
            if old_live and (not cur_live or old.value != cur.value):
                self._append(key, old.value, False, writer, step, None, None, version)
            elif not old_live and cur_live:
                self._append(key, None, True, writer, step, None, None, version)
        return self.version

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return the whole write history as plain dicts, oldest first."""
        return [r.to_dict() for r in self._writes]


# --------------------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------------------


class _Staged:
    """The view an ``apply`` function gets: reads see staged writes, nothing is committed."""

    def __init__(self, store: Store) -> None:
        """Wrap ``store`` (read only) with an empty list of staged operations."""
        self._store = store
        self.ops: list[dict[str, Any]] = []
        self._overlay: dict[str, Any] = {}

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Return the value ``key`` would have after the staged operations."""
        if key in self._overlay:
            value = self._overlay[key]
            if value is _MISSING:
                if default is _MISSING:
                    raise StoreError(f"no live key {key!r}")
                return default
            return plain_json(value)
        return self._store.get(key, default)

    def __contains__(self, key: object) -> bool:
        """Return True when ``key`` would be live after the staged operations."""
        if isinstance(key, str) and key in self._overlay:
            return self._overlay[key] is not _MISSING
        return key in self._store

    def put(self, key: str, value: Any) -> None:
        """Stage a write."""
        self._overlay[_check_text(key, "key")] = plain_json(value, "value")
        self.ops.append({"op": "put", "key": key, "value": plain_json(value)})

    def delete(self, key: str) -> None:
        """Stage a tombstone for a live key."""
        if key not in self:
            raise StoreError(f"cannot delete {key!r}: no such live key")
        self._overlay[key] = _MISSING
        self.ops.append({"op": "delete", "key": key})

    def snapshot(self) -> dict[str, Any]:
        """Return the live state as it would be after the staged operations."""
        state = self._store.snapshot()
        for key, value in self._overlay.items():
            if value is _MISSING:
                state.pop(key, None)
            else:
                state[key] = plain_json(value)
        return state


@dataclass(frozen=True)
class TransactionRecord:
    """One entry of the transaction log. Replaying committed entries rebuilds the store."""

    index: int
    name: str
    params: Any
    writer: str
    step: int | None
    answer: dict[str, Any] | None
    rule: str | None
    status: str
    ops: tuple[dict[str, Any], ...]
    error: str | None
    version_before: int
    version_after: int

    @property
    def committed(self) -> bool:
        """True when the transaction committed."""
        return self.status == "committed"

    def to_dict(self) -> dict[str, Any]:
        """Return the record as a plain dict."""
        return {
            "index": self.index,
            "name": self.name,
            "params": plain_json(self.params),
            "writer": self.writer,
            "step": self.step,
            "answer": plain_json(self.answer),
            "rule": self.rule,
            "status": self.status,
            "ops": plain_json(list(self.ops)),
            "error": self.error,
            "version_before": self.version_before,
            "version_after": self.version_after,
        }


def _apply_ops(store: Store, rec: Mapping[str, Any]) -> None:
    """Write the operations of a transaction record into ``store`` with its provenance."""
    for op in rec["ops"]:
        meta = {
            "writer": rec["writer"],
            "step": rec["step"],
            "answer": rec["answer"],
            "rule": rec["rule"],
        }
        if op["op"] == "put":
            store.put(op["key"], op["value"], **meta)
        else:
            store.delete(op["key"], **meta)


class Transactor:
    """Run changes to a ``Store`` as ``validate -> apply -> commit``, all or nothing.

    ``run`` stages the changes on a view, so a failure in ``validate``, ``apply`` or
    ``invariant`` leaves the store untouched (rollback). Every attempt, committed or rolled
    back, is appended to ``log``. ``replay_transactions(log)`` rebuilds the store from the
    committed entries alone, with the same history and provenance.
    """

    def __init__(self, store: Store | None = None) -> None:
        """Wrap ``store`` (a new empty one by default)."""
        self.store = Store() if store is None else store
        self._log: list[TransactionRecord] = []

    @property
    def log(self) -> list[TransactionRecord]:
        """Every attempt so far, as copies: editing the result never changes the log."""
        return [_detach(r) for r in self._log]

    def run(
        self,
        name: str,
        apply: Callable[[Any, Any], Any],
        *,
        params: Any = None,
        writer: str,
        step: int | None = None,
        answer: Any = None,
        rule: str | None = None,
        validate: Callable[[Any, Any], Any] | None = None,
        invariant: Callable[[Any], Any] | None = None,
        raise_on_failure: bool = True,
    ) -> TransactionRecord:
        """Run one transaction and return its log record.

        ``validate(view, params)`` runs first: it must return None or True, and anything else
        (False, a non-empty list of problems, or an exception) rejects. ``apply(view, params)``
        stages changes with ``view.put(key, value)`` / ``view.delete(key)`` and reads with
        ``view.get`` / ``key in view`` / ``view.snapshot()``. ``invariant(view)`` runs after
        ``apply`` on the staged state under the same rule. On success the staged operations
        are committed to the store as one batch with provenance (``writer``, ``step``,
        ``answer``, ``rule``). On any failure nothing is written, the record has status
        ``"rolled_back"`` and the reason, and ``TransactionFailed`` is raised unless
        ``raise_on_failure`` is False. ``params`` must be plain JSON so the log can replay.
        """
        name = _check_text(name, "name")
        params = plain_json(params, "params")
        meta = {
            "writer": _check_text(writer, "writer"),
            "step": _check_step(step),
            "answer": _answer_dict(answer),
            "rule": None if rule is None else _check_text(rule, "rule"),
        }
        before = self.store.version
        view = _Staged(self.store)
        error: str | None = None
        try:
            if validate is not None:
                _require_ok(validate(view, plain_json(params)), "validate")
            apply(view, plain_json(params))
            if invariant is not None:
                _require_ok(invariant(view), "invariant")
        except Exception as exc:  # any failure, of any type, must roll back
            error = f"{type(exc).__name__}: {exc}"
        if error is None:
            _apply_ops(self.store, {"ops": view.ops, **meta})
        record = TransactionRecord(
            len(self._log),
            name,
            params,
            meta["writer"],
            meta["step"],
            meta["answer"],
            meta["rule"],
            "committed" if error is None else "rolled_back",
            tuple(view.ops) if error is None else (),
            error,
            before,
            self.store.version,
        )
        self._log.append(record)
        if error is not None and raise_on_failure:
            raise TransactionFailed(f"transaction {name!r} rolled back: {error}", _detach(record))
        return _detach(record)

    def to_dicts(self) -> list[dict[str, Any]]:
        """Return the transaction log as plain dicts."""
        return [r.to_dict() for r in self._log]


def _require_ok(result: Any, what: str) -> None:
    """Raise ``ValueError`` unless a validator result means 'fine' (None or True)."""
    if result is None or result is True:
        return
    raise ValueError(f"{what} rejected: {result!r}")


_RECORD_KEYS = frozenset(
    {
        "index",
        "name",
        "params",
        "writer",
        "step",
        "answer",
        "rule",
        "status",
        "ops",
        "error",
        "version_before",
        "version_after",
    }
)


def _stage_record(out: Store, rec: Mapping[str, Any]) -> _Staged:
    """Check one log entry completely and stage its operations; write nothing to ``out``."""
    if set(rec) != _RECORD_KEYS:
        raise ValueError(f"unexpected keys {sorted(set(rec) ^ _RECORD_KEYS)}")
    if rec["status"] not in ("committed", "rolled_back"):
        raise ValueError(f"unknown status {rec['status']!r}")
    if rec["version_before"] != out.version:
        raise ValueError(f"expected the store at version {rec['version_before']}, at {out.version}")
    _check_text(rec["writer"], "writer")
    _check_step(rec["step"])
    _answer_dict(rec["answer"])
    if rec["rule"] is not None:
        _check_text(rec["rule"], "rule")
    view = _Staged(out)
    if rec["status"] == "rolled_back":
        if rec["ops"]:
            raise ValueError("a rolled-back entry must have no operations")
        if rec["version_after"] != rec["version_before"]:
            raise ValueError("a rolled-back entry must not change the version")
        return view
    for op in rec["ops"]:
        kind = op.get("op") if isinstance(op, Mapping) else None
        if kind == "put" and set(op) == {"op", "key", "value"}:
            view.put(op["key"], op["value"])
        elif kind == "delete" and set(op) == {"op", "key"}:
            view.delete(op["key"])
        else:
            raise ValueError(f"unknown or malformed operation {op!r}")
    if rec["version_after"] != rec["version_before"] + len(view.ops):
        raise ValueError(
            f"version_after {rec['version_after']} does not match "
            f"{rec['version_before']} + {len(view.ops)} operations"
        )
    return view


def replay_transactions(
    log: Iterable[TransactionRecord | Mapping[str, Any]], store: Store | None = None
) -> Store:
    """Rebuild a store by re-applying the committed entries of a transaction log in order.

    Replay is strict: it raises ``ReplayMismatch`` for an entry with missing or extra keys, a
    status other than ``"committed"`` or ``"rolled_back"``, an operation other than ``put`` or
    ``delete`` (or one that cannot apply), a rolled-back entry that has operations, and for any
    entry whose ``version_before`` or ``version_after`` does not follow from the store as
    rebuilt so far (so a missing or reordered entry is caught). Each entry is staged first and
    written only if it is fully valid, so a failing entry leaves the store as it was before
    that entry. Rolled-back entries change nothing. Entries may be records or their
    ``to_dict()`` form. ``store`` must be at the version the first entry started from (a new
    empty store for a log that began on an empty store). Returns the store.
    """
    out = Store() if store is None else store
    for item in log:
        rec = item.to_dict() if isinstance(item, TransactionRecord) else item
        try:
            rec = plain_json(dict(rec), "entry")
            view = _stage_record(out, rec)
        except (TypeError, ValueError, KeyError) as exc:
            index = rec.get("index") if isinstance(rec, Mapping) else None
            raise ReplayMismatch(f"transaction log entry {index!r} cannot replay: {exc}") from exc
        if rec["status"] == "committed":
            meta = {k: rec[k] for k in ("writer", "step", "answer", "rule")}
            _apply_ops(out, {"ops": view.ops, **meta})
    return out


# --------------------------------------------------------------------------------------
# Budget
# --------------------------------------------------------------------------------------


class Budget:
    """Named limits (retries, calls, steps...) and stop conditions, enforced in Python.

    ``Budget(calls=20, retries=3)`` creates counters. ``spend("calls")`` adds to a counter and
    raises ``BudgetExceeded`` if that would pass the limit, leaving the counter unchanged, so a
    used amount never exceeds its limit. Nothing here reads a model answer: a recipe decides
    what to spend, and the limit holds whatever the model says. ``stop_when`` maps a name to a
    predicate over a state you pass to ``check``; the first true one raises
    ``StopConditionMet``.
    """

    def __init__(
        self,
        stop_when: Mapping[str, Callable[[Any], bool]] | None = None,
        **limits: int,
    ) -> None:
        """Create counters from keyword limits (non-negative ints) and optional stop rules."""
        if not limits and not stop_when:
            raise ValueError("a budget needs at least one limit or stop condition")
        self._limits = {k: _check_int(v, f"limit {k!r}") for k, v in limits.items()}
        self._used = dict.fromkeys(self._limits, 0)
        self._stop_when = dict(stop_when or {})

    def _known(self, name: str) -> None:
        """Raise ``KeyError`` for a counter this budget does not have."""
        if name not in self._limits:
            raise KeyError(f"no budget named {name!r}; known: {sorted(self._limits)}")

    def limit(self, name: str) -> int:
        """Return the limit of counter ``name``."""
        self._known(name)
        return self._limits[name]

    def used(self, name: str) -> int:
        """Return how much of ``name`` has been spent."""
        self._known(name)
        return self._used[name]

    def remaining(self, name: str) -> int:
        """Return how much of ``name`` is left (never negative)."""
        self._known(name)
        return self._limits[name] - self._used[name]

    def can_spend(self, name: str, amount: int = 1) -> bool:
        """Return True if ``amount`` more of ``name`` fits within the limit."""
        _check_int(amount, "amount", 1)
        return amount <= self.remaining(name)

    def spend(self, name: str, amount: int = 1) -> int:
        """Spend ``amount`` (a positive int) of ``name``; return what remains.

        Raises ``BudgetExceeded`` (and changes nothing) if the limit would be passed.
        """
        _check_int(amount, "amount", 1)
        left = self.remaining(name)
        if amount > left:
            raise BudgetExceeded(
                f"budget {name!r} exceeded: asked for {amount}, "
                f"{left} of {self._limits[name]} remaining"
            )
        self._used[name] += amount
        return left - amount

    def exhausted(self, name: str) -> bool:
        """Return True when nothing is left of ``name``."""
        return self.remaining(name) == 0

    def stop_reason(self, state: Any = None) -> str | None:
        """Return the name of the first true stop condition for ``state``, or None."""
        for name, predicate in self._stop_when.items():
            if predicate(state):
                return name
        return None

    def check(self, state: Any = None) -> None:
        """Raise ``StopConditionMet`` if any stop condition is true for ``state``."""
        reason = self.stop_reason(state)
        if reason is not None:
            raise StopConditionMet(f"stop condition {reason!r} is met")

    def to_dict(self) -> dict[str, dict[str, int]]:
        """Return ``{name: {"limit", "used", "remaining"}}`` for display."""
        return {
            k: {"limit": self._limits[k], "used": self._used[k], "remaining": self.remaining(k)}
            for k in self._limits
        }
