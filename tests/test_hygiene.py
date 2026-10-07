"""Every hygiene check must be able to fail, and must stay quiet on legitimate text.

Key-like values are assembled at run time so this file itself contains nothing a scanner
would flag.
"""

from __future__ import annotations

import base64
import gzip
import importlib.util
import io
import json
import random
import string
import subprocess
import sys
import zipfile
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


# --- fix round 1: files that cannot be skipped silently --------------------------------


def test_unreadable_binary_is_reported_but_known_image_suffixes_are_skipped(tmp_path):
    odd = tmp_path / "blob.bin"
    odd.write_bytes(b"\0\1" + KEY.encode())
    assert rules(hygiene.scan_file(odd)) == {"unscanned-file"}
    png = tmp_path / "pic.png"
    png.write_bytes(b"\x89PNG\0\0" + KEY.encode())
    assert hygiene.scan_file(png) == []


def test_large_notebook_is_still_scanned(tmp_path):
    big = "A" * 3_000_000  # an image payload far over the old 2 MB limit
    nb = notebook(
        outputs=[
            result({"image/png": big, "text/plain": "<Figure>"}),
            stream(f"Authorization: Bearer {KEY}"),
        ]
    )
    path = tmp_path / "big.ipynb"
    path.write_text(json.dumps(nb))
    assert path.stat().st_size > 2_000_000
    assert "bearer-token" in rules(hygiene.scan_file(path))


@pytest.mark.parametrize("codec", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_file_is_decoded_and_scanned(codec, tmp_path):
    # utf-16 writes a BOM; the -le and -be forms have none and rely on the NUL pattern.
    path = tmp_path / "out.txt"
    path.write_bytes(f"TYPESAFE_API_KEY={KEY}\r\n".encode(codec))
    assert "secret-assignment" in rules(hygiene.scan_file(path))


def test_utf8_bom_file_is_scanned(tmp_path):
    path = tmp_path / "out.txt"
    path.write_bytes(b"\xef\xbb\xbf" + f"api_key={KEY}".encode())
    assert "secret-assignment" in rules(hygiene.scan_file(path))


def test_nbformat3_notebook_is_scanned(tmp_path):
    stream_output = {
        "output_type": "stream",
        "stream": "stdout",
        "text": [f"Authorization: Bearer {KEY}\n"],
    }
    image_output = {"output_type": "pyout", "png": _random_token(300), "text": ["x"]}
    cell = {
        "cell_type": "code",
        "language": "python",
        "input": ["print(1)"],
        "metadata": {},
        "prompt_number": 1,
        "outputs": [stream_output, image_output],
    }
    nb = {"nbformat": 3, "nbformat_minor": 0, "metadata": {}, "worksheets": [{"cells": [cell]}]}
    assert "bearer-token" in rules(scan(tmp_path, nb))


def test_unrecognized_notebook_layout_is_reported(tmp_path):
    found = rules(scan(tmp_path, {"nbformat": 9, "metadata": {}}))
    assert found == {"unrecognized-notebook-layout"}


def test_oversized_non_notebook_file_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene, "MAX_FILE_BYTES", 100)
    path = tmp_path / "huge.txt"
    path.write_text("x" * 200)
    assert rules(hygiene.scan_file(path)) == {"unscanned-file"}


# --- fix round 1: ANSI colour codes ----------------------------------------------------

ESC = "\x1b"


@pytest.mark.parametrize(
    ("path_text", "rule"),
    [
        (WIN_USER, "windows-user-path"),
        ("/home/" + "alice/.venv/lib/x.py", "linux-home-path"),
        ("/Users/" + "alice/proj/x.py", "macos-home-path"),
        ("/mnt/" + "c/Users/alice/x.py", "wsl-windows-path"),
    ],
)
def test_ansi_coloured_traceback_paths_are_caught(path_text, rule, tmp_path):
    # The shape of a real IPython traceback: every frame path is wrapped in colour codes.
    frame = f"File {ESC}[0;32m{path_text}{ESC}[0m:{ESC}[0;34m12{ESC}[0m, in {ESC}[0;36mf{ESC}[0m"
    error = {
        "output_type": "error",
        "ename": "ValueError",
        "evalue": "x",
        "traceback": [f"{ESC}[0;31m{'-' * 40}{ESC}[0m", frame],
    }
    assert rule in rules(scan(tmp_path, notebook(outputs=[error])))
    assert rule in rules(scan(tmp_path, notebook(outputs=[stream(f"{ESC}[1;32m{path_text}")])))


def test_ansi_before_a_vendor_prefix_is_caught(tmp_path):
    nb = notebook(outputs=[stream(f"{ESC}[0m{GH_TOKEN}")])
    assert "github-token" in rules(scan(tmp_path, nb))


def test_ansi_only_traceback_is_clean(tmp_path):
    error = {
        "output_type": "error",
        "ename": "ValueError",
        "evalue": "bad",
        "traceback": [f"{ESC}[0;31mValueError{ESC}[0m: bad"],
    }
    assert scan(tmp_path, notebook(outputs=[error])) == []


# --- fix round 1: URL and hash-path false positives ------------------------------------

SHA40 = "8cf0c2f9d1a2b3c4d5e6f708192a3b4c5d6e7f80"
SHA64 = "0123456789abcdef" * 4


@pytest.mark.parametrize(
    "text",
    [
        f"https://github.com/Jev-Engineering/cookbook/blob/{SHA40}/README.md",
        f"https://github.com/Jev-Engineering/cookbook/commit/{SHA40}",
        f"fixtures/replay/{SHA64}.json",
        f"FixtureMiss: no response recorded at recipes/03-triage/fixtures/replay/{SHA64}.json",
        f'{{"{SHA64}": {{"answer": "yes"}}}}',
        f"sha256:{SHA64}",
    ],
)
def test_urls_and_hash_paths_are_not_flagged(text, tmp_path):
    assert hygiene.scan_text(text) == []
    assert scan(tmp_path, notebook(outputs=[stream(text)])) == []


def test_hex_tokens_are_never_entropy_findings_and_that_is_documented():
    # Hex cannot reach the entropy threshold, so a bare hex key is only caught by the
    # header, bearer and assignment rules. Pin that behaviour so nobody assumes otherwise.
    assert hygiene.scan_text(f"value {SHA64}") == []
    assert "secret-assignment" in {r for _, r, _ in hygiene.scan_text(f"api_key={SHA64}")}
    assert "bearer-token" in {r for _, r, _ in hygiene.scan_text(f"Bearer {SHA64}")}


def test_key_is_still_caught_inside_a_url():
    text = f"https://example.org/hook/{KEY}{KEY[:10]}/send"
    assert "high-entropy-token" in {r for _, r, _ in hygiene.scan_text(text)}


# --- fix round 1: home paths without a trailing slash, WSL UNC -------------------------

BS = "\\"
WSL_LOCALHOST = (
    BS * 2 + "wsl.localhost" + BS + "Ubuntu" + BS + "home" + BS + "tim" + BS + "cookbook"
)
WSL_DOLLAR = BS * 2 + "wsl$" + BS + "Ubuntu" + BS + "home" + BS + "tim"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("PosixPath('/home/" + "tim')", "linux-home-path"),
        ("cwd: /home/" + "tim", "linux-home-path"),
        ("/home/" + "tim", "linux-home-path"),
        ("'/Users/" + "tim'", "macos-home-path"),
        ("PosixPath('/Users/" + "tim')", "macos-home-path"),
        (WSL_LOCALHOST, "wsl-unc-path"),
        (WSL_DOLLAR, "wsl-unc-path"),
    ],
)
def test_home_path_forms_without_trailing_slash_are_caught(text, rule, tmp_path):
    assert rule in rules(scan(tmp_path, notebook(outputs=[stream(text)])))
    assert rule in rules(scan(tmp_path, notebook(outputs=[result({"text/plain": text})])))


def test_home_placeholders_and_prose_are_still_allowed(tmp_path):
    text = "PosixPath('/home/<user>') and the /home directory and /Users/ folder"
    assert scan(tmp_path, notebook(outputs=[stream(text)])) == []


# --- fix round 2: archives, slash-containing keys, large-notebook limit ----------------


def _zip_bytes(members: dict, compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for member, data in members.items():
            zf.writestr(member, data)
    return buf.getvalue()


def test_gz_archive_contents_are_scanned(tmp_path):
    path = tmp_path / "log.txt.gz"
    path.write_bytes(gzip.compress(f"TYPESAFE_API_KEY={KEY}\n".encode()))
    assert "secret-assignment" in rules(hygiene.scan_file(path))


@pytest.mark.parametrize("compression", [zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED])
def test_zip_containing_a_notebook_is_scanned(compression, tmp_path):
    nb = notebook(outputs=[stream(f"Authorization: Bearer {KEY}")])
    path = tmp_path / "bundle.zip"
    path.write_bytes(_zip_bytes({"a/notebook.ipynb": json.dumps(nb)}, compression))
    found = hygiene.scan_file(path)
    assert "bearer-token" in rules(found)
    assert "bundle.zip!a/notebook.ipynb" in found[0].path


def test_npz_and_npy_are_scanned(tmp_path):
    npz = tmp_path / "arrays.npz"
    npz.write_bytes(_zip_bytes({"x.npy": b"\x93NUMPY\0\0" + f"api_key={KEY}".encode()}))
    npy = tmp_path / "x.npy"
    npy.write_bytes(b"\x93NUMPY\0\0" + f"api_key={KEY}".encode())
    assert "secret-assignment" in rules(hygiene.scan_file(npz))
    assert "secret-assignment" in rules(hygiene.scan_file(npy))


def test_nested_zip_and_broken_archives(tmp_path):
    inner = _zip_bytes({"k.txt": f"api_key={KEY}"})
    path = tmp_path / "outer.zip"
    path.write_bytes(_zip_bytes({"inner.zip": inner}))
    assert "secret-assignment" in rules(hygiene.scan_file(path))
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    assert rules(hygiene.scan_file(bad)) == {"unscanned-file"}


def test_clean_archives_pass(tmp_path):
    path = tmp_path / "ok.zip"
    path.write_bytes(_zip_bytes({"a.txt": "hello"}))
    assert hygiene.scan_file(path) == []


def _base64_keys(count: int, seed: int = 11) -> list[str]:
    rng = random.Random(seed)
    return [base64.b64encode(rng.randbytes(30)).decode() for _ in range(count)]


def test_base64_keys_with_and_without_slash_are_all_caught(tmp_path):
    keys = _base64_keys(300)
    assert sum("/" in k for k in keys) > 100  # the set really exercises "/"
    for key in keys:
        assert "high-entropy-token" in {r for _, r, _ in hygiene.scan_text(f"value {key}")}, key
    nb = notebook(outputs=[stream(f"value {k}") for k in keys])
    found = scan(tmp_path, nb)
    assert len(found) >= len(keys)


def test_url_and_path_exemptions_survive_whole_run_scoring():
    for text in (
        f"https://github.com/Jev-Engineering/cookbook/commit/{SHA40}",
        f"fixtures/replay/{SHA64}.json",
        f"/home/runner/work/{SHA64}",
    ):
        assert not [h for h in hygiene.scan_text(text) if h[1] == "high-entropy-token"], text


def test_large_notebook_exemption_is_what_lets_it_through(tmp_path, monkeypatch):
    monkeypatch.setattr(hygiene, "MAX_FILE_BYTES", 1000)
    nb = notebook(outputs=[result({"image/png": "A" * 5000}), stream(f"Bearer {KEY}")])
    path = tmp_path / "big.ipynb"
    path.write_text(json.dumps(nb))
    assert path.stat().st_size > 1000
    assert "bearer-token" in rules(hygiene.scan_file(path))


# --- audit #97: paths, usernames, malformed cells, directory arguments ------------------

DRIVE_FWD = "D:/" + "work/project/x.py"
PYTEST_TMP = "/tmp/" + "pytest-of-alice/pytest-0/test_x0/out.txt"


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (DRIVE_FWD, "windows-drive-path"),
        ("saved to d:/data/run1", "windows-drive-path"),
        (PYTEST_TMP, "username-temp-path"),
        ("C:\\\\Temp\\\\" + "pytest-of-alice\\\\x", "username-temp-path"),
        ("/opt/" + "conda/lib/python3.12/site-packages/x.py", "local-install-path"),
        ("/opt/" + "miniconda3/envs/a/bin/python", "local-install-path"),
        ("/opt/" + "homebrew/bin/python3", "local-install-path"),
        ("/private/" + "var/folders/zz/abc/T/tmpq1", "local-temp-path"),
        ("/var/" + "folders/zz/abc/T/tmpq1", "local-temp-path"),
        ("/Volumes/" + "Data/run", "local-install-path"),
    ],
)
def test_missed_local_paths_fail_in_outputs_and_metadata(text, rule, tmp_path):
    error = {"output_type": "error", "ename": "E", "evalue": "x", "traceback": [text]}
    for nb in (
        notebook(outputs=[stream(f"saved: {text}\n")]),
        notebook(outputs=[result({"text/plain": text})]),
        notebook(outputs=[error]),
        notebook(metadata={"papermill": {"input_path": text}}),
    ):
        assert rule in rules(scan(tmp_path, nb)), (text, nb)


def test_missed_local_paths_stay_allowed_where_the_policy_allows_them(tmp_path):
    text = f"{DRIVE_FWD} {PYTEST_TMP} /opt/conda/bin"
    assert scan(tmp_path, notebook(source=f"# {text}", markdown=text)) == []
    assert hygiene.scan_text(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "https://example.com/a/b and http://localhost:8000/x and ftp://h/p",
        "a://b/c and mailto:/x is not a path",
        "/tmp/pytest-of-<user>/pytest-0 and pytest-of-{name}",
        "/opt/condatools and /opt/conda-forge-notes and /optional/conda",
        "/var/foldersmith and var/folders/x",
        "Volumes/ and the /Volumes directory",
        "ratio 3:/4 and 10:/20",
    ],
)
def test_ordinary_text_near_the_new_path_rules_is_not_flagged(text, tmp_path):
    assert scan(tmp_path, notebook(outputs=[stream(text)])) == []


@pytest.fixture
def account(monkeypatch):
    """Pretend the check runs under the given local account names."""

    def use(*names: str) -> None:
        monkeypatch.setattr(hygiene, "_local_usernames", lambda: frozenset(names))
        hygiene._username_pattern.cache_clear()

    yield use
    monkeypatch.undo()
    hygiene._username_pattern.cache_clear()


def test_local_username_in_outputs_and_metadata_fails_without_echoing_it(account, tmp_path):
    name = "zanzibar"
    account(name)
    for nb in (
        notebook(outputs=[stream(f"hello from {name.upper()}!\n")]),
        notebook(outputs=[result({"text/plain": f"owner={name}"})]),
        notebook(metadata={"author": name}),
    ):
        found = scan(tmp_path, nb)
        assert rules(found) == {"local-username"}, nb
        assert all(name not in str(f).lower() for f in found)
    # Source, markdown and plain text files are not in scope: the name may be authorship.
    assert scan(tmp_path, notebook(source=f"# {name}", markdown=f"by {name}")) == []
    assert hygiene.scan_text(f"by {name}") == []


def test_local_username_is_not_a_blanket_word_rule(account, tmp_path):
    account("zanzibar")
    nb = notebook(outputs=[stream("zanzibarian spices; ordinary words stay readable\n")])
    assert scan(tmp_path, nb) == []  # whole word only: a longer word is not the account name
    assert scan(tmp_path, notebook(outputs=[stream("results: accuracy 0.93\n")])) == []


def test_generic_and_short_account_names_are_never_checked_by_name(monkeypatch):
    for var in ("USER", "USERNAME", "LOGNAME"):
        monkeypatch.delenv(var, raising=False)

    def getuser():
        raise OSError("no account")

    monkeypatch.setattr(hygiene.getpass, "getuser", lambda: "runner")
    assert hygiene._local_usernames() == frozenset()
    monkeypatch.setenv("USER", "tim")
    monkeypatch.setenv("LOGNAME", "Admin")
    assert hygiene._local_usernames() == frozenset()
    monkeypatch.setenv("USER", "Zanzibar")
    assert hygiene._local_usernames() == {"zanzibar"}
    monkeypatch.setattr(hygiene.getpass, "getuser", getuser)
    assert hygiene._local_usernames() == {"zanzibar"}


def test_no_account_name_means_the_name_check_is_off(account, tmp_path):
    account()
    assert scan(tmp_path, notebook(outputs=[stream("zanzibar\n")])) == []


BEARER_CELL = f"Authorization: Bearer {KEY}"


@pytest.mark.parametrize(
    "cells",
    [
        [BEARER_CELL],
        [None],
        [42],
        [["x = 1", BEARER_CELL]],
        [{"cell_type": "code", "source": "ok"}, BEARER_CELL],
    ],
)
def test_non_object_cells_are_findings_and_still_scanned(cells, tmp_path):
    nb = {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}
    found = scan(tmp_path, nb)
    assert "malformed-notebook-node" in rules(found), found
    assert all(f.location.startswith("cell ") for f in found)
    text = "\n".join(str(f) for f in found)
    assert KEY not in text
    assert len(text) < 800  # bounded: type names and masked snippets only
    if BEARER_CELL in json.dumps(cells):
        assert {"authorization-header-value", "bearer-token"} & rules(found)


def test_malformed_cell_finding_names_the_cell_index(tmp_path):
    nb = {"cells": [{"cell_type": "code", "source": "x"}, BEARER_CELL], "nbformat": 4}
    found = scan(tmp_path, nb)
    assert any(f.location == "cell 1" and f.rule == "malformed-notebook-node" for f in found)
    assert any(f.location.startswith("cell 1") and f.rule.endswith("value") for f in found)


@pytest.mark.parametrize(
    "nb",
    [
        {"nbformat": 4, "cells": BEARER_CELL},
        {"nbformat": 4, "cells": {"a": BEARER_CELL}},
        {"nbformat": 3, "worksheets": BEARER_CELL},
        {"nbformat": 3, "worksheets": [BEARER_CELL]},
        {"nbformat": 3, "worksheets": [{"cells": BEARER_CELL}]},
        {"nbformat": 4, "cells": [{"cell_type": "code", "source": {"k": BEARER_CELL}}]},
        {"nbformat": 4, "cells": [{"cell_type": "code", "source": 7}]},
    ],
)
def test_other_malformed_containers_are_findings_and_still_scanned(nb, tmp_path):
    found = scan(tmp_path, nb)
    assert rules(found) & {"malformed-notebook-node", "unrecognized-notebook-layout"}
    assert KEY not in "\n".join(str(f) for f in found)
    if BEARER_CELL in json.dumps(nb):
        assert {"authorization-header-value", "bearer-token"} & rules(found)


def test_well_formed_notebooks_gain_no_malformed_findings(tmp_path):
    assert scan(tmp_path, notebook(outputs=[stream("ok")], markdown="text")) == []


def test_cli_fails_on_a_bare_string_cell_with_redacted_output(tmp_path):
    path = tmp_path / "n.ipynb"
    path.write_text(json.dumps({"cells": [BEARER_CELL], "nbformat": 4, "metadata": {}}))
    proc = _run(str(path))
    assert proc.returncode == 1
    assert "malformed-notebook-node" in proc.stdout and "cell 0" in proc.stdout
    assert KEY not in proc.stdout + proc.stderr


def test_directory_argument_is_rejected_not_reported_as_scanned(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i in range(3):
        nb = notebook(outputs=[stream(BEARER_CELL)])
        (corpus / f"bad{i}.ipynb").write_text(json.dumps(nb))
    proc = _run(str(corpus))
    assert proc.returncode == 2
    assert "a directory" in proc.stderr
    assert "passed" not in proc.stdout + proc.stderr
    # The same files named one by one fail as findings.
    assert _run(*map(str, sorted(corpus.iterdir()))).returncode == 1


def test_directory_among_valid_files_still_fails_and_a_missing_file_is_not_skipped(tmp_path):
    good = tmp_path / "ok.ipynb"
    good.write_text(json.dumps(notebook(outputs=[stream("ok")])))
    proc = _run(str(good), str(tmp_path / "missing.ipynb"), str(tmp_path))
    assert proc.returncode == 2
    assert "missing or not a regular file" in proc.stderr and "a directory" in proc.stderr
    assert "passed" not in proc.stdout


def test_valid_file_arguments_still_pass(tmp_path):
    a = tmp_path / "a.ipynb"
    a.write_text(json.dumps(notebook(outputs=[stream("ok")])))
    b = tmp_path / "b.txt"
    b.write_text("hello")
    proc = _run(str(a), str(b))
    assert proc.returncode == 0 and "2 file(s) scanned" in proc.stdout


def test_run_library_call_cannot_false_pass_on_a_directory(tmp_path):
    findings = hygiene.run([tmp_path], ROOT, named=True)
    assert [f.rule for f in findings] == ["not-a-file"]
    assert hygiene.run([tmp_path], ROOT) == []  # git ls-files mode: submodules are skipped
