"""Issue #556: replacement needs unambiguous, consistently synthetic provenance.

These black-box tests are derived from the issue and the stored-answer contract in
answers.py, not a proposed guard implementation. Only disposable synthetic copies run.
The existing #489 harness supplies catalog discovery, CLI isolation and completion of
text-author TODOs; none of its guard predicates or test assertions is reused here.
"""

import copy
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

# Load this sibling explicitly: tests is not a package, and pytest uses importlib mode.
_SUPPORT_PATH = Path(__file__).with_name("test_fixture_overwrite_contract.py")
_SPEC = importlib.util.spec_from_file_location("fixture_overwrite_cli_support", _SUPPORT_PATH)
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)
REPO = Path(__file__).resolve().parents[1]
SENTINEL = "SYNTHETIC-FIXTURE-CONTENT-556"
RECORDED = {"source": "recorded", "model": SENTINEL, "date": "2026-01-01"}


def _json(value):
    return json.dumps(value, ensure_ascii=True)


def _object(pairs):
    """Encode pairs without losing duplicates before the builder sees their bytes."""
    return "{" + ",".join(_json(key) + ":" + value for key, value in pairs) + "}"


def _seed(raw):
    key, entry = next(iter(json.loads(raw).items()))
    entry = copy.deepcopy(entry)
    # A planted answer name makes accidental content/exception disclosure observable.
    answer = copy.deepcopy(next(iter(entry["answers"].values())))
    entry["answers"] = {SENTINEL: answer}
    return key, entry


def _payload(raw, case):
    key, entry = _seed(raw)
    answer = entry["answers"][SENTINEL]
    recorded_answer = copy.deepcopy(answer)
    recorded_answer["provenance"] = RECORDED
    recorded_entry = copy.deepcopy(entry)
    recorded_entry["model"] = SENTINEL
    recorded_entry["answers"] = {SENTINEL: recorded_answer}
    if case == "duplicate-response":
        text = _object([(key, _json(recorded_entry)), (key, _json(entry))])
    elif case == "duplicate-entry-model":
        text = _object(
            [
                (
                    key,
                    _object(
                        [
                            ("model", _json(SENTINEL)),
                            *[(name, _json(value)) for name, value in entry.items()],
                        ]
                    ),
                )
            ]
        )
    elif case == "duplicate-answer-name":
        answers = _object([(SENTINEL, _json(recorded_answer)), (SENTINEL, _json(answer))])
        text = _object(
            [
                (
                    key,
                    _object(
                        [
                            (name, answers if name == "answers" else _json(value))
                            for name, value in entry.items()
                        ]
                    ),
                )
            ]
        )
    elif case == "duplicate-answer-provenance":
        encoded_answer = _object(
            [
                ("provenance", _json(RECORDED)),
                *[(name, _json(value)) for name, value in answer.items()],
            ]
        )
        text = _object(
            [
                (
                    key,
                    _object(
                        [
                            (
                                name,
                                _object([(SENTINEL, encoded_answer)])
                                if name == "answers"
                                else _json(value),
                            )
                            for name, value in entry.items()
                        ]
                    ),
                )
            ]
        )
    elif case in {"duplicate-provenance-source", "escaped-provenance-source"}:
        # The escaped key spells the same decoded JSON member name as "source".
        provenance = (
            '{"source":"recorded",'
            + (
                '"sour\\u0063e":"synthetic"'
                if case.startswith("escaped")
                else '"source":"synthetic"'
            )
            + ',"model":null,"date":null}'
        )
        encoded_answer = _object(
            [
                (name, provenance if name == "provenance" else _json(value))
                for name, value in answer.items()
            ]
        )
        text = _object(
            [
                (
                    key,
                    _object(
                        [
                            (
                                name,
                                _object([(SENTINEL, encoded_answer)])
                                if name == "answers"
                                else _json(value),
                            )
                            for name, value in entry.items()
                        ]
                    ),
                )
            ]
        )
    elif case == "duplicate-identical-synthetic":
        text = _object([(key, _json(entry)), (key, _json(entry))])
    elif case == "duplicate-usage-field":
        text = _object(
            [
                (
                    key,
                    _object(
                        [
                            (
                                name,
                                '{"input_tokens":null,"input_tokens":null,"output_tokens":null}'
                                if name == "usage"
                                else _json(value),
                            )
                            for name, value in entry.items()
                        ]
                    ),
                )
            ]
        )
    else:
        if case == "recorded-answer":
            answer["provenance"] = RECORDED
        elif case == "mixed-answer-sources":
            entry["answers"]["second-synthetic-test-answer"] = recorded_answer
        elif case == "missing-provenance":
            del answer["provenance"]
        elif case == "missing-source":
            answer["provenance"].pop("source")
        elif case == "unknown-source":
            answer["provenance"]["source"] = SENTINEL
        elif case == "null-source":
            answer["provenance"]["source"] = None
        elif case == "synthetic-with-model":
            answer["provenance"]["model"] = SENTINEL
        elif case == "synthetic-with-date":
            answer["provenance"]["date"] = "2026-01-01"
        elif case == "unknown-provenance-field":
            answer["provenance"][SENTINEL] = True
        elif case == "unsupported-entry-provenance":
            entry["provenance"] = RECORDED
        elif case == "null-provenance":
            answer["provenance"] = None
        elif case == "list-provenance":
            answer["provenance"] = []
        elif case == "string-provenance":
            answer["provenance"] = SENTINEL
        elif case == "missing-answers":
            del entry["answers"]
        elif case == "empty-answers":
            entry["answers"] = {}
        elif case == "null-answers":
            entry["answers"] = None
        elif case == "list-answers":
            entry["answers"] = []
        elif case == "non-object-answer":
            entry["answers"][SENTINEL] = None
        elif case == "later-ambiguous-entry":
            later = copy.deepcopy(entry)
            next(iter(later["answers"].values()))["provenance"] = RECORDED
            return (_json({key: entry, "f" * 64: later}) + "\r\n").encode()
        else:
            raise AssertionError(f"unknown planted case: {case}")
        text = _json({key: entry})
    return (text + "\r\n").encode("utf-8")


CASES = (
    "duplicate-response",
    "duplicate-entry-model",
    "duplicate-answer-name",
    "duplicate-answer-provenance",
    "duplicate-provenance-source",
    "escaped-provenance-source",
    "duplicate-identical-synthetic",
    "duplicate-usage-field",
    "recorded-answer",
    "mixed-answer-sources",
    "missing-provenance",
    "missing-source",
    "unknown-source",
    "null-source",
    "synthetic-with-model",
    "synthetic-with-date",
    "unknown-provenance-field",
    "unsupported-entry-provenance",
    "null-provenance",
    "list-provenance",
    "string-provenance",
    "missing-answers",
    "empty-answers",
    "null-answers",
    "list-answers",
    "non-object-answer",
    "later-ambiguous-entry",
)
CORE_CASES = ("duplicate-response", "recorded-answer")


def _assert_refusal(result, path, planted):
    diagnostic = result.stdout + result.stderr
    preserved = path.read_bytes() == planted
    explicit = result.returncode != 0 and "refus" in diagnostic.lower() and "--force" in diagnostic
    assert preserved and explicit, (
        f"{path.name}: original_bytes_preserved={preserved}, explicit_refusal={explicit}, "
        f"builder_exit={result.returncode}"
    )
    assert str(path) in diagnostic
    assert "Traceback" not in diagnostic
    assert SENTINEL not in diagnostic, "response contents or parser details leaked to the CLI"


@pytest.fixture(scope="module", params=("template", "replay", "replay-images"))
def provenance_source(request, tmp_path_factory):
    return _SUPPORT._make_generated_source(
        request.param, tmp_path_factory.mktemp(f"provenance-{request.param}")
    )


@pytest.fixture
def provenance_copy(provenance_source, tmp_path):
    folder = tmp_path / provenance_source.name
    shutil.copytree(provenance_source, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder


@pytest.mark.parametrize("case", CASES)
def test_template_and_generated_variants_preserve_uncertain_provenance(provenance_copy, case):
    folder = provenance_copy
    expected = _SUPPORT._fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    planted = _payload(path.read_bytes(), case)
    path.write_bytes(planted)
    for name in ("inputs.jsonl", "labels.jsonl"):
        (path.parent / name).write_bytes(b"planted synthetic stale input\n")
    result = _SUPPORT._run(folder / "build_fixtures.py")
    _assert_refusal(result, path, planted)
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (path.parent / name).read_bytes() == expected[name]


@pytest.mark.parametrize("case", CASES)
def test_force_replaces_uncertain_provenance_deterministically(provenance_copy, case):
    """Separate from refusal tests so override controls still run on a vulnerable baseline."""
    folder = provenance_copy
    expected = _SUPPORT._fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    path.write_bytes(_payload(path.read_bytes(), case))
    result = _SUPPORT._run(folder / "build_fixtures.py", "--force")
    assert result.returncode == 0, result.stderr
    assert _SUPPORT._fixture_bytes(folder) == expected


@pytest.mark.parametrize("recorded", (False, True), ids=("valid-synthetic", "valid-recorded"))
def test_valid_provenance_controls(provenance_copy, recorded):
    folder = provenance_copy
    expected = _SUPPORT._fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    script = folder / "build_fixtures.py"
    if recorded:
        planted = _SUPPORT._recorded_bytes(path.read_bytes())
        path.write_bytes(planted)
        _assert_refusal(_SUPPORT._run(script), path, planted)
        result = _SUPPORT._run(script, "--force")
    else:
        result = _SUPPORT._run(script)
    assert result.returncode == 0, result.stderr
    assert _SUPPORT._fixture_bytes(folder) == expected


@pytest.mark.parametrize("variant", ("empty-store", "omitted-metadata", "omitted-usage"))
def test_valid_optional_fields_and_empty_store_can_regenerate(provenance_copy, variant):
    """Provenance's optional metadata and DecisionResult's default usage stay optional."""
    folder = provenance_copy
    expected = _SUPPORT._fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    data = json.loads(path.read_bytes())
    if variant == "empty-store":
        data = {}
    else:
        for entry in data.values():
            if variant == "omitted-usage":
                entry.pop("usage")
            else:
                for answer in entry["answers"].values():
                    answer["provenance"].pop("model")
                    answer["provenance"].pop("date")
    path.write_bytes((_json(data) + "\r\n").encode())
    result = _SUPPORT._run(folder / "build_fixtures.py")
    assert result.returncode == 0, result.stderr
    assert _SUPPORT._fixture_bytes(folder) == expected


@pytest.mark.parametrize("name", ("responses-atlas.json", "responses-north.json"))
@pytest.mark.parametrize("case", CORE_CASES)
@pytest.mark.parametrize("force", (False, True), ids=("refuse", "force"))
def test_recipe50_sidecar_provenance(tmp_path, name, case, force):
    source = next(
        path for path in _SUPPORT.PUBLISHED_REPLAY_BUILDERS if path.name.startswith("50-")
    )
    script = _SUPPORT._copy_builder(source, tmp_path / source.name)
    shutil.copytree(source / "fixtures", script.parent / "fixtures")
    expected = _SUPPORT._fixture_bytes(script.parent)
    path = script.parent / "fixtures" / name
    planted = _payload(path.read_bytes(), case)
    path.write_bytes(planted)
    result = _SUPPORT._run(script, *(["--force"] if force else []))
    if force:
        assert result.returncode == 0, result.stderr
        assert _SUPPORT._fixture_bytes(script.parent) == expected
    else:
        _assert_refusal(result, path, planted)


@pytest.mark.parametrize("case", CORE_CASES)
@pytest.mark.parametrize("force", (False, True), ids=("refuse", "force"))
def test_image_provenance_preflight_precedes_asset_writes(tmp_path, case, force):
    folder = _SUPPORT._make_generated_source("replay-images", tmp_path)
    script = folder / "build_fixtures.py"
    path = folder / "fixtures" / "responses.json"
    original = path.read_bytes()
    planted = _payload(original, case)
    path.write_bytes(planted)
    image = next((folder / "assets").glob("*.png"))
    original_image = image.read_bytes()
    image.write_bytes(b"planted synthetic changed image\n")
    tracked = [
        *sorted((folder / "fixtures").iterdir()),
        *sorted((folder / "assets").iterdir()),
        folder / "assets-manifest.json",
    ]
    before = {file: file.read_bytes() for file in tracked if file.is_file()}
    result = _SUPPORT._run(script, "--overwrite-assets", *(["--force"] if force else []))
    if force:
        assert result.returncode == 0, result.stderr
        assert path.read_bytes() == original
        assert image.read_bytes() == original_image
        for file, raw in before.items():
            if file not in (image, path):
                assert file.read_bytes() == raw
    else:
        _assert_refusal(result, path, planted)
        assert {file: file.read_bytes() for file in before} == before
