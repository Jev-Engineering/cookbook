"""Read backend-derived budget evidence without executing a recipe in the unit guard.

The supported notebook convention is deliberately small. Source anchoring rejects detached
or literal summaries; the separate fresh-kernel notebook CI check establishes freshness.
This is not a general proof about arbitrary Python or helper implementation behavior.
"""

from __future__ import annotations

import ast
import json
import re

from jev_cookbook._canonical import canonical_json
from jev_cookbook.accounting import AUDIT_PREFIX


def _source(cell: dict) -> str:
    source = cell.get("source", "")
    return "".join(source) if isinstance(source, list) else source


def _stdout(cell: dict) -> str:
    return "".join(
        "".join(output.get("text", ""))
        for output in cell.get("outputs", [])
        if output.get("output_type") == "stream" and output.get("name") == "stdout"
    )


def audited_call_count(cells: list[dict], fixture_keys: set[str] | None) -> int | None:
    """Return verified actual calls, or None only when no audit was attempted.

    A failed/malformed/incomplete audit is an error, never a route back to the proxy.
    An audited scripted notebook needs no fixture inventory; a replay notebook must
    exercise exactly its inventory, including every key, while allowing repeated calls.
    """
    code = [cell for cell in cells if cell.get("cell_type") == "code" and _source(cell).strip()]
    trees = [ast.parse(_source(cell)) for cell in code]
    nodes = [node for tree in trees for node in ast.walk(tree)]
    output_lines = [line for cell in code for line in _stdout(cell).splitlines()]
    attempted = any(
        isinstance(node, ast.Name)
        and node.id == "AuditedBackend"
        or isinstance(node, ast.alias)
        and node.name == "AuditedBackend"
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
                    if local in {"AuditedBackend", "get_backend"}:
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
    assert len(creations) == 1, "request audit: require one top-level audited backend binding"
    creation = creations[0]
    backend_name = creation.targets[0].id
    assert backend_name not in {"AuditedBackend", "get_backend", "print"}, (
        "request audit: backend binding replaces a protected name"
    )
    protected = {"AuditedBackend", "get_backend", "print", backend_name}
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in node.names:
                assert name.name != "*", "request audit: wildcard import can replace audit bindings"
                local = name.asname or name.name.split(".")[0]
                if local in protected:
                    assert name in approved_imports and node in statements, (
                        "request audit: import replaced a protected binding"
                    )
                    assert statements.index(node) < statements.index(creation), (
                        "request audit: shared imports must precede backend construction"
                    )
    wrapper = creation.value
    assert len(wrapper.args) == 1 and not wrapper.keywords, (
        "request audit: construct AuditedBackend(get_backend(...)) directly"
    )
    factory = wrapper.args[0]
    assert (
        isinstance(factory, ast.Call)
        and isinstance(factory.func, ast.Name)
        and factory.func.id == "get_backend"
    ), "request audit: wrap get_backend directly, without a separate raw backend alias"
    constructors = {
        "AuditedBackend",
        "get_backend",
        "ReplayBackend",
        "ScriptedBackend",
        "LiveBackend",
    }
    for node in nodes:
        if isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else (node.func.attr if isinstance(node.func, ast.Attribute) else None)
            )
            if name in constructors:
                assert node is wrapper or node is factory, (
                    "request audit: additional backend construction bypasses the audit"
                )
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id in protected:
                assert node is creation.targets[0], "request audit: protected binding was replaced"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.arg)):
            name = node.arg if isinstance(node, ast.arg) else node.name
            assert name not in protected, "request audit: protected binding was shadowed"
        if isinstance(node, ast.ExceptHandler):
            assert node.name not in protected, "request audit: exception binding replaces audit"
        if isinstance(node, (ast.MatchAs, ast.MatchStar, ast.MatchMapping)):
            name = node.rest if isinstance(node, ast.MatchMapping) else node.name
            assert name not in protected, "request audit: pattern binding replaces audit"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in protected - {backend_name}:
                assert isinstance(node.ctx, ast.Load), "request audit: shared object was modified"
            if node.value.id == backend_name:
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
    expected = ast.parse(f"print({backend_name}.audit_json())").body
    assert len(final) == 1 and ast.dump(final[0]) == ast.dump(expected[0]), (
        "request audit: final code cell must be print(backend.audit_json())"
    )
    audit_calls = [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "audit_json"
    ]
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
    assert type(payload) is dict and set(payload) == {
        "schema",
        "decide_calls",
        "distinct_requests",
        "calls",
    }, "request audit: invalid audit fields"
    assert type(payload["schema"]) is int and payload["schema"] == 1, (
        "request audit: unsupported schema"
    )
    calls = payload["calls"]
    assert type(calls) is list, "request audit: missing ordered call ledger"
    keys = []
    for call in calls:
        assert type(call) is dict and set(call) == {"replay_key", "returned"}, (
            "request audit: invalid call entry"
        )
        assert type(call["replay_key"]) is str and re.fullmatch(
            r"[0-9a-f]{64}", call["replay_key"]
        ), "request audit: malformed replay key"
        assert call["returned"] is True, "request audit: a delegated call did not return"
        keys.append(call["replay_key"])
    assert type(payload["decide_calls"]) is int and payload["decide_calls"] == len(keys), (
        "request audit: stated call count differs from the actual call ledger"
    )
    assert type(payload["distinct_requests"]) is int and payload["distinct_requests"] == len(
        set(keys)
    ), "request audit: stated distinct count differs from the call ledger"
    expected_payload = {
        "schema": 1,
        "decide_calls": len(keys),
        "distinct_requests": len(set(keys)),
        "calls": [{"replay_key": key, "returned": True} for key in keys],
    }
    assert lines[0] == AUDIT_PREFIX + canonical_json(expected_payload), (
        "request audit: output is not the shared canonical audit"
    )
    if fixture_keys is not None:
        assert set(keys) == fixture_keys, (
            "request audit: executed distinct keys differ from fixture inventory "
            f"(missing={len(fixture_keys - set(keys))}, extra={len(set(keys) - fixture_keys)})"
        )
    return len(keys)
