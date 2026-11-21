"""Issue #501: the real scaffolded force guard must reject changed synthetic bytes.

Run emitted and committed test functions against disposable recipe copies. Mutations
run only after a successful builder CLI invocation with --force; build_responses and
ordinary/refused runs retain their original behavior. No notebook or service runs.
The #489 support module supplies source discovery and author-TODO completion only.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SUPPORT_PATH = Path(__file__).with_name("test_fixture_overwrite_contract.py")
SPEC = importlib.util.spec_from_file_location("fixture_force_source_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
MUTATIONS = ("usage", "whitespace")
GUARD_NAME = "test_build_fixtures_separates_inputs_labels_from_responses"
GUARD_FILE = "test_build_fixtures.py"
MARKER = "force-501-before-mutation.bin"


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    """Nested builder processes resolve this checkout and cannot opt into live use."""
    monkeypatch.setenv("PYTHONPATH", str(REPO / "src"))
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "0")
    for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _copy_source(source, target, test_file=GUARD_FILE):
    target.mkdir()
    (target / "tests").mkdir()
    for name in ("helpers.py", "build_fixtures.py"):
        shutil.copyfile(source / name, target / name)
    shutil.copyfile(source / "tests" / test_file, target / "tests" / test_file)
    if (source / "assets").is_dir():
        shutil.copytree(source / "assets", target / "assets")
    return target


def _plant_force_only_mutation(source, mutation):
    """Append a separate CLI-only mutation; leave every builder function untouched."""
    assert mutation in MUTATIONS
    script = source / "build_fixtures.py"
    payload = (
        "\n# Synthetic --force-only fault injected by the #501 regression.\n"
        "if __name__ == '__main__':\n"
        "    import sys as _force_501_sys\n"
        "    if '--force' in _force_501_sys.argv[1:]:\n"
        "        from jev_cookbook import dump_responses as _force_501_dump\n"
        "        _force_501_path = HERE / 'fixtures' / 'responses.json'\n"
        "        _force_501_raw = _force_501_path.read_bytes()\n"
        f"        (HERE / {MARKER!r}).write_bytes(_force_501_raw)\n"
    )
    if mutation == "usage":
        # Real response metadata changes, with the model and every provenance left synthetic.
        # Token counts are optional non-negative integers, so this is not a malformed-store test.
        payload += (
            "        _force_501_data = json.loads(_force_501_raw)\n"
            "        assert _force_501_data\n"
            "        next(iter(_force_501_data.values()))['usage']['input_tokens'] = 501\n"
            "        _force_501_path.write_text(\n"
            "            _force_501_dump(_force_501_data), encoding='utf-8', newline='\\n'\n"
            "        )\n"
        )
    else:
        # A trailing JSON whitespace change preserves every parsed value and provenance.
        payload += "        _force_501_path.write_bytes(_force_501_raw + b' \\n')\n"
    script.write_text(script.read_text("utf-8") + payload, encoding="utf-8", newline="\n")


def _call_real_test(source, work, test_file=GUARD_FILE, test_name=GUARD_NAME):
    work.mkdir()
    spec = importlib.util.spec_from_file_location(
        "force_byte_guard_under_test", source / "tests" / test_file
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, test_name)(work)


def _assert_force_mutation_happened(work, mutation):
    """Prove rejection was reached after successful --force, not a setup/import error."""
    markers = list(work.glob(f"*/{MARKER}"))
    assert len(markers) == 1, "the real fixture test did not complete its forced builder call"
    marker = markers[0]
    before = marker.read_bytes()
    after = (marker.parent / "fixtures" / "responses.json").read_bytes()
    assert after != before, "negative control did not change the forced output bytes"
    original, changed = json.loads(before), json.loads(after)
    assert original and changed
    assert all(value["model"] == "synthetic" for value in changed.values())
    assert all(
        answer["provenance"]["source"] == "synthetic"
        for value in changed.values()
        for answer in value["answers"].values()
    )
    if mutation == "whitespace":
        assert changed == original, "format-only fault changed a parsed response value"
    else:
        assert changed != original, "content fault changed no parsed response value"
        assert next(iter(changed.values()))["usage"]["input_tokens"] == 501


def _assert_real_test_rejects_mutation(source, work, mutation, **test_arguments):
    failure = None
    try:
        _call_real_test(source, work, **test_arguments)
    except AssertionError as error:
        failure = error
    _assert_force_mutation_happened(work, mutation)
    assert failure is not None, (
        f"{source.name}: real fixture guard accepted changed --force {mutation} bytes "
        "although every model/provenance stayed synthetic"
    )


@pytest.fixture(scope="module", params=("template", "replay", "replay-images"))
def scaffold_source(request, tmp_path_factory):
    root = tmp_path_factory.mktemp(f"force-byte-source-{request.param}")
    source = SUPPORT._make_generated_source(request.param, root)
    if request.param == "template":
        (source / "tests").mkdir()
        shutil.copyfile(
            REPO / "recipes" / "_template" / "tests" / GUARD_FILE,
            source / "tests" / GUARD_FILE,
        )
    return source


def test_unchanged_template_and_generated_force_guards_pass(scaffold_source, tmp_path):
    source = _copy_source(scaffold_source, tmp_path / scaffold_source.name)
    _call_real_test(source, tmp_path / "guard-work")


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_template_and_generated_force_guards_reject_changed_synthetic_bytes(
    scaffold_source, tmp_path, mutation
):
    source = _copy_source(scaffold_source, tmp_path / scaffold_source.name)
    _plant_force_only_mutation(source, mutation)
    _assert_real_test_rejects_mutation(source, tmp_path / "guard-work", mutation)


@pytest.mark.parametrize("published", SUPPORT.PUBLISHED_REPLAY_BUILDERS, ids=lambda path: path.name)
@pytest.mark.parametrize("mutation", (None, *MUTATIONS), ids=("unchanged", *MUTATIONS))
def test_every_published_force_guard_checks_its_own_bytes(published, tmp_path, mutation):
    """Discovery pins all 50 baseline replay recipes and includes new published copies."""
    source = _copy_source(published, tmp_path / published.name)
    if mutation is None:
        _call_real_test(source, tmp_path / "guard-work")
    else:
        _plant_force_only_mutation(source, mutation)
        _assert_real_test_rejects_mutation(source, tmp_path / "guard-work", mutation)


@pytest.mark.parametrize("mutation", (None, *MUTATIONS), ids=("unchanged", *MUTATIONS))
def test_recipe51_existing_adjunct_still_discriminates(tmp_path, mutation):
    """Keep exercising the actual adjunct, which already detects both faults before #501."""
    adjunct = "test_build_fixtures_exact.py"
    source = _copy_source(
        REPO / "recipes" / "51-stalled-loop-detection",
        tmp_path / "51-stalled-loop-detection",
        adjunct,
    )
    arguments = {"test_file": adjunct, "test_name": "test_force_restores_the_exact_synthetic_bytes"}
    if mutation is None:
        _call_real_test(source, tmp_path / "guard-work", **arguments)
    else:
        _plant_force_only_mutation(source, mutation)
        _assert_real_test_rejects_mutation(source, tmp_path / "guard-work", mutation, **arguments)
