"""Issue 499: preserve scaffold output while bounding real image-build work.

The goldens in fixtures/image_scaffold_text_digests.json were captured from the commit and
tree recorded as parent_commit and parent_tree in that file, using files_for() for every text
recipe and main() for image recipe 77. Only the generated source is allowed to change for images.
Shared-template architecture is reviewed separately; these tests deliberately know no
template-constant names.

Recapturing the goldens. A recapture belongs only in a pull request whose stated purpose is to
change scaffold output, and that pull request must say so and record the new parent_commit and
parent_tree (git rev-parse HEAD and HEAD^{tree} of the tree the digests came from). Never
recapture to make an unexplained mismatch pass.

* Text digests ("text.replay" and "text.scripted") do not depend on the platform. From a clean
  checkout with the package importable (PYTHONPATH=src), run:

      python -c "import importlib.util as u, json; s = u.spec_from_file_location('t',
      'tests/test_image_scaffold_efficiency.py'); m = u.module_from_spec(s); s.loader.exec_module(m);
      print(json.dumps({k: m._text_fingerprint(k) for k in ('replay', 'scripted')}, indent=2))"

* Image digests ("images"): "semantic_sha256" is platform independent; "canonical_files" and
  "canonical_sha256" must be captured on Linux with the notebook pin (pip install -c
  .github/constraints-notebooks.txt), Pillow 12.3.0 with classic zlib, where
  si.bytes_are_canonical() is True. Run the image_build fixture's build for recipe 77, then
  print _image_fingerprints(folder) (for example from a temporary test). Hosted Tests jobs do not
  install the pin on every leg, so a canonical digest captured elsewhere is not caught until
  someone runs under the pin. Off the pin the canonical assertion is skipped explicitly.
"""

import hashlib
import importlib.util
import json
import sys
import types
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

import jev_cookbook
from jev_cookbook import synthetic_images as si
from jev_cookbook import vision

REPO = Path(__file__).resolve().parent.parent
GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "image_scaffold_text_digests.json").read_text("utf-8")
)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


new_recipe = _load(REPO / "tools" / "new_recipe.py", "new_recipe_efficiency_test")
CATALOG = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))


def _digest(value):
    # JSON frames names and values unambiguously; every emitted UTF-8 byte participates.
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_fingerprint(mode):
    files = {
        f"{recipe['rank']}/{name}": hashlib.sha256(text.encode("utf-8")).hexdigest()
        for recipe in CATALOG["recipes"]
        for name, text in new_recipe.files_for(CATALOG, recipe, mode).items()
    }
    return {"files": len(files), "sha256": _digest(files)}


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_every_text_scaffold_byte_matches_the_parent(mode):
    assert len(CATALOG["recipes"]) == 100
    assert _text_fingerprint(mode) == GOLDEN["text"][mode]


@pytest.fixture(scope="module")
def image_build(tmp_path_factory):
    """Execute a normal full build, with real drawings, asset IO and serialization.

    Patch public dependencies before importing the generated script, so imports by name
    are observed too. Counters wrap the real functions and never substitute their output.
    The counts end when main() returns; verification afterwards does not inflate them.
    """
    folder = tmp_path_factory.mktemp("image-build-work")
    recipe = next(row for row in CATALOG["recipes"] if row["rank"] == 77)
    for name, text in new_recipe.files_for(CATALOG, recipe, "replay-images").items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    counts = {name: Counter() for name in ("draws", "keys", "loads", "encodes")}
    original_draw = si.login_screen
    original_key = jev_cookbook.replay_key
    original_load = vision.image_asset
    original_encode = vision.base64.b64encode

    def draw(*args, **kwargs):
        counts["draws"][_digest([args, kwargs])] += 1
        return original_draw(*args, **kwargs)

    def key(*args, **kwargs):
        result = original_key(*args, **kwargs)
        counts["keys"][result] += 1
        return result

    def load(path, **kwargs):
        counts["loads"][str(path)] += 1
        return original_load(path, **kwargs)

    def encode(data, *args, **kwargs):
        counts["encodes"][hashlib.sha256(data).hexdigest()] += 1
        return original_encode(data, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(si, "login_screen", draw)
        patch.setattr(jev_cookbook, "replay_key", key)
        patch.setattr(vision, "image_asset", load)
        # synthetic_images also base64-encodes PNG bytes for its independent
        # byte-policy validation. Instrument the vision loader's encoding only.
        patch.setattr(
            vision, "base64", types.SimpleNamespace(**{**vars(vision.base64), "b64encode": encode})
        )
        module = _load(folder / "build_fixtures.py", "image_efficiency_generated_build")
        patch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
        module.main()
    return folder, counts


def test_a_full_image_build_draws_each_row_once(image_build):
    _, counts = image_build
    assert len(counts["draws"]) == 14
    assert counts["draws"].total() == 14, counts["draws"]


def test_a_full_image_build_computes_each_replay_key_once(image_build):
    _, counts = image_build
    assert len(counts["keys"]) == 14
    assert counts["keys"].total() == 14, counts["keys"]


def test_a_full_image_build_loads_and_base64_encodes_each_image_once(image_build):
    _, counts = image_build
    assert len(counts["loads"]) == len(counts["encodes"]) == 14
    # Check both counts together, so failures expose real IO and base64 work separately.
    actual = {name: counts[name].total() for name in ("loads", "encodes")}
    assert actual == {"loads": 14, "encodes": 14}


def _image_fingerprints(folder):
    raw = {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in folder.rglob("*")
        if path.is_file()
        and (
            path.parent.name == "fixtures"
            or path.suffix == ".png"
            or path.name == "assets-manifest.json"
        )
    }
    pixels = {}
    for path in (folder / "assets").glob("*.png"):
        with Image.open(path) as picture:
            pixels[path.relative_to(folder).as_posix()] = si.pixels_sha256(picture)
    inputs = [
        json.loads(line)
        for line in (folder / "fixtures/inputs.jsonl").read_text("utf-8").splitlines()
    ]
    key_to_id = {row["replay_keys"][0]: row["id"] for row in inputs}
    responses = json.loads((folder / "fixtures/responses.json").read_text("utf-8"))
    assert len(inputs) == len(key_to_id) == len(responses) == len(pixels) == 14
    assert set(key_to_id) == set(responses)
    # Keys and hashes depend on PNG encoding; preserve their relationships on every
    # platform and compare all other content plus decoded pixels against the parent.
    helpers = jev_cookbook.load_helpers(folder)
    questions = helpers.build_questions()
    for row in inputs:
        state, assets = helpers.build_request(row["fields"])
        assert row["replay_keys"] == [jev_cookbook.replay_key(state, questions, assets=assets)]
        row["replay_keys"] = [key_to_id[key] for key in row["replay_keys"]]
    manifest = json.loads((folder / "assets-manifest.json").read_text("utf-8"))
    for entry in manifest["assets"]:
        assert entry.pop("sha256") == raw[entry["path"]]
    semantic = {
        "inputs": inputs,
        "labels": (folder / "fixtures/labels.jsonl").read_text("utf-8"),
        "responses": {key_to_id[key]: value for key, value in responses.items()},
        "manifest": manifest,
        "pixels": pixels,
    }
    return {
        "canonical_files": len(raw),
        "canonical_sha256": _digest(raw),
        "semantic_sha256": _digest(semantic),
    }


def test_the_image_build_preserves_parent_fixtures_manifest_and_pixels(image_build):
    folder, _ = image_build
    actual = _image_fingerprints(folder)
    expected = GOLDEN["images"]
    assert actual["semantic_sha256"] == expected["semantic_sha256"]
    assert actual["canonical_files"] == expected["canonical_files"]
    if not si.bytes_are_canonical():
        pytest.skip(
            "semantic digest checked; canonical PNG byte digest needs the Linux notebook pin "
            "(Pillow 12.3.0, classic zlib)"
        )
    assert actual["canonical_sha256"] == expected["canonical_sha256"]


@pytest.mark.parametrize("kind", ["label", "answer", "manifest"])
def test_preservation_control_detects_changed_image_content(image_build, tmp_path, kind):
    """An altered gold rectangle, probability or provenance must fail preservation."""
    import shutil

    source, _ = image_build
    folder = tmp_path / "changed"
    shutil.copytree(source, folder)
    if kind == "label":
        path = folder / "fixtures/labels.jsonl"
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        rows[0]["label"] = {"present": False}
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    elif kind == "answer":
        path = folder / "fixtures/responses.json"
        data = json.loads(path.read_text("utf-8"))
        next(iter(data.values()))["model"] = "changed-synthetic-control"
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path = folder / "assets-manifest.json"
        data = json.loads(path.read_text("utf-8"))
        data["assets"][0]["description"] = "Changed synthetic provenance control."
        path.write_text(json.dumps(data), encoding="utf-8")
    assert _image_fingerprints(folder)["semantic_sha256"] != GOLDEN["images"]["semantic_sha256"]


def test_a_second_main_uses_the_new_saved_image_for_inputs_and_responses(
    image_build, tmp_path, monkeypatch
):
    """The same imported module must not retain drawings or keys across invocations."""
    import shutil

    source, _ = image_build
    folder = tmp_path / "freshness"
    shutil.copytree(source, folder)
    module = _load(folder / "build_fixtures.py", "image_efficiency_freshness_build")
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    module.main()
    first_inputs = [
        json.loads(line)
        for line in (folder / "fixtures/inputs.jsonl").read_text("utf-8").splitlines()
    ]
    first_key = first_inputs[0]["replay_keys"][0]
    picture = folder / first_inputs[0]["fields"]["image"]
    first_bytes = picture.read_bytes()
    changed = list(module.ROWS[0])
    changed[4] += 1234567  # another deterministic drawing seed, same scene and objects
    module.ROWS[0] = tuple(changed)
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py"), "--overwrite-assets"])
    module.main()
    assert picture.read_bytes() != first_bytes
    second_inputs = [
        json.loads(line)
        for line in (folder / "fixtures/inputs.jsonl").read_text("utf-8").splitlines()
    ]
    helpers = jev_cookbook.load_helpers(folder)
    state, assets = helpers.build_request(second_inputs[0]["fields"])
    second_key = jev_cookbook.replay_key(state, helpers.build_questions(), assets=assets)
    responses = json.loads((folder / "fixtures/responses.json").read_text("utf-8"))
    assert second_inputs[0]["replay_keys"] == [second_key]
    assert second_key != first_key and second_key in responses and first_key not in responses


def test_the_answers_for_hook_controls_main_and_standalone_responses(
    image_build, tmp_path, monkeypatch
):
    """A recipe author's documented answer customization must reach both writers."""
    import shutil
    from dataclasses import replace

    source, _ = image_build
    folder = tmp_path / "custom-answers"
    shutil.copytree(source, folder)
    module = _load(folder / "build_fixtures.py", "image_efficiency_answer_hook_build")
    expected = json.loads((folder / "fixtures/responses.json").read_text("utf-8"))
    assert len(expected) == 14
    for response in expected.values():
        assert response["answers"]["present"]["noul"] != 0.123
        response["answers"]["present"]["noul"] = 0.123
    original = module.answers_for

    def customized_answers_for(row, provenance, **kwargs):
        answers = original(row, provenance, **kwargs)
        answers["present"] = replace(answers["present"], noul=0.123)
        return answers

    monkeypatch.setattr(module, "answers_for", customized_answers_for)
    monkeypatch.setattr(sys, "argv", [str(folder / "build_fixtures.py")])
    module.main()
    saved = json.loads((folder / "fixtures/responses.json").read_text("utf-8"))
    standalone = module.build_responses(module.ROWS)
    assert saved == expected
    assert standalone == expected
