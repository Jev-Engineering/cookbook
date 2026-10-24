"""An unreadable capture is protected data, never permission to overwrite it."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

RECIPE = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    "contents",
    [
        b'{"request":{"model":"jev-1.14.0","answers":',
        b"[]",
        b"null",
        b"\xff\xfe",
        b'{"broken":{"model":"synthetic"}}',
    ],
)
def test_rebuild_refuses_unverifiable_capture_without_force(tmp_path, contents):
    for name in ("helpers.py", "build_fixtures.py"):
        (tmp_path / name).write_bytes((RECIPE / name).read_bytes())
    folder = tmp_path / "fixtures"
    folder.mkdir()
    responses = folder / "responses.json"
    responses.write_bytes(contents)
    script = tmp_path / "build_fixtures.py"
    refused = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    assert refused.returncode != 0 and "--force" in refused.stderr
    assert responses.read_bytes() == contents
    assert len((folder / "inputs.jsonl").read_text().splitlines()) == 26
    forced = subprocess.run(
        [sys.executable, str(script), "--force"], capture_output=True, text=True
    )
    assert forced.returncode == 0, forced.stderr
    rebuilt = json.loads(responses.read_text())
    assert len(rebuilt) == 26
    assert all(value["model"] == "synthetic" for value in rebuilt.values())
