"""Declared replay lanes: synthetic unit controls, never service/inference evidence."""

import json
from types import SimpleNamespace

import pytest

from jev_cookbook import AuditedBackend, Noul, ReplayBackend, ReplayMiss, replay_key
from jev_cookbook.accounting import parse_budget, render_budget_note

QUESTIONS = {"present": Noul(instructions="The package is present.")}
KEY = replay_key("a", QUESTIONS)


def responses(recorded=False):
    provenance = {"source": "synthetic", "model": None, "date": None}
    model = "synthetic"
    if recorded:
        # A fabricated serialization control, not captured inference or a new model claim.
        model = "jev-1.13.0"
        provenance = {"source": "recorded", "model": model, "date": "2026-10-01"}
    return {
        KEY: {
            "model": model,
            "usage": {"input_tokens": None, "output_tokens": None},
            "answers": {"present": {"type": "noul", "noul": 0.9, "provenance": provenance}},
        }
    }


def test_replay_cannot_switch_to_live_even_with_live_environment(tmp_path, monkeypatch):
    import jev_cookbook.backends as backends

    def fail(*args, **kwargs):
        raise AssertionError("replay reached live construction")

    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setattr(backends, "_make_live_backend", fail)
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(responses()))
    lane = AuditedBackend(ReplayBackend.from_json(path), label="saved", replay_only=True)
    assert lane.decide("a", QUESTIONS).source == "synthetic"
    assert lane.audit()["source"] == {
        "mode": "synthetic",
        "model": "synthetic",
        "recorded_dates": [],
    }
    assert lane.audit()["replay_only"] is True
    assert not hasattr(lane, "requests_made")


def test_only_exact_replay_type_is_allowed_before_any_delegate_call():
    class Pretender:
        mode = "recorded"

        def decide(self, *args, **kwargs):
            raise AssertionError("must not delegate")

    class Subclass(ReplayBackend):
        pass

    for backend in (Pretender(), SimpleNamespace(mode="live"), Subclass(responses())):
        with pytest.raises(TypeError, match="exact ReplayBackend"):
            AuditedBackend(backend, label="saved", replay_only=True)


@pytest.mark.parametrize("value", [1, 0, None, "true", [], {}])
def test_replay_flag_is_a_bool(value):
    with pytest.raises(TypeError, match="must be a bool"):
        AuditedBackend(ReplayBackend(responses()), replay_only=value)


def test_snapshot_and_immutability_prevent_delegate_substitution():
    original = ReplayBackend(responses())
    lane = AuditedBackend(original, label="saved", replay_only=True)
    original.decide = lambda *args, **kwargs: pytest.fail("mutable original used")
    original.mode = "live"
    original._stored.clear()
    assert lane.decide("a", QUESTIONS).source == "synthetic"
    for name, value in (
        ("_backend", original),
        ("_replay_only", False),
        ("mode", "live"),
        ("decide", original.decide),
        ("max_retries", 1),
    ):
        with pytest.raises(AttributeError, match="immutable"):
            setattr(lane, name, value)
    with pytest.raises(AttributeError, match="immutable"):
        del lane._replay_only


def test_recorded_replay_preserves_source_and_dates_without_new_recording():
    stored = responses(recorded=True)
    lane = AuditedBackend(ReplayBackend(stored), label="saved", replay_only=True)
    assert lane.decide("a", QUESTIONS).to_dict() == stored[KEY]
    assert lane.audit()["source"] == {
        "mode": "recorded",
        "model": "jev-1.13.0",
        "recorded_dates": ["2026-10-01"],
    }
    assert not hasattr(lane, "recorded")
    assert not hasattr(lane, "accounting")


def test_repeated_replay_and_miss_keep_an_honest_ordered_ledger():
    lane = AuditedBackend(ReplayBackend(responses()), label="saved", replay_only=True)
    lane.decide("a", QUESTIONS)
    lane.decide("a", QUESTIONS)
    with pytest.raises(ReplayMiss):
        lane.decide("missing", QUESTIONS)
    entry = lane.audit()
    assert entry["decide_calls"] == 3
    assert entry["distinct_requests"] == 2
    assert entry["calls"] == [
        {"replay_key": KEY, "returned": True},
        {"replay_key": KEY, "returned": True},
        {"replay_key": replay_key("missing", QUESTIONS), "returned": False},
    ]
    entry["source"]["mode"] = "live"
    assert lane.audit()["source"]["mode"] == "synthetic"


def declaration(**change):
    saved = {"requests": 7, "fixtures": "saved.json", "replay_only": True, **change}
    return parse_budget(
        {
            "schema": 1,
            "backends": {
                "current": {"requests": 2, "at_most": 4, "fixtures": "current.json"},
                "saved": saved,
            },
        }
    )


def test_replay_counts_are_excluded_from_live_total_and_cap_but_remain_declared():
    budget = declaration()
    assert (budget.total, budget.worst_total, budget.cap) == (2, 4, 4)
    assert budget.backends[1].requests == 7
    note = render_budget_note(budget)
    assert "exactly **2** requests" in note
    assert "up to **4**" in note
    assert "MAX_REQUESTS=4" in note
    assert "`saved` 7" in note and "no live requests" in note
    assert "saved answers, not new inference" in note


def test_replay_only_notebook_needs_no_live_cap():
    budget = parse_budget(
        {
            "schema": 1,
            "backends": {"saved": {"requests": 7, "fixtures": "saved.json", "replay_only": True}},
        }
    )
    assert (budget.total, budget.worst_total, budget.cap) == (0, 0, 0)
    note = render_budget_note(budget)
    assert "No live request cap is needed" in note
    assert "MAX_REQUESTS=" not in note


@pytest.mark.parametrize(
    "change", [{"replay_only": "true"}, {"replay_only": 1}, {"fixtures": None}, {"at_most": 8}]
)
def test_replay_declaration_rejects_ambiguous_or_live_shaped_values(change):
    with pytest.raises(ValueError, match="replay"):
        declaration(**change)
