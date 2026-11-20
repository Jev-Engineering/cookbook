"""The template builder must preserve responses whose provenance it cannot establish."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "recipes" / "_template"


@pytest.fixture
def recipe(tmp_path):
    folder = tmp_path / "recipe"
    folder.mkdir()
    for name in ("build_fixtures.py", "helpers.py"):
        shutil.copyfile(TEMPLATE / name, folder / name)
    (folder / "fixtures").mkdir()
    return folder


def run_builder(recipe, *args):
    return subprocess.run(
        [sys.executable, str(recipe / "build_fixtures.py"), *args],
        cwd=recipe.parent,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "content",
    [
        b'{"answer": {"model": "recorded-example"},}\n',
        b'{"answer": {"model": "recorded-example", "choices":',
        b'<<<<<<< recorded\n{"answer": {"model": "recorded-example"}}\n=======\n{}\n>>>>>>> edit\n',
        b'{"answer": {"model": "recorded-example", "text": "\xff"}}\n',
        b"",
        b"[]\n",
        b"null\n",
        b'"not an object"\n',
        b'{"answer": null}\n',
        b'{"answer": []}\n',
        b'{"answer": {}}\n',
    ],
    ids=[
        "trailing-comma",
        "truncated",
        "merge-conflict",
        "invalid-utf8",
        "empty",
        "list",
        "null",
        "string",
        "null-entry",
        "list-entry",
        "missing-model",
    ],
)
def test_unreadable_responses_require_force_and_keep_original_bytes(recipe, content):
    responses = recipe / "fixtures" / "responses.json"
    responses.write_bytes(content)

    refused = run_builder(recipe)

    assert refused.returncode != 0
    assert "refusing to overwrite" in refused.stderr
    assert "--force" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert responses.read_bytes() == content
    assert (responses.parent / "inputs.jsonl").is_file()
    assert (responses.parent / "labels.jsonl").is_file()

    forced = run_builder(recipe, "--force")

    assert forced.returncode == 0, forced.stderr
    data = json.loads(responses.read_text(encoding="utf-8"))
    assert data
    assert all(entry["model"] == "synthetic" for entry in data.values())
    regenerated = responses.read_bytes()
    repeated = run_builder(recipe)
    assert repeated.returncode == 0, repeated.stderr
    assert responses.read_bytes() == regenerated


def test_recorded_responses_still_require_force(recipe):
    first = run_builder(recipe)
    assert first.returncode == 0, first.stderr
    responses = recipe / "fixtures" / "responses.json"
    data = json.loads(responses.read_text(encoding="utf-8"))
    next(iter(data.values()))["model"] = "recorded-example"
    original = (json.dumps(data, indent=2) + "\n").encode()
    responses.write_bytes(original)

    refused = run_builder(recipe)

    assert refused.returncode != 0
    assert "recorded" in refused.stderr and "--force" in refused.stderr
    assert responses.read_bytes() == original

    forced = run_builder(recipe, "--force")
    assert forced.returncode == 0, forced.stderr
    assert all(
        entry["model"] == "synthetic"
        for entry in json.loads(responses.read_text(encoding="utf-8")).values()
    )


@pytest.mark.parametrize("force", [False, True])
def test_read_errors_require_force_without_claiming_the_file_is_synthetic(
    recipe, monkeypatch, force
):
    script = recipe / "build_fixtures.py"
    spec = importlib.util.spec_from_file_location("template_fixture_overwrite", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    responses = recipe / "fixtures" / "responses.json"
    original = b'{"answer": {"model": "recorded-example"}}\n'
    responses.write_bytes(original)
    read_text = Path.read_text

    def unreadable_response(path, *args, **kwargs):
        if path == responses:
            raise OSError("simulated read failure")
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable_response)
    monkeypatch.setattr(sys, "argv", [str(script), *(["--force"] if force else [])])

    if force:
        module.main()
        data = json.loads(responses.read_bytes())
        assert data
        assert all(entry["model"] == "synthetic" for entry in data.values())
    else:
        with pytest.raises(SystemExit, match="refusing to overwrite.*--force"):
            module.main()
        assert responses.read_bytes() == original
