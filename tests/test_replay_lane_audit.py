"""Positive and mutation controls for declared replay-only notebook lanes (#371)."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path

import pytest

from jev_cookbook import Noul, replay_key
from jev_cookbook._canonical import canonical_json
from jev_cookbook.accounting import AUDIT_PREFIX, parse_budget

spec = importlib.util.spec_from_file_location(
    "replay_lane_audit_guard", Path(__file__).with_name("request_audit.py")
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SETUP = """from jev_cookbook import AuditedBackend, ReplayBackend, audit_json, get_backend, Noul
current = AuditedBackend(get_backend(fixtures="saved.json"), label="current")
saved = AuditedBackend(ReplayBackend.from_json("saved.json"), label="saved", replay_only=True)
questions = {"present": Noul(instructions="The package is present.")}
"""
CALLS = 'current.decide("a", questions)\nsaved.decide("a", questions)'
FINAL = "print(audit_json(current, saved))"


@pytest.fixture
def replay_case(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    key = replay_key("a", {"present": Noul(instructions="The package is present.")})
    (tmp_path / "saved.json").write_text(
        json.dumps(
            {
                key: {
                    "model": "synthetic",
                    "answers": {
                        "present": {
                            "type": "noul",
                            "noul": 0.9,
                            "provenance": {"source": "synthetic", "model": None, "date": None},
                        }
                    },
                }
            }
        )
    )
    namespace = {}
    cells = []
    for count, source in enumerate((SETUP, CALLS, FINAL), 1):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(source, namespace)
        cells.append(
            {
                "cell_type": "code",
                "source": source,
                "execution_count": count,
                "outputs": [{"output_type": "stream", "name": "stdout", "text": output.getvalue()}],
            }
        )
    data = {
        "schema": 1,
        "backends": {
            "current": {"requests": 1, "fixtures": "saved.json"},
            "saved": {"requests": 1, "fixtures": "saved.json", "replay_only": True},
        },
    }
    return cells, data, tmp_path


def test_declared_replay_lane_passes_and_keeps_source_metadata(replay_case):
    cells, data, folder = replay_case
    evidence = guard.audited_evidence(cells)
    guard.check_against_declaration(evidence, parse_budget(data), folder)
    assert evidence[0].replay_fixtures is None
    assert evidence[1].replay_fixtures == "saved.json"
    assert evidence[1].source == {"mode": "synthetic", "model": "synthetic", "recorded_dates": []}


@pytest.mark.parametrize(
    "old,new",
    [
        ('ReplayBackend.from_json("saved.json")', 'get_backend(fixtures="saved.json")'),
        ('ReplayBackend.from_json("saved.json")', "ReplayBackend({})"),
        ('ReplayBackend.from_json("saved.json")', "ReplayBackend.from_json(path)"),
        ('ReplayBackend.from_json("saved.json")', 'ReplayBackend.from_json("saved" + ".json")'),
        ('ReplayBackend.from_json("saved.json")', 'ReplayBackend.from_json("../saved.json")'),
        ('ReplayBackend.from_json("saved.json")', 'ReplayBackend.from_json("/tmp/saved.json")'),
        ('ReplayBackend.from_json("saved.json")', "ReplayBackend.from_json(**options)"),
        ("replay_only=True", "replay_only=1"),
        ("replay_only=True", "replay_only=False"),
        ("replay_only=True", "replay_only=flag"),
        (", replay_only=True", ""),
        (', label="saved"', ""),
        ("ReplayBackend, audit_json", "ReplayBackend as R, audit_json"),
        ('ReplayBackend.from_json("saved.json")', 'R.from_json("saved.json")'),
        ('ReplayBackend.from_json("saved.json")', 'getattr(module, name)("saved.json")'),
        ('label="saved"', 'label="current"'),
    ],
)
def test_unsafe_or_ambiguous_replay_constructions_fail_closed(replay_case, old, new):
    cells, _, _ = replay_case
    cells[0]["source"] = cells[0]["source"].replace(old, new)
    assert cells[0]["source"] != SETUP
    with pytest.raises(AssertionError, match="request audit"):
        guard.audited_evidence(cells)


@pytest.mark.parametrize(
    "extra",
    [
        'other = ReplayBackend.from_json("saved.json")',
        "factory = ReplayBackend",
        "ReplayBackend.from_json = lambda path: current",
        "saved = current",
        "saved.decide = current.decide",
        "saved._backend = current",
        'setattr(saved, "mode", "live")',
        'factory = getattr(module, "ReplayBackend")',
        'factory = getattr(module, "Replay" + "Backend")',
        "import importlib",
    ],
)
def test_aliases_mutations_and_extra_backends_are_rejected(replay_case, extra):
    cells, _, _ = replay_case
    cells[1]["source"] += "\n" + extra
    with pytest.raises(AssertionError, match="request audit"):
        guard.audited_evidence(cells)


def change_output(cells, edit):
    output = cells[-1]["outputs"][0]
    payload = json.loads(output["text"].removeprefix(AUDIT_PREFIX))
    edit(payload["backends"][1])
    output["text"] = AUDIT_PREFIX + canonical_json(payload) + "\n"


@pytest.mark.parametrize(
    "edit",
    [
        lambda entry: entry.pop("replay_only"),
        lambda entry: entry.pop("source"),
        lambda entry: entry.update(replay_only=False),
        lambda entry: entry.update(decide_calls=0),
        lambda entry: entry["source"].update(mode="live"),
        lambda entry: entry["source"].update(model="another-model"),
        lambda entry: entry["source"].update(recorded_dates=["2026-10-01"]),
        lambda entry: entry["source"].update(extra=True),
    ],
)
def test_tampered_counts_or_replay_provenance_are_rejected(replay_case, edit):
    cells, data, folder = replay_case
    change_output(cells, edit)
    with pytest.raises(AssertionError, match="request audit"):
        evidence = guard.audited_evidence(cells)
        guard.check_against_declaration(evidence, parse_budget(data), folder)


@pytest.mark.parametrize(
    "change", [{"replay_only": False}, {"fixtures": "other.json"}, {"requests": 2}, {"distinct": 0}]
)
def test_replay_declaration_must_match_constructed_and_executed_lane(replay_case, change):
    cells, data, folder = replay_case
    data["backends"]["saved"].update(change)
    with pytest.raises((AssertionError, ValueError)):
        guard.check_against_declaration(guard.audited_evidence(cells), parse_budget(data), folder)


def test_a_live_capable_construction_cannot_disguise_itself_as_replay(replay_case):
    cells, data, folder = replay_case
    data["backends"]["current"]["replay_only"] = True
    with pytest.raises(AssertionError, match="disagree"):
        guard.check_against_declaration(guard.audited_evidence(cells), parse_budget(data), folder)


def test_replay_path_cannot_resolve_to_an_external_fixture(replay_case, tmp_path):
    cells, data, folder = replay_case
    outside = folder.parent / (folder.name + "-outside.json")
    outside.write_bytes((folder / "saved.json").read_bytes())
    (folder / "saved.json").unlink()
    try:
        (folder / "saved.json").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symbolic links")
    with pytest.raises(AssertionError, match="outside the recipe"):
        guard.check_against_declaration(guard.audited_evidence(cells), parse_budget(data), folder)


def test_ordinary_live_capable_ledger_cannot_add_replay_fields(replay_case):
    cells, _, _ = replay_case
    output = cells[-1]["outputs"][0]
    payload = json.loads(output["text"].removeprefix(AUDIT_PREFIX))
    payload["backends"][0].update(source=copy.deepcopy(payload["backends"][1]["source"]))
    output["text"] = AUDIT_PREFIX + canonical_json(payload) + "\n"
    with pytest.raises(AssertionError, match="invalid audit fields"):
        guard.audited_evidence(cells)


@pytest.mark.parametrize("position", ["before-live", "between-lanes", "after-replay"])
def test_replay_constructor_import_precedes_its_own_first_use(replay_case, position):
    cells, data, folder = replay_case
    lines = cells[0]["source"].splitlines()
    lines[0] = lines[0].replace("AuditedBackend, ReplayBackend,", "AuditedBackend,")
    index = {"before-live": 1, "between-lanes": 2, "after-replay": 3}[position]
    lines.insert(index, "from jev_cookbook import ReplayBackend")
    cells[0]["source"] = "\n".join(lines)
    assert cells[0]["source"] != SETUP
    if position == "after-replay":
        with pytest.raises(AssertionError, match="imports must precede"):
            guard.audited_evidence(cells)
    else:
        evidence = guard.audited_evidence(cells)
        guard.check_against_declaration(evidence, parse_budget(data), folder)
