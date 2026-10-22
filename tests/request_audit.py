"""Read backend-derived budget evidence without executing a recipe in the unit guard.

Three things are checked here, in this order, and none of them is a count the README or the
fixture file states about itself:

1. ``audited_evidence``: the notebook's committed audit line really is the shared wrapper's output
   for the backends the notebook creates (source anchoring, committed execution evidence,
   canonical form, every count recomputed from the ordered ledgers).
2. ``check_against_declaration``: that execution evidence equals the recipe's one declaration,
   ``request_budget.json``: the call count, no request decided twice unless the repeats are
   declared (the offending key is named), the exact fixture inventory, and any registered
   profile quantity.
3. ``check_readme_note``: the README holds the paragraph rendered from the declaration, byte for
   byte, and its ``## Switch to live`` section states no other request count or cap.

The supported notebook convention is deliberately small. Source anchoring rejects detached
or literal summaries; the separate fresh-kernel notebook CI check establishes freshness.
This is not a general proof about arbitrary Python or helper implementation behavior.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import NamedTuple

from jev_cookbook._canonical import canonical_json
from jev_cookbook.accounting import (
    AUDIT_PREFIX,
    AUDIT_SCHEMA,
    BUDGET_FILE,
    DEFAULT_LABEL,
    LABEL,
    NOTE_BEGIN,
    NOTE_END,
    PROFILE_COUNTERS,
    RequestBudget,
    load_budget,
    render_budget_note,
    repeated_keys,
)
from jev_cookbook.live import DEFAULT_MAX_REQUESTS

# The README sentence shapes older recipes state their count in; outside the rendered block
# a recipe that has a declaration may not state a count at all.
LIVE_CALL_COUNT = re.compile(
    r"makes\s+exactly\s+(?:\*\*)?(\d+)(?:\*\*)?\s+(?:calls?|requests?)\b"
    r"|makes\s+exactly\s+one\s+(?:call|request)\s+for\s+each\s+of\s+(?:the\s+)?(\d+)\b"
)
STORED_RESPONSES = "fixtures/responses.json"
CAP_ASSIGNMENT = re.compile(r"JEV_COOKBOOK_LIVE_MAX_REQUESTS\s*=\s*\d+")

# Every way into a backend object. An audited notebook may name these only in the one spelling
# the audit anchors on (``AuditedBackend(get_backend(...), label=...)``); any other reference,
# alias, attribute access, subclass or string naming one is a backend the ledger cannot see.
CONSTRUCTORS = frozenset(
    {
        "AuditedBackend",
        "get_backend",
        "live_backend_from_env",
        "ReplayBackend",
        "ScriptedBackend",
        "LiveBackend",
    }
)
# Ways to reach a name without writing it: the audit fails closed on these rather than guess.
DYNAMIC_NAMES = frozenset(
    {"getattr", "__import__", "eval", "exec", "compile", "globals", "locals", "vars", "importlib"}
)
DYNAMIC_ATTRS = frozenset({"__dict__", "__getattribute__", "__builtins__", "__globals__"})


class BackendEvidence(NamedTuple):
    """One audited backend's verified, ordered ledger (a NamedTuple, not a dataclass: this module
    is loaded by file path, which dataclasses' annotation lookup cannot handle)."""

    label: str
    keys: tuple[str, ...]
    profile_totals: dict[str, int]


def _source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _stdout(cell: dict) -> str:
    return "".join(
        "".join(output.get("text", ""))
        for output in cell.get("outputs", [])
        if output.get("output_type") == "stream" and output.get("name") == "stdout"
    )


def _is_call_of(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == name)
        or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
    )


def audited_evidence(cells: list[dict]) -> list[BackendEvidence] | None:
    """Return the verified ledgers, or None only when no audit was attempted.

    A failed/malformed/incomplete audit is an error, never a route back to the proxy. Every
    backend the notebook wraps is named, in creation order, by the one final audit line.
    """
    code = [cell for cell in cells if cell.get("cell_type") == "code" and _source(cell).strip()]
    trees = [ast.parse(_source(cell)) for cell in code]
    nodes = [node for tree in trees for node in ast.walk(tree)]
    output_lines = [line for cell in code for line in _stdout(cell).splitlines()]
    shared = {"AuditedBackend", "audit_json", "get_backend"}
    attempted = any(
        isinstance(node, ast.Name)
        and node.id in {"AuditedBackend", "audit_json"}
        or isinstance(node, ast.alias)
        and node.name in {"AuditedBackend", "audit_json"}
        or isinstance(node, ast.Attribute)
        and node.attr == "audit_json"
        for node in nodes
    ) or any(line.startswith(AUDIT_PREFIX) for line in output_lines)
    if not attempted:
        return None

    imports = {}
    approved_imports = set()
    statements = [node for tree in trees for node in tree.body]
    for tree in trees:
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for name in node.names:
                    local = name.asname or name.name
                    if local in shared:
                        assert node.level == 0, "request audit: relative import is not shared code"
                        assert local not in imports, f"request audit: repeated import of {local}"
                        imports[local] = (node.module, name.name)
                        approved_imports.add(name)
    assert imports.get("AuditedBackend") in {
        ("jev_cookbook", "AuditedBackend"),
        ("jev_cookbook.accounting", "AuditedBackend"),
    }, "request audit: import the shared AuditedBackend directly"
    assert imports.get("get_backend") in {
        ("jev_cookbook", "get_backend"),
        ("jev_cookbook.backends", "get_backend"),
    }, "request audit: import the shared get_backend directly"

    creations = [
        node
        for tree in trees
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "AuditedBackend"
    ]
    assert creations, "request audit: require a top-level audited backend binding"
    names = [creation.targets[0].id for creation in creations]
    assert len(set(names)) == len(names), "request audit: one binding per audited backend"
    labels = []
    wrappers = set()
    factories = set()
    for creation in creations:
        wrapper = creation.value
        assert len(wrapper.args) == 1 and len(wrapper.keywords) <= 1, (
            "request audit: construct AuditedBackend(get_backend(...), label=...) directly"
        )
        label = DEFAULT_LABEL
        if wrapper.keywords:
            (keyword,) = wrapper.keywords
            assert (
                keyword.arg == "label"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
                and LABEL.fullmatch(keyword.value.value)
            ), "request audit: label must be a string literal"
            label = keyword.value.value
        labels.append(label)
        factory = wrapper.args[0]
        assert _is_call_of(factory, "get_backend") and isinstance(factory.func, ast.Name), (
            "request audit: wrap get_backend directly, without a separate raw backend alias"
        )
        wrappers.add(wrapper)
        factories.add(factory)
    assert len(set(labels)) == len(labels), (
        "request audit: every audited backend needs its own label"
    )
    assert imports.get("audit_json", ("jev_cookbook", "audit_json")) in {
        ("jev_cookbook", "audit_json"),
        ("jev_cookbook.accounting", "audit_json"),
    }, "request audit: import the shared audit_json directly"
    assert len(creations) == 1 or "audit_json" in imports, (
        "request audit: import the shared audit_json to print several backends"
    )

    protected = shared | {"print"} | set(names)
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in node.names:
                assert name.name != "*", "request audit: wildcard import can replace audit bindings"
                local = name.asname or name.name.split(".")[0]
                if local in protected:
                    assert name in approved_imports and node in statements, (
                        "request audit: import replaced a protected binding"
                    )
                    assert statements.index(node) < statements.index(creations[0]), (
                        "request audit: shared imports must precede backend construction"
                    )
    targets = {creation.targets[0] for creation in creations}
    approved_names = {wrapper.func for wrapper in wrappers} | {
        factory.func for factory in factories
    }
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                assert name.name not in CONSTRUCTORS or name.asname in (None, name.name), (
                    f"request audit: import {name.name} under its own name, not as "
                    f"{name.asname!r}: an alias hides a backend constructor from the audit"
                )
        if isinstance(node, ast.Import):
            for name in node.names:
                assert name.name.split(".")[0] != "importlib", (
                    "request audit: importlib can reach a backend constructor the audit cannot see"
                )
        if isinstance(node, ast.Name):
            assert node.id not in DYNAMIC_NAMES, (
                f"request audit: {node.id} can reach a backend constructor the audit cannot see"
            )
            assert node.id not in CONSTRUCTORS or node in approved_names, (
                f"request audit: {node.id} is used outside AuditedBackend(get_backend(...)): "
                "additional backend construction bypasses the audit"
            )
        if isinstance(node, ast.Attribute):
            assert node.attr not in CONSTRUCTORS, (
                f"request audit: .{node.attr} reaches a backend constructor outside "
                "AuditedBackend(get_backend(...)): additional backend construction bypasses the audit"
            )
            assert node.attr not in DYNAMIC_ATTRS, (
                f"request audit: .{node.attr} can reach a backend constructor the audit cannot see"
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in CONSTRUCTORS, (
                f"request audit: the string {node.value!r} names a backend constructor"
            )
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in protected:
                assert node in targets, "request audit: protected binding was replaced"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.arg)):
            name = node.arg if isinstance(node, ast.arg) else node.name
            assert name not in protected, "request audit: protected binding was shadowed"
        if isinstance(node, ast.ExceptHandler):
            assert node.name not in protected, "request audit: exception binding replaces audit"
        if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping)):
            name = node.rest if isinstance(node, ast.MatchMapping) else node.name
            assert name not in protected, "request audit: pattern binding replaces audit"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in protected - set(names):
                assert isinstance(node.ctx, ast.Load), "request audit: shared object was modified"
            if node.value.id in names:
                assert not node.attr.startswith("_"), "request audit: private ledger access"
                if node.attr in {"audit", "audit_json", "decide"}:
                    assert isinstance(node.ctx, ast.Load), "request audit: audit method replaced"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"setattr", "delattr"}
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in protected
        ):
            raise AssertionError("request audit: dynamic modification of a protected object")

    # A separate final cell prevents a summary before later decisions or helper invocations.
    final = trees[-1].body
    accepted = [ast.parse(f"print(audit_json({', '.join(names)}))").body[0]]
    if len(names) == 1:
        accepted.append(ast.parse(f"print({names[0]}.audit_json())").body[0])
    if len(final) == 1 and ast.dump(final[0]) == ast.dump(accepted[0]):
        assert "audit_json" in imports, (
            "request audit: the final cell uses an unimported audit_json"
        )
    assert len(final) == 1 and ast.dump(final[0]) in {ast.dump(x) for x in accepted}, (
        "request audit: final code cell must be print(backend.audit_json()) "
        "or print(audit_json(<every audited backend, in creation order>))"
    )
    audit_calls = [node for node in nodes if _is_call_of(node, "audit_json")]
    assert len(audit_calls) == 1, "request audit: emit exactly one final audit"
    counts = [cell.get("execution_count") for cell in code]
    assert all(type(count) is int and count > 0 for count in counts), (
        "request audit: committed execution evidence is missing"
    )
    assert counts == sorted(set(counts)), "request audit: code cells were not executed in order"
    lines = [line for line in output_lines if line.startswith(AUDIT_PREFIX)]
    assert len(lines) == 1 and _stdout(code[-1]) == lines[0] + "\n", (
        "request audit: require exactly the shared audit line in the final cell's stdout"
    )
    try:
        payload = json.loads(lines[0][len(AUDIT_PREFIX) :])
    except (ValueError, TypeError) as exc:
        raise AssertionError("request audit: invalid JSON") from exc
    assert type(payload) is dict and set(payload) == {"schema", "backends"}, (
        "request audit: invalid audit fields"
    )
    assert type(payload["schema"]) is int and payload["schema"] == AUDIT_SCHEMA, (
        "request audit: unsupported schema"
    )
    entries = payload["backends"]
    assert type(entries) is list and len(entries) == len(labels), (
        "request audit: the audit must hold exactly the notebook's audited backends"
    )
    evidence = []
    rebuilt = []
    for label, entry in zip(labels, entries, strict=True):
        evidence_entry, canonical = _verified_entry(label, entry)
        evidence.append(evidence_entry)
        rebuilt.append(canonical)
    assert lines[0] == AUDIT_PREFIX + canonical_json(
        {"schema": AUDIT_SCHEMA, "backends": rebuilt}
    ), "request audit: output is not the shared canonical audit"
    return evidence


def _verified_entry(label: str, entry: object) -> tuple[BackendEvidence, dict]:
    core = {"label", "decide_calls", "distinct_requests", "calls"}
    assert type(entry) is dict and core <= set(entry) <= core | {"profile_totals"}, (
        "request audit: invalid audit fields"
    )
    assert entry["label"] == label, (
        f"request audit: audit entry {entry['label']!r} does not match the notebook's {label!r}"
    )
    calls = entry["calls"]
    assert type(calls) is list, "request audit: missing ordered call ledger"
    keys = []
    totals: dict[str, int] = {}
    canonical_calls = []
    for call in calls:
        assert type(call) is dict and {"replay_key", "returned"} <= set(call) <= {
            "replay_key",
            "returned",
            "profile",
        }, "request audit: invalid call entry"
        assert type(call["replay_key"]) is str and re.fullmatch(
            r"[0-9a-f]{64}", call["replay_key"]
        ), "request audit: malformed replay key"
        assert call["returned"] is True, "request audit: a delegated call did not return"
        keys.append(call["replay_key"])
        canonical_call = {"replay_key": call["replay_key"], "returned": True}
        if "profile" in call:
            profile = call["profile"]
            assert type(profile) is dict and profile, "request audit: invalid call profile"
            for name, amount in profile.items():
                assert name in PROFILE_COUNTERS, f"request audit: unknown profile quantity {name!r}"
                assert type(amount) is int and amount > 0, "request audit: invalid profile amount"
                totals[name] = totals.get(name, 0) + amount
            canonical_call["profile"] = dict(profile)
        canonical_calls.append(canonical_call)
    assert type(entry["decide_calls"]) is int and entry["decide_calls"] == len(keys), (
        "request audit: stated call count differs from the actual call ledger"
    )
    assert type(entry["distinct_requests"]) is int and entry["distinct_requests"] == len(
        set(keys)
    ), "request audit: stated distinct count differs from the call ledger"
    assert entry.get("profile_totals", {}) == totals, (
        "request audit: stated profile totals differ from the call ledger"
    )
    canonical = {
        "label": label,
        "decide_calls": len(keys),
        "distinct_requests": len(set(keys)),
        "calls": canonical_calls,
    }
    if totals:
        canonical["profile_totals"] = totals
    return BackendEvidence(label, tuple(keys), totals), canonical


def check_against_declaration(
    evidence: list[BackendEvidence], budget: RequestBudget, recipe_dir: Path
) -> None:
    """The audited execution equals the declaration, backend by backend."""
    declared = {backend.label: backend for backend in budget.backends}
    measured = {item.label: item for item in evidence}
    assert set(declared) == set(measured), (
        f"request audit: {BUDGET_FILE} declares backends {sorted(declared)}, "
        f"the notebook audits {sorted(measured)}"
    )
    for label, backend in declared.items():
        keys = list(measured[label].keys)
        repeats = repeated_keys(keys)
        if backend.distinct == backend.requests and repeats:
            key, times = next(iter(repeats.items()))
            raise AssertionError(
                f"request audit: backend {label!r} decided the same request {times} times "
                f"(replay_key {key}; {len(repeats)} repeated key(s) in all) -- a live run pays "
                "for each; decide it once and reuse the answer, or declare the repeats"
            )
        assert len(keys) == backend.requests, (
            f"request audit: backend {label!r} made {len(keys)} decide() calls, "
            f"{BUDGET_FILE} declares {backend.requests}"
        )
        assert len(set(keys)) == backend.distinct, (
            f"request audit: backend {label!r} made {len(set(keys))} distinct requests, "
            f"{BUDGET_FILE} declares {backend.distinct}"
        )
        assert measured[label].profile_totals == dict(backend.profile), (
            f"request audit: backend {label!r} profile {measured[label].profile_totals}, "
            f"{BUDGET_FILE} declares {dict(backend.profile)}"
        )
        if backend.fixtures is not None:
            path = recipe_dir / backend.fixtures
            assert path.is_file(), f"request audit: declared fixtures {backend.fixtures} not found"
            inventory = set(json.loads(path.read_text("utf-8")))
            assert set(keys) == inventory, (
                "request audit: executed distinct keys differ from fixture inventory "
                f"(missing={len(inventory - set(keys))}, extra={len(set(keys) - inventory)})"
            )
    stored = recipe_dir / STORED_RESPONSES
    if stored.is_file():
        assert any(
            backend.fixtures is not None and Path(backend.fixtures) == Path(STORED_RESPONSES)
            for backend in budget.backends
        ), (
            f"request audit: the recipe stores {STORED_RESPONSES} but {BUDGET_FILE} declares no "
            "backend that replays it, so unused or missing stored answers would go unchecked"
        )


def check_readme_note(readme: str, budget: RequestBudget) -> None:
    """The README holds the paragraph rendered from the declaration, in ``## Switch to live``, and
    that section states no other request count or cap (see ``stray_count_sentences`` for the reach)."""
    expected = render_budget_note(budget)
    assert readme.count(NOTE_BEGIN) == 1 and readme.count(NOTE_END) == 1, (
        f"request audit: README needs exactly one {NOTE_BEGIN} ... {NOTE_END} block "
        "(jev_cookbook.accounting.render_recipe_note prints it)"
    )
    start = readme.index(NOTE_BEGIN)
    end = readme.index(NOTE_END) + len(NOTE_END)
    assert start < end, "request audit: README budget markers are out of order"
    assert readme[start:end] == expected.rstrip("\n"), (
        "request audit: README budget paragraph differs from the one rendered from "
        f"{BUDGET_FILE}; do not edit it by hand, render it"
    )
    heading = readme.find("\n## Switch to live")
    assert heading != -1 and heading < start and "\n## " not in readme[heading + 4 : start], (
        "request audit: the rendered paragraph belongs in the README's '## Switch to live' section"
    )
    outside = readme[:start] + readme[end:]
    assert not LIVE_CALL_COUNT.search(outside) and not CAP_ASSIGNMENT.search(outside), (
        f"request audit: README states a request count or cap outside the rendered block; "
        f"{BUDGET_FILE} is the one source"
    )
    section_end = readme.find("\n## ", end)
    section_end = len(readme) if section_end == -1 else section_end
    stray = stray_count_sentences(readme[heading:start] + readme[end:section_end])
    assert not stray, (
        "request audit: a sentence in '## Switch to live' outside the rendered block states a "
        f"number beside request, call, budget, cap or raise wording ({stray[0]!r}"
        + (f" and {len(stray) - 1} more" if len(stray) > 1 else "")
        + f"); {BUDGET_FILE} is the one source, so remove it"
    )


# Wording that makes a number in the budget section a claim about requests or the cap.
CLAIM_WORDS = re.compile(
    r"requests?|calls?|budget|\bcap\b|JEV_COOKBOOK_LIVE_MAX_REQUESTS|\braise\b|set it to"
    r"|or higher|at least|at most|up to",
    re.IGNORECASE,
)


def stray_count_sentences(section: str) -> list[str]:
    """Sentences of ``section`` that pair a number with request/call/budget/cap/raise wording.

    A number in a link target or a version (``3.14``) is not a count, and the library default
    (``DEFAULT_MAX_REQUESTS``) may be named in a sentence that says "default". Spelled-out numbers
    ("forty") and prose outside the budget section are not read: this is a reach to state, not a
    proof, and a migrating recipe's reviewer still reads the section.
    """
    text = re.sub(r"\]\([^)]*\)", "]", section)
    text = re.sub(r"\b\d+(?:\.\d+)+\b", "", text)
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n\s*\n", text):
        numbers = [int(n) for n in re.findall(r"\d+", sentence)]
        if "default" in sentence.lower():
            numbers = [n for n in numbers if n != DEFAULT_MAX_REQUESTS]
        if numbers and CLAIM_WORDS.search(sentence):
            found.append(" ".join(sentence.split())[:100])
    return found


def audit_recipe(recipe_dir: Path, cells: list[dict]) -> int | None:
    """Verify one recipe's audit route; return the declared live total, or None for the legacy route.

    The declaration, an audited notebook and the rendered README paragraph come together or
    not at all: any one of them without the other two fails (a paragraph with neither of the
    others, a declaration or an audit line without the rest), so nothing can quietly keep the
    old proxy while reading like audited output.
    """
    evidence = audited_evidence(cells)
    declared = (recipe_dir / BUDGET_FILE).is_file()
    if evidence is None and not declared:
        readme = recipe_dir / "README.md"
        text = readme.read_text("utf-8") if readme.is_file() else ""
        assert NOTE_BEGIN not in text and NOTE_END not in text, (
            f"request audit: the README holds the rendered budget paragraph but the recipe has no "
            f"{BUDGET_FILE} and no audited notebook; the paragraph, the declaration and the audit "
            "line come together or not at all"
        )
        return None
    assert declared, f"request audit: an audited notebook needs {BUDGET_FILE} (the declared count)"
    assert evidence is not None, (
        f"request audit: {BUDGET_FILE} declares a count but the notebook emits no audit line"
    )
    budget = load_budget(recipe_dir)
    check_against_declaration(evidence, budget, recipe_dir)
    check_readme_note((recipe_dir / "README.md").read_text("utf-8"), budget)
    return budget.total
