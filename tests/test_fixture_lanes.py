"""Explicit comparison inventories keep legacy validation and exact per-lane coverage."""

import copy
import json

import pytest

from jev_cookbook.fixtures import FixtureFileError, load_inputs, validate_recipe

KEYS = [character * 64 for character in "abcd"]


def response():
    return {
        "model": "synthetic",
        "answers": {
            "q": {
                "type": "noul",
                "noul": 0.9,
                "provenance": {"source": "synthetic", "model": None, "date": None},
            }
        },
    }


def data():
    rows = []
    for index, split in enumerate(("validation", "test")):
        keys = KEYS[index * 2 : index * 2 + 2]
        rows.append(
            {
                "id": f"r{index}",
                "split": split,
                "state": f"example {index}",
                "replay_keys": keys,
                "replay_lanes": [
                    {"responses": "responses.json", "keys": keys},
                    {"responses": "responses-saved.json", "keys": keys[:1]},
                ],
            }
        )
    return {
        "rows": rows,
        "responses.json": {key: response() for key in KEYS},
        "responses-saved.json": {key: response() for key in KEYS[::2]},
    }


def write(folder, values):
    fixtures = folder / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "inputs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in values["rows"])
    )
    labels = [{"id": row["id"], "label": "present"} for row in values["rows"]]
    (fixtures / "labels.jsonl").write_text("".join(json.dumps(row) + "\n" for row in labels))
    for name, responses in values.items():
        if name != "rows":
            (fixtures / name).write_text(json.dumps(responses))
    return folder


def test_branching_lanes_have_exact_distinct_inventories_and_keep_task_identity(tmp_path):
    values = data()
    write(tmp_path, values)
    assert not validate_recipe(tmp_path)
    examples = load_inputs(tmp_path)
    assert examples[0].replay_keys == tuple(KEYS[:2])
    assert examples[0].replay_lanes == (
        ("responses.json", tuple(KEYS[:2])),
        ("responses-saved.json", (KEYS[0],)),
    )
    assert (examples[0].id, examples[0].split, examples[0].state) == (
        "r0",
        "validation",
        "example 0",
    )


def test_legacy_comparisons_still_require_every_shared_key_in_every_file(tmp_path):
    values = data()
    for row in values["rows"]:
        del row["replay_lanes"]
    write(tmp_path, values)
    assert any(
        "no response for replay key" in str(problem) for problem in validate_recipe(tmp_path)
    )
    values["responses-saved.json"] = copy.deepcopy(values["responses.json"])
    write(tmp_path, values)
    assert not validate_recipe(tmp_path)


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        (lambda v: v["rows"][0].pop("replay_lanes"), "every response file"),
        (lambda v: v["rows"][0]["replay_lanes"].pop(), "every response file"),
        (
            lambda v: v["rows"][0]["replay_lanes"].append(
                copy.deepcopy(v["rows"][0]["replay_lanes"][0])
            ),
            "unique response names",
        ),
        (lambda v: v["rows"][0]["replay_lanes"][0].update(keys=[]), "replay_keys union"),
        (lambda v: v["rows"][0]["replay_lanes"][1]["keys"].append(KEYS[2]), "replay_keys union"),
        (lambda v: v["rows"][0]["replay_lanes"][1]["keys"].append(KEYS[0]), "repeat an item"),
        (
            lambda v: v["rows"][0]["replay_lanes"][1].update(responses="../responses.json"),
            "pattern",
        ),
        (
            lambda v: v["rows"][0]["replay_lanes"][1].update(responses="responses-other.json"),
            "every response file",
        ),
        (lambda v: v["rows"][0]["replay_lanes"][1].update(extra=True), "unknown field"),
        (lambda v: v["rows"][0].update(replay_lanes=[]), "at least 1"),
        (lambda v: v["rows"][0]["replay_lanes"][1].update(keys=["not-a-key"]), "pattern"),
        (lambda v: v["responses-saved.json"].pop(KEYS[0]), "no response for replay key"),
        (lambda v: v["responses-saved.json"].update({KEYS[1]: response()}), "no input lists"),
        (
            lambda v: v.update({"responses-extra.json": {KEYS[0]: response()}}),
            "every response file",
        ),
    ],
)
def test_lane_inventory_mutations_fail_with_specific_diagnostics(tmp_path, mutation, fragment):
    values = data()
    mutation(values)
    write(tmp_path, values)
    problems = validate_recipe(tmp_path)
    assert any(fragment in str(problem) for problem in problems), problems


def test_duplicate_lane_names_are_rejected_by_loader_too(tmp_path):
    values = data()
    values["rows"][0]["replay_lanes"].append(copy.deepcopy(values["rows"][0]["replay_lanes"][0]))
    write(tmp_path, values)
    with pytest.raises(FixtureFileError, match="unique response names"):
        load_inputs(tmp_path)


def test_lane_extension_does_not_hide_invalid_response_provenance(tmp_path):
    values = data()
    values["responses-saved.json"][KEYS[0]]["answers"]["q"]["provenance"]["source"] = "live"
    write(tmp_path, values)
    assert validate_recipe(tmp_path)


def test_different_shared_unions_cannot_hide_identical_lane_requests_across_splits(tmp_path):
    values = data()
    row = values["rows"][1]
    row["replay_keys"].append(KEYS[0])
    row["replay_lanes"][1]["keys"] = [KEYS[0]]
    values["responses-saved.json"].pop(KEYS[2])
    write(tmp_path, values)
    assert any("different split" in str(problem) for problem in validate_recipe(tmp_path))
