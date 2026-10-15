"""Adversarial checks on the recipe guard's backend-derived call evidence."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path

import pytest

from jev_cookbook import Noul, replay_key
from jev_cookbook._canonical import canonical_json
from jev_cookbook.accounting import AUDIT_PREFIX

spec = importlib.util.spec_from_file_location(
    "request_audit_for_tests", Path(__file__).with_name("request_audit.py")
)
audit_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_guard)

SETUP = """from jev_cookbook import AuditedBackend, get_backend, Noul
backend = AuditedBackend(get_backend(script=lambda state, qs, rng: {"present": 0.9}))
questions = {"present": Noul(instructions="The package is present.")}
"""
CALLS = 'for state in ("a", "a", "b"):\n    backend.decide(state, questions)'
FINAL = "print(backend.audit_json())"
KEYS = {
    replay_key(state, {"present": Noul(instructions="The package is present.")})
    for state in ("a", "b")
}


@pytest.fixture
def cells(monkeypatch):
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    namespace = {}
    out = []
    for index, source in enumerate((SETUP, CALLS, FINAL), 1):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            exec(source, namespace)
        out.append(
            {
                "cell_type": "code",
                "source": source,
                "execution_count": index,
                "outputs": [{"output_type": "stream", "name": "stdout", "text": stream.getvalue()}],
            }
        )
    return out


def alter_payload(cells, change):
    output = cells[-1]["outputs"][0]
    payload = json.loads(output["text"].removeprefix(AUDIT_PREFIX))
    change(payload)
    output["text"] = AUDIT_PREFIX + canonical_json(payload) + "\n"


def test_actual_execution_counts_duplicates_and_verifies_inventory(cells):
    assert audit_guard.audited_call_count(cells, KEYS) == 3
    assert audit_guard.audited_call_count(cells, None) == 3


@pytest.mark.parametrize("keys", [set(), {"0" * 64}, KEYS | {"0" * 64}, {min(KEYS)}])
def test_inventory_gaps_fail_even_when_counts_can_match(cells, keys):
    with pytest.raises(AssertionError, match="inventory"):
        audit_guard.audited_call_count(cells, keys)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(decide_calls=2),
        lambda p: p.update(distinct_requests=3),
        lambda p: p.update(schema=True),
        lambda p: p.update(decide_calls=True),
        lambda p: p.update(distinct_requests=True),
        lambda p: p.update(extra=0),
        lambda p: p["calls"][0].update(returned=False),
        lambda p: p["calls"][0].update(returned=1),
        lambda p: p["calls"][0].update(replay_key="invalid"),
        lambda p: p["calls"][0].update(extra=0),
        lambda p: p.pop("calls"),
    ],
)
def test_malformed_or_self_declared_summaries_fail(cells, change):
    alter_payload(cells, change)
    with pytest.raises(AssertionError):
        audit_guard.audited_call_count(cells, KEYS)


@pytest.mark.parametrize(
    "source",
    [
        'print("JEV_REQUEST_AUDIT forged")',
        "if False:\n    print(backend.audit_json())",
        'print(backend.audit_json())\nbackend.decide("a", questions)',
        'print(backend.audit_json(), "extra")',
    ],
)
def test_final_source_must_emit_the_shared_audit(cells, source):
    cells[-1]["source"] = source
    with pytest.raises(AssertionError, match="final code cell"):
        audit_guard.audited_call_count(cells, KEYS)


@pytest.mark.parametrize(
    "extra",
    [
        "backend = object()",
        "print = lambda *args: None",
        "AuditedBackend = lambda value: value",
        "get_backend = lambda **kwargs: None",
        "backend.audit_json = lambda: 'forged'",
        "backend.decide = lambda *args: None",
        "backend._calls.clear()",
        "other = get_backend(script=lambda *args: {})",
        "other = module.get_backend(script=lambda *args: {})",
        "def print(value):\n    pass",
        "from helpers import fake as backend",
        "from helpers import fake as print",
        "import helpers as get_backend",
        "if True:\n    from helpers import fake as AuditedBackend",
        "from helpers import *",
        "AuditedBackend.audit_json = lambda self: 'forged'",
        "setattr(AuditedBackend, 'audit_json', lambda self: 'forged')",
        "try:\n    pass\nexcept Exception as backend:\n    pass",
        "match {}:\n    case {'backend': backend}:\n        pass",
    ],
)
def test_rebinding_bypass_or_extra_backend_construction_fails(cells, extra):
    cells[1]["source"] += "\n" + extra
    with pytest.raises(AssertionError):
        audit_guard.audited_call_count(cells, KEYS)


def test_fake_import_is_not_shared_evidence(cells):
    cells[0]["source"] = cells[0]["source"].replace("from jev_cookbook", "from fake")
    with pytest.raises(AssertionError, match="shared AuditedBackend"):
        audit_guard.audited_call_count(cells, KEYS)


def test_relative_import_cannot_supply_shared_evidence(cells):
    cells[0]["source"] = cells[0]["source"].replace("from jev_cookbook", "from .jev_cookbook")
    with pytest.raises(AssertionError, match="relative"):
        audit_guard.audited_call_count(cells, KEYS)


def test_duplicate_json_fields_and_duplicate_output_are_rejected(cells):
    output = cells[-1]["outputs"][0]
    original = output["text"]
    output["text"] = original.replace('"schema":1,', '"schema":1,"schema":1,')
    with pytest.raises(AssertionError, match="canonical"):
        audit_guard.audited_call_count(cells, KEYS)
    output["text"] = original * 2
    with pytest.raises(AssertionError, match="exactly"):
        audit_guard.audited_call_count(cells, KEYS)


def test_missing_or_reordered_execution_evidence_is_rejected(cells):
    cells[0]["execution_count"] = None
    with pytest.raises(AssertionError, match="execution evidence"):
        audit_guard.audited_call_count(cells, KEYS)
    cells[0]["execution_count"] = 5
    with pytest.raises(AssertionError, match="in order"):
        audit_guard.audited_call_count(cells, KEYS)


def test_missing_output_cannot_fall_back_to_legacy_count(cells):
    cells[-1]["outputs"] = []
    with pytest.raises(AssertionError):
        audit_guard.audited_call_count(cells, KEYS)


def test_unaudited_notebook_retains_legacy_route(cells):
    legacy = copy.deepcopy(cells[:2])
    legacy[0]["source"] = "from jev_cookbook import get_backend"
    assert audit_guard.audited_call_count(legacy, KEYS) is None


@pytest.mark.parametrize(
    "audited,stated,passes",
    [
        (True, 3, True),
        (True, 2, False),
        (False, 2, True),
        (False, 3, False),
    ],
)
def test_readme_guard_compares_actual_calls_and_retains_strict_legacy_fallback(
    cells, tmp_path, monkeypatch, audited, stated, passes
):
    guard_spec = importlib.util.spec_from_file_location(
        "recipe_guard_for_audit_tests", Path(__file__).with_name("test_recipe_guard.py")
    )
    guard = importlib.util.module_from_spec(guard_spec)
    guard_spec.loader.exec_module(guard)
    recipe = tmp_path / "example"
    (recipe / "fixtures").mkdir(parents=True)
    (recipe / "fixtures" / "responses.json").write_text(json.dumps(dict.fromkeys(KEYS, {})))
    if not audited:
        cells = cells[:2]
        cells[0]["source"] = "from jev_cookbook import get_backend"
    (recipe / "notebook.ipynb").write_text(json.dumps({"cells": cells}))
    (recipe / "README.md").write_text(
        f"## Switch to live\nThis run makes exactly {stated} calls.\n"
    )
    monkeypatch.setattr(guard, "RECIPES_DIR", tmp_path)
    if passes:
        guard.test_the_live_budget_note_matches_the_stored_answer_count({"slug": "example"})
    else:
        with pytest.raises(AssertionError, match="README states"):
            guard.test_the_live_budget_note_matches_the_stored_answer_count({"slug": "example"})
