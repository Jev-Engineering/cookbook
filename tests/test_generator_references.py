"""The fixture validator checks generators as source words without executing the source."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from jev_cookbook import synthetic_images as si
from jev_cookbook.fixtures import _assets as assets_module
from jev_cookbook.fixtures import validate_recipe


@pytest.fixture
def recipe(tmp_path):
    """Small scripted recipe; image references are tested through its manifest."""
    recipe = tmp_path / "recipe"
    recipe.mkdir()
    (recipe / "assets").mkdir()
    (recipe / "fixtures").mkdir()
    data = si.Canvas(300, 300).png()
    (recipe / "assets" / "scene.png").write_bytes(data)
    for filename, rows in (
        (
            "inputs.jsonl",
            [
                {"id": s, "split": s, "fields": {"note": s}, "replay_keys": []}
                for s in ("validation", "test")
            ],
        ),
        ("labels.jsonl", [{"id": s, "label": "present"} for s in ("validation", "test")]),
    ):
        (recipe / "fixtures" / filename).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), "utf-8"
        )
    return recipe


def manifest(recipe, generator, *, copies=1):
    """Hand-write the manifest entry that the validator checks."""
    data = (recipe / "assets" / "scene.png").read_bytes()
    entry = {
        "path": "assets/scene.png",
        "sha256": hashlib.sha256(data).hexdigest(),
        "format": "PNG",
        "width": 300,
        "height": 300,
        "origin": "generated",
        "generator": generator,
        "parameters": {},
        "licence": "CC0-1.0",
        "description": "A plain synthetic square.",
        "attestations": {
            "synthetic": True,
            "real_photo": False,
            "real_brand": False,
            "real_person": False,
            "third_party_content": False,
        },
    }
    entries = [entry]
    for i in range(1, copies):
        other = copy.deepcopy(entry)
        other["path"] = f"assets/scene-{i}.png"
        (recipe / other["path"]).write_bytes(data)
        entries.append(other)
    (recipe / "assets-manifest.json").write_text(
        json.dumps({"schema": 1, "assets": entries}), "utf-8"
    )
    return entries


def messages(recipe):
    return [str(problem) for problem in validate_recipe(recipe)]


@pytest.mark.parametrize(
    "text,accepted",
    [
        ("def draw_scene(): pass\n", True),
        ("# draw_scene is documented here\nraise RuntimeError('do not execute')\n", True),
        ("draw_scene = 7\n", True),
        ("draw_scene = (\n", True),  # word presence does not require valid Python
        ('label = "draw_scene"\n', True),
        ("def draw_scene_v2(): pass\n", False),
        ("def redraw_scene(): pass\n", False),
        ("# _draw_scene draw_scene_ édraw_scene\n", False),
    ],
)
def test_script_generator_uses_whole_words(recipe, text, accepted):
    (recipe / "build.py").write_text(text, "utf-8")
    generator = "build.py:draw_scene"
    manifest(recipe, generator)
    found = messages(recipe)
    if accepted:
        assert found == []
    else:
        assert len(found) == 1 and "[generator]" in found[0] and "draw_scene" in found[0]


def test_package_noncallable_source_word_is_accepted(recipe):
    generator = "jev_cookbook.synthetic_images:SCENES"
    manifest(recipe, generator)
    assert messages(recipe) == []


@pytest.fixture
def package_root(tmp_path, monkeypatch):
    root = tmp_path / "package"
    root.mkdir()
    monkeypatch.setattr(assets_module, "_PACKAGE_DIR", root)
    # The old implementation has no shared helper; public regressions must reach its behavior.
    helper = sys.modules.get("jev_cookbook._generator_refs")
    if helper is not None:
        monkeypatch.setattr(helper, "PACKAGE_DIR", root)
    return root


def test_neither_package_target_nor_parent_is_executed(recipe, package_root, monkeypatch):
    parent = package_root / "paint"
    parent.mkdir()
    marker = recipe / "executed"
    source = (
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('stop')\n"
    )
    (parent / "__init__.py").write_text(source, "utf-8")
    (parent / "scene.py").write_text(source + "# draw_scene\n", "utf-8")
    generator = "jev_cookbook.paint.scene:draw_scene"
    manifest(recipe, generator)
    monkeypatch.setattr(sys.modules["jev_cookbook"], "__path__", [str(package_root)])
    monkeypatch.delitem(sys.modules, "jev_cookbook.paint", raising=False)
    monkeypatch.delitem(sys.modules, "jev_cookbook.paint.scene", raising=False)
    assert messages(recipe) == []
    assert not marker.exists()
    assert "jev_cookbook.paint" not in sys.modules
    assert "jev_cookbook.paint.scene" not in sys.modules


@pytest.mark.parametrize("kind", ["script", "package"])
@pytest.mark.parametrize("failure", ["missing", "directory", "undecodable", "unreadable"])
def test_bad_sources_are_findings(recipe, package_root, monkeypatch, kind, failure):
    source = recipe / "build.py" if kind == "script" else package_root / "draw.py"
    generator = "build.py:draw_scene" if kind == "script" else "jev_cookbook.draw:draw_scene"
    if failure == "directory":
        source.mkdir()
    elif failure == "undecodable":
        source.write_bytes(b"\xff draw_scene")
    elif failure == "unreadable":
        source.write_text("# draw_scene\n", "utf-8")
        original = Path.read_text

        def denied(path, *args, **kwargs):
            if path == source:
                raise PermissionError("synthetic unreadable source")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", denied)
    manifest(recipe, generator)
    found = messages(recipe)
    assert len(found) == 1 and "[generator]" in found[0]


@pytest.mark.parametrize(
    "generator",
    [
        "build.py:",
        "build.py:draw scene",
        "build.py:draw:again",
        "os:system",
        "jev_cookbook..draw:scene",
        "jev_cookbook.draw:scene()",
    ],
)
def test_invalid_references_keep_the_manifest_field_category(recipe, generator):
    manifest(recipe, generator)
    found = messages(recipe)
    assert len(found) == 1 and "[manifest-field]" in found[0]


@pytest.mark.parametrize("kind", ["script", "package"])
def test_cache_reused_within_validation_but_fresh_after_same_stat_edit(
    recipe, package_root, monkeypatch, kind
):
    source = recipe / "build.py" if kind == "script" else package_root / "draw.py"
    generator = "build.py:draw_scene" if kind == "script" else "jev_cookbook.draw:draw_scene"
    source.write_text("# draw_scene\n", "utf-8")
    manifest(recipe, generator, copies=4)
    original = Path.read_text
    reads = []

    def counted(path, *args, **kwargs):
        if path == source:
            reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    assert messages(recipe) == []
    assert reads == [source]
    before = source.stat()
    source.write_text("# miss_scene\n", "utf-8")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (
        before.st_size,
        before.st_mtime_ns,
    )
    found = messages(recipe)
    assert len(found) == 4 and all("[generator]" in text for text in found)
    assert reads == [source, source]


def test_cache_keeps_function_answers_distinct(recipe, package_root):
    (package_root / "draw.py").write_text("# draw_scene\n", "utf-8")
    entries = manifest(recipe, "jev_cookbook.draw:draw_scene", copies=2)
    entries[1]["generator"] = "jev_cookbook.draw:other_scene"
    (recipe / "assets-manifest.json").write_text(json.dumps({"schema": 1, "assets": entries}))
    found = messages(recipe)
    assert len(found) == 1 and "other_scene" in found[0] and "[generator]" in found[0]


@pytest.mark.parametrize("layout", ["namespace", "namespace_parent", "archive"])
def test_namespace_and_archive_targets_are_explicitly_unsupported(
    recipe, package_root, monkeypatch, layout
):
    target = package_root / "paint"
    target.mkdir()
    generator = "jev_cookbook.paint:draw_scene"
    if layout == "namespace_parent":
        (target / "scene.py").write_text("# draw_scene\n", "utf-8")
        generator = "jev_cookbook.paint.scene:draw_scene"
    elif layout == "archive":
        # A package path inside an archive is not a regular installed source directory.
        archive = package_root / "installed.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("jev_cookbook/paint/__init__.py", "# draw_scene\n")
        monkeypatch.setattr(assets_module, "_PACKAGE_DIR", archive / "jev_cookbook")
        helper = sys.modules.get("jev_cookbook._generator_refs")
        if helper is not None:
            monkeypatch.setattr(helper, "PACKAGE_DIR", archive / "jev_cookbook")
    manifest(recipe, generator)
    found = messages(recipe)
    assert len(found) == 1 and "[generator]" in found[0] and "is not a module" in found[0]


@pytest.mark.parametrize("contained", [False, True])
def test_script_symlink_must_stay_inside_the_recipe(recipe, tmp_path, monkeypatch, contained):
    source = (recipe if contained else tmp_path) / "target.py"
    source.write_text("# draw_scene\n", "utf-8")
    try:
        (recipe / "linked.py").symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("this platform cannot create symbolic links")
    generator = "linked.py:draw_scene"
    manifest(recipe, generator)
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert contained or path.resolve() != source, "reject escaping source before reading"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    found = messages(recipe)
    if contained:
        assert found == []
    else:
        assert len(found) == 1
        assert "[generator]" in found[0] and "not a readable file in the recipe" in found[0]
