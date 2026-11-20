"""Issue 506 acceptance checks, with temporary synthetic assets and fake builders only.

These tests exercise emitted Python directly; they never execute notebooks, start a
kernel, contact a service, or rely on a particular PNG encoder being installed.
"""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jev_cookbook import synthetic_images as si

REPO = Path(__file__).resolve().parent.parent
CATALOG = json.loads((REPO / "catalog/recipes.json").read_text("utf-8"))
RECIPE = next(row for row in CATALOG["recipes"] if row["rank"] == 77)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Dataclass-bearing emitted modules must be visible during their import.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


new_recipe = _load(REPO / "tools/new_recipe.py", "new_recipe_robustness")


@pytest.fixture
def generated(tmp_path):
    folder = tmp_path / "recipe"
    folder.mkdir()
    for name, text in new_recipe.files_for(CATALOG, RECIPE, "replay-images").items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    module = _load(folder / "build_fixtures.py", f"robustness_builder_{tmp_path.name}")
    # Three rows are enough to expose a late refusal after an earlier absent file.
    module.ROWS = module.ROWS[:3]
    return folder, module


def _snapshot(folder):
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


@pytest.mark.parametrize("canonical", [False, True])
def test_success_warns_exactly_when_encoder_is_noncanonical(
    tmp_path, monkeypatch, capsys, canonical
):
    target = tmp_path / "recipe"
    target.mkdir()
    events = []

    def succeeded(*args, **kwargs):
        before_build = capsys.readouterr()
        assert "warn" not in (before_build.out + before_build.err).lower()
        events.append("built")
        return subprocess.CompletedProcess(args, 0, stdout="built synthetic images\n", stderr="")

    monkeypatch.setattr(new_recipe.subprocess, "run", succeeded)
    monkeypatch.setattr(si, "bytes_are_canonical", lambda: canonical)
    new_recipe._draw_images(target)
    captured = capsys.readouterr()
    output = (captured.out + captured.err).lower()
    assert events == ["built"] and target.is_dir()
    warned = "warn" in output and "canonical" in output
    assert warned is (not canonical), output


@pytest.mark.parametrize("late_problem", ["different_pixels", "unreadable_file"])
def test_late_batch_refusal_preserves_every_existing_byte_and_creates_no_assets(
    generated, monkeypatch, late_problem
):
    folder, builder = generated
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    builder.main()
    first = folder / builder.image_path(builder.ROWS[0][0])
    late = folder / builder.image_path(builder.ROWS[-1][0])
    first.unlink()  # tempting early write, before the deliberately mismatching final row
    if late_problem == "different_pixels":
        changed = list(builder.ROWS[-1])
        changed[4] += 1234567
        builder.ROWS[-1] = tuple(changed)
    else:
        late.write_bytes(b"synthetic invalid PNG control\n")
    before = _snapshot(folder)
    # Explicitly retain the fixtures whose consistency an orphan PNG would undermine.
    assert {"assets-manifest.json", "fixtures/responses.json"} <= before.keys()
    with pytest.raises(SystemExit) as refused:
        builder.main()
    assert "refus" in str(refused.value).lower() and late.name in str(refused.value)
    assert _snapshot(folder) == before
    assert not first.exists()


def test_successful_batch_can_be_rerun_without_changing_assets_or_fixtures(generated, monkeypatch):
    folder, builder = generated
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    builder.main()
    before = _snapshot(folder)
    builder.main()
    assert _snapshot(folder) == before
    assert len(list((folder / "assets").glob("*.png"))) == 3


def _redraw_guard(folder):
    emitted = _load(
        folder / "tests/test_helpers.py", f"robustness_generated_guard_{folder.parent.name}"
    )
    return emitted.test_every_scene_can_be_redrawn_from_its_manifest_entry


def _run_without_skip(guard):
    try:
        guard()
    except pytest.skip.Exception as skipped:
        pytest.fail(f"custom-scene coverage must assert applicable facts, not skip: {skipped}")


def test_custom_scene_has_an_applicable_generator_assertion_instead_of_a_skip(
    generated, monkeypatch
):
    folder, builder = generated
    original_draw = builder.draw

    def custom_draw(row):
        return original_draw(row).provenance("build_fixtures.py:draw", {"row": list(row)})

    monkeypatch.setattr(builder, "draw", custom_draw)
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    builder.main()
    _run_without_skip(_redraw_guard(folder))


def test_shared_scene_redraw_guard_still_verifies_committed_assets(generated, monkeypatch):
    folder, builder = generated
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    builder.main()
    guard = _redraw_guard(folder)
    _run_without_skip(guard)
    picture = folder / builder.image_path(builder.ROWS[0][0])
    picture.write_bytes(b"synthetic invalid PNG redraw control\n")
    with pytest.raises(si.RegenerationMismatch):
        _run_without_skip(guard)


@pytest.mark.parametrize(
    "generator", ["build_fixtures.py:no_such_generator", "missing_builder.py:draw"]
)
def test_custom_scene_guard_rejects_a_generator_the_builder_cannot_cover(
    generated, monkeypatch, generator
):
    folder, builder = generated
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    builder.main()
    path = folder / "assets-manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    # Include a valid shared entry too: checking only shared entries must not hide
    # the invalid custom generator at the end of a mixed manifest.
    manifest["assets"][-1]["generator"] = generator
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises((AssertionError, ValueError)):
        _run_without_skip(_redraw_guard(folder))


# Every replacement in the image notebook needs its text-notebook anchor. These
# literals describe the public cell IDs used by consumers of the emitted notebook.
@pytest.mark.parametrize(
    "missing_id",
    [
        "setup-md",
        "setup",
        "state-md",
        "state",
        "answer-md",
        "answer",
        "python-md",
        "python-rule",
        "evaluation-md",
        "evaluation",
    ],
)
def test_renamed_replacement_anchor_fails_loudly(monkeypatch, missing_id):
    base = copy.deepcopy(new_recipe.notebook_cells(CATALOG, RECIPE, "replay"))
    anchor = next(cell for cell in base if cell["id"] == missing_id)
    anchor["id"] = f"renamed-{missing_id}"
    monkeypatch.setattr(new_recipe, "notebook_cells", lambda *args, **kwargs: base)
    with pytest.raises((AssertionError, ValueError, new_recipe.ScaffoldError)) as refused:
        new_recipe.image_notebook_cells(CATALOG, RECIPE)
    assert missing_id in str(refused.value)


@pytest.mark.parametrize("failure_kind", ["nonzero_exit", "timeout"])
def test_failed_builder_keeps_early_stderr_and_stdout_after_folder_cleanup(
    tmp_path, monkeypatch, capsys, failure_kind
):
    target = tmp_path / "recipe"
    target.mkdir()
    (target / "partial.txt").write_text("synthetic partial build", encoding="utf-8")
    stdout = "stdout-start: synthetic build context\nstdout-end: synthetic summary\n"
    stderr = "stderr-start: synthetic root cause\n" + "".join(
        f"stderr-detail-{i}: synthetic diagnostic\n" for i in range(20)
    )

    def failed(*args, **kwargs):
        if failure_kind == "timeout":
            # TimeoutExpired retains bytes even when subprocess.run(text=True).
            raise subprocess.TimeoutExpired(
                args[0], 1, output=stdout.encode(), stderr=stderr.encode()
            )
        return subprocess.CompletedProcess(args, 17, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(new_recipe.subprocess, "run", failed)
    with pytest.raises(new_recipe.ScaffoldError) as refused:
        new_recipe._draw_images(target)
    assert not target.exists()
    captured = capsys.readouterr()
    # The issue permits either the error output itself or a durable log outside
    # the removed folder. Search only this test's synthetic temporary tree.
    retained = "\n".join(path.read_text("utf-8") for path in tmp_path.rglob("*") if path.is_file())
    diagnostics = str(refused.value) + captured.out + captured.err + retained
    for line in (stdout + stderr).splitlines():
        assert line in diagnostics, f"lost builder diagnostic: {line}"
