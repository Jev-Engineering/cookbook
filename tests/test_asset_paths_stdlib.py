"""Path extraction regressions, independent of Pillow and a warmed pytest interpreter."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import textwrap
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Both hooks matter: __import__ sees ordinary imports even when a dependency is already
# cached; the finder also sees importlib.import_module. Record attempts so a swallowed
# ImportError cannot turn an unwanted optional import into a passing test.
IMPORT_GUARD = """
import builtins
import json
import sys
from pathlib import Path
from types import SimpleNamespace

attempts = []
def forbidden(name):
    return name.split('.')[0] in {'PIL', 'matplotlib'}

assert not [name for name in sys.modules if forbidden(name)]
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if forbidden(name):
        attempts.append(name)
        raise ImportError('optional image dependency attempted: ' + name)
    return original_import(name, *args, **kwargs)

class ImportGuard:
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            attempts.append(fullname)
            raise ImportError('optional image dependency attempted: ' + fullname)

builtins.__import__ = guarded_import
sys.meta_path.insert(0, ImportGuard())
"""
IMPORT_CHECK = """
assert not attempts, attempts
assert not [name for name in sys.modules if forbidden(name)]
assert 'jev_cookbook.vision' not in sys.modules
"""


def run_clean(script: str, *, guard: bool = True) -> str:
    """Use this checkout even when the parent runner has imported vision already."""
    code = f"import sys\nsys.path.insert(0, {str(ROOT / 'src')!r})\n"
    if guard:
        code += textwrap.dedent(IMPORT_GUARD)
    code += textwrap.dedent(script)
    if guard:
        code += textwrap.dedent(IMPORT_CHECK)
    done = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.mark.parametrize("module", ["jev_cookbook._paths", "jev_cookbook.fixtures._assets"])
def test_path_and_manifest_modules_import_without_optional_image_dependencies(module):
    run_clean(f"import {module}\n")


def png_bytes() -> bytes:
    """An actual RGB PNG, including CRCs and compressed pixels, made only with stdlib."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 320, 300, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x20\x40\x60" * 320) * 300))
        + chunk(b"IEND", b"")
    )


def image_recipe(tmp_path: Path) -> tuple[Path, dict]:
    recipe = tmp_path / "recipe"
    (recipe / "assets").mkdir(parents=True)
    data = png_bytes()
    (recipe / "assets" / "scene.png").write_bytes(data)
    (recipe / "build_fixtures.py").write_text("def draw_scene():\n    pass\n", encoding="utf-8")
    manifest = {
        "schema": 1,
        "assets": [
            {
                "path": "assets/scene.png",
                "sha256": hashlib.sha256(data).hexdigest(),
                "format": "PNG",
                "width": 320,
                "height": 300,
                "origin": "generated",
                "generator": "build_fixtures.py:draw_scene",
                "parameters": {},
                "licence": "CC0-1.0",
                "description": "A synthetic solid blue rectangle.",
                "attestations": {
                    "synthetic": True,
                    "real_photo": False,
                    "real_brand": False,
                    "real_person": False,
                    "third_party_content": False,
                },
            }
        ],
    }
    write_manifest(recipe, manifest)
    return recipe, manifest


def write_manifest(recipe: Path, manifest: dict) -> None:
    (recipe / "assets-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def check_in_clean_process(recipe: Path, fields: dict) -> list:
    # Exercise the manifest checker itself, with the package's strict JSON reader.
    return json.loads(
        run_clean(f"""
from jev_cookbook.fixtures import _read_manifest
from jev_cookbook.fixtures._assets import check_assets
examples = [SimpleNamespace(id='e0', split='validation', fields={fields!r})]
findings = check_assets(Path({str(recipe)!r}), examples,
                        read_json=_read_manifest, leak_splits=('validation', 'test'))
print(json.dumps(findings))
""")
    )


def test_valid_image_manifest_checks_bytes_without_optional_image_dependencies(tmp_path):
    recipe, _ = image_recipe(tmp_path)
    assert check_in_clean_process(recipe, {"image": "assets/scene.png"}) == []


def test_public_recipe_validator_handles_images_without_optional_image_dependencies(tmp_path):
    recipe, _ = image_recipe(tmp_path)
    (recipe / "fixtures").mkdir()
    run_clean(f"""
from jev_cookbook import DecisionResult, NoulAnswer, Provenance
from jev_cookbook.fixtures import validate_recipe
recipe = Path({str(recipe)!r})
key = 'a' * 64
test_key = 'b' * 64
row = {{'id': 'e0', 'split': 'validation',
        'fields': {{'image': 'assets/scene.png'}}, 'replay_keys': [key]}}
test_row = {{'id': 'e1', 'split': 'test',
             'fields': {{'note': 'A separate synthetic text example.'}},
             'replay_keys': [test_key]}}
(recipe / 'fixtures/inputs.jsonl').write_text(
    json.dumps(row) + '\\n' + json.dumps(test_row) + '\\n', encoding='utf-8')
(recipe / 'fixtures/labels.jsonl').write_text(
    json.dumps({{'id': 'e0', 'label': 'present'}}) + '\\n'
    + json.dumps({{'id': 'e1', 'label': 'absent'}}) + '\\n', encoding='utf-8')
answer = NoulAnswer(0.9, Provenance.synthetic())
test_answer = NoulAnswer(0.1, Provenance.synthetic())
responses = {{key: DecisionResult({{'present': answer}}, 'synthetic').to_dict(),
             test_key: DecisionResult({{'present': test_answer}}, 'synthetic').to_dict()}}
(recipe / 'fixtures/responses.json').write_text(json.dumps(responses), encoding='utf-8')
report = validate_recipe(recipe)
assert not list(report), list(report)
""")


@pytest.mark.parametrize("manifest_problem", [False, True], ids=["no-manifest", "bad-schema"])
def test_text_only_manifest_validation_stays_stdlib_only(tmp_path, manifest_problem):
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    if manifest_problem:
        write_manifest(recipe, {"schema": 2, "assets": []})
    note = "Plain text without an image reference." if manifest_problem else "assets/equity"
    findings = check_in_clean_process(recipe, {"note": note})
    if manifest_problem:
        assert findings
        assert all("[manifest-field]" in message for _, message, _ in findings)
    else:
        assert findings == []


@pytest.mark.parametrize("problem", ["hash", "missing", "traversal", "unlisted"])
def test_image_manifest_error_paths_stay_stdlib_only(tmp_path, problem):
    recipe, manifest = image_recipe(tmp_path)
    fields = {"image": "assets/scene.png"}
    if problem == "hash":
        manifest["assets"][0]["sha256"] = "0" * 64
        expected_rule = "[hash-mismatch]"
    elif problem == "missing":
        (recipe / "assets" / "scene.png").unlink()
        expected_rule = "[missing-file]"
    elif problem == "traversal":
        fields["image"] = "../scene.png"
        expected_rule = "[asset-path]"
    else:
        fields["image"] = "assets/unlisted.png"
        expected_rule = "[unlisted-asset]"
    write_manifest(recipe, manifest)
    findings = check_in_clean_process(recipe, fields)
    assert len(findings) == 1, findings
    assert expected_rule in findings[0][1]
    assert findings[0][2] == ("e0" if problem in {"traversal", "unlisted"} else None)


def test_vision_reexports_the_identical_path_objects():
    # vision deliberately retains its drawing dependencies; identity is checked in a
    # separate interpreter without the dependency guard used by validation above.
    run_clean(
        """
from jev_cookbook import _paths, vision
assert vision.resolve_asset_path is _paths.resolve_asset_path
assert vision.AssetPathError is _paths.AssetPathError
assert issubclass(vision.AssetPathError, ValueError)
assert {'resolve_asset_path', 'AssetPathError'} <= set(vision.__all__)
""",
        guard=False,
    )


def test_extracted_resolver_keeps_contained_and_missing_path_behavior(tmp_path):
    recipe, _ = image_recipe(tmp_path)
    run_clean(f"""
from jev_cookbook._paths import resolve_asset_path
root = Path({str(recipe)!r})
expected = (root / 'assets/scene.png').resolve()
assert resolve_asset_path('assets/scene.png', root=root) == expected
assert resolve_asset_path(Path('assets/../assets/scene.png'), root=str(root)) == expected
missing = resolve_asset_path('assets/missing.png', root=root)
assert missing == (root / 'assets/missing.png').resolve()
assert not missing.exists()
try:
    missing.open('rb')
except FileNotFoundError:
    pass
else:
    raise AssertionError('contained missing path must remain a filesystem error')
""")


@pytest.mark.parametrize("kind", ["url", "data", "absolute", "traversal", "symlink"])
def test_extracted_resolver_preserves_refusal_types_and_messages(tmp_path, kind):
    recipe, _ = image_recipe(tmp_path)
    if kind == "url":
        value = "https://example.invalid/image.png"
        message = "image_asset requires a local file path, not a URL"
    elif kind == "data":
        value = "data:image/png;base64,AAAA"
        message = "image_asset requires a local file path, not a URL"
    elif kind == "absolute":
        value = str(recipe / "assets" / "scene.png")
        message = f"asset path {value!r} must be relative to the recipe folder"
    else:
        value = "../outside.png" if kind == "traversal" else "assets/escape.png"
        if kind == "symlink":
            try:
                (recipe / value).symlink_to(tmp_path / "outside.png")
            except (OSError, NotImplementedError):
                pytest.skip("this platform cannot create symbolic links")
        message = f"asset path {value!r} resolves outside the recipe folder {str(recipe)!r}"
    run_clean(f"""
from jev_cookbook._paths import AssetPathError, resolve_asset_path
try:
    resolve_asset_path({value!r}, root=Path({str(recipe)!r}))
except AssetPathError as exc:
    assert isinstance(exc, ValueError)
    assert str(exc) == {message!r}, str(exc)
else:
    raise AssertionError('unsafe path was accepted')
""")


@pytest.mark.parametrize("error", [OSError("unreadable component"), RuntimeError("symlink loop")])
def test_an_unresolvable_path_is_refused_as_an_asset_path_error(tmp_path, monkeypatch, error):
    # Added with the port: a symlink loop cannot be built on every platform, so raise the
    # error that Path.resolve would raise and require the documented refusal.
    from jev_cookbook._paths import AssetPathError, resolve_asset_path

    def broken(self, strict=False):
        raise error

    monkeypatch.setattr(Path, "resolve", broken)
    with pytest.raises(AssetPathError, match="cannot be resolved") as caught:
        resolve_asset_path("assets/scene.png", root=tmp_path)
    assert caught.value.__cause__ is error


def test_check_assets_has_no_early_return_gate():
    # Added with the port: the removed gate only repeated the conditions of the loops below
    # it, so restoring it changes no report today; pin its absence at the source instead.
    import ast

    tree = ast.parse((ROOT / "src/jev_cookbook/fixtures/_assets.py").read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "check_assets"
    )
    own_returns = []
    stack = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            own_returns.append(node)
        stack.extend(ast.iter_child_nodes(node))
    assert len(own_returns) == 1, [node.lineno for node in own_returns]
    assert func.body[-1] is own_returns[0]
