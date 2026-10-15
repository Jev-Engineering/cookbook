"""Rules the model cannot change, plus matched-task and reporting integrity."""

from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import ChoiceAnswer, Provenance, ReplayBackend, load_helpers, replay_key
from jev_cookbook.evaluation import select_confidence_threshold
from jev_cookbook.fixtures import load_inputs, load_labels, responses_path, validate_recipe

HERE = Path(__file__).resolve().parent.parent
helpers = load_helpers(HERE)


def builder():
    spec = importlib.util.spec_from_file_location(
        "recipe98_fixture_builder", HERE / "build_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def study():
    examples = load_inputs(HERE)
    labels = load_labels(HERE)
    validation = [e for e in examples if e.split == "validation"]
    experiment = helpers.Experiment(ReplayBackend.from_json(responses_path(HERE)), HERE)
    candidates = {
        (mode, k): [experiment.run(e, mode, focused_k=k or 1) for e in validation]
        for mode, k in (("full", 0), ("focused", 1), ("focused", 2), ("staged", 0))
    }
    policy, scores = helpers.freeze_policy(
        validation, candidates, {e.id: labels[e.id] for e in validation}
    )
    return examples, labels, experiment, candidates, policy, scores


def test_all_arms_have_same_ids_splits_gold_and_identical_final_questions(study):
    examples, labels, experiment, _, policy, _ = study
    test = [e for e in examples if e.split == "test"]
    final_schema = {name: q.to_dict() for name, q in helpers.final_questions().items()}
    expected_ids = [e.id for e in test]
    gold_before = copy.deepcopy(labels)
    for mode in helpers.MODES:
        rows = [experiment.run(e, mode, focused_k=policy.focused_k) for e in test]
        assert [r.task_id for r in rows] == expected_ids
        assert {r.split for r in rows} == {"test"}
        assert len({r.task_id for r in rows}) == len(rows)
        for example, row in zip(test, rows, strict=True):
            request = helpers.final_request(example.fields, row.selected_ids, HERE)
            assert {name: q.to_dict() for name, q in request[1].items()} == final_schema
            assert request[2] == helpers.image_payload(example.fields, HERE)[1]
            assert all(call["replay_key"] in example.replay_keys for call in row.requests)
        assert helpers.evaluate(rows, labels, policy)["n"] == len(test)
    assert labels == gold_before


def test_retriever_cannot_see_gold_or_authored_response_hints():
    example = load_inputs(HERE)[1]
    original = helpers.lexical_ids(example.fields, 2)
    poisoned = copy.deepcopy(example.fields)
    poisoned.update(gold={"audit": "contradicted"}, label="note-f", response_hint="note-f")
    for document in poisoned["documents"]:
        document["gold"] = "select me " * 100
    assert helpers.lexical_ids(poisoned, 2) == original
    state, _, _ = helpers.final_request(poisoned, original, HERE)
    serialized = json.dumps(state)
    assert "response_hint" not in serialized and '"gold"' not in serialized
    assert list(helpers.lexical_ids(example.fields, 1)) == list(original[:1])


def test_freeze_rejects_test_rows_and_labels_and_is_immutable(study):
    examples, labels, _, candidates, policy, _ = study
    validation = [e for e in examples if e.split == "validation"]
    test = [e for e in examples if e.split == "test"]
    with pytest.raises(ValueError, match="only the validation"):
        helpers.freeze_policy(test, candidates, {e.id: labels[e.id] for e in test})
    with pytest.raises(ValueError, match="only validation labels"):
        helpers.freeze_policy(validation, candidates, labels)
    with pytest.raises(FrozenInstanceError):
        policy.focused_k = 2
    changed = copy.deepcopy(labels)
    for example in test:
        changed[example.id]["audit"] = "corrupt-test-label"
    again, _ = helpers.freeze_policy(
        validation, candidates, {e.id: changed[e.id] for e in validation}
    )
    assert policy == again
    changed_validation = [
        SimpleNamespace(id=e.id, split=e.split, fields=copy.deepcopy(e.fields)) for e in validation
    ]
    changed_validation[0].fields["query"] += " revised phrasing"
    different, _ = helpers.freeze_policy(
        changed_validation, candidates, {e.id: labels[e.id] for e in validation}
    )
    assert different.selection_digest != policy.selection_digest


def test_selection_objective_is_pinned_in_helper_and_notebook():
    source = (HERE / "helpers.py").read_text()
    assert "min_coverage=0.75" in source
    assert "key=lambda k: (-scores[k], k)" in source
    notebook = json.loads((HERE / "notebook.ipynb").read_text())
    code = "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code")
    assert "helpers.freeze_policy(" in code
    assert code.index("helpers.freeze_policy(") < code.index('select_split(examples, "test")')
    assert "labels[e.id] for e in validation" in code


def test_stored_answers_are_not_all_right(study):
    examples, labels, experiment, candidates, policy, _ = study
    validation = (
        candidates["full", 0] + candidates["focused", policy.focused_k] + candidates["staged", 0]
    )
    assert {row.split for row in validation} == {"validation"}
    gate = select_confidence_threshold(
        [row.result["audit"].choice == labels[row.task_id]["audit"] for row in validation],
        [row.result["audit"].confidence for row in validation],
        min_coverage=0.75,
    )
    assert gate == policy.choice_gate
    rows = [experiment.run(e, "full") for e in examples if e.split == "test"]
    outcomes = [helpers.outcome(row, policy) for row in rows]
    wrong_above_gate = [
        row.task_id
        for row, out in zip(rows, outcomes, strict=True)
        if out["accepted"]
        and out["audit"] != labels[row.task_id]["audit"]
        and row.result["audit"].confidence >= gate
    ]
    assert wrong_above_gate, "a held-out error must survive the validation-frozen gate"


def test_audit_reviews_carry_explicit_outcome_and_exact_reason(study):
    _, _, _, candidates, policy, _ = study
    rows = {row.task_id: row for row in candidates["full", 0]}
    uncertain = helpers.outcome(rows["v05"], policy)
    low_confidence = helpers.outcome(rows["v07"], policy)
    assert uncertain["outcome"] == low_confidence["outcome"] == helpers.REVIEW == "review"
    assert not uncertain["accepted"] and not low_confidence["accepted"]
    assert uncertain["reason"] == "insufficient active evidence"
    assert low_confidence["reason"] == "confidence below the threshold"


def test_arbitrary_selector_answers_never_add_docs_or_loop():
    fields = load_inputs(HERE)[1].fields
    choices = [entry["id"] for entry in fields["index"]] + ["uncertain", "invented", None]
    for choice in choices:
        for confidence in (None, -1, 0, 0.49, 0.5, 1, float("nan"), float("inf")):
            selected = helpers.selected_from_answer(
                fields, SimpleNamespace(choice=choice, confidence=confidence)
            )
            assert len(selected) <= 1
            assert set(selected) <= {entry["id"] for entry in fields["index"]}
            if choice in ("uncertain", "invented", None) or confidence is None:
                assert not selected
    oversized = copy.deepcopy(fields)
    oversized["index"] *= 2
    with pytest.raises(ValueError, match="selection budget"):
        helpers.selector_request(oversized)


def test_logical_budget_stops_under_every_mode():
    example = next(e for e in load_inputs(HERE) if e.split == "test")
    for mode in helpers.MODES:
        for limit in (0, 1, 2):
            experiment = helpers.Experiment(
                ReplayBackend.from_json(responses_path(HERE)), HERE, logical_limit=limit
            )
            row = experiment.run(example, mode, focused_k=1)
            assert experiment.budget.used <= limit
            assert len(row.requests) <= 2
            if limit == 0 or (limit == 1 and mode == "staged"):
                assert row.stopped == "request_cap" and row.result is None


def test_zero_and_single_index_resolve_in_python():
    class EmptyBackend:
        mode = "synthetic"
        model = "synthetic"

        def decide(self, *_args, **_kwargs):
            raise AssertionError("the zero logical budget should stop before a final call")

    example = load_inputs(HERE)[1]
    for count in (0, 1):
        fields = copy.deepcopy(example.fields)
        fields["index"] = fields["index"][:count]
        sample = SimpleNamespace(id=example.id, split=example.split, fields=fields)
        experiment = helpers.Experiment(EmptyBackend(), HERE, logical_limit=0)
        row = experiment.run(sample, "staged")
        assert row.selected_ids == tuple(entry["id"] for entry in helpers.eligible_index(fields))
        assert row.stopped == "request_cap"


def test_no_fabricated_inference_measurements(study):
    _, _, _, candidates, _, _ = study
    report = helpers.accounting(candidates["staged", 0])
    assert report["logical_requests"] == 16
    assert report["http_attempts_this_execution"] == 0
    for field in ("input_tokens", "output_tokens", "latency_seconds", "cost_usd"):
        assert report[field] is None
        assert report[f"missing_{field}"] == 16
    assert report["state_characters"] > 0


def test_full_notebook_request_count_keeps_duplicate_requests_independent():
    class CountingBackend:
        mode = "synthetic"
        model = "synthetic"

        def __init__(self):
            self.replay = ReplayBackend.from_json(responses_path(HERE))
            self.keys = []

        def decide(self, state, questions, *, assets):
            self.keys.append(replay_key(state, questions, assets=assets))
            return self.replay.decide(state, questions, assets=assets)

    examples, labels = load_inputs(HERE), load_labels(HERE)
    backend = CountingBackend()
    experiment = helpers.Experiment(backend, HERE, logical_limit=73)
    experiment.run(next(e for e in examples if e.split == "demo"), "full")
    validation = [e for e in examples if e.split == "validation"]
    candidates = {
        (mode, k): [experiment.run(e, mode, focused_k=k or 1) for e in validation]
        for mode, k in (("full", 0), ("focused", 1), ("focused", 2), ("staged", 0))
    }
    policy, _ = helpers.freeze_policy(
        validation, candidates, {e.id: labels[e.id] for e in validation}
    )
    for mode in helpers.MODES:
        for example in (e for e in examples if e.split == "test"):
            experiment.run(example, mode, focused_k=policy.focused_k)
    assert experiment.budget.used == len(backend.keys) == 73
    assert len(set(backend.keys)) == 70
    assert len(backend.keys) - len(set(backend.keys)) == 3


def test_presence_and_unknown_confidence_suppress_boxes(study):
    _, _, _, candidates, policy, _ = study
    row = copy.copy(candidates["full", 0][1])
    original = dict(row.result.answers)
    for presence, confidence in ((0.01, 0.99), (0.99, None), (0.99, 0.1)):
        row.result = {
            **original,
            "present": SimpleNamespace(noul=presence),
            "crate": SimpleNamespace(box=original["crate"].box, confidence=confidence),
        }
        assert helpers.outcome(row, policy)["box"] is None


def test_scale_is_deterministic_preserves_tasks_and_has_named_external_counts(tmp_path):
    example = load_inputs(HERE)[1]
    calls = []

    def external_test_counter(state, questions, assets):
        assert set(questions) == {"audit", "present", "obstruction", "crate"}
        assert assets
        calls.append(len(state["documents"]))
        # Unit-test counter only. No claim this equals any tokenizer's output.
        return 100 + 50 * len(state["documents"])

    arguments = dict(
        target_tokens=1000,
        counter=external_test_counter,
        counter_id="test-counter-v1",
        max_blocks=50,
    )
    first, manifest = helpers.scale_to_external_budget(example.fields, HERE, **arguments)
    second, duplicate = helpers.scale_to_external_budget(example.fields, HERE, **arguments)
    assert first == second and manifest == duplicate
    assert first["documents"][: len(example.fields["documents"])] == example.fields["documents"]
    assert first["image"] == example.fields["image"] and first["index"] == example.fields["index"]
    assert manifest["external_preflight_tokens"] <= 1000
    assert manifest["external_preflight_tokens"] + 50 > 1000
    assert manifest["server_input_tokens"] is None
    assert len(calls) < 25
    payload = {
        "examples": [{"id": example.id, "split": example.split, "fields": first}],
        "preflight": {example.id: manifest},
    }
    path = tmp_path / "workload.json"
    path.write_text(json.dumps(payload))
    expanded, _ = helpers.apply_workload_manifest([example], path)
    assert expanded[0].id == example.id
    payload["examples"][0]["fields"]["subject"] = "different subject"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="underlying task"):
        helpers.apply_workload_manifest([example], path)


@pytest.mark.parametrize("target", [-1, 0, 262_000, 300_000, True])
def test_scale_limits_are_enforced_before_counter(target):
    def never(*_args):
        raise AssertionError("invalid target must not reach the counter")

    with pytest.raises(ValueError, match="invalid target"):
        helpers.scale_to_external_budget(
            load_inputs(HERE)[1].fields,
            HERE,
            target_tokens=target,
            counter=never,
            counter_id="test",
        )


def test_scale_search_treats_character_cap_as_an_upper_bound(monkeypatch):
    example = load_inputs(HERE)[1]
    monkeypatch.setattr(helpers, "MAX_CONTEXT_CHARACTERS", 5000)
    fields, metadata = helpers.scale_to_external_budget(
        example.fields,
        HERE,
        target_tokens=1000,
        counter=lambda state, _questions, _assets: len(state["documents"]),
        counter_id="test-counter-low-density",
        max_blocks=50,
    )
    assert 0 < metadata["background_blocks"] < 50
    assert metadata["reached_character_cap"]
    request = helpers.final_request(fields, [d["id"] for d in fields["documents"]], HERE)
    assert len(json.dumps(request[0], ensure_ascii=False)) <= 5000


def test_backend_attempt_cap_counts_retries_and_records_failure(tmp_path):
    from jev_cookbook.live import BudgetExceeded, LiveBackend

    class AlwaysTimeout:
        def __init__(self):
            self.calls = 0

        def system_one(self, **_kwargs):
            self.calls += 1
            raise TimeoutError("injected local timeout")

    client = AlwaysTimeout()
    backend = LiveBackend(
        helpers.MODEL,
        client=client,
        images=True,
        long_context=True,
        max_requests=2,
        max_retries=5,
        sleep=lambda _: None,
    )
    experiment = helpers.Experiment(backend, HERE, capture_dir=tmp_path / "capture")
    with pytest.raises(BudgetExceeded):
        experiment.run(load_inputs(HERE)[0], "full")
    assert client.calls == backend.requests_made == 2
    assert experiment.records[0]["http_attempts"] == 2
    sidecar = json.loads((tmp_path / "capture" / "run-record.json").read_text())
    assert sidecar["backend_ledger"]["requests_made"] == 2
    assert sidecar["calls"][0]["input_tokens"] is None


def test_recorded_replay_preserves_different_answers_to_the_same_request():
    example = load_inputs(HERE)[0]
    request = helpers.final_request(
        example.fields, [doc["id"] for doc in example.fields["documents"]], HERE
    )
    key = replay_key(*request[:2], assets=request[2])
    stored = (
        ReplayBackend.from_json(responses_path(HERE))
        .decide(*request[:2], assets=request[2])
        .to_dict()
    )
    provenance = Provenance.recorded("jev-1.14.0", "2026-10-15")
    stored["model"] = "jev-1.14.0"
    for answer in stored["answers"].values():
        answer["provenance"] = provenance.to_dict()
    second = copy.deepcopy(stored)
    second["answers"]["audit"] = ChoiceAnswer.from_probabilities(
        {"consistent": 0.03, "contradicted": 0.94, "unresolved": 0.03}, provenance
    ).to_dict()
    captures = [
        {
            "task_id": example.id,
            "arm": mode,
            "stage": "final",
            "replay_key": key,
            "model": "jev-1.14.0",
            "latency_seconds": elapsed,
            "http_attempts": attempts,
            "response": response,
        }
        for mode, response, elapsed, attempts in (
            ("full", stored, 1.25, 1),
            ("focused", second, 3.5, 2),
        )
    ]
    # The map retains only the last answer; the per-call sidecar retains both.
    experiment = helpers.Experiment(ReplayBackend({key: second}), HERE, captured_calls=captures)
    one = experiment.call(
        request, task_id=example.id, split=example.split, mode="full", stage="final"
    )
    two = experiment.call(
        request, task_id=example.id, split=example.split, mode="focused", stage="final"
    )
    assert one["audit"].choice == "consistent"
    assert two["audit"].choice == "contradicted"
    assert [r["latency_seconds"] for r in experiment.records] == [1.25, 3.5]
    assert [r["captured_http_attempts"] for r in experiment.records] == [1, 2]
    assert [r["http_attempts"] for r in experiment.records] == [0, 0]
    with pytest.raises(ValueError, match="no matching captured call"):
        experiment.call(
            request, task_id=example.id, split=example.split, mode="full", stage="final"
        )


def test_fixtures_validate_and_rebuild_identically(tmp_path):
    assert not validate_recipe(HERE)
    module = builder()
    module.write_fixtures(tmp_path)
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (tmp_path / "fixtures" / name).read_bytes() == (
            HERE / "fixtures" / name
        ).read_bytes()
    for path in (HERE / "assets").glob("*.png"):
        assert (tmp_path / "assets" / path.name).read_bytes() == path.read_bytes()


def test_recorded_generator_guard_preserves_all_files(tmp_path):
    module = builder()
    module.write_fixtures(tmp_path)
    path = tmp_path / "fixtures" / "responses.json"
    path.write_text('{"existing":{"model":"jev-1.14.0"}}\n')
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="refusing to overwrite"):
        module.write_fixtures(tmp_path)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    module.write_fixtures(tmp_path, force=True)
    assert json.loads(path.read_text()) != {"existing": {"model": "jev-1.14.0"}}


def test_replay_keys_include_image_bytes():
    example = load_inputs(HERE)[1]
    request = helpers.final_request(example.fields, helpers.lexical_ids(example.fields, 1), HERE)
    key = replay_key(*request[:2], assets=request[2])
    other = copy.deepcopy(request[2])
    replacement = helpers.image_payload(load_inputs(HERE)[2].fields, HERE)[1]
    other[next(iter(other))] = next(iter(replacement.values()))
    assert replay_key(*request[:2], assets=other) != key
