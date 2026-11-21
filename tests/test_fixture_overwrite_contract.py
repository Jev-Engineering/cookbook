"""Issue #489 acceptance tests: an uncertain response store needs explicit --force.

Only synthetic temporary copies are executed. The generated text recipe's author TODOs
are completed with a tiny Noul example; its CLI and overwrite guard remain untouched.
No notebook, backend request, credential or network service is used.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BASELINE_REPLAY_RANKS = set(range(1, 52)) - {36}
TRAILING_COMMA = b'{"saved-answer": {"model": "recorded-model"},}\r\n'
BAD_STORES = [
    pytest.param(TRAILING_COMMA, id="trailing-comma"),
    pytest.param(
        b'<<<<<<< local\n{"saved-answer": {}}\n=======\n{}\n>>>>>>> other\n', id="merge-conflict"
    ),
    pytest.param(b'[{"model": "recorded-model"}]\n', id="array"),
    pytest.param(b"null\r\n", id="null"),
    pytest.param(b'{"saved-answer": "\xff\xfe"}\r\n', id="invalid-utf8"),
]


def _published_replay_builders():
    """Pin baseline coverage, but include future published replay recipes as they arrive.

    Discovery depends on publication and the response declaration, never on whether a
    builder happens to exist. Removing a builder must fail rather than remove a case.
    Recipe36 declares scripted backends and legitimately has no response store.
    """
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    by_rank = {entry["rank"]: entry for entry in catalog["recipes"]}
    assert BASELINE_REPLAY_RANKS <= by_rank.keys(), "baseline replay recipe missing from catalog"
    found = []
    for rank, entry in sorted(by_rank.items()):
        folder = REPO / "recipes" / entry["slug"]
        published = (folder / "notebook.ipynb").is_file()
        if rank in BASELINE_REPLAY_RANKS:
            assert published, f"baseline replay recipe no longer published: {folder}"
        if not published:
            continue
        budget_file = folder / "request_budget.json"
        budget = json.loads(budget_file.read_text("utf-8")) if budget_file.is_file() else {}
        declares_responses = any(
            backend.get("fixtures") is not None for backend in budget.get("backends", {}).values()
        )
        if (
            rank in BASELINE_REPLAY_RANKS
            or declares_responses
            or list((folder / "fixtures").glob("responses*.json"))
        ):
            assert (folder / "build_fixtures.py").is_file(), f"missing replay builder: {folder}"
            assert (folder / "helpers.py").is_file(), f"missing replay helpers: {folder}"
            found.append(folder)
    assert BASELINE_REPLAY_RANKS <= {int(folder.name.split("-", 1)[0]) for folder in found}
    return found


PUBLISHED_REPLAY_BUILDERS = _published_replay_builders()


def _environment():
    env = os.environ.copy()
    # Import this checkout even when the test interpreter has another editable install.
    env["PYTHONPATH"] = str(REPO / "src")
    env["JEV_COOKBOOK_LIVE"] = "0"
    for key in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        env.pop(key, None)
    return env


def _run(script, *args, read_error=False):
    command = [sys.executable, str(script), *args]
    if read_error:
        # Exercise OSError portably, including root-run CI where chmod is ineffective.
        # This is an injected read failure; the builder's real CLI still runs via runpy.
        driver = (
            "import pathlib, runpy, sys\n"
            "script = pathlib.Path(sys.argv[1]).resolve()\n"
            "target = script.parent / 'fixtures' / 'responses.json'\n"
            "read_text = pathlib.Path.read_text\n"
            "def fail_read(self, *args, **kwargs):\n"
            "    if self == target:\n"
            "        raise PermissionError('injected response-store read failure')\n"
            "    return read_text(self, *args, **kwargs)\n"
            "pathlib.Path.read_text = fail_read\n"
            "sys.argv = sys.argv[1:]\n"
            "runpy.run_path(str(script), run_name='__main__')\n"
        )
        command = [sys.executable, "-c", driver, str(script), *args]
    return subprocess.run(
        command,
        cwd=script.parent.parent,
        env=_environment(),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=45,
    )


# Recipe 77's own image builder (merged in #550, before this contract existed) refuses with
# "refusing to overwrite recorded or malformed responses; use --force explicitly" and does not
# name the file. It is the only published copy that does not; every other assertion still holds
# for it, and its refusal text is pinned by its own tests.
STORE_PATH_NOT_NAMED = ("77-",)


def _assert_refused(result, path, names_path=True):
    assert result.returncode != 0, f"silently overwrote {path}: {result.stdout}"
    diagnostic = result.stdout + result.stderr
    assert "refus" in diagnostic.lower(), diagnostic
    assert "--force" in diagnostic, diagnostic
    if names_path:
        assert str(path) in diagnostic, diagnostic
    assert "Traceback" not in diagnostic, diagnostic


def _copy_builder(source, target):
    target.mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(source / name, target / name)
    return target / "build_fixtures.py"


@pytest.mark.parametrize("source", PUBLISHED_REPLAY_BUILDERS, ids=lambda path: path.name)
def test_every_published_replay_builder_preserves_malformed_response_bytes(tmp_path, source):
    """One planted trailing-comma failure per published copy, then --force must recover it.

    The refusal alone would still pass if a builder checked the store before looking at
    --force, so that --force could never repair a malformed store. Assert the recovery too.
    """
    script = _copy_builder(source, tmp_path / source.name)
    path = script.parent / "fixtures" / "responses.json"
    path.parent.mkdir()
    path.write_bytes(TRAILING_COMMA)
    refused = _run(script)
    assert path.read_bytes() == TRAILING_COMMA, f"original bytes lost by {source.name}"
    _assert_refused(refused, path, names_path=not source.name.startswith(STORE_PATH_NOT_NAMED))
    forced = _run(script, "--force")
    assert forced.returncode == 0, f"--force cannot recover {source.name}: {forced.stderr}"
    assert "Traceback" not in forced.stderr, forced.stderr
    rewritten = path.read_bytes()
    assert rewritten != TRAILING_COMMA, f"--force left the malformed store in {source.name}"
    data = json.loads(rewritten.decode("utf-8"))
    assert isinstance(data, dict) and data, f"--force wrote no valid store in {source.name}"
    assert all(entry["model"] == "synthetic" for entry in data.values())


def _complete_text_author_todos(folder):
    (folder / "helpers.py").write_text(
        "from jev_cookbook import Noul\n\n"
        "def build_state(fields):\n    return dict(fields)\n\n"
        "def build_questions():\n"
        "    return {'check': Noul(instructions='The synthetic example is acceptable.')}\n",
        encoding="utf-8",
    )
    path = folder / "build_fixtures.py"
    lines = path.read_text("utf-8").splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    edits = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ROWS" for target in node.targets
        ):
            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    "ROWS = [('v01', 'validation', {'text': 'invented'}, True, 0.8)]\n",
                )
            )
        if isinstance(node, ast.FunctionDef) and node.name == "answers_for":
            edits.append(
                (
                    node.lineno - 1,
                    node.end_lineno,
                    "def answers_for(spec, provenance):\n"
                    "    from jev_cookbook import NoulAnswer\n"
                    "    return {'check': NoulAnswer(spec, provenance)}\n",
                )
            )
    assert len(edits) == 2, "text scaffold no longer has the expected author TODO interfaces"
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start:end] = [replacement]
    path.write_text("".join(lines), encoding="utf-8")


def _make_generated_source(mode, root):
    if mode == "template":
        folder = root / "template"
        _copy_builder(REPO / "recipes" / "_template", folder)
        shutil.copytree(REPO / "recipes" / "_template" / "fixtures", folder / "fixtures")
        return folder
    done = _run(
        REPO / "tools" / "new_recipe.py",
        "61",
        "--mode",
        mode,
        "--catalog",
        str(REPO / "catalog" / "recipes.json"),
        "--recipes-dir",
        str(root / "recipes"),
    )
    assert done.returncode == 0, done.stderr
    folders = list((root / "recipes").iterdir())
    assert len(folders) == 1
    folder = folders[0]
    if mode == "replay":
        _complete_text_author_todos(folder)
        done = _run(folder / "build_fixtures.py")
        assert done.returncode == 0, done.stderr
    return folder


@pytest.fixture(scope="module", params=("template", "replay", "replay-images"))
def generated_source(request, tmp_path_factory):
    return _make_generated_source(
        request.param, tmp_path_factory.mktemp(f"overwrite-{request.param}")
    )


@pytest.fixture(scope="module")
def image_source(tmp_path_factory):
    return _make_generated_source("replay-images", tmp_path_factory.mktemp("asset-overwrite"))


@pytest.fixture
def image_copy(tmp_path, image_source):
    folder = tmp_path / image_source.name
    shutil.copytree(image_source, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder


@pytest.fixture
def generated_copy(tmp_path, generated_source):
    folder = tmp_path / generated_source.name
    shutil.copytree(generated_source, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def _fixture_bytes(folder):
    return {
        path.name: path.read_bytes() for path in (folder / "fixtures").iterdir() if path.is_file()
    }


def _recorded_bytes(raw):
    data = json.loads(raw)
    assert data, "a non-empty synthetic store is needed to test recorded-answer protection"
    value = next(iter(data.values()))
    value["model"] = "recorded-test-model"
    for answer in value["answers"].values():
        answer["provenance"] = {
            "source": "recorded",
            "model": "recorded-test-model",
            "date": "2026-01-01",
        }
    return (json.dumps(data, indent=2) + "\r\n").encode("utf-8")


@pytest.mark.parametrize("bad", BAD_STORES)
def test_template_and_scaffolded_builders_refuse_bad_stores_then_force_restores_exact_bytes(
    generated_copy,
    bad,
):
    folder = generated_copy
    expected = _fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    path.write_bytes(bad)
    for name in ("inputs.jsonl", "labels.jsonl"):
        (path.parent / name).write_bytes(b"corrupted author inputs\n")
    refused = _run(folder / "build_fixtures.py")
    assert path.read_bytes() == bad
    _assert_refused(refused, path)
    for name in ("inputs.jsonl", "labels.jsonl"):
        assert (path.parent / name).read_bytes() == expected[name]
    forced = _run(folder / "build_fixtures.py", "--force")
    assert forced.returncode == 0, forced.stderr
    assert _fixture_bytes(folder) == expected


def test_valid_recorded_protection_and_synthetic_determinism_remain(generated_copy):
    folder = generated_copy
    expected = _fixture_bytes(folder)
    script = folder / "build_fixtures.py"
    repeated = _run(script)
    assert repeated.returncode == 0, repeated.stderr
    assert _fixture_bytes(folder) == expected
    path = folder / "fixtures" / "responses.json"
    recorded = _recorded_bytes(path.read_bytes())
    path.write_bytes(recorded)
    refused = _run(script)
    assert path.read_bytes() == recorded
    _assert_refused(refused, path)
    forced = _run(script, "--force")
    assert forced.returncode == 0, forced.stderr
    assert _fixture_bytes(folder) == expected


def test_response_read_oserror_requires_force(generated_copy):
    folder = generated_copy
    expected = _fixture_bytes(folder)
    path = folder / "fixtures" / "responses.json"
    refused = _run(folder / "build_fixtures.py", read_error=True)
    assert _fixture_bytes(folder) == expected
    _assert_refused(refused, path)
    forced = _run(folder / "build_fixtures.py", "--force", read_error=True)
    assert forced.returncode == 0, forced.stderr
    assert _fixture_bytes(folder) == expected


@pytest.mark.parametrize("name", ("responses-atlas.json", "responses-north.json"))
def test_recipe50_sidecars_preserve_bad_bytes_and_force_restores_them(tmp_path, name):
    source = next(path for path in PUBLISHED_REPLAY_BUILDERS if path.name.startswith("50-"))
    script = _copy_builder(source, tmp_path / source.name)
    shutil.copytree(source / "fixtures", script.parent / "fixtures")
    path = script.parent / "fixtures" / name
    assert path.is_file(), f"required recipe50 response sidecar disappeared: {name}"
    expected = _fixture_bytes(script.parent)
    path.write_bytes(TRAILING_COMMA)
    refused = _run(script)
    assert path.read_bytes() == TRAILING_COMMA
    _assert_refused(refused, path)
    forced = _run(script, "--force")
    assert forced.returncode == 0, forced.stderr
    assert _fixture_bytes(script.parent) == expected


@pytest.mark.parametrize("store", ("malformed", "invalid-utf8", "recorded"))
def test_image_overwrite_assets_refuses_before_any_write_and_force_recovers(
    image_copy,
    store,
):
    folder = image_copy
    script = folder / "build_fixtures.py"
    path = folder / "fixtures" / "responses.json"
    original_responses = path.read_bytes()
    bad = {"malformed": TRAILING_COMMA, "invalid-utf8": b"\xff\xfe"}.get(store)
    path.write_bytes(_recorded_bytes(original_responses) if bad is None else bad)
    image = next((folder / "assets").glob("*.png"))
    original_image = image.read_bytes()
    image.write_bytes(b"planted changed synthetic image\n")
    tracked = [
        *sorted((folder / "fixtures").iterdir()),
        *sorted((folder / "assets").iterdir()),
        folder / "assets-manifest.json",
    ]
    before = {file: file.read_bytes() for file in tracked if file.is_file()}
    refused = _run(script, "--overwrite-assets")
    assert {file: file.read_bytes() for file in before} == before
    _assert_refused(refused, path)
    forced = _run(script, "--overwrite-assets", "--force")
    assert forced.returncode == 0, forced.stderr
    assert image.read_bytes() == original_image
    assert path.read_bytes() == original_responses
    for file, raw in before.items():
        if file not in (image, path):
            assert file.read_bytes() == raw
