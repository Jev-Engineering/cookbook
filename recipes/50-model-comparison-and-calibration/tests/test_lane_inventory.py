"""Recipe 50's lane inventories: each arm stores exactly the requests its own policy reaches.

These tests live apart from ``test_build_fixtures.py``, which the recipe guard holds
byte-identical to the scaffold, so the three-arm generator and inventory checks sit here."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

RECIPE = Path(__file__).resolve().parent.parent


def load_module_at(path, name):
    """Import build_fixtures.py by file path so its functions and module-level values are plain
    Python objects."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generator_reproduces_every_committed_lane_file(tmp_path):
    copy = tmp_path / "50-model-comparison-and-calibration"
    copy.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        (copy / name).write_bytes((RECIPE / name).read_bytes())
    done = subprocess.run(
        [sys.executable, str(copy / "build_fixtures.py")], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    for name in (
        "inputs.jsonl",
        "labels.jsonl",
        "responses.json",
        "responses-atlas.json",
        "responses-north.json",
    ):
        assert (copy / "fixtures" / name).read_bytes() == (RECIPE / "fixtures" / name).read_bytes()


def test_each_arm_stores_exactly_its_policy_reachable_requests():
    """No padded request-B answer for an arm whose own category skips it.

    Shared per-arm validation and the notebook audit must agree with the executed policy.
    """
    from jev_cookbook import AuditedBackend, ReplayBackend, load_helpers, replay_key
    from jev_cookbook.fixtures import load_inputs

    helpers = load_helpers(RECIPE)
    module = load_module_at(RECIPE / "build_fixtures.py", "recipe50_policy_inventory")
    observed_counts = {}
    for name, tag in module.BACKEND_TAGS.items():
        filename = "responses.json" if tag is None else f"responses-{tag}.json"
        committed = json.loads((RECIPE / "fixtures" / filename).read_text("utf-8"))
        generated = module.build_responses(module.ROWS, name)
        assert committed == generated
        lane = AuditedBackend(ReplayBackend(committed), label=name, replay_only=True)
        observed = set()
        for example in load_inputs(RECIPE):
            state = helpers.build_state(example.fields)
            questions_a = helpers.build_questions_a()
            answer = lane.decide(state, questions_a)["category"]
            observed.add(replay_key(state, questions_a))
            if helpers.needs_followup(answer):
                questions_b = helpers.build_questions_b()
                lane.decide(state, questions_b)
                observed.add(replay_key(state, questions_b))
        declared = {
            key
            for example in load_inputs(RECIPE)
            for file, keys in example.replay_lanes
            if file == filename
            for key in keys
        }
        assert set(committed) == observed == declared
        assert {call["replay_key"] for call in lane.audit()["calls"]} == observed
        observed_counts[name] = len(observed)
    assert observed_counts == {"jev": 41, "atlas-compact": 40, "northstar-7b": 41}


def test_atlas_t03_other_does_not_store_an_unreachable_followup():
    from jev_cookbook import load_helpers, replay_key

    helpers = load_helpers(RECIPE)
    module = load_module_at(RECIPE / "build_fixtures.py", "recipe50_t03_inventory")
    t03 = next(row for row in module.ROWS if row["id"] == "t03")
    state = helpers.build_state(
        {"statement": t03["statement"], "resubmission": t03["resubmission"]}
    )
    key_a = replay_key(state, helpers.build_questions_a())
    key_b = replay_key(state, helpers.build_questions_b())
    atlas = module.build_responses(module.ROWS, "atlas-compact")
    assert atlas[key_a]["answers"]["category"]["choice"] == "other"
    assert key_b not in atlas
    for name in ("jev", "northstar-7b"):
        assert key_b in module.build_responses(module.ROWS, name)
