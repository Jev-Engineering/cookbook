"""Request accounting measures actual delegate invocations, not fixture inventory."""

import base64
import io
import json
import re

import pytest
from PIL import Image

from jev_cookbook import (
    AuditedBackend,
    Backend,
    BudgetExceeded,
    DecisionResult,
    LiveBackend,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ReplayMiss,
    ScriptedBackend,
    record,
    replay_key,
)
from jev_cookbook.accounting import (
    AUDIT_PREFIX,
    NOTE_BEGIN,
    NOTE_END,
    PROFILE_COUNTERS,
    audit_json,
    load_budget,
    parse_budget,
    register_profile,
    render_budget_note,
    render_recipe_note,
    repeated_keys,
)
from jev_cookbook.style import run_header_text

QUESTIONS = {"present": Noul(instructions="The package is present.")}


def test_duplicate_calls_delegate_independently_and_keep_original_keys():
    observations = []

    def script(state, questions, rng):
        observations.append(state)
        return {"present": len(observations) / 10}

    backend = AuditedBackend(ScriptedBackend(script))
    answers = [backend.decide("package", QUESTIONS)["present"].noul for _ in range(3)]
    assert answers == [0.1, 0.2, 0.3]
    assert observations == ["package"] * 3
    assert isinstance(backend, Backend)
    key = replay_key("package", QUESTIONS)
    audit = backend.audit()
    assert audit == {
        "label": "main",
        "decide_calls": 3,
        "distinct_requests": 1,
        "calls": [{"replay_key": key, "returned": True}] * 3,
    }
    audit["calls"].clear()
    assert len(backend.audit()["calls"]) == 3
    assert json.loads(backend.audit_json().removeprefix(AUDIT_PREFIX)) == {
        "schema": 2,
        "backends": [backend.audit()],
    }


def test_failed_delegate_is_counted_and_local_validation_failure_is_not():
    result = DecisionResult({"present": NoulAnswer(0.9, Provenance.synthetic())}, "synthetic")
    backend = AuditedBackend(ReplayBackend({replay_key("known", QUESTIONS): result.to_dict()}))
    backend.decide("known", QUESTIONS)
    with pytest.raises(ReplayMiss):
        backend.decide("missing", QUESTIONS)
    with pytest.raises(TypeError, match="state"):
        backend.decide(None, QUESTIONS)
    assert backend.audit()["decide_calls"] == 2
    assert backend.audit()["distinct_requests"] == 2
    assert [call["returned"] for call in backend.audit()["calls"]] == [True, False]


def test_recorded_provenance_and_dates_remain_visible():
    result = DecisionResult(
        {"present": NoulAnswer(0.9, Provenance.recorded("jev-test", "2026-10-01"))},
        "jev-test",
    )
    backend = AuditedBackend(ReplayBackend({replay_key("known", QUESTIONS): result.to_dict()}))
    assert backend.mode == "recorded"
    assert backend.model == "jev-test"
    assert backend.recorded_dates == ("2026-10-01",)
    assert backend.decide("known", QUESTIONS).to_dict() == result.to_dict()
    assert "2026-10-01" in run_header_text(1, "Accounting", backend=backend, n_examples=1)


def test_image_content_is_bound_to_the_same_key_and_passed_unchanged():
    png = io.BytesIO()
    Image.new("RGB", (280, 280), "pink").save(png, format="PNG")
    assets = {
        "image-main": {
            "type": "image",
            "format": "png",
            "data_base64": base64.b64encode(png.getvalue()).decode("ascii"),
        }
    }
    received = []

    class Delegate:
        mode = "synthetic"
        model = "synthetic"

        def decide(self, state, questions, *, assets):
            received.append((state, questions, assets))
            return DecisionResult({"present": NoulAnswer(0.9, Provenance.synthetic())}, "synthetic")

    backend = AuditedBackend(Delegate())
    state = {"photo": "image-main"}
    backend.decide(state, QUESTIONS, assets=assets)
    assert received[0][0] is state and received[0][1] is QUESTIONS and received[0][2] is assets
    key = backend.audit()["calls"][0]["replay_key"]
    assert key == replay_key(state, QUESTIONS, assets=assets)
    assert key != replay_key(state, QUESTIONS)


def test_live_recorder_dynamic_attributes_and_failed_calls_without_network(tmp_path):
    class Client:
        def __init__(self):
            self.calls = []

        def system_one(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "model": "jev-1.14.0",
                "answers": {"present": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }

    client = Client()
    live = LiveBackend("jev-preview", client=client, max_requests=2, today=lambda: "2026-10-01")
    backend = AuditedBackend(live)
    backend.max_retries = 0
    assert live.max_retries == 0
    assert backend.model == "jev-preview"
    path = tmp_path / "responses.json"
    ledger = tmp_path / "ledger.json"
    with backend as entered:
        assert entered is backend
        for _ in range(2):
            record(backend, [("package", QUESTIONS)], path, overwrite=True, ledger_path=ledger)
        with pytest.raises(BudgetExceeded):
            record(backend, [("package", QUESTIONS)], path, overwrite=True, ledger_path=ledger)
    assert backend.model == "jev-1.14.0"
    assert backend.requests_made == 2
    assert len(client.calls) == len(backend.records) == 2
    assert backend.audit()["decide_calls"] == 3
    assert backend.audit()["distinct_requests"] == 1
    assert [call["returned"] for call in backend.audit()["calls"]] == [True, True, False]
    assert len(json.loads(path.read_text())) == 1
    stored_ledger = json.loads(ledger.read_text())
    assert any(line["status"] == "budget_stopped" for line in stored_ledger.values())


# --------------------------------------------------------------------------------------------
# #213: several audited backends, the extension point, the declaration, the cap arithmetic
# --------------------------------------------------------------------------------------------


def _scripted(label="main"):
    return AuditedBackend(
        ScriptedBackend(lambda state, questions, rng: {"present": 0.9}), label=label
    )


def test_several_audited_backends_print_one_line_in_the_order_given():
    first, second = _scripted("arm-a"), _scripted("arm-b")
    for state in ("x", "y"):
        first.decide(state, QUESTIONS)
    second.decide("x", QUESTIONS)
    payload = json.loads(audit_json(second, first).removeprefix(AUDIT_PREFIX))
    assert payload["schema"] == 2
    assert [(b["label"], b["decide_calls"]) for b in payload["backends"]] == [
        ("arm-b", 1),
        ("arm-a", 2),
    ]
    # the same key in two backends is two requests: the live budget is per backend
    assert payload["backends"][0]["calls"][0] == payload["backends"][1]["calls"][0]


@pytest.mark.parametrize("label", ["", "Main", "1st", "a b", "x" * 33, None, 3])
def test_a_label_must_be_a_short_lowercase_name(label):
    with pytest.raises(ValueError, match="label"):
        AuditedBackend(ScriptedBackend(lambda state, questions, rng: {}), label=label)


def test_audit_json_rejects_duplicate_labels_and_non_audited_arguments():
    with pytest.raises(ValueError, match="distinct labels"):
        audit_json(_scripted(), _scripted())
    with pytest.raises(TypeError):
        audit_json()
    with pytest.raises(TypeError):
        audit_json(ScriptedBackend(lambda state, questions, rng: {}))


def test_a_registered_profile_is_additive_and_leaves_existing_lines_byte_identical(monkeypatch):
    """The extension point: a quantity counted per request (an image count, say) is registered, not
    added to the core fields. A notebook that never uses it prints exactly the line it printed
    before the quantity existed, so its committed output stays valid."""

    def run():
        backend = _scripted()
        backend.decide("plain", QUESTIONS)
        backend.decide("with-extra", QUESTIONS)
        return backend

    before = run().audit_json()
    amounts = {"plain": 0, "with-extra": 3}
    monkeypatch.setitem(PROFILE_COUNTERS, "extras", lambda state, questions, assets: amounts[state])
    after = run().audit()
    assert set(after["calls"][0]) == {"replay_key", "returned"}
    assert after["calls"][1]["profile"] == {"extras": 3}
    assert after["profile_totals"] == {"extras": 3}
    amounts["with-extra"] = 0
    assert run().audit_json() == before  # a zero is omitted: nothing changes for a text-only run
    assert '"profile' not in before


def test_register_profile_validates_and_refuses_a_second_registration(monkeypatch):
    monkeypatch.setattr("jev_cookbook.accounting.PROFILE_COUNTERS", {})
    register_profile("images", lambda state, questions, assets: 0)
    with pytest.raises(ValueError, match="already registered"):
        register_profile("images", lambda state, questions, assets: 0)
    with pytest.raises(ValueError, match="profile name"):
        register_profile("Images", lambda state, questions, assets: 0)


def test_a_counter_that_returns_a_bad_amount_fails_before_the_request(monkeypatch):
    monkeypatch.setitem(PROFILE_COUNTERS, "bad", lambda state, questions, assets: -1)
    backend = _scripted()
    with pytest.raises(ValueError, match="non-negative"):
        backend.decide("x", QUESTIONS)
    assert backend.audit()["decide_calls"] == 0


def test_repeated_keys_names_each_repeat_once_in_first_seen_order():
    assert repeated_keys(["b", "a", "b", "c", "a", "b"]) == {"b": 3, "a": 2}
    assert repeated_keys(["a", "b"]) == {}


GOOD = {
    "schema": 1,
    "backends": {"main": {"requests": 40, "fixtures": "fixtures/responses.json"}},
}


def test_a_valid_declaration_parses_with_defaults():
    budget = parse_budget(GOOD)
    (backend,) = budget.backends
    assert (backend.label, backend.requests, backend.distinct) == ("main", 40, 40)
    assert backend.fixtures == "fixtures/responses.json" and backend.profile == ()
    assert (budget.total, budget.cap) == (40, 40)


TWO_ARMS = {
    "schema": 1,
    "backends": {
        "arm-a": {"requests": 30, "fixtures": None},
        "arm-b": {"requests": 12, "distinct": 10, "fixtures": None},
    },
}


def test_the_cap_is_the_largest_backend_and_the_total_is_the_sum():
    budget = parse_budget(TWO_ARMS)
    assert (budget.total, budget.cap) == (42, 30)


def _with(**changes):
    body = {"requests": 40, "fixtures": None}
    body.update(changes)
    return {"schema": 1, "backends": {"main": body}}


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"schema": 1},
        {"schema": 2, "backends": {"main": {"requests": 1, "fixtures": None}}},
        {"schema": True, "backends": {"main": {"requests": 1, "fixtures": None}}},
        {"schema": 1, "backends": {}},
        {"schema": 1, "backends": {"Main": {"requests": 1, "fixtures": None}}},
        {"schema": 1, "backends": {"main": {"requests": 1}}},
        {"schema": 1, "backends": {"main": {"fixtures": None}}},
        {"schema": 1, "extra": 0, "backends": {"main": {"requests": 1, "fixtures": None}}},
        _with(requests=0),
        _with(requests=True),
        _with(requests="40"),
        _with(requests=2.0),
        _with(distinct=41),
        _with(distinct=0),
        _with(at_most=39),
        _with(at_most=True),
        _with(at_most=0),
        _with(fixtures=""),
        _with(fixtures="/etc/passwd"),
        _with(fixtures="../other/responses.json"),
        _with(fixtures="fixtures\\responses.json"),
        _with(fixtures="C:/responses.json"),
        _with(fixtures=3),
        _with(profile={"unregistered": 1}),
        _with(profile=[]),
        _with(extra=1),
    ],
)
def test_malformed_declarations_fail(data):
    with pytest.raises(ValueError):
        parse_budget(data)


def test_a_registered_profile_can_be_declared(monkeypatch):
    monkeypatch.setitem(PROFILE_COUNTERS, "extras", lambda state, questions, assets: 1)
    (backend,) = parse_budget(_with(profile={"extras": 5})).backends
    assert backend.profile == (("extras", 5),)
    with pytest.raises(ValueError):
        parse_budget(_with(profile={"extras": 0}))


def test_the_rendered_note_is_deterministic_and_states_the_cap_not_the_total():
    single = render_budget_note(parse_budget(GOOD))
    assert single == render_budget_note(parse_budget(GOOD))
    assert single.startswith(NOTE_BEGIN + "\n") and single.endswith(NOTE_END + "\n")
    assert "makes exactly **40** requests, each decided once" in single
    assert "JEV_COOKBOOK_LIVE_MAX_REQUESTS=40" in single
    multi = render_budget_note(parse_budget(TWO_ARMS))
    assert "makes exactly **42** requests across 2 audited backends" in multi
    assert "`arm-a` 30; `arm-b` 12 (10 distinct, 2 repeated on purpose)" in multi
    assert "JEV_COOKBOOK_LIVE_MAX_REQUESTS=30" in multi and "=42" not in multi
    assert "the largest single count, not the total" in multi
    repeated = render_budget_note(parse_budget(_with(requests=10, distinct=7)))
    assert "of which 7 are distinct (the other 3 repeat a request on purpose)" in repeated


def test_render_recipe_note_reads_the_declaration_in_the_folder(tmp_path):
    (tmp_path / "request_budget.json").write_text(json.dumps(GOOD))
    assert render_recipe_note(tmp_path) == render_budget_note(parse_budget(GOOD))


class _Client:
    def __init__(self):
        self.calls = 0

    def system_one(self, **kwargs):
        self.calls += 1
        return {
            "model": "jev-1.14.0",
            "answers": {"present": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }


def _live(client, cap):
    return LiveBackend("jev-preview", client=client, max_requests=cap, today=lambda: "2026-10-01")


def _run(backend, n):
    for index in range(n):
        backend.decide(f"example-{index}", QUESTIONS)


def test_following_the_documented_cap_cannot_abort_the_run_and_one_less_does():
    """Criterion 4 of #213, against the real LiveBackend: the cap is inclusive, so the cap the
    README states (the largest declared backend) runs every backend to its declared count; each
    backend has its own budget, so the cap is not the total; one less stops the last request."""
    budget = parse_budget(
        {
            "schema": 1,
            "backends": {
                "arm-a": {"requests": 7, "fixtures": None},
                "arm-b": {"requests": 4, "fixtures": None},
            },
        }
    )
    note = render_budget_note(budget)
    cap = int(re.search(r"JEV_COOKBOOK_LIVE_MAX_REQUESTS=(\d+)", note).group(1))
    assert cap == budget.cap == 7 and cap != budget.total
    clients = [_Client(), _Client()]
    for client, backend in zip(clients, budget.backends, strict=True):
        live = _live(client, cap)
        _run(live, backend.requests)
        assert live.requests_made == backend.requests and client.calls == backend.requests
    short = _Client()
    live = _live(short, cap - 1)
    with pytest.raises(BudgetExceeded):
        _run(live, budget.backends[0].requests)
    assert short.calls == cap - 1  # the cap stopped the last request: nothing was sent past it


def test_the_cap_is_per_backend_so_a_second_backend_is_a_second_budget():
    first, second = _Client(), _Client()
    cap = 3
    for client in (first, second):
        _run(_live(client, cap), cap)
    assert first.calls + second.calls == 2 * cap  # the env cap alone would not stop a second one


def test_an_answer_dependent_count_declares_its_worst_case_and_the_cap_follows_it():
    """A cascade replays the committed answers, so the audit measures the count on that path;
    ``at_most`` is the author's stated bound on every other path, and the cap is sized by it."""
    budget = parse_budget(_with(requests=36, at_most=44))
    (backend,) = budget.backends
    assert (backend.requests, backend.at_most) == (36, 44)
    assert (budget.total, budget.worst_total, budget.cap) == (36, 44, 44)
    note = render_budget_note(budget)
    assert "makes exactly **36** requests, each decided once when every live answer" in note
    assert "and up to **44** when a live answer sends it down a longer path" in note
    assert "JEV_COOKBOOK_LIVE_MAX_REQUESTS=44" in note and "=36" not in note
    live = _live(_Client(), budget.cap)
    _run(live, backend.at_most)  # the longest path still fits the stated cap
    assert live.requests_made == 44
    multi = render_budget_note(
        parse_budget(
            {
                "schema": 1,
                "backends": {
                    "arm-a": {"requests": 30, "at_most": 36, "fixtures": None},
                    "arm-b": {"requests": 12, "fixtures": None},
                },
            }
        )
    )
    assert "`arm-a` 30 (up to 36 if live answers differ); `arm-b` 12" in multi
    assert "JEV_COOKBOOK_LIVE_MAX_REQUESTS=36" in multi


def test_a_declaration_file_with_a_repeated_key_is_rejected(tmp_path):
    (tmp_path / "request_budget.json").write_text(
        '{"schema": 1, "backends": {"main": {"requests": 5, "requests": 50, "fixtures": null}}}'
    )
    with pytest.raises(ValueError, match="appears twice"):
        load_budget(tmp_path)
