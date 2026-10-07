"""The fixture loaders and the validator.

Every check must be able to fail: each bad fixture below breaks exactly one rule, and the
test asserts the specific message for it. Key-like strings are assembled at run time so this
file contains nothing a secret scanner would flag.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jev_cookbook import (
    DecisionResult,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    get_backend,
    replay_key,
)
from jev_cookbook import fixtures as fixtures_module
from jev_cookbook.fixtures import (
    FixtureFileError,
    load_inputs,
    load_labels,
    load_responses,
    load_schema,
    responses_path,
    select_split,
    validate_all,
    validate_recipe,
)
from jev_cookbook.fixtures import _scan as scan_module
from jev_cookbook.fixtures.__main__ import main
from jev_cookbook.fixtures._scan import scan_text
from jev_cookbook.fixtures._schema import check

ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"
QUESTIONS = {"billing": Noul(instructions="Is this ticket about billing?")}


def request_key(text: str) -> str:
    return replay_key({"text": text}, QUESTIONS)


def result(source: str = "synthetic", model: str = "model-a", p: float = 0.9) -> dict:
    if source == "synthetic":
        answer = NoulAnswer(p, Provenance.synthetic())
        return DecisionResult({"billing": answer}, "synthetic").to_dict()
    answer = NoulAnswer(p, Provenance.recorded(model, "2026-01-02"))
    return DecisionResult({"billing": answer}, model).to_dict()


def good_set() -> dict:
    """Four examples (two validation, two test), a label each, and one response each."""
    inputs, labels, responses = [], [], {}
    for i, split in enumerate(["validation", "validation", "test", "test"]):
        text = f"ticket {i}: I was charged twice"
        key = request_key(text)
        inputs.append(
            {"id": f"t{i}", "split": split, "state": {"text": text}, "replay_keys": [key]}
        )
        labels.append({"id": f"t{i}", "label": "billing" if i % 2 == 0 else "other"})
        responses[key] = result()
    return {"inputs": inputs, "labels": labels, "responses": responses}


def write(recipe: Path, data: dict, *, bom: bool = False) -> Path:
    """Write the fixture files; ``bom`` puts a byte order mark on inputs and labels only.

    ``data["responses"]`` of ``None`` writes no responses file, and ``data["tagged"]``
    (``{tag: responses}``) writes ``responses-<tag>.json`` files.
    """
    folder = recipe / "fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    enc = "utf-8-sig" if bom else "utf-8"
    for name, rows in (("inputs", data["inputs"]), ("labels", data["labels"])):
        text = "".join(json.dumps(r) + "\n" for r in rows)
        (folder / f"{name}.jsonl").write_text(text, encoding=enc, newline="\n")
    files = {"responses.json": data["responses"]}
    files.update({f"responses-{tag}.json": r for tag, r in data.get("tagged", {}).items()})
    for name, responses in files.items():
        if responses is None:
            (folder / name).unlink(missing_ok=True)
        else:
            (folder / name).write_text(
                json.dumps(responses, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
    return recipe


def messages(recipe: Path) -> list[str]:
    return [str(p) for p in validate_recipe(recipe)]


def expect(recipe: Path, *fragments: str) -> None:
    found = messages(recipe)
    for fragment in fragments:
        assert any(fragment in m for m in found), f"{fragment!r} not in {found}"


@pytest.fixture
def recipe(tmp_path: Path) -> Path:
    return write(tmp_path / "01-demo", good_set())


# ------------------------------------------------------------------ the good example


def test_good_set_is_valid(recipe):
    assert messages(recipe) == []


def test_loaders_read_the_good_set(recipe):
    examples = load_inputs(recipe)
    assert [e.id for e in examples] == ["t0", "t1", "t2", "t3"]
    assert examples[0].state == {"text": "ticket 0: I was charged twice"}
    assert examples[0].fields is None
    assert [e.id for e in select_split(examples, "test")] == ["t2", "t3"]
    assert load_labels(recipe) == {"t0": "billing", "t1": "other", "t2": "billing", "t3": "other"}
    assert set(load_responses(recipe)) == {k for e in examples for k in e.replay_keys}


def test_replay_backend_accepts_the_responses_file(recipe):
    backend = ReplayBackend.from_json(responses_path(recipe))
    state = {"text": "ticket 0: I was charged twice"}
    assert backend.decide(state, QUESTIONS)["billing"].noul == 0.9
    assert get_backend(fixtures=responses_path(recipe)).mode == "synthetic"


def test_default_directory_is_the_working_directory(recipe, monkeypatch):
    monkeypatch.chdir(recipe)
    assert [e.id for e in load_inputs()] == ["t0", "t1", "t2", "t3"]
    assert validate_recipe() == []
    assert responses_path() == Path("fixtures/responses.json")


def test_fields_can_replace_state(recipe):
    data = good_set()
    row = data["inputs"][0]
    row["fields"] = {"text": row.pop("state")["text"]}
    write(recipe, data)
    assert messages(recipe) == []
    assert load_inputs(recipe)[0].fields == {"text": "ticket 0: I was charged twice"}


def test_state_may_be_text_or_a_list_of_strings_and_train_and_demo_splits_exist(recipe):
    data = good_set()
    for i, (state, split) in enumerate([("plain text", "train"), (["a", "b"], "demo")]):
        key = request_key(f"extra {i}")
        data["inputs"].append({"id": f"x{i}", "split": split, "state": state, "replay_keys": [key]})
        data["responses"][key] = result()
    data["labels"].append({"id": "x0", "label": 1})  # a train example needs a label
    write(recipe, data)
    assert messages(recipe) == []  # the demo example needs none


def test_recorded_set_is_valid(recipe):
    data = good_set()
    data["responses"] = {k: result("recorded") for k in data["responses"]}
    write(recipe, data)
    assert messages(recipe) == []
    assert get_backend(fixtures=responses_path(recipe)).mode == "recorded"


def test_label_may_be_a_structure_and_unicode_survives(recipe):
    data = good_set()
    data["labels"][0]["label"] = {"billing": True, "tags": ["café", "☃"]}
    write(recipe, data)
    assert messages(recipe) == []
    assert load_labels(recipe)["t0"]["tags"] == ["café", "☃"]


def test_a_label_may_be_a_list_and_an_empty_list(recipe):
    data = good_set()
    data["labels"][0]["label"] = ["billing", "refund"]
    data["labels"][1]["label"] = []
    write(recipe, data)
    assert messages(recipe) == []
    assert load_labels(recipe)["t0"] == ["billing", "refund"]
    assert load_labels(recipe)["t1"] == []


# ----------------------------------------------------------- inputs and labels: schema


def mutate_inputs(recipe: Path, change) -> Path:
    data = good_set()
    change(data["inputs"])
    return write(recipe, data)


def test_duplicate_input_id(recipe):
    mutate_inputs(recipe, lambda rows: rows[1].update(id="t0"))
    expect(recipe, "inputs.jsonl:2 (id 't0'): duplicate id (first used on line 1)")


def test_unknown_split(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].update(split="holdout"))
    expect(recipe, "inputs.jsonl:1 (id 't0'): field 'split': must be one of")


def test_missing_required_splits(recipe):
    def change(rows):
        for row in rows:
            row["split"] = "validation"

    mutate_inputs(recipe, change)
    expect(recipe, "no example has the required split 'test'")


def test_missing_validation_split(recipe):
    def change(rows):
        for row in rows:
            row["split"] = "test"

    mutate_inputs(recipe, change)
    expect(recipe, "no example has the required split 'validation'")


def test_state_and_fields_together(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].update(fields={"a": 1}))
    expect(recipe, "must have exactly one of 'state', 'fields', found 2")


def test_neither_state_nor_fields(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].pop("state"))
    expect(recipe, "must have exactly one of 'state', 'fields', found 0")


def test_unknown_input_field(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].update(extra=1))
    expect(recipe, "field 'extra': unknown field 'extra'")


def test_missing_replay_keys(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].pop("replay_keys"))
    expect(recipe, "missing required field 'replay_keys'")


@pytest.mark.parametrize("bad", ["not-a-key", "A" * 64, "a" * 63])
def test_malformed_replay_key_in_input(recipe, bad):
    mutate_inputs(recipe, lambda rows: rows[0].update(replay_keys=[bad]))
    expect(recipe, "field 'replay_keys[0]'", "does not match the pattern")


def test_repeated_replay_key_in_one_input(recipe):
    def change(rows):
        rows[0]["replay_keys"] = rows[0]["replay_keys"] * 2

    mutate_inputs(recipe, change)
    expect(recipe, "field 'replay_keys': must not repeat an item")


@pytest.mark.parametrize("bad", ["", "has space", "../x", "-lead", "x" * 65, 7])
def test_bad_id(recipe, bad):
    mutate_inputs(recipe, lambda rows: rows[0].update(id=bad))
    assert any("field 'id'" in m for m in messages(recipe))


def test_state_of_the_wrong_type(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].update(state=5))
    expect(recipe, "field 'state': must be string or object or array, found integer")


def test_an_empty_state_string_is_rejected(recipe):
    data = good_set()
    data["inputs"][0]["state"] = ""
    write(recipe, data)
    expect(recipe, "inputs.jsonl:1 (id 't0'): field 'state':")


def test_state_list_must_hold_strings(recipe):
    mutate_inputs(recipe, lambda rows: rows[0].update(state=["a", 1]))
    expect(recipe, "field 'state[1]': must be string, found integer")


def test_same_state_in_two_splits(recipe):
    def change(rows):
        rows[2]["state"] = copy.deepcopy(rows[0]["state"])

    mutate_inputs(recipe, change)
    expect(recipe, "(id 't2'): same state as 't0' (validation) in a different split (test)")


def test_a_demo_example_may_repeat_a_state(recipe):
    data = good_set()
    data["inputs"].append({**data["inputs"][0], "id": "d1", "split": "demo"})
    write(recipe, data)
    assert messages(recipe) == []


def test_missing_label(recipe):
    data = good_set()
    data["labels"].pop(1)
    write(recipe, data)
    expect(recipe, "labels.jsonl (id 't1'): no label for the validation example")


def test_orphan_label(recipe):
    data = good_set()
    data["labels"].append({"id": "ghost", "label": "billing"})
    write(recipe, data)
    expect(recipe, "labels.jsonl:5 (id 'ghost'): label for an id that is not in the inputs")


def test_duplicate_label_id(recipe):
    data = good_set()
    data["labels"].append({"id": "t0", "label": "other"})
    write(recipe, data)
    expect(recipe, "labels.jsonl:5 (id 't0'): duplicate id (first used on line 1)")


def test_null_label_is_rejected(recipe):
    data = good_set()
    data["labels"][0]["label"] = None
    write(recipe, data)
    expect(recipe, "labels.jsonl:1 (id 't0'): field 'label': must be string or number")


def test_label_without_label_field(recipe):
    data = good_set()
    del data["labels"][0]["label"]
    write(recipe, data)
    expect(recipe, "labels.jsonl:1 (id 't0'): missing required field 'label'")


# --------------------------------------------------------------- responses and linking


def test_input_names_a_response_that_does_not_exist(recipe):
    data = good_set()
    data["inputs"][0]["replay_keys"] = [request_key("something else")]
    write(recipe, data)
    expect(recipe, "responses.json (id 't0'): no response for replay key")
    expect(recipe, "response that no input lists in replay_keys")


def test_response_without_an_input(recipe):
    data = good_set()
    key = request_key("nobody asked")
    data["responses"][key] = result()
    write(recipe, data)
    expect(recipe, f"responses.json (id {key!r}): response that no input lists in replay_keys")


def test_malformed_response_key(recipe):
    data = good_set()
    data["responses"]["ABC"] = result()
    write(recipe, data)
    expect(recipe, "replay key must be 64 lowercase hex characters: 'ABC'")


def test_stored_response_that_replay_would_reject(recipe):
    data = good_set()
    key = data["inputs"][0]["replay_keys"][0]
    data["responses"][key]["answers"]["billing"]["noul"] = 1.5
    write(recipe, data)
    expect(recipe, f"responses.json (id {key!r}): bad stored response:")


def test_a_provenance_that_is_not_an_object_is_a_problem_not_a_crash(recipe):
    data = good_set()
    key = data["inputs"][0]["replay_keys"][0]
    data["responses"][key]["answers"]["billing"]["provenance"] = []
    write(recipe, data)
    expect(recipe, f"responses.json (id {key!r}): bad stored response:")
    with pytest.raises(FixtureFileError, match="bad stored response"):
        load_responses(recipe)


def test_a_parser_that_overflows_anyway_is_a_problem_not_a_crash(recipe, monkeypatch):
    """The depth scan normally stops deep input first. This makes ``json.loads`` raise
    RecursionError for input that passes the scan, to cover the backstop in ``_loads``."""
    real_loads = json.loads

    def loads(text, **kwargs):
        if "OVERFLOW" in text:
            raise RecursionError("maximum recursion depth exceeded")
        return real_loads(text, **kwargs)

    monkeypatch.setattr(fixtures_module.json, "loads", loads)
    folder = recipe / "fixtures"
    (folder / "labels.jsonl").write_text(
        '{"id": "t0", "label": "x"}\n{"id": "t1", "label": "OVERFLOW"}\n', encoding="utf-8"
    )
    expect(recipe, "labels.jsonl:2: invalid JSON: nested too deeply")
    (folder / "responses.json").write_text('{"a": "OVERFLOW"}', encoding="utf-8")
    expect(recipe, "responses.json: invalid JSON: nested too deeply")
    with pytest.raises(FixtureFileError, match="nested too deeply"):
        load_responses(recipe)


# ----------------------------------------------------------- the nesting limit


def nested(levels: int, inner: object = 1) -> object:
    """``{"a": {"a": ... inner}}`` with ``levels`` objects (built without recursion)."""
    value = inner
    for _ in range(levels):
        value = {"a": value}
    return value


def deep_text(levels: int) -> str:
    return '{"a":' * levels + "1" + "}" * levels


def limit_set(levels: int, where: str) -> dict:
    """The good set with one value that makes its line ``levels`` deep (the line is level 1)."""
    data = good_set()
    if where == "state":
        state = nested(levels - 1)
        key = request_key_for(state)
        data["inputs"][0]["state"] = state
        data["responses"][key] = data["responses"].pop(data["inputs"][0]["replay_keys"][0])
        data["inputs"][0]["replay_keys"] = [key]
    elif where == "fields":
        data["inputs"][0]["fields"] = nested(levels - 1)
        del data["inputs"][0]["state"]
    else:
        data["labels"][0]["label"] = nested(levels - 1)
    return data


def request_key_for(state: object) -> str:
    return replay_key(state, QUESTIONS)


LIMIT = 64  # the documented nesting limit (docs/fixtures.md)
TOO_DEEP = "nested deeper than 64 levels"


@pytest.mark.parametrize("where", ["state", "fields", "label"])
def test_nesting_up_to_the_limit_is_valid_and_one_more_level_is_not(recipe, where):
    write(recipe, limit_set(LIMIT, where))
    assert messages(recipe) == []
    write(recipe, limit_set(LIMIT + 1, where))
    name = "labels" if where == "label" else "inputs"
    found = [m for m in messages(recipe) if TOO_DEEP in m]
    assert len(found) == 1 and found[0].startswith(
        f"{(recipe / 'fixtures' / name).as_posix()}.jsonl:1: "
    ), found


def test_a_responses_file_nested_deeper_than_the_limit_is_reported_with_its_line(recipe):
    for name in ("responses.json", "responses-b.json"):
        write(recipe, {**good_set(), "tagged": {"b": good_set()["responses"]}})
        path = recipe / "fixtures" / name
        for levels, deep in ((LIMIT, False), (LIMIT + 1, True)):
            # the open brace of the value is on line 3 of the file
            path.write_text('{\n"a":\n' + deep_text(levels - 1) + "\n}\n", encoding="utf-8")
            found = [m for m in messages(recipe) if TOO_DEEP in m]
            assert bool(found) is deep, (name, levels, found)
            if deep:
                assert any(m.startswith(f"{path.as_posix()}:3: ") for m in found), found
    with pytest.raises(FixtureFileError, match=TOO_DEEP):
        load_responses(recipe, "b")


@pytest.mark.parametrize(
    "name", ["inputs.jsonl", "labels.jsonl", "responses.json", "responses-b.json"]
)
def test_a_very_deep_line_is_a_problem_on_every_interpreter_and_the_run_goes_on(recipe, name):
    """Unmocked: 100,000 levels, which the parser and the stack treat differently per platform."""
    folder = recipe / "fixtures"
    (folder / "responses-b.json").write_text("{}", encoding="utf-8")
    deep = "[" * 100_000 + "]" * 100_000
    if name.endswith(".jsonl"):
        row = '{"id": "x9", "split": "demo", "replay_keys": [], "state": ' + deep + "}"
        row = row if name == "inputs.jsonl" else '{"id": "x9", "label": ' + deep + "}"
        with (folder / name).open("a", encoding="utf-8") as handle:
            handle.write(row + "\n")
    else:
        (folder / name).write_text('{"a": ' + deep + "}", encoding="utf-8")
    found = [m for m in messages(recipe) if TOO_DEEP in m]
    assert len(found) == 1 and found[0].startswith((folder / name).as_posix()), found
    assert main(["validate", str(recipe)]) == 1


QUOTE = '"'  # a string value that holds one double quote (written `\"` in the file)


def state_set(state: object) -> dict:
    """The good set with ``state`` as the first example's state, re-keyed to match."""
    data = good_set()
    key = request_key_for(state)
    data["inputs"][0]["state"] = state
    data["responses"][key] = data["responses"].pop(data["inputs"][0]["replay_keys"][0])
    data["inputs"][0]["replay_keys"] = [key]
    return data


@pytest.mark.parametrize(
    "state",
    [
        "[" * 100 + "{" * 100,
        'say "' + "{" * 100,
        "ends with a backslash \\" + "[" * 100,
        r"\u005b" * 100,
        {"[" * 100: "{" * 100, "k": 'x"' + "[" * 100},
    ],
    ids=["plain", "after-escaped-quote", "after-backslash", "escaped-bracket", "in-a-key"],
)
def test_brackets_inside_strings_do_not_count_toward_the_nesting_limit(recipe, state):
    write(recipe, state_set(state))
    assert messages(recipe) == []
    data = good_set()
    data["labels"][0]["label"] = state if isinstance(state, str) else "x"
    write(recipe, data)
    assert messages(recipe) == []


@pytest.mark.parametrize("string", [QUOTE, "a" + QUOTE, "\\", QUOTE + "\\", "\\" + QUOTE], ids=repr)
def test_a_deep_value_after_a_string_with_an_escape_is_still_too_deep(recipe, string):
    """The string ends where the parser says it does, so what follows it counts."""
    data = state_set({"q": string, "x": nested(LIMIT)})
    write(recipe, data)
    assert [m for m in messages(recipe) if TOO_DEEP in m], messages(recipe)
    data = good_set()
    data["labels"][0]["label"] = [string, nested(LIMIT)]
    write(recipe, data)
    assert [m for m in messages(recipe) if TOO_DEEP in m], messages(recipe)


def test_a_string_that_never_closes_is_checked_in_linear_time(recipe):
    """A 64 KB line of escaped quotes with no closing quote: quadratic scanning took ~18 s."""
    row = '{"id": "x9", "split": "demo", "replay_keys": [], "state": "' + '\\"' * 32_000
    with (recipe / "fixtures" / "inputs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(row + "\n")
    start = time.perf_counter()
    found = messages(recipe)
    elapsed = time.perf_counter() - start
    assert any("invalid JSON" in m for m in found), found
    assert elapsed < 1.0, f"took {elapsed:.2f} s"
    start = time.perf_counter()
    fixtures_module._check_depth('"' + '\\"' * 500_000)
    assert time.perf_counter() - start < 1.0


def test_response_without_provenance(recipe):
    data = good_set()
    key = data["inputs"][0]["replay_keys"][0]
    del data["responses"][key]["answers"]["billing"]["provenance"]
    write(recipe, data)
    expect(recipe, f"(id {key!r}): bad stored response:")


def test_empty_responses_file(recipe):
    (recipe / "fixtures" / "responses.json").write_text("{}\n", encoding="utf-8")
    expect(recipe, "responses.json: has no responses")


def test_a_malformed_key_does_not_switch_off_the_other_checks(recipe):
    data = good_set()
    data["responses"]["NOTAKEY"] = result()
    data["labels"].pop(1)
    data["inputs"][2]["replay_keys"] = [request_key("something else")]
    write(recipe, data)
    expect(
        recipe,
        "replay key must be 64 lowercase hex characters: 'NOTAKEY'",
        "labels.jsonl (id 't1'): no label for the validation example",
        "responses.json (id 't2'): no response for replay key",
    )


def test_responses_must_be_an_object(recipe):
    (recipe / "fixtures" / "responses.json").write_text("[]\n", encoding="utf-8")
    expect(recipe, "responses.json: must be a JSON object of replay_key -> response")


def test_duplicate_key_in_responses_file(recipe):
    path = recipe / "fixtures" / "responses.json"
    text = path.read_text(encoding="utf-8")
    key = next(iter(json.loads(text)))
    path.write_text(text.rstrip()[:-1] + f',\n"{key}": {{}}}}\n', encoding="utf-8")
    expect(recipe, "responses.json:", "duplicate key")


# ------------------------------------------------------------------------- provenance


def test_mixed_synthetic_and_recorded(recipe):
    data = good_set()
    first = data["inputs"][0]["replay_keys"][0]
    data["responses"][first] = result("recorded")
    write(recipe, data)
    expect(recipe, "mixes recorded answers (1 response(s)) with synthetic answers (3 response(s)")


def test_recorded_file_with_one_synthetic_answer(recipe):
    data = good_set()
    data["responses"] = {k: result("recorded") for k in data["responses"]}
    data["responses"][data["inputs"][3]["replay_keys"][0]] = result()
    write(recipe, data)
    expect(recipe, "mixes recorded answers (3 response(s)) with synthetic answers (1 response(s)")


def test_two_models(recipe):
    data = good_set()
    data["responses"] = {k: result("recorded") for k in data["responses"]}
    last = data["inputs"][3]["replay_keys"][0]
    data["responses"][last] = result("recorded", model="model-b")
    write(recipe, data)
    expect(recipe, "responses come from more than one model: ['model-a', 'model-b']")


def test_recorded_dates_may_differ_between_responses(recipe):
    data = good_set()
    data["responses"] = {k: result("recorded") for k in data["responses"]}
    last = data["inputs"][3]["replay_keys"][0]
    for answer in data["responses"][last]["answers"].values():
        answer["provenance"]["date"] = "2026-02-03"
    write(recipe, data)
    assert messages(recipe) == []


# --------------------------------------------- ids, keys, splits, demo and the leak rule


@pytest.mark.parametrize("bad", ["t0\n", "t0 ", "t0\r"])
def test_an_id_must_match_the_whole_pattern(recipe, bad):
    # Python's "$" also matches before a trailing newline; the pattern is matched whole.
    data = good_set()
    data["inputs"][0]["id"] = bad
    data["labels"][0]["id"] = bad
    write(recipe, data)
    found = messages(recipe)
    assert any("inputs.jsonl:1" in m and "field 'id'" in m for m in found), found
    assert any("labels.jsonl:1" in m and "field 'id'" in m for m in found), found


def test_a_replay_key_must_match_the_whole_pattern(recipe):
    data = good_set()
    key = data["inputs"][0]["replay_keys"][0]
    data["inputs"][0]["replay_keys"] = [key + "\n"]
    write(recipe, data)
    expect(recipe, "field 'replay_keys[0]'", "does not match the pattern")


def test_ids_that_differ_only_by_case_are_an_error(recipe):
    mutate_inputs(recipe, lambda rows: rows[1].update(id="T0"))
    expect(recipe, "inputs.jsonl:2 (id 'T0'): id differs only by case from 't0' (line 1)")
    data = good_set()
    data["labels"].append({"id": "T1", "label": "x"})
    write(recipe, data)
    expect(recipe, "labels.jsonl:5 (id 'T1'): id differs only by case from 't1' (line 2)")


def test_a_label_for_a_demo_example_is_an_error(recipe):
    data = good_set()
    data["inputs"].append({**data["inputs"][0], "id": "d1", "split": "demo"})
    data["labels"].append({"id": "d1", "label": "billing"})
    write(recipe, data)
    expect(recipe, "labels.jsonl:5 (id 'd1'): label for a demo example")


def test_a_key_copied_from_another_example_is_reported(recipe):
    """t3 lists t2's key and loses its own response: every key still has a response."""
    data = good_set()
    own = data["inputs"][3]["replay_keys"][0]
    data["inputs"][3]["replay_keys"] = list(data["inputs"][2]["replay_keys"])
    del data["responses"][own]
    write(recipe, data)
    found = messages(recipe)
    assert not any("no response for replay key" in m or "no input lists" in m for m in found)
    expect(
        recipe, "inputs.jsonl (id 't3'): replay key", "is also listed by 't2', whose state differs"
    )


def test_fields_examples_that_differ_only_in_a_python_owned_field_may_share_a_key(recipe):
    """build_state keeps only the text, so the request (and the key) is the same."""
    data = good_set()
    for row in data["inputs"]:
        row["fields"] = {"text": row.pop("state")["text"], "role": "admin"}
    data["inputs"][1]["fields"] = {**data["inputs"][0]["fields"], "role": "viewer"}
    data["inputs"][1]["replay_keys"] = list(data["inputs"][0]["replay_keys"])
    del data["responses"][request_key("ticket 1: I was charged twice")]
    write(recipe, data)
    assert messages(recipe) == []


def test_a_state_example_and_a_fields_example_may_make_the_same_request(recipe):
    data = good_set()
    data["inputs"][1]["fields"] = {"text": data["inputs"][0]["state"]["text"], "role": "viewer"}
    del data["inputs"][1]["state"]
    data["inputs"][1]["replay_keys"] = list(data["inputs"][0]["replay_keys"])
    del data["responses"][request_key("ticket 1: I was charged twice")]
    write(recipe, data)
    assert messages(recipe) == []


def test_multi_request_examples_may_share_a_later_request(recipe):
    """Each example makes its own routing request, then the same policy request."""
    data = good_set()
    policy = request_key("the policy request, identical for every example")
    for row in data["inputs"]:
        row["replay_keys"].append(policy)
    data["responses"][policy] = result()
    write(recipe, data)
    assert messages(recipe) == []


def test_examples_with_the_same_state_may_share_a_key(recipe):
    data = good_set()
    data["inputs"].append({**data["inputs"][0], "id": "d1", "split": "demo"})  # same keys
    write(recipe, data)
    assert messages(recipe) == []


@pytest.mark.parametrize(
    ("a", "b"), [("train", "validation"), ("validation", "test"), ("train", "test")]
)
def test_same_state_in_any_two_of_train_validation_test_is_a_leak(recipe, a, b):
    def change(rows):
        rows[0]["split"], rows[2]["split"] = a, b
        rows[1]["split"], rows[3]["split"] = "validation", "test"
        rows[2]["state"] = copy.deepcopy(rows[0]["state"])
        rows[2]["replay_keys"] = list(rows[0]["replay_keys"])

    data = good_set()
    change(data["inputs"])
    del data["responses"][request_key("ticket 2: I was charged twice")]
    write(recipe, data)
    expect(recipe, f"(id 't2'): same state as 't0' ({a}) in a different split ({b})")


def test_same_fields_in_two_splits_is_a_leak(recipe):
    data = good_set()
    for row in data["inputs"]:
        row["fields"] = {"text": row.pop("state")["text"]}
    data["inputs"][2]["fields"] = copy.deepcopy(data["inputs"][0]["fields"])
    data["inputs"][2]["replay_keys"] = list(data["inputs"][0]["replay_keys"])
    del data["responses"][request_key("ticket 2: I was charged twice")]
    write(recipe, data)
    expect(recipe, "(id 't2'): same fields as 't0' (validation) in a different split (test)")


@pytest.mark.parametrize("what", ["state", "fields"])
def test_the_leak_rule_ignores_the_order_of_keys(recipe, what):
    data = good_set()
    first = {"text": "ticket 0: I was charged twice", "lang": "en"}
    second = {"lang": "en", "text": "ticket 0: I was charged twice"}  # same content, other order
    assert first == second and list(first) != list(second)
    for row in data["inputs"]:
        row.pop("state")
    data["inputs"][0][what], data["inputs"][2][what] = first, second
    data["inputs"][1][what] = {"text": "ticket 1: I was charged twice"}
    data["inputs"][3][what] = {"text": "ticket 3: I was charged twice"}
    for row in data["inputs"]:
        row["replay_keys"] = [request_key(row[what]["text"])]
    data["responses"] = {row["replay_keys"][0]: result() for row in data["inputs"]}
    write(recipe, data)
    expect(recipe, f"(id 't2'): same {what} as 't0' (validation) in a different split (test)")


def test_the_same_state_twice_in_one_split_is_not_a_leak(recipe):
    data = good_set()
    data["inputs"][1]["state"] = copy.deepcopy(data["inputs"][0]["state"])
    data["inputs"][1]["replay_keys"] = list(data["inputs"][0]["replay_keys"])
    del data["responses"][request_key("ticket 1: I was charged twice")]
    write(recipe, data)
    assert messages(recipe) == []


# ------------------------------------------------- modes: replay and scripted recipes


def scripted_set() -> dict:
    """Examples that nothing replays: no keys, no responses file."""
    data = good_set()
    for row in data["inputs"]:
        row["replay_keys"] = []
    data["responses"] = None
    return data


def test_replay_mode_is_reported(recipe):
    report = validate_recipe(recipe)
    assert report == [] and report.mode == "replay"


def test_a_scripted_recipe_needs_no_keys_and_no_responses_file(recipe):
    write(recipe, scripted_set())
    assert not (recipe / "fixtures" / "responses.json").exists()
    report = validate_recipe(recipe)
    assert report == [] and report.mode == "scripted"
    assert len(load_inputs(recipe)) == 4 and load_inputs(recipe)[0].replay_keys == ()


def test_a_scripted_recipe_may_omit_replay_keys_per_example(recipe):
    data = good_set()
    data["inputs"][0]["replay_keys"] = []  # one example the notebook does not replay
    del data["responses"][request_key("ticket 0: I was charged twice")]
    write(recipe, data)
    report = validate_recipe(recipe)
    assert report == [] and report.mode == "replay"


def test_a_responses_file_nobody_lists_is_an_error_in_scripted_mode(recipe):
    data = scripted_set()
    data["responses"] = good_set()["responses"]
    write(recipe, data)
    expect(recipe, "response that no input lists in replay_keys")
    assert validate_recipe(recipe).mode == "scripted"


def test_listed_keys_without_a_responses_file(recipe):
    data = good_set()
    data["responses"] = None
    write(recipe, data)
    found = messages(recipe)
    assert found == [f"{(recipe / 'fixtures' / 'responses.json').as_posix()}: file is missing"]


def test_the_report_keeps_its_mode_through_slicing_copying_and_adding_and_shows_it(recipe):
    (recipe / "fixtures" / "labels.jsonl").unlink()
    report = validate_recipe(recipe)
    assert report.mode == "replay" and len(report) == 1
    assert report[:].mode == "replay" and report[0:1] == list(report)
    assert report.copy().mode == "replay" and (report + list(report)).mode == "replay"
    assert not isinstance(report[0], list) and len(report + list(report)) == 2
    assert repr(report).startswith("Report(mode='replay', problems=[Problem(")
    assert repr(validate_recipe(recipe / "nowhere")).startswith("Report(mode=None")


def test_mode_is_unknown_when_the_inputs_cannot_be_read(recipe):
    (recipe / "fixtures" / "inputs.jsonl").unlink()
    assert validate_recipe(recipe).mode is None


def test_cli_prints_the_mode(recipe, tmp_path, capsys):
    assert main(["validate", str(recipe)]) == 0
    assert "fixtures valid (mode replay)" in capsys.readouterr().out
    other = write(tmp_path / "02-scripted", scripted_set())
    assert main(["validate", str(other)]) == 0
    assert "fixtures valid (mode scripted)" in capsys.readouterr().out
    (other / "fixtures" / "labels.jsonl").unlink()
    assert main(["validate", str(other)]) == 1
    captured = capsys.readouterr()
    assert "02-scripted: mode scripted" in captured.out


# ---------------------------------------------- comparison recipes: responses-<tag>.json


def tagged_set(tags=("b",), model="model-b") -> dict:
    data = good_set()
    data["responses"] = {k: result("recorded", "model-a") for k in data["responses"]}
    data["tagged"] = {t: {k: result("recorded", model) for k in data["responses"]} for t in tags}
    return data


def test_tagged_responses_are_valid_and_may_use_another_model(recipe):
    write(recipe, tagged_set(tags=("b", "gpt.4-x")))
    assert messages(recipe) == []
    assert set(load_responses(recipe, "b")) == set(load_responses(recipe))
    assert load_responses(recipe, "b")[next(iter(load_responses(recipe)))]["model"] == "model-b"
    assert responses_path(recipe, "b").name == "responses-b.json"
    assert get_backend(fixtures=responses_path(recipe, "b")).mode == "recorded"


def test_every_listed_key_must_be_in_every_tagged_file(recipe):
    data = tagged_set()
    del data["tagged"]["b"][data["inputs"][1]["replay_keys"][0]]
    write(recipe, data)
    expect(recipe, "responses-b.json (id 't1'): no response for replay key")


def test_a_tagged_file_may_not_hold_a_response_nobody_lists(recipe):
    data = tagged_set()
    data["tagged"]["b"][request_key("nobody asked")] = result("recorded", "model-b")
    write(recipe, data)
    expect(recipe, "responses-b.json", "response that no input lists in replay_keys")


def test_each_tagged_file_keeps_one_provenance_and_one_model(recipe):
    data = tagged_set()
    last = data["inputs"][3]["replay_keys"][0]
    data["tagged"]["b"][last] = result("recorded", "model-c")
    write(recipe, data)
    expect(recipe, "responses-b.json: responses come from more than one model")
    data = tagged_set()
    data["tagged"]["b"][last] = result()  # synthetic among recorded
    write(recipe, data)
    expect(recipe, "responses-b.json: mixes recorded answers")


def test_a_tagged_file_alone_does_not_stand_in_for_responses_json(recipe):
    data = tagged_set()
    data["responses"] = None
    write(recipe, data)
    assert messages(recipe) == [
        f"{(recipe / 'fixtures' / 'responses.json').as_posix()}: file is missing"
    ]


def test_a_tagged_file_in_a_scripted_recipe_is_an_error(recipe):
    data = scripted_set()
    data["tagged"] = {"b": good_set()["responses"]}
    write(recipe, data)
    expect(recipe, "responses-b.json", "response that no input lists in replay_keys")


@pytest.mark.parametrize("bad", ["bad tag", "../x", "", "x" * 65])
def test_a_bad_tag_is_refused(recipe, bad):
    with pytest.raises(ValueError, match="bad responses tag"):
        responses_path(recipe, bad)
    with pytest.raises(ValueError, match="bad responses tag"):
        load_responses(recipe, bad)


def test_loading_a_missing_tagged_file_names_it(recipe):
    with pytest.raises(FixtureFileError, match=r"responses-nope\.json: file is missing"):
        load_responses(recipe, "nope")


# ------------------------------------------------------ other files in fixtures/


@pytest.mark.parametrize(
    "name",
    [
        "ledger.json",
        "notes.txt",
        "responses-.json",
        "responses-bad tag.json",
        "responses.json.bak",
        "responses-b.json.bak",
        "responses.drift-x.json",
        "responses-b.drift-x.json",
    ],
)
def test_any_other_file_in_the_fixtures_folder_is_an_error(recipe, name):
    (recipe / "fixtures" / name).write_text("{}\n", encoding="utf-8")
    found = messages(recipe)
    assert len(found) == 1 and found[0].startswith((recipe / "fixtures" / name).as_posix()), found
    assert "unexpected entry in the fixtures folder" in found[0]


def test_a_folder_inside_fixtures_is_an_error(recipe):
    (recipe / "fixtures" / "ledgers").mkdir()
    expect(recipe, "ledgers: unexpected entry in the fixtures folder")


def test_a_key_shaped_string_in_a_tagged_file_is_found(recipe):
    data = tagged_set()
    data["tagged"]["b"][data["inputs"][0]["replay_keys"][0]]["note"] = FAKE_SK
    write(recipe, data)
    hits = [m for m in messages(recipe) if "[sk-prefixed-key]" in m]
    assert hits and "responses-b.json" in hits[0]


# ------------------------------------------------------------ files: BOM, JSON, UTF-8


def test_utf8_bom_is_accepted_in_inputs_and_labels(tmp_path):
    recipe = write(tmp_path / "bom", good_set(), bom=True)
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (recipe / "fixtures" / name).read_bytes().startswith(BOM)
    assert not (recipe / "fixtures" / "responses.json").read_bytes().startswith(BOM)
    assert messages(recipe) == []
    assert len(load_inputs(recipe)) == 4 and len(load_labels(recipe)) == 4
    assert len(load_responses(recipe)) == 4
    assert get_backend(fixtures=responses_path(recipe)).mode == "synthetic"


@pytest.mark.parametrize("tag", [None, "other"])
def test_bom_on_a_responses_file_is_rejected_because_replay_cannot_read_it(recipe, tag):
    data = good_set()
    data["tagged"] = {"other": data["responses"]}
    write(recipe, data)
    path = responses_path(recipe, tag)
    path.write_bytes(BOM + path.read_bytes())
    name = path.name
    expect(recipe, f"{name}: starts with a UTF-8 byte order mark, which ReplayBackend cannot")
    # the reason: the backend really cannot read it, and the loader says so by file name
    with pytest.raises(json.JSONDecodeError):
        ReplayBackend.from_json(path)
    with pytest.raises(FixtureFileError, match=rf"{name}: starts with a UTF-8 byte order mark"):
        load_responses(recipe, tag)


def test_whatever_validates_can_be_replayed(recipe):
    """The validator may not accept a responses file that ``get_backend`` cannot load."""
    data = good_set()
    data["tagged"] = {"b": data["responses"]}
    write(recipe, data)
    assert messages(recipe) == []
    for tag in (None, "b"):
        backend = get_backend(fixtures=responses_path(recipe, tag))
        state = {"text": "ticket 0: I was charged twice"}
        assert backend.decide(state, QUESTIONS)["billing"].noul == 0.9


def test_bad_json_line_names_file_and_line(recipe):
    path = recipe / "fixtures" / "inputs.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2][:-1]  # drop the closing brace
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    expect(recipe, "inputs.jsonl:3: invalid JSON:")
    with pytest.raises(FixtureFileError, match=r"inputs\.jsonl:3: invalid JSON") as caught:
        load_inputs(recipe)
    assert caught.value.problems[0].line == 3


def test_bad_json_in_responses_names_file_and_line(recipe):
    path = recipe / "fixtures" / "responses.json"
    path.write_text('{\n  "a": 1,\n  "b": \n', encoding="utf-8")
    with pytest.raises(FixtureFileError, match=r"responses\.json:4: invalid JSON"):
        load_responses(recipe)


def test_nan_is_not_json(recipe):
    path = recipe / "fixtures" / "labels.jsonl"
    path.write_text('{"id": "t0", "label": NaN}\n', encoding="utf-8")
    expect(recipe, "labels.jsonl:1: invalid JSON: NaN is not valid JSON")


def test_duplicate_object_key_within_a_line(recipe):
    path = recipe / "fixtures" / "labels.jsonl"
    path.write_text('{"id": "t0", "id": "t1", "label": 1}\n', encoding="utf-8")
    expect(recipe, "labels.jsonl:1: invalid JSON: duplicate key 'id'")


def test_blank_lines_and_crlf_are_tolerated_and_keep_line_numbers(recipe):
    path = recipe / "fixtures" / "labels.jsonl"
    rows = [json.dumps(r) for r in good_set()["labels"]]
    path.write_bytes(("\r\n\r\n".join(rows) + "\r\n{oops}\r\n").encode())
    expect(recipe, "labels.jsonl:8: invalid JSON:")


def test_a_line_separator_inside_a_string_does_not_split_a_row(recipe):
    data = good_set()
    data["labels"][0]["label"] = "a\u2028b"
    folder = recipe / "fixtures"
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data["labels"])
    (folder / "labels.jsonl").write_text(text, encoding="utf-8")
    assert load_labels(recipe)["t0"] == "a\u2028b"


def test_not_utf8(recipe):
    (recipe / "fixtures" / "labels.jsonl").write_bytes(b'{"id": "t0", "label": "caf\xe9"}\n')
    expect(recipe, "labels.jsonl: not valid UTF-8 (byte")


@pytest.mark.parametrize("name", ["inputs.jsonl", "labels.jsonl", "responses.json"])
def test_missing_file(recipe, name):
    (recipe / "fixtures" / name).unlink()
    found = messages(recipe)
    assert any(m.endswith(f"{name}: file is missing") for m in found)
    # one problem, not a cascade of "no label" / "no response" for a file that is simply absent
    assert len(found) == 1, found


def test_missing_fixtures_folder(tmp_path):
    assert messages(tmp_path) == [
        f"{(tmp_path / 'fixtures').as_posix()}: fixtures folder is missing"
    ]


def test_loader_error_for_missing_file(tmp_path):
    with pytest.raises(FixtureFileError, match=r"inputs\.jsonl: file is missing"):
        load_inputs(tmp_path)


def test_select_split_rejects_a_misspelled_split(recipe):
    with pytest.raises(ValueError, match="unknown split 'tests'"):
        select_split(load_inputs(recipe), "tests")


# ----------------------------------------------------------- key- and token-shaped text

# Assembled here, not written out, so this file stays clean for the repository scan.
FAKE_SK = "sk-" + "Ab3dE6gH9jK2mN5pQ8sT1vW4"
FAKE_GH = "ghp_" + "aB3d" * 9  # a repeated chunk: matches the vendor rule, not the entropy rule
FAKE_ASSIGN = "api_key" + ' = "' + "Qw3rT6yU9iO2pA5sD8fG1hJ4" + '"'
FAKE_BEARER = "Bearer " + "Zx3cV6bN9mQ2wE5rT8yU1iO4pA7"
FAKE_AWS = "AKIA" + "ABCDEFGH" + "IJKLMNOP"


@pytest.mark.parametrize(
    ("secret", "rule"),
    [
        (FAKE_SK, "sk-prefixed-key"),
        (FAKE_GH, "github-token"),
        (FAKE_ASSIGN, "secret-assignment"),
        (FAKE_BEARER, "bearer-token"),
        (FAKE_AWS, "aws-access-key-id"),
    ],
)
@pytest.mark.parametrize("where", ["inputs", "labels", "responses"])
def test_key_shaped_string_is_found_in_every_file(recipe, secret, rule, where):
    data = good_set()
    if where == "inputs":
        data["inputs"][0]["state"] = {"text": f"please use {secret} today"}
        key = request_key("x")
        data["inputs"][0]["replay_keys"] = [key]
        data["responses"] = {k: v for k, v in data["responses"].items()}
        data["responses"][key] = result()
        data["responses"].pop(request_key("ticket 0: I was charged twice"))
    elif where == "labels":
        data["labels"][0]["label"] = f"note {secret}"
    else:
        key = data["inputs"][0]["replay_keys"][0]
        data["responses"][key]["note"] = secret  # also an unknown key, reported separately
    write(recipe, data)
    hits = [m for m in messages(recipe) if f"[{rule}]" in m]
    assert hits, messages(recipe)
    assert f"{where}.json" in hits[0]
    assert secret not in hits[0]  # the message never repeats the whole value


@pytest.mark.parametrize("where", ["inputs", "labels", "responses"])
def test_a_key_shaped_string_in_an_object_key_is_found(recipe, where):
    """Only the decoded-string scan sees this: in the file the quotes are written ``\\"``."""
    secret_key = "api_key" + ' = "' + "Zq8Lm4Vr9Tx2Wp7Ks" + '"'
    if where == "inputs":
        data = state_set({secret_key: "x"})
    else:
        data = good_set()
        if where == "labels":
            data["labels"][0]["label"] = {secret_key: "x"}
        else:
            data["responses"][data["inputs"][0]["replay_keys"][0]]["note"] = {secret_key: "x"}
    write(recipe, data)
    hits = [m for m in messages(recipe) if "[secret-assignment]" in m]
    assert hits and f"{where}.json" in hits[0], messages(recipe)


def test_scan_reports_the_line_number(recipe):
    data = good_set()
    data["labels"][2]["label"] = FAKE_SK
    write(recipe, data)
    expect(recipe, "labels.jsonl:3: looks like a key or token [sk-prefixed-key]")


def test_a_secret_named_field_with_a_long_value_is_flagged_with_its_line(recipe):
    """Only the raw-text scan sees this: the key and the value are separate decoded strings."""
    data = good_set()
    data["labels"][2]["label"] = {"session_token": "abcd1234" * 2 + "abcd"}
    write(recipe, data)
    expect(recipe, "labels.jsonl:3: looks like a key or token [secret-assignment]")
    data["labels"][2]["label"] = {"session_token": "EXAMPLE-" + "abcd1234" * 2}  # marker
    write(recipe, data)
    assert messages(recipe) == []


def flag_rules(text: str) -> set[str]:
    return {rule for _, rule, _ in scan_text(text)}


# Assembled at run time, like the fakes above, so this file stays clean for the repository scan.
MARKED_BUT_FLAGGED = [
    ("sk-" + "EXAMPLE" + "aBcDeFgHiJkLmNoPqRsT", "sk-prefixed-key"),
    ("ghp_" + "EXAMPLE" + "a1" * 15, "github-token"),
    ("AKIA" + "IOSFODNN7" + "EXAMPLE", "aws-access-key-id"),
    ("api_key=" + "EXAMPLE_sk_live_" + "51HxQ2bL9", "high-entropy-token"),
]


@pytest.mark.parametrize(("text", "rule"), MARKED_BUT_FLAGGED)
def test_a_placeholder_marker_does_not_exempt_vendor_shaped_or_random_looking_values(text, rule):
    assert rule in flag_rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "password: EXAMPLE-Summer2024Holiday",
        "Authorization: Bearer <redacted>",
        "api_key = your-key-goes-here-0123456789",
        "secret: ***" + "0123456789abcdef",
        "<redacted>",
        "sk-...",
        "ghp_...",
    ],
)
def test_a_marker_exempts_key_name_and_header_style_values(text):
    assert flag_rules(text) == set()


def test_the_fake_credential_example_in_the_doc_is_accepted(recipe):
    doc = (ROOT / "docs" / "fixtures.md").read_text(encoding="utf-8")
    marker = "<!-- accepted-fake-credential -->\n```text\n"
    start = doc.index(marker) + len(marker)
    example = doc[start : doc.index("\n```", start)]
    data = good_set()
    data["labels"][2]["label"] = example
    write(recipe, data)
    assert messages(recipe) == []


def test_a_field_called_token_is_not_needed_and_prose_is_not_flagged(recipe):
    data = good_set()
    data["labels"][0]["label"] = "billing question about a refund token of goodwill"
    write(recipe, data)
    assert messages(recipe) == []


def load_repository_scanner():
    """``tools/check_hygiene.py`` as a module, imported by path (``tools/`` is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "check_hygiene_for_parity", ROOT / "tools" / "check_hygiene.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def pattern_state(pattern):
    return (pattern.pattern, pattern.flags)


SCANNER_FUNCTIONS = (
    "_scan_secrets_line",
    "_mask",
    "_is_placeholder",
    "_entropy",
    "_letters_and_digits",
)
SCANNER_PATTERNS = (
    "_AUTH_HEADER", "_BEARER", "_ASSIGNMENT", "_WORD", "_TOKEN", "_TOKEN_SLASH",
    "_PATH_SHAPED", "_DATA_URI", "_ANSI",
)  # fmt: skip


def test_the_packaged_scanner_has_the_same_rules_as_the_repository_scanner():
    """Every rule constant and every rule function is compared with ``tools/check_hygiene.py``.

    Comparing outputs on samples cannot see a changed threshold or a dropped vendor prefix;
    comparing the definitions does, so editing either copy alone fails here.
    """
    hygiene = load_repository_scanner()
    ours = {name: pattern_state(p) for name, p in scan_module._VENDOR_PATTERNS}
    theirs = {name: pattern_state(p) for name, p in hygiene._VENDOR_PATTERNS}
    assert list(ours) == list(theirs)
    assert ours == theirs
    for name in SCANNER_PATTERNS:
        assert pattern_state(getattr(scan_module, name)) == pattern_state(getattr(hygiene, name)), (
            name
        )
    assert scan_module._PLACEHOLDER_MARKERS == hygiene._PLACEHOLDER_MARKERS
    assert scan_module._ENTROPY_THRESHOLD == hygiene._ENTROPY_THRESHOLD
    for name in SCANNER_FUNCTIONS:
        ours_source = inspect.getsource(getattr(scan_module, name))
        assert ours_source == inspect.getsource(getattr(hygiene, name)), name


def test_the_packaged_scanner_flags_one_sample_per_rule_like_the_repository_scanner():
    hygiene = load_repository_scanner()
    # (sample, rule): each sample is the shortest thing that trips exactly that rule
    samples = [
        (FAKE_SK, "sk-prefixed-key"),
        (FAKE_GH, "github-token"),
        (FAKE_ASSIGN, "secret-assignment"),
        (FAKE_BEARER, "bearer-token"),
        (FAKE_AWS, "aws-access-key-id"),
        ("-----BEGIN RSA PRIVATE" + " KEY-----", "private-key-block"),
        ("github_pat_" + "a1B2" * 10, "github-fine-grained-token"),
        ("xoxb-" + "1234567890-abcdefghij", "slack-token"),
        ("AIza" + "Sy" + "a1B2" * 8 + "c", "google-api-key"),
        (
            "eyJhbGciOiJIUzI1NiJ9."
            + "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            + "dBjftJeZ4CVPmB92K27uhbUJU1p1r",
            "jwt",
        ),
        ("Authorization: " + "Basic " + "dXNlcjpwYXNzd29yZDEyMzQ1", "authorization-header-value"),
        (
            "word " + "Zx3cV6bN" + "9mQ2wE5r" + "T8yU1iO4" + "pA7sD0fG" + "2hJ" + " end",
            "high-entropy-token",
        ),
    ]
    for sample, rule in samples:
        assert rule in {r for _, r, _ in scan_text(sample)}, rule
    quiet = [
        "TYPESAFE_API_KEY=<your key>",
        "api_key = $KEY",
        "just an ordinary sentence about a billing ticket",
        "fixtures/replay/" + "a" * 64 + ".json",
        "0123456789abcdef" * 4,
        "Zm9vYmFy" * 6,
    ]
    for sample in [s for s, _ in samples] + quiet:
        assert scan_text(sample) == hygiene.scan_text(sample), sample
    assert not any(scan_text(s) for s in quiet)


# --------------------------------------------------------------------------------- CLI


def test_cli_exits_zero_on_a_good_recipe(recipe, capsys):
    assert main(["validate", str(recipe)]) == 0
    assert "fixtures valid" in capsys.readouterr().out


def test_cli_exits_nonzero_with_one_message_per_problem(recipe, capsys):
    data = good_set()
    data["inputs"][1]["id"] = "t0"
    data["labels"].pop(0)
    write(recipe, data)
    assert main(["validate", str(recipe)]) == 1
    err = capsys.readouterr().err.splitlines()
    assert any("duplicate id" in line for line in err)
    assert any("no label for the validation example" in line for line in err)
    assert err[-1].startswith(f"{len(err) - 1} problem(s) in 1 recipe(s)")


def test_cli_through_a_real_process(recipe, tmp_path):
    cmd = [sys.executable, "-m", "jev_cookbook.fixtures", "validate", str(recipe)]
    ok = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    assert ok.returncode == 0, ok.stderr
    (recipe / "fixtures" / "labels.jsonl").unlink()
    bad = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    assert bad.returncode == 1
    assert "labels.jsonl: file is missing" in bad.stderr


def test_cli_usage_errors_exit_two(recipe):
    with pytest.raises(SystemExit) as caught:
        main(["validate"])
    assert caught.value.code == 2
    with pytest.raises(SystemExit) as caught:
        main(["validate", str(recipe), "--all"])
    assert caught.value.code == 2


def make_recipes(root: Path, good: int, bad: int) -> Path:
    recipes = root / "recipes"
    for i in range(good):
        write(recipes / f"{i + 1:02d}-good", good_set())
    for i in range(bad):
        data = good_set()
        data["labels"].pop(0)
        write(recipes / f"{i + 50:02d}-bad", data)
    return recipes


def test_all_with_no_fixture_folders_passes(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "recipes" / "01-x").mkdir(parents=True)  # a recipe without fixtures/
    assert main(["validate", "--all"]) == 0
    assert "nothing to validate" in capsys.readouterr().out


def test_all_with_a_missing_recipes_directory_is_a_usage_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for argv in (["validate", "--all"], ["validate", "--all", "--recipes-dir", "recpies"]):
        with pytest.raises(SystemExit) as caught:
            main(argv)
        assert caught.value.code == 2
    assert "is not a directory" in capsys.readouterr().err


def test_all_goes_on_after_a_recipe_with_a_malformed_response(tmp_path, capsys):
    recipes = tmp_path / "recipes"
    crash = good_set()
    key = crash["inputs"][0]["replay_keys"][0]
    crash["responses"][key]["answers"]["billing"]["provenance"] = []
    write(recipes / "01-crash", crash)
    nolabel = good_set()
    nolabel["labels"].pop(0)
    write(recipes / "02-nolabel", nolabel)
    write(recipes / "03-good", good_set())
    assert main(["validate", "--all", "--recipes-dir", str(recipes)]) == 1
    captured = capsys.readouterr()
    assert f"(id {key!r}): bad stored response" in captured.err
    assert "no label for the validation example" in captured.err
    assert "03-good: fixtures valid" in captured.out
    assert "problem(s) in 2 recipe(s)" in captured.err


def test_all_validates_every_recipe_that_has_fixtures(tmp_path, capsys):
    recipes = make_recipes(tmp_path, good=2, bad=1)
    (recipes / "03-no-fixtures").mkdir()
    assert sorted(validate_all(recipes)) == sorted(
        [(recipes / n).as_posix() for n in ("01-good", "02-good", "50-bad")]
    )
    assert main(["validate", "--all", "--recipes-dir", str(recipes)]) == 1
    captured = capsys.readouterr()
    assert "01-good: fixtures valid" in captured.out
    assert "50-bad" in captured.err and "no label" in captured.err
    assert "1 problem(s) in 1 recipe(s)" in captured.err
    only_good = make_recipes(tmp_path / "only", good=2, bad=0)
    assert main(["validate", "--all", "--recipes-dir", str(only_good)]) == 0


# --------------------------------------------------------------- schema and packaging


def test_schema_is_packaged_and_has_the_two_row_definitions():
    schema = load_schema()
    assert set(schema["$defs"]) == {"input", "label"}
    assert schema["$defs"]["input"]["properties"]["split"]["enum"] == [
        "train",
        "validation",
        "test",
        "demo",
    ]


def test_schema_checker_rejects_keywords_it_does_not_implement():
    with pytest.raises(ValueError, match="not supported"):
        check(1, {"minimum": 3}, {})


def test_importing_the_module_does_not_import_tools_or_sdk():
    code = (
        "import sys, jev_cookbook.fixtures;"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('check_hygiene', 'tools', 'typesafe_sdk')];"
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
