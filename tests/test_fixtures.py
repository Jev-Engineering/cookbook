"""The fixture loaders and the validator.

Every check must be able to fail: each bad fixture below breaks exactly one rule, and the
test asserts the specific message for it. Key-like strings are assembled at run time so this
file contains nothing a secret scanner would flag.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
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
from jev_cookbook.fixtures.__main__ import main
from jev_cookbook.fixtures._scan import scan_text
from jev_cookbook.fixtures._schema import check

ROOT = Path(__file__).resolve().parent.parent
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
    folder = recipe / "fixtures"
    folder.mkdir(parents=True, exist_ok=True)
    enc = "utf-8-sig" if bom else "utf-8"
    for name, rows in (("inputs", data["inputs"]), ("labels", data["labels"])):
        text = "".join(json.dumps(r) + "\n" for r in rows)
        (folder / f"{name}.jsonl").write_text(text, encoding=enc, newline="\n")
    (folder / "responses.json").write_text(
        json.dumps(data["responses"], indent=2) + "\n", encoding=enc, newline="\n"
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


def test_response_without_provenance(recipe):
    data = good_set()
    key = data["inputs"][0]["replay_keys"][0]
    del data["responses"][key]["answers"]["billing"]["provenance"]
    write(recipe, data)
    expect(recipe, f"(id {key!r}): bad stored response:")


def test_empty_responses_file(recipe):
    (recipe / "fixtures" / "responses.json").write_text("{}\n", encoding="utf-8")
    expect(recipe, "responses.json: has no responses")


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


# ------------------------------------------------------------ files: BOM, JSON, UTF-8


def test_utf8_bom_is_accepted_everywhere(tmp_path):
    recipe = write(tmp_path / "bom", good_set(), bom=True)
    for name in ("inputs.jsonl", "labels.jsonl", "responses.json"):
        assert (recipe / "fixtures" / name).read_bytes().startswith(b"\xef\xbb\xbf")
    assert messages(recipe) == []
    assert len(load_inputs(recipe)) == 4 and len(load_labels(recipe)) == 4
    assert len(load_responses(recipe)) == 4


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
    data["labels"][0]["label"] = "a b"
    folder = recipe / "fixtures"
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data["labels"])
    (folder / "labels.jsonl").write_text(text, encoding="utf-8")
    assert load_labels(recipe)["t0"] == "a b"


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
FAKE_GH = "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4xY7zA0bC3d"
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


def test_scan_reports_the_line_number(recipe):
    data = good_set()
    data["labels"][2]["label"] = FAKE_SK
    write(recipe, data)
    expect(recipe, "labels.jsonl:3: looks like a key or token [sk-prefixed-key]")


def test_a_field_called_token_is_not_needed_and_prose_is_not_flagged(recipe):
    data = good_set()
    data["labels"][0]["label"] = "billing question about a refund token of goodwill"
    write(recipe, data)
    assert messages(recipe) == []


def test_scan_text_matches_the_repository_scanner():
    """The packaged scan is a copy of tools/check_hygiene.py's secret rules: keep them equal."""
    spec = importlib.util.spec_from_file_location(
        "check_hygiene", ROOT / "tools" / "check_hygiene.py"
    )
    hygiene = importlib.util.module_from_spec(spec)
    sys.modules["check_hygiene"] = hygiene
    spec.loader.exec_module(hygiene)
    samples = [
        FAKE_SK,
        FAKE_GH,
        FAKE_ASSIGN,
        FAKE_BEARER,
        FAKE_AWS,
        "-----BEGIN RSA PRIVATE" + " KEY-----",
        "Authorization: " + "Basic " + "dXNlcjpwYXNzd29yZDEyMzQ1",
        "eyJhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "dBjftJeZ4CVPmB92K27uhbUJU1p1r",
        "xoxb-" + "1234567890-abcdefghij",
        "TYPESAFE_API_KEY=<your key>",
        "api_key = $KEY",
        "just an ordinary sentence about a billing ticket",
        "fixtures/replay/" + "a" * 64 + ".json",
        "0123456789abcdef" * 4,
        "Zm9vYmFy" * 6,
    ]
    for sample in samples:
        assert scan_text(sample) == hygiene.scan_text(sample), sample
    assert any(scan_text(s) for s in samples[:5])


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
    assert main(["validate", "--all"]) == 0  # no recipes/ directory at all
    (tmp_path / "recipes" / "01-x").mkdir(parents=True)  # a recipe without fixtures/
    assert main(["validate", "--all"]) == 0
    assert "nothing to validate" in capsys.readouterr().out


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
