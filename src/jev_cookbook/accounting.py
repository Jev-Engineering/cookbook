"""Count actual backend decisions independently of distinct replay fixtures.

Two things live here: the ledger a notebook prints (:class:`AuditedBackend`,
:func:`audit_json`) and the one declaration a recipe makes about it (``request_budget.json``,
:func:`parse_budget`, :func:`render_budget_note`).

The audit line
    ``JEV_REQUEST_AUDIT {"schema":2,"backends":[{...}]}``: one entry per audited backend, in the
    order the notebook names them. An entry is ``label``, ``decide_calls``, ``distinct_requests``
    and the ordered ``calls`` (each ``replay_key`` and whether the delegate ``returned``);
    both counts are derived from ``calls``.

Extension point (how a later change adds a counted quantity without breaking a notebook)
    A quantity that is measured per request, such as the images a request carries, is a *profile*
    entry: register a counter in :data:`PROFILE_COUNTERS` (name -> ``counter(state, questions,
    assets) -> int``). A call then carries ``"profile": {name: n}`` and the backend entry carries
    ``"profile_totals": {name: sum}``. A zero is **omitted**, and both keys are omitted when empty,
    so a notebook that never uses the quantity prints byte-for-byte the line it printed before the
    quantity existed, and its committed output stays valid. Core fields never change meaning; a
    change to one of those is the only thing that bumps :data:`AUDIT_SCHEMA`. The verifier in
    ``tests/request_audit.py`` accepts exactly the registered names, recomputes every total from
    the calls, and compares the totals with the recipe's declared ``profile``. This module
    registers two itself for requests that carry images: ``images`` (copies, every place a
    reference is replaced by its image) and ``distinct_images`` (assets uploaded); counts only.

The declaration
    ``request_budget.json`` beside the notebook is the one place a recipe states its live request
    count. The README's budget paragraph is *rendered* from it (:func:`render_budget_note`), never
    typed, and the guard compares the README, the declaration and the audited execution.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._canonical import canonical_json
from .answers import DecisionResult
from .backends import Assets, Backend, replay_key
from .live import DEFAULT_MAX_REQUESTS
from .questions import Question

AUDIT_PREFIX = "JEV_REQUEST_AUDIT "
AUDIT_SCHEMA = 2
BUDGET_FILE = "request_budget.json"
BUDGET_SCHEMA = 1
DEFAULT_LABEL = "main"
NOTE_BEGIN = "<!-- request-budget:begin -->"
NOTE_END = "<!-- request-budget:end -->"

LABEL = re.compile(r"[a-z][a-z0-9_-]{0,31}")
PROFILE_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")

ProfileCounter = Callable[[Any, Mapping[str, Question], "Assets | None"], int]

# The extension registry (see the module docstring). A text-only request has no per-request
# quantity beyond the call itself; the image quantities below are registered when this module is
# imported, so ``import jev_cookbook`` is all a notebook or the guard needs.
PROFILE_COUNTERS: dict[str, ProfileCounter] = {}


def register_profile(name: str, counter: ProfileCounter) -> None:
    """Add a per-request quantity to the audit (the extension point; see the module docstring)."""
    if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name):
        raise ValueError(f"profile name must match {PROFILE_NAME.pattern!r}, got {name!r}")
    if name in PROFILE_COUNTERS:
        raise ValueError(f"profile {name!r} is already registered")
    PROFILE_COUNTERS[name] = counter


__all__ = [
    "AUDIT_PREFIX",
    "AUDIT_SCHEMA",
    "BUDGET_FILE",
    "NOTE_BEGIN",
    "NOTE_END",
    "PROFILE_COUNTERS",
    "AuditedBackend",
    "BackendBudget",
    "RequestBudget",
    "audit_json",
    "load_budget",
    "parse_budget",
    "register_profile",
    "render_budget_note",
    "render_recipe_note",
    "repeated_keys",
]


def _image_counter(field: str) -> ProfileCounter:
    """A counter for one count of ``vision.image_request_profile`` (copies or distinct assets)."""

    def count(state: Any, questions: Mapping[str, Question], assets: Assets | None) -> int:
        if not assets:
            return 0  # a text-only request never imports the image code
        from .vision import image_request_profile

        return getattr(image_request_profile(state, questions, assets), field)

    return count


# ``images``: the image copies a request expands to (every place a reference is replaced, an
# image in the instructions once per question); ``distinct_images``: the assets it uploads.
# Counts only, never bytes or content. Both are zero, hence omitted, for a text-only request.
register_profile("images", _image_counter("copies"))
register_profile("distinct_images", _image_counter("distinct_assets"))


class AuditedBackend:
    """Delegate every decision, preserving an ordered, duplicate-inclusive request ledger.

    A ledger entry is added immediately before delegation. ``returned`` becomes true only
    after the delegate returns; exceptions propagate unchanged and leave a false entry.
    Requests rejected while computing their replay key never reach the delegate and are
    not counted. These are logical ``decide`` calls, not HTTP attempts or paid requests.

    ``label`` names this backend in the audit line and in ``request_budget.json``; a notebook
    that audits several backends gives each its own label (the live budget is per backend, so a
    second backend is a second budget, which is why it is named rather than merged).

    Public backend settings and live recorder attributes are forwarded, including writes
    such as ``max_retries = 0``. Mode, model and recorded dates remain dynamic. No responses,
    request contents, assets, credentials, timestamps or latency appear in the audit.
    """

    __slots__ = ("_backend", "_calls", "_label")

    def __init__(self, backend: Backend, *, label: str = DEFAULT_LABEL) -> None:
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            raise ValueError(f"audit label must match {LABEL.pattern!r}, got {label!r}")
        self._backend = backend
        self._label = label
        self._calls: list[tuple[str, bool, dict[str, int]]] = []

    @property
    def audit_label(self) -> str:
        return self._label

    @property
    def mode(self) -> str:
        return self._backend.mode

    @property
    def model(self) -> str:
        return self._backend.model

    @property
    def recorded_dates(self) -> tuple[str, ...]:
        return getattr(self._backend, "recorded_dates", ())

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._backend, name, value)

    def __enter__(self) -> AuditedBackend:
        self._backend.__enter__()
        return self

    def __exit__(self, *exc: object) -> Any:
        return self._backend.__exit__(*exc)

    def decide(
        self, state: Any, questions: Mapping[str, Question], *, assets: Assets | None = None
    ) -> DecisionResult:
        key = replay_key(state, questions, assets=assets)
        profile = _profile(state, questions, assets)
        index = len(self._calls)
        self._calls.append((key, False, profile))
        result = (
            self._backend.decide(state, questions)
            if assets is None
            else self._backend.decide(state, questions, assets=assets)
        )
        self._calls[index] = (key, True, profile)
        return result

    def audit(self) -> dict[str, Any]:
        """A fresh snapshot of this backend's entry; every count is derived from the calls."""
        calls = []
        totals: dict[str, int] = {}
        for key, returned, profile in self._calls:
            call: dict[str, Any] = {"replay_key": key, "returned": returned}
            if profile:
                call["profile"] = dict(profile)
                for name, amount in profile.items():
                    totals[name] = totals.get(name, 0) + amount
            calls.append(call)
        entry: dict[str, Any] = {
            "label": self._label,
            "decide_calls": len(self._calls),
            "distinct_requests": len({key for key, _, _ in self._calls}),
            "calls": calls,
        }
        if totals:
            entry["profile_totals"] = totals
        return entry

    def audit_json(self) -> str:
        """The deterministic, machine-readable line printed at the end of a notebook."""
        return audit_json(self)


def audit_json(*backends: AuditedBackend) -> str:
    """The one audit line for every audited backend a notebook created, in the order given.

    A notebook with several audited backends prints ``audit_json(a, b)`` once, in its final cell.
    """
    if not backends or not all(isinstance(backend, AuditedBackend) for backend in backends):
        raise TypeError("audit_json takes one or more AuditedBackend objects")
    labels = [backend.audit_label for backend in backends]
    if len(set(labels)) != len(labels):
        raise ValueError(f"audited backends need distinct labels, got {labels}")
    payload = {"schema": AUDIT_SCHEMA, "backends": [backend.audit() for backend in backends]}
    return AUDIT_PREFIX + canonical_json(payload)


def _profile(
    state: Any, questions: Mapping[str, Question], assets: Assets | None
) -> dict[str, int]:
    """The registered per-request quantities of one request; zeros are omitted."""
    out: dict[str, int] = {}
    for name in sorted(PROFILE_COUNTERS):
        amount = PROFILE_COUNTERS[name](state, questions, assets)
        if type(amount) is not int or amount < 0:
            raise ValueError(f"profile counter {name!r} must return a non-negative int")
        if amount:
            out[name] = amount
    return out


def repeated_keys(keys: list[str]) -> dict[str, int]:
    """Each replay key a ledger holds more than once, with how many times, in first-seen order."""
    seen: dict[str, int] = {}
    for key in keys:
        seen[key] = seen.get(key, 0) + 1
    return {key: count for key, count in seen.items() if count > 1}


# --------------------------------------------------------------------------------------------
# The declaration: request_budget.json
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BackendBudget:
    """What one audited backend is declared to do in a live run.

    ``requests`` is the number of ``decide`` calls; ``distinct`` the number of different
    requests among them (equal to ``requests`` unless the notebook repeats a request on
    purpose, in which case it is declared, never inferred); ``fixtures`` the recipe-relative
    replay file whose keys the backend must exercise exactly, or ``None`` for a scripted lane;
    ``profile`` the declared totals of any registered per-request quantity; ``at_most`` the
    most requests a live run can make when the count depends on the answers (a cascade whose
    second stage runs only for some first-stage answers, a game played by a model's own
    moves): the audited execution replays the committed answers and so measures ``requests``,
    and cannot see the other paths, so the author states the bound (equal to ``requests`` when
    nothing depends on an answer).
    """

    label: str
    requests: int
    distinct: int
    fixtures: str | None
    profile: tuple[tuple[str, int], ...] = ()
    at_most: int = 0

    def __post_init__(self) -> None:
        if self.at_most == 0:
            object.__setattr__(self, "at_most", self.requests)


@dataclass(frozen=True)
class RequestBudget:
    backends: tuple[BackendBudget, ...]

    @property
    def total(self) -> int:
        """What the run is billed against the committed answers: the sum over backends."""
        return sum(b.requests for b in self.backends)

    @property
    def worst_total(self) -> int:
        """What the run is billed if every answer sends it down its longest path."""
        return sum(b.at_most for b in self.backends)

    @property
    def cap(self) -> int:
        """The smallest ``JEV_COOKBOOK_LIVE_MAX_REQUESTS`` that cannot stop the run: the budget
        is per backend and inclusive, so it is the largest single backend's worst case, not the
        total."""
        return max(b.at_most for b in self.backends)


def _whole(value: Any, where: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{BUDGET_FILE}: {where} must be a whole number of at least {minimum}")
    return value


def parse_budget(data: Any) -> RequestBudget:
    """Validate a decoded ``request_budget.json``; every unexpected field is an error.

    ``{"schema": 1, "backends": {"main": {"requests": 40, "fixtures": "fixtures/responses.json"}}}``;
    each backend may also carry ``"distinct"`` and ``"at_most"`` (both default: ``requests``)
    and ``"profile"``.
    """
    if type(data) is not dict or set(data) != {"schema", "backends"}:
        raise ValueError(f"{BUDGET_FILE}: expected exactly the fields 'schema' and 'backends'")
    if type(data["schema"]) is not int or data["schema"] != BUDGET_SCHEMA:
        raise ValueError(f"{BUDGET_FILE}: unsupported schema {data['schema']!r}")
    declared = data["backends"]
    if type(declared) is not dict or not declared:
        raise ValueError(f"{BUDGET_FILE}: 'backends' must name at least one audited backend")
    backends = []
    for label, body in declared.items():
        if not LABEL.fullmatch(label):
            raise ValueError(f"{BUDGET_FILE}: backend label {label!r} must match {LABEL.pattern!r}")
        allowed = {"requests", "fixtures", "distinct", "profile", "at_most"}
        if type(body) is not dict or not {"requests", "fixtures"} <= set(body) <= allowed:
            raise ValueError(
                f"{BUDGET_FILE}: backend {label!r} needs 'requests' and 'fixtures' "
                "(a recipe-relative replay file, or null for a scripted backend) "
                "and may add 'distinct', 'at_most' and 'profile'"
            )
        requests = _whole(body["requests"], f"{label}.requests", 1)
        distinct = _whole(body.get("distinct", requests), f"{label}.distinct", 1)
        if distinct > requests:
            raise ValueError(f"{BUDGET_FILE}: {label}.distinct cannot exceed requests")
        at_most = _whole(body.get("at_most", requests), f"{label}.at_most", 1)
        if at_most < requests:
            raise ValueError(f"{BUDGET_FILE}: {label}.at_most cannot be below requests")
        fixtures = body["fixtures"]
        if fixtures is not None and (
            type(fixtures) is not str
            or not fixtures
            or fixtures.startswith(("/", "\\"))
            or ".." in Path(fixtures).parts
            or "\\" in fixtures
            or ":" in fixtures
        ):
            raise ValueError(
                f"{BUDGET_FILE}: {label}.fixtures must be null or a path inside the recipe"
            )
        profile = body.get("profile", {})
        if type(profile) is not dict or not all(name in PROFILE_COUNTERS for name in profile):
            raise ValueError(
                f"{BUDGET_FILE}: {label}.profile names only registered quantities "
                f"({sorted(PROFILE_COUNTERS)})"
            )
        totals = tuple(
            (name, _whole(amount, f"{label}.profile.{name}", 1))
            for name, amount in sorted(profile.items())
        )
        backends.append(BackendBudget(label, requests, distinct, fixtures, totals, at_most))
    return RequestBudget(tuple(backends))


def load_budget(recipe_dir: Path) -> RequestBudget:
    """The validated declaration in ``recipe_dir``."""
    return parse_budget(
        json.loads((recipe_dir / BUDGET_FILE).read_text("utf-8"), object_pairs_hook=_unique_keys)
    )


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``json`` keeps the last of two equal keys silently; a declaration may not say a thing twice."""
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError(
            f"{BUDGET_FILE}: a key appears twice ({sorted(k for k in keys if keys.count(k) > 1)})"
        )
    return dict(pairs)


def render_budget_note(budget: RequestBudget) -> str:
    """The README's budget paragraph for ``budget``, markers included, byte for byte.

    This is the only place the sentence is written. The guard re-renders it and demands the
    README contain it unchanged, so a README count cannot be typed, edited or left behind when
    the declaration moves.
    """
    backends = budget.backends
    if len(backends) == 1:
        (only,) = backends
        first = f"In live mode this notebook makes exactly **{budget.total}** requests"
        first += _repeats(only, whole=True)
        if only.at_most > only.requests:
            first += (
                f" when every live answer matches the committed one, and up to "
                f"**{only.at_most}** when a live answer sends it down a longer path"
            )
    else:
        parts = "; ".join(f"`{b.label}` {b.requests}{_detail(b)}" for b in backends)
        first = (
            f"In live mode this notebook makes exactly **{budget.total}** requests across "
            f"{len(backends)} audited backends, each with its own budget ({parts})"
        )
    cap = budget.cap
    scope = (
        "Each backend counts separately, so the cap is the largest single count, not the total. "
        if len(backends) > 1
        else ""
    )
    second = (
        f"{scope}Set `JEV_COOKBOOK_LIVE_MAX_REQUESTS={cap}` or higher before running it live "
        f"(the default cap is {DEFAULT_MAX_REQUESTS}): the cap is inclusive and every attempt counts "
        "against it, retries included, so a lower cap stops the run partway through with "
        "`BudgetExceeded` and a run that retries needs more."
    )
    return f"{NOTE_BEGIN}\n{first}. {second}\n{NOTE_END}\n"


def render_recipe_note(recipe_dir: str | Path) -> str:
    """:func:`render_budget_note` for the declaration in ``recipe_dir``; what to paste into the
    README: ``python -c "from jev_cookbook.accounting import render_recipe_note as r;
    print(r('recipes/NN-slug'), end='')"``."""
    return render_budget_note(load_budget(Path(recipe_dir)))


def _repeats(backend: BackendBudget, whole: bool = False) -> str:
    if backend.distinct == backend.requests:
        return ", each decided once" if whole else ""
    extra = backend.requests - backend.distinct
    return (
        f", of which {backend.distinct} are distinct (the other {extra} repeat a request on purpose)"
        if whole
        else f"{backend.distinct} distinct, {extra} repeated on purpose"
    )


def _detail(backend: BackendBudget) -> str:
    """The parenthetical a backend adds to its entry in a multi-backend sentence, if any."""
    notes = []
    if backend.distinct != backend.requests:
        notes.append(_repeats(backend))
    if backend.at_most > backend.requests:
        notes.append(f"up to {backend.at_most} if live answers differ")
    return f" ({'; '.join(notes)})" if notes else ""
