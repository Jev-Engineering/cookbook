"""The notebook must consult current evidence before reusing an accepted identity."""

import ast
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import ReplayMiss, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, responses_path

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


class CountingReplay:
    def __init__(self):
        self.backend = get_backend(fixtures=responses_path(RECIPE))
        self.keys = []

    def decide(self, state, questions, *, assets):
        self.keys.append(replay_key(state, questions, assets=assets))
        return self.backend.decide(state, questions, assets=assets)


def notebook_result_for(backend, cache):
    """Exercise the committed notebook's actual lookup function, not a test reimplementation."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    cell = next(c for c in notebook["cells"] if c["id"] == "setup")
    tree = ast.parse("".join(cell["source"]))
    function = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "result_for"
    )
    namespace = {"backend": backend, "results": cache, "helpers": helpers}
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "notebook_lookup", "exec"), namespace
    )
    return namespace["result_for"]


@pytest.mark.parametrize("change", ["query_pixels", "reference_pixels", "context"])
def test_same_id_with_changed_evidence_cannot_return_a_cached_accepted_answer(
    change, tmp_path, monkeypatch
):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    monkeypatch.chdir(tmp_path)
    example = next(e for e in load_inputs(RECIPE) if e.id == "d01")
    backend, cache = CountingReplay(), {}
    result_for = notebook_result_for(backend, cache)
    first = result_for(example)
    assert helpers.route(example.id, first["piece"], 0.7).outcome == "bridge_tile"
    assert result_for(example) is first
    assert len(backend.keys) == len(cache) == 1
    assert set(cache) == set(backend.keys)

    if change == "context":
        original = helpers.build_request

        def changed_context(fields, recipe_dir=Path(".")):
            state, questions, assets = original(fields, recipe_dir)
            return {**state, "view_context": "oblique tabletop view"}, questions, assets

        monkeypatch.setattr(helpers, "build_request", changed_context)
    else:
        relative = (
            example.fields["crop"] if change == "query_pixels" else helpers.CATALOG["bridge_tile"]
        )
        path = tmp_path / relative
        with Image.open(path) as image:
            edited = image.copy()
        red, green, blue = edited.getpixel((0, 0))
        edited.putpixel((0, 0), ((red + 1) % 256, green, blue))
        edited.save(path)

    # A changed request has no stored answer. Returning the old accepted result would fail.
    with pytest.raises(ReplayMiss):
        result_for(example)
    assert len(backend.keys) == 2
    assert backend.keys[0] != backend.keys[1]
    assert len(cache) == 1
    with pytest.raises(ReplayMiss):
        result_for(example)
    assert len(backend.keys) == 3


def test_unchanged_evidence_keeps_26_requests_and_identity_does_not_control_cache(monkeypatch):
    monkeypatch.chdir(RECIPE)
    backend, cache = CountingReplay(), {}
    result_for = notebook_result_for(backend, cache)
    examples = load_inputs(RECIPE)
    for example in examples:
        result = result_for(example)
        assert result_for(example) is result
        renamed = SimpleNamespace(id="another-python-id", fields=example.fields)
        assert result_for(renamed) is result
    assert len(cache) == len(backend.keys) == len(examples) == 26
