"""Every hygiene check must be able to fail, and must stay quiet on legitimate text.

Key-like values are assembled at run time so this file itself contains nothing a scanner
would flag.
"""

from __future__ import annotations

import importlib.util
import json
import random
import string
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "check_hygiene.py"

_spec = importlib.util.spec_from_file_location("check_hygiene", SCRIPT)
hygiene = importlib.util.module_from_spec(_spec)
sys.modules["check_hygiene"] = hygiene
_spec.loader.exec_module(hygiene)


def _random_token(n: int = 40, seed: int = 7) -> str:
    rng = random.Random(seed)
    alphabet = string.ascii_letters + string.digits
    token = "".join(rng.choice(alphabet) for _ in range(n))
    return "a1" + token  # guarantees letters and digits


def notebook(*, source="x = 1", outputs=None, metadata=None, markdown=None) -> dict:
    cells = [
        {
            "cell_type": "code",
            "execution_count": 1,
            "id": "c1",
            "metadata": {},
            "source": source.splitlines(keepends=True),
            "outputs": outputs or [],
        }
    ]
    if markdown is not None:
        cells.append({"cell_type": "markdown", "id": "m1", "metadata": {}, "source": markdown})
    return {
        "cells": cells,
        "metadata": metadata or {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def stream(text: str) -> dict:
    return {"output_type": "stream", "name": "stdout", "text": text.splitlines(keepends=True)}


def result(mimes: dict) -> dict:
    return {"output_type": "execute_result", "execution_count": 1, "metadata": {}, "data": mimes}


def scan(tmp_path: Path, nb: dict):
    path = tmp_path / "notebook.ipynb"
    path.write_text(json.dumps(nb), encoding="utf-8")
    return hygiene.scan_file(path)


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


KEY = _random_token()
# The shapes below are built from pieces so no literal in this file looks like a credential.
SK_KEY = "sk" + "-" + KEY
GH_TOKEN = "gh" + "p_" + KEY[:36]
AWS_ID = "AK" + "IA" + "ABCDEFGH12345678"
JWT = "ey" + "Jhbgciokfwerty" + ".ey" + "Jzdwiokfwerty" + ".abcdefghij1234"
WIN_USER = "C:" + "\\" + "Users" + "\\" + "alice" + "\\" + "proj" + "\\" + "x.py"
WIN_DRIVE = "D:" + "\\" + "work" + "\\" + "data.csv"


# --- clean inputs ---------------------------------------------------------------------


def test_clean_notebook_passes(tmp_path):
    nb = notebook(
        source="print('hello')",
        outputs=[stream("hello\n"), result({"text/plain": "3", "text/html": "<b>3</b>"})],
    )
    assert scan(tmp_path, nb) == []


@pytest.mark.parametrize(
    "text",
    [
        "Set TYPESAFE_API_KEY in your environment and JEV_COOKBOOK_LIVE=1 to opt in.",
        "Authorization: Bearer <API_KEY>",
        'headers = {"Authorization": f"Bearer {key}"}',
        "api_key = os.environ['TYPESAFE_API_KEY']",
        "TYPESAFE_API_KEY=your-key-here",
        "client = Client(api_key=api_key)",
        "max_tokens = 1024",
        "commit 8cf0c2f9d1a2b3c4d5e6f708192a3b4c5d6e7f80",
        "src/jev_cookbook/backends/replay_backend_for_fixtures/module_name.py",
    ],
)
def test_legitimate_text_is_not_flagged(text, tmp_path):
    assert hygiene.scan_text(text) == []
    assert scan(tmp_path, notebook(outputs=[stream(text)])) == []


def test_image_payloads_are_not_scanned(tmp_path):
    blob = _random_token(400, seed=3)
    nb = notebook(outputs=[result({"image/png": blob, "text/plain": "<Figure>"})])
    assert scan(tmp_path, nb) == []
    html = f'<img src="data:image/png;base64,{blob}">'
    assert scan(tmp_path, notebook(outputs=[result({"text/html": html})])) == []


# --- each secret rule can fail ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (f"key is {SK_KEY}", "sk-prefixed-key"),
        (f"token {GH_TOKEN}", "github-token"),
        (f"id {AWS_ID}", "aws-access-key-id"),
        (f"jwt {JWT}", "jwt"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "private-key-block"),
        (f"Authorization: Bearer {KEY}", "authorization-header-value"),
        (f"curl -H 'Authorization: {KEY}'", "authorization-header-value"),
        (f"sent Bearer {KEY}", "bearer-token"),
        (f"api_key={KEY}", "secret-assignment"),
        (f'client = Client(api_key="{KEY}")', "secret-assignment"),
        (f"TYPESAFE_API_KEY={KEY}", "secret-assignment"),
        (f"os.environ['TYPESAFE_API_KEY'] = '{KEY}'", "secret-assignment"),
        (f'{{"token": "{KEY}"}}', "secret-assignment"),
        (f"opaque {KEY}{KEY[:10]}", "high-entropy-token"),
    ],
)
def test_secret_rules_fail_in_text_and_every_notebook_place(text, rule, tmp_path):
    assert rule in {r for _, r, _ in hygiene.scan_text(text)}
    error = {"output_type": "error", "ename": "ValueError", "evalue": text, "traceback": [text]}
    display = {"output_type": "display_data", "metadata": {}, "data": {"text/plain": text}}
    places = {
        "stream": notebook(outputs=[stream(text)]),
        "text/plain": notebook(outputs=[result({"text/plain": text})]),
        "text/html": notebook(outputs=[result({"text/html": f"<pre>{text}</pre>"})]),
        "display_data": notebook(outputs=[display]),
        "error": notebook(outputs=[error]),
        "source": notebook(source=text),
        "markdown": notebook(markdown=text),
        "notebook metadata": notebook(metadata={"note": text}),
    }
    for place, nb in places.items():
        assert rule in rules(scan(tmp_path, nb)), place


def test_text_split_across_list_lines_is_joined(tmp_path):
    nb = notebook(outputs=[stream(f"Authorization: Bearer {KEY}\nnext line\n")])
    assert "authorization-header-value" in rules(scan(tmp_path, nb))


def test_finding_does_not_print_the_secret(tmp_path):
    findings = scan(tmp_path, notebook(outputs=[stream(f"api_key={KEY}")]))
    assert findings
    assert all(KEY not in str(f) for f in findings)


def test_env_file_is_flagged_but_example_is_not(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.example").write_text("TYPESAFE_API_KEY=\n")
    assert rules(hygiene.scan_file(tmp_path / ".env")) == {"env-file"}
    assert hygiene.scan_file(tmp_path / ".env.example") == []


def test_env_contents_in_a_file_are_flagged(tmp_path):
    path = tmp_path / "settings.txt"
    path.write_text(f"TYPESAFE_API_KEY={KEY}\n")
    assert "secret-assignment" in rules(hygiene.scan_file(path))


# --- local paths and environment dumps -------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (f"File {WIN_USER}", "windows-user-path"),
        ("File C:/Users/" + "alice/proj/x.py", "windows-user-path"),
        (WIN_DRIVE, "windows-absolute-path"),
        ("/home/" + "alice/proj/x.py", "linux-home-path"),
        ("/home/" + "runner/work/cookbook/x.py", "linux-home-path"),
        ("/Users/" + "alice/proj/x.py", "macos-home-path"),
        ("/mnt/" + "c/stuff", "wsl-windows-path"),
        ("/ro" + "ot/.cache/x", "root-home-path"),
    ],
)
def test_local_path_rules_fail_in_outputs(text, rule, tmp_path):
    error = {"output_type": "error", "ename": "E", "evalue": "x", "traceback": [text]}
    for nb in (
        notebook(outputs=[stream(text)]),
        notebook(outputs=[result({"text/plain": text})]),
        notebook(outputs=[error]),
        notebook(metadata={"papermill": {"input_path": text}}),
    ):
        assert rule in rules(scan(tmp_path, nb))


def test_local_paths_in_source_and_docs_are_allowed(tmp_path):
    text = "see /home/" + "alice/x"
    assert scan(tmp_path, notebook(source=f"# {text}")) == []
    assert hygiene.scan_text(text) == []


def test_username_placeholder_paths_are_allowed(tmp_path):
    nb = notebook(outputs=[stream("/home/<user>/x and /Users/<name>/y")])
    assert scan(tmp_path, nb) == []


def test_environ_repr_dump_fails(tmp_path):
    nb = notebook(outputs=[result({"text/plain": "environ({'A': 'b'})"})])
    assert "environment-dump" in rules(scan(tmp_path, nb))


def test_dict_of_well_known_variables_fails(tmp_path):
    text = "{'HOME': 'x', 'PATH': 'y', 'SHELL': 'z'}"
    assert "environment-dump" in rules(scan(tmp_path, notebook(outputs=[stream(text)])))


def test_env_style_listing_fails(tmp_path):
    text = "\n".join(f"VAR_{i}=value{i}" for i in range(8)) + "\n"
    assert "environment-dump" in rules(scan(tmp_path, notebook(outputs=[stream(text)])))


def test_one_variable_mentioned_is_fine(tmp_path):
    nb = notebook(outputs=[stream("JEV_COOKBOOK_LIVE=0\nPATH: ok\n")])
    assert scan(tmp_path, nb) == []


# --- file handling and CLI -------------------------------------------------------------


def test_invalid_notebook_json_is_reported(tmp_path):
    path = tmp_path / "bad.ipynb"
    path.write_text("{not json")
    assert rules(hygiene.scan_file(path)) == {"invalid-notebook-json"}


def test_binary_files_are_skipped(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"\0" + KEY.encode())
    assert hygiene.scan_file(path) == []


def _run(*args: str):
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def test_cli_exits_nonzero_for_a_planted_key(tmp_path):
    path = tmp_path / "planted.ipynb"
    path.write_text(json.dumps(notebook(outputs=[stream(f"Authorization: Bearer {KEY}")])))
    proc = _run(str(path))
    assert proc.returncode == 1
    assert "authorization-header-value" in proc.stdout
    assert KEY not in proc.stdout + proc.stderr
    assert "Hygiene check failed" in proc.stderr


def test_cli_exits_zero_for_a_clean_notebook(tmp_path):
    path = tmp_path / "clean.ipynb"
    path.write_text(json.dumps(notebook(outputs=[stream("ok")])))
    proc = _run(str(path))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_repository_itself_is_clean():
    proc = _run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
