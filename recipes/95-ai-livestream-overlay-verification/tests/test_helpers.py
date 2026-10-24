"""The visual judgments cannot bypass Python's evidence and freshness gates."""

import ast
import copy
import inspect
import json
import math
from pathlib import Path

import pytest
from PIL import Image

from jev_cookbook import NoulAnswer, Provenance, ReplayBackend, ReplayMiss, load_helpers, replay_key
from jev_cookbook.simulation import ActionLog, ReviewQueue

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


def noul(probability):
    return NoulAnswer(noul=probability, provenance=Provenance.synthetic())


def supported_answers():
    return {
        f"{claim}_{question}": noul(0.99)
        for claim in ("phase", "action", "status")
        for question in ("resolvable", "supported")
    }


@pytest.fixture
def fields():
    return {
        "frames": [
            {"path": "assets/prior.png", "captured_ms": 9500},
            {"path": "assets/current.png", "captured_ms": 10000},
        ],
        "agent_claims": {"phase": "combat", "action": "attack", "status": "ready"},
        "game_telemetry": {"phase": "combat", "action": "attack", "status": "ready"},
        "overlay_updated_ms": 9750,
        "observed_ms": 10100,
    }


def routed(fields, answers, gate=0.5):
    actions, queue = ActionLog(), ReviewQueue()
    outcome = helpers.route("example", fields, answers, gate, actions=actions, queue=queue)
    return outcome, actions, queue


@pytest.mark.parametrize("claim", ["phase", "action", "status"])
@pytest.mark.parametrize(
    ("resolvable", "supported", "expected"),
    [
        (0.99, 0.01, "unsupported"),
        (0.01, 0.01, "unresolved"),
        (0.01, 0.99, "unresolved"),
        (0.99, 0.60, "unresolved"),
        (0.60, 0.99, "unresolved"),
    ],
)
def test_each_claim_needs_its_own_resolvable_and_certain_evidence(
    fields, claim, resolvable, supported, expected
):
    answers = supported_answers()
    answers[f"{claim}_resolvable"] = noul(resolvable)
    answers[f"{claim}_supported"] = noul(supported)
    outcome, actions, queue = routed(fields, answers)
    assert outcome.claims[claim] == expected
    assert all(label == "supported" for other, label in outcome.claims.items() if other != claim)
    assert outcome.semantic_mismatch is (expected == "unsupported")
    assert outcome.review
    assert len(queue) == 1
    assert len(actions) == 0


@pytest.mark.parametrize("question", ["resolvable", "supported"])
def test_a_probability_tie_is_unresolved_even_with_a_zero_gate(fields, question):
    answers = supported_answers()
    answers[f"action_{question}"] = noul(0.5)
    outcome, actions, queue = routed(fields, answers, gate=0.0)
    assert outcome.claims["action"] == "unresolved"
    assert not outcome.semantic_mismatch
    assert len(actions) == 0
    assert len(queue) == 1


def test_unknown_claim_vocabulary_cannot_be_authorized_by_maximum_certainty(fields):
    fields["agent_claims"]["phase"] = "unrecognised_phase"
    answers = {key: noul(1.0) for key in supported_answers()}
    outcome, actions, queue = routed(fields, answers, gate=1.0)
    assert outcome.claims["phase"] == "unresolved"
    assert not outcome.semantic_mismatch
    assert outcome.review
    assert len(actions) == 0
    assert len(queue) == 1


def test_fresh_supported_evidence_records_only_a_simulated_recommendation(fields):
    outcome, actions, queue = routed(fields, supported_answers())
    assert not outcome.review
    assert not outcome.semantic_mismatch
    assert outcome.time_flags == ()
    assert len(queue) == 0
    assert len(actions) == 1
    entry = actions.to_dicts()[0]
    assert entry["kind"] == "overlay recommendation"
    assert entry["payload"]["recommendation"] == "retain the verified overlay"
    assert entry["executed"] is False


def test_certainty_boundary_is_inclusive(fields):
    answers = supported_answers()
    answers["action_supported"] = noul(0.75)  # |2p - 1| = 0.5, not p itself.
    accepted, actions, queue = routed(fields, answers, gate=0.5)
    assert not accepted.review
    assert len(actions) == 1
    assert len(queue) == 0
    rejected, actions, queue = routed(fields, answers, gate=0.500001)
    assert rejected.claims["action"] == "unresolved"
    assert len(actions) == 0
    assert len(queue) == 1


@pytest.mark.parametrize("gate", [-0.01, 1.01, float("nan"), float("inf"), True, "0.5"])
def test_bad_gates_fail_before_either_log_is_written(fields, gate):
    actions, queue = ActionLog(), ReviewQueue()
    with pytest.raises(ValueError, match="gate"):
        helpers.route("example", fields, supported_answers(), gate, actions=actions, queue=queue)
    assert len(actions) == len(queue) == 0


@pytest.mark.parametrize(
    ("observed", "updated", "expected"),
    [
        (12000, 7000, ()),
        (12001, 7000, ("stream_stale",)),
        (12000, 6999, ("overlay_delayed",)),
        (12001, 6999, ("stream_stale", "overlay_delayed")),
    ],
)
def test_time_limits_are_inclusive_and_independent(fields, observed, updated, expected):
    fields["observed_ms"] = observed
    fields["overlay_updated_ms"] = updated
    outcome, actions, queue = routed(fields, supported_answers())
    assert outcome.time_flags == expected
    assert set(outcome.claims.values()) == {"supported"}
    assert not outcome.semantic_mismatch
    assert outcome.review is bool(expected)
    assert len(actions) == (0 if expected else 1)
    assert len(queue) == (1 if expected else 0)


@pytest.mark.parametrize(
    ("previous", "current", "observed", "updated"),
    [
        (10000, 10000, 10100, 9750),  # Repeated capture.
        (10001, 10000, 10100, 9750),  # Reversed capture order.
        (9500, 10000, 9999, 9750),  # Capture is in the future.
        (9500, 10000, 10100, 10001),  # Overlay update postdates captured evidence.
        (-1, 10000, 10100, 9750),
        (9500, float("nan"), 10100, 9750),
        (9500, 10000, float("inf"), 9750),
        (9500, 10000, 10100, True),
        ("9500", 10000, 10100, 9750),
    ],
)
def test_invalid_times_block_even_maximum_certainty(fields, previous, current, observed, updated):
    fields["frames"][0]["captured_ms"] = previous
    fields["frames"][1]["captured_ms"] = current
    fields["observed_ms"] = observed
    fields["overlay_updated_ms"] = updated
    answers = {key: noul(1.0) for key in supported_answers()}
    outcome, actions, queue = routed(fields, answers, gate=1.0)
    assert outcome.time_flags == ("invalid_timestamps",)
    assert set(outcome.claims.values()) == {"unresolved"}
    assert not outcome.semantic_mismatch
    assert outcome.review
    assert len(actions) == 0
    assert len(queue) == 1


@pytest.mark.parametrize("frame_count", [0, 1, 3])
def test_exactly_two_frame_timestamps_are_required(fields, frame_count):
    frame = fields["frames"][0]
    fields["frames"] = [dict(frame) for _ in range(frame_count)]
    outcome, actions, queue = routed(fields, supported_answers())
    assert outcome.time_flags == ("invalid_timestamps",)
    assert len(actions) == 0
    assert len(queue) == 1


def test_stale_capture_and_visual_disagreement_retain_both_reasons(fields):
    fields["observed_ms"] = 14000
    answers = supported_answers()
    answers["action_supported"] = noul(0.01)
    outcome, actions, queue = routed(fields, answers)
    assert outcome.claims["action"] == "unsupported"
    assert outcome.semantic_mismatch
    assert outcome.time_flags == ("stream_stale",)
    assert len(actions) == 0
    assert len(queue) == 1
    reason = queue.to_dicts()[0]["reason"]
    assert "stream_stale" in reason
    assert "visible disagreement" in reason


@pytest.fixture(scope="module")
def replayed():
    examples = [
        json.loads(line)
        for line in (RECIPE / "fixtures" / "inputs.jsonl").read_text("utf-8").splitlines()
    ]
    gold = {
        row["id"]: row["label"]
        for row in map(
            json.loads,
            (RECIPE / "fixtures" / "labels.jsonl").read_text("utf-8").splitlines(),
        )
    }
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    questions = helpers.build_questions()
    answers = {}
    for example in examples:
        state, assets = helpers.build_request(example["fields"], RECIPE)
        answers[example["id"]] = backend.decide(state, questions, assets=assets).answers
    return examples, answers, gold


def test_every_replay_key_matches_the_current_images_state_and_questions(replayed):
    examples, _, _ = replayed
    questions = helpers.build_questions()
    for example in examples:
        state, assets = helpers.build_request(example["fields"], RECIPE)
        assert example["replay_keys"] == [replay_key(state, questions, assets=assets)]
        repeated_state, repeated_assets = helpers.build_request(example["fields"], RECIPE)
        assert (
            replay_key(repeated_state, questions, assets=repeated_assets)
            == (example["replay_keys"][0])
        )


def test_request_preserves_raw_claims_and_telemetry_but_excludes_labels_and_paths(replayed):
    examples, _, _ = replayed
    fields = copy.deepcopy(examples[0]["fields"])
    state, assets = helpers.build_request(fields, RECIPE)
    fields.update(
        {
            "id": "gold-leak-sentinel",
            "split": "test",
            "label": {"claims": {"phase": "unsupported"}},
            "semantic_mismatch": True,
        }
    )
    poisoned_state, poisoned_assets = helpers.build_request(fields, RECIPE)
    assert poisoned_state == state
    assert poisoned_assets.keys() == assets.keys()
    assert state["agent_claims"] == fields["agent_claims"]
    assert state["game_telemetry"] == fields["game_telemetry"]
    rendered = json.dumps(state)
    assert "gold-leak-sentinel" not in rendered
    for frame in fields["frames"]:
        assert frame["path"] not in rendered
    assert str(RECIPE) not in rendered


def test_same_pixels_at_another_path_produce_the_same_request_key(replayed, tmp_path):
    examples, _, _ = replayed
    original = examples[0]["fields"]
    relocated = copy.deepcopy(original)
    for index, frame in enumerate(relocated["frames"]):
        destination = tmp_path / f"renamed-{index}.png"
        destination.write_bytes((RECIPE / original["frames"][index]["path"]).read_bytes())
        frame["path"] = destination.name
    questions = helpers.build_questions()
    state, assets = helpers.build_request(original, RECIPE)
    moved_state, moved_assets = helpers.build_request(relocated, tmp_path)
    assert moved_state == state
    assert replay_key(moved_state, questions, assets=moved_assets) == replay_key(
        state, questions, assets=assets
    )


def test_validation_and_test_use_distinct_authored_image_bytes(replayed):
    examples, _, _ = replayed
    references = {"validation": set(), "test": set()}
    for example in examples:
        if example["split"] in references:
            _, assets = helpers.build_request(example["fields"], RECIPE)
            references[example["split"]].update(assets)
    assert references["validation"]
    assert references["test"]
    assert references["validation"].isdisjoint(references["test"])


def test_changed_pixels_cannot_reuse_the_old_replay_answer(replayed, tmp_path):
    examples, _, _ = replayed
    fields = copy.deepcopy(examples[0]["fields"])
    for index, frame in enumerate(fields["frames"]):
        target = tmp_path / f"image-{index}.png"
        with Image.open(RECIPE / frame["path"]) as image:
            if index == 1:
                image.putpixel((0, 0), (2, 3, 4))
            image.save(target)
        frame["path"] = target.name
    state, assets = helpers.build_request(fields, tmp_path)
    questions = helpers.build_questions()
    assert replay_key(state, questions, assets=assets) != examples[0]["replay_keys"][0]
    backend = ReplayBackend.from_json(RECIPE / "fixtures" / "responses.json")
    with pytest.raises(ReplayMiss):
        backend.decide(state, questions, assets=assets)


def test_stale_telemetry_can_agree_with_claims_while_pixels_contradict_them(replayed):
    examples, answers, gold = replayed
    example = next(row for row in examples if row["id"] == "t02")
    baseline = helpers.exact_baseline(example["fields"])
    visual, actions, queue = routed(example["fields"], answers["t02"])
    assert baseline["phase"] == "supported"
    assert gold["t02"]["claims"]["phase"] == "unsupported"
    assert visual.claims["phase"] == "unsupported"
    assert visual.semantic_mismatch
    assert len(actions) == 0
    assert len(queue) == 1


def test_frozen_validation_gate_retains_wrong_acceptance_and_false_mismatch(replayed):
    examples, answers, gold = replayed
    validation = [row for row in examples if row["split"] == "validation"]
    test = [row for row in examples if row["split"] == "test"]
    gate, _ = helpers.select_gate(validation, answers, gold)
    assert gate == 0.5
    reports, outcomes, actions, queue = helpers.evaluate(test, answers, gold, gate)
    missed = outcomes["t11"]
    assert gold["t11"]["claims"]["action"] == "unsupported"
    assert missed.claims["action"] == "supported"
    assert not missed.review
    assert not missed.semantic_mismatch
    assert any(entry["payload"]["example"] == "t11" for entry in actions.to_dicts())
    false_alarm = outcomes["t05"]
    assert not gold["t05"]["semantic_mismatch"]
    assert false_alarm.semantic_mismatch
    assert false_alarm.review
    assert any(entry["item"]["example"] == "t05" for entry in queue.to_dicts())
    assert not any(entry["payload"]["example"] == "t05" for entry in actions.to_dicts())
    event = reports["visual"]["event"]
    assert event["fp"] >= 1
    assert event["fn"] >= 1


@pytest.mark.parametrize("review_case", [None, "unresolved", "stream_stale", "invalid_timestamps"])
def test_event_accuracy_counts_all_episodes_including_review_cases(fields, review_case):
    # One of each confusion-matrix outcome; the optional reviewed negative makes
    # accuracy differ from precision and recall without changing positive counts.
    cases = [
        ("false_positive", False, True),
        ("false_negative", True, False),
        ("true_negative", False, False),
        ("true_positive", True, True),
    ]
    if review_case is not None:
        cases.append(("review_negative", False, False))
    examples, answers, gold = [], {}, {}
    for ident, expected_mismatch, predicted_mismatch in cases:
        episode = copy.deepcopy(fields)
        evidence = supported_answers()
        if predicted_mismatch:
            evidence["action_supported"] = noul(0.01)
            episode["game_telemetry"]["action"] = "block"
        expected_claims = dict.fromkeys(("phase", "action", "status"), "supported")
        if expected_mismatch:
            expected_claims["action"] = "unsupported"
        if ident == "review_negative":
            if review_case == "unresolved":
                evidence["action_resolvable"] = noul(0.01)
                evidence["action_supported"] = noul(0.01)
                episode["game_telemetry"]["action"] = "unavailable"
                expected_claims["action"] = "unresolved"
            elif review_case == "stream_stale":
                episode["observed_ms"] = 14000
            else:
                episode["frames"][0]["captured_ms"] = episode["frames"][1]["captured_ms"]
                expected_claims = dict.fromkeys(expected_claims, "unresolved")
        examples.append({"id": ident, "fields": episode})
        answers[ident] = evidence
        gold[ident] = {"claims": expected_claims, "semantic_mismatch": expected_mismatch}

    reports, outcomes, _, _ = helpers.evaluate(examples, answers, gold, 0.5)
    assert {
        ident: (gold[ident]["semantic_mismatch"], outcome.semantic_mismatch)
        for ident, outcome in outcomes.items()
    } == {ident: (expected, predicted) for ident, expected, predicted in cases}
    if review_case is not None:
        reviewed = outcomes["review_negative"]
        assert reviewed.review
        assert not reviewed.semantic_mismatch
        if review_case == "unresolved":
            assert reviewed.claims["action"] == "unresolved"
        else:
            assert reviewed.time_flags == (review_case,)
    expected_n, expected_correct = (4, 2) if review_case is None else (5, 3)
    for method in ("visual", "exact_baseline"):
        event = reports[method]["event"]
        assert event["N"] == expected_n
        assert type(event["correct"]) is int
        assert event["correct"] == expected_correct
        assert event["accuracy"] == pytest.approx(expected_correct / expected_n)
        assert (event["tp"], event["fp"], event["fn"]) == (1, 1, 1)
        assert event["precision"] == event["recall"] == 0.5
        if review_case is not None:
            assert event["accuracy"] != event["precision"]
            assert event["accuracy"] != event["recall"]


def test_frozen_validation_gate_reports_held_out_event_accuracy(replayed):
    examples, answers, gold = replayed
    validation = [row for row in examples if row["split"] == "validation"]
    held_out = [row for row in examples if row["split"] == "test"]
    gate, _ = helpers.select_gate(validation, answers, gold)
    assert gate == 0.5
    assert len(held_out) == 12
    reports, outcomes, _, _ = helpers.evaluate(held_out, answers, gold, gate)
    for method, expected_correct, expected_errors in (
        ("visual", 10, {"t05", "t11"}),
        ("exact_baseline", 11, {"t02"}),
    ):
        errors = set()
        for example in held_out:
            ident = example["id"]
            predicted_mismatch = (
                outcomes[ident].semantic_mismatch
                if method == "visual"
                else "unsupported" in helpers.exact_baseline(example["fields"]).values()
            )
            if predicted_mismatch != gold[ident]["semantic_mismatch"]:
                errors.add(ident)
        assert errors == expected_errors
        event = reports[method]["event"]
        assert event["N"] == 12
        assert type(event["correct"]) is int
        assert event["correct"] == expected_correct == len(held_out) - len(errors)
        assert event["accuracy"] == pytest.approx(expected_correct / 12)


def test_claim_abstention_and_frame_review_use_distinct_denominators(replayed):
    examples, answers, gold = replayed
    subset = [row for row in examples if row["id"] in {"t06", "t12"}]
    reports, outcomes, actions, queue = helpers.evaluate(subset, answers, gold, 0.5)
    assert all(outcome.review for outcome in outcomes.values())
    assert len(queue) == 2
    assert len(actions) == 0
    claims = reports["visual"]["claims"]
    assert claims["phase"]["N"] == 2
    assert claims["phase"]["answered"] == 2
    assert claims["phase"]["abstention"] == 0.0
    assert claims["action"]["answered"] == 1
    assert claims["action"]["abstention"] == 0.5
    event = reports["visual"]["event"]
    assert event["tp"] == event["fp"] == event["fn"] == 0
    assert math.isnan(event["precision"])
    assert math.isnan(event["recall"])


def test_gate_selection_prefers_coverage_and_then_the_lowest_qualifying_gate(fields):
    examples = [{"id": "clear", "fields": fields}, {"id": "weaker", "fields": fields}]
    weaker = supported_answers()
    weaker["action_supported"] = noul(0.8)
    answers = {"clear": supported_answers(), "weaker": weaker}
    gold = {
        ident: {"claims": dict.fromkeys(("phase", "action", "status"), "supported")}
        for ident in ("clear", "weaker")
    }
    gate, _ = helpers.select_gate(examples, answers, gold)
    assert gate == 0.0


def test_gate_selection_fails_if_no_candidate_meets_the_declared_accuracy(fields):
    examples = [{"id": "wrong", "fields": fields}]
    answers = {"wrong": supported_answers()}
    gold = {"wrong": {"claims": dict.fromkeys(("phase", "action", "status"), "unsupported")}}
    with pytest.raises(ValueError, match="no validation gate"):
        helpers.select_gate(examples, answers, gold)


def test_threshold_objective_pins_the_executed_accuracy_requirement():
    """A changed accuracy target must fail even if it selects the same fixture threshold."""
    source = inspect.getsource(helpers.select_gate)
    tree = ast.parse(source)
    requirements = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "accuracy"
    ]
    assert len(requirements) == 1
    requirement = requirements[0]
    assert len(requirement.ops) == 1
    assert isinstance(requirement.ops[0], ast.GtE)
    assert len(requirement.comparators) == 1
    assert isinstance(requirement.comparators[0], ast.Constant)
    assert requirement.comparators[0].value == 1.0
