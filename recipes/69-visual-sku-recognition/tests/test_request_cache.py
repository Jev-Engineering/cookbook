"""Exercise the notebook's actual cache against changing requests and a real replay backend."""

import ast
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import Choice, load_helpers, replay_key
from jev_cookbook.backends import ReplayBackend, ReplayMiss
from jev_cookbook.fixtures import load_inputs, responses_path
from jev_cookbook.vision import image_asset

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


class CountingReplay:
    """Count real replay attempts, including misses, without any live inference."""

    def __init__(self):
        self.backend = ReplayBackend.from_json(responses_path(RECIPE))
        self.keys = []

    def decide(self, state, questions, *, assets):
        self.keys.append(replay_key(state, questions, assets=assets))
        return self.backend.decide(state, questions, assets=assets)


def notebook_cache(builder, backend):
    """Compile only the committed decide function; execute neither setup nor live selection."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    setup = next(cell for cell in notebook["cells"] if cell["id"] == "setup")
    tree = ast.parse("".join(setup["source"]))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "decide"
    )
    module = ast.Module(body=[function], type_ignores=[])
    results = {}
    namespace = {
        "helpers": SimpleNamespace(build_request=builder),
        "backend": backend,
        "results": results,
        "replay_key": replay_key,
    }
    exec(compile(module, "<notebook decide>", "exec"), namespace)
    return namespace["decide"], results


def test_identical_requests_reuse_one_decision_even_when_example_ids_differ():
    original = load_inputs(RECIPE)[0]
    duplicate = SimpleNamespace(id="another-bookkeeping-id", fields=dict(original.fields))
    backend = CountingReplay()
    decide, results = notebook_cache(helpers.build_request, backend)
    answer = decide(original)
    assert decide(original) is answer
    assert decide(duplicate) is answer
    assert len(backend.keys) == 1
    state, questions, assets = helpers.build_request(original.fields)
    assert set(results) == {replay_key(state, questions, assets=assets)}


@pytest.mark.parametrize(
    "change",
    ["query_pixels", "reference_pixels", "state_context", "question_context", "asset_bytes"],
)
def test_changed_evidence_under_the_same_id_cannot_reuse_an_accepted_answer(tmp_path, change):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    example = load_inputs(RECIPE)[0]
    original_request = helpers.build_request(example.fields, root=tmp_path)
    changed_context = False

    def builder(fields):
        state, questions, assets = helpers.build_request(fields, root=tmp_path)
        if changed_context and change == "state_context":
            state = {**state, "inspection_context": "Identify the visible front-facing variant."}
        elif changed_context and change == "question_context":
            current = questions["sku"]
            questions = {
                "sku": Choice(
                    instructions=current.instructions + " Treat a missing label as unknown.",
                    criteria=current.criteria,
                )
            }
        elif changed_context and change == "asset_bytes":
            # References may be arbitrary opaque names in the backend contract. Hold the
            # name/state/question fixed here to ensure the cache includes the bytes too.
            original_state, original_questions, original_assets = original_request
            assets = {
                **original_assets,
                original_state["query_image"]: image_asset(tmp_path / fields["image"]),
            }
            state, questions = original_state, original_questions
        return state, questions, assets

    backend = CountingReplay()
    decide, results = notebook_cache(builder, backend)
    answer = decide(example)
    assert helpers.classify(example.id, answer, 0.7).outcome == helpers.ACCEPTED
    assert decide(example) is answer
    assert len(backend.keys) == 1

    if change in {"query_pixels", "reference_pixels", "asset_bytes"}:
        relative = (
            next(iter(helpers.CATALOG.values()))
            if change == "reference_pixels"
            else example.fields["image"]
        )
        path = tmp_path / relative
        with Image.open(path) as image:
            changed = image.convert("RGB")
        red, green, blue = changed.getpixel((0, 0))
        changed.putpixel((0, 0), ((red + 1) % 256, green, blue))
        changed.save(path)
    changed_context = True

    # Replaying edited evidence must fail closed, not return the old accepted SKU.
    with pytest.raises(ReplayMiss):
        decide(example)
    assert len(backend.keys) == 2
    assert backend.keys[0] != backend.keys[1]
    assert set(results) == {backend.keys[0]}
    with pytest.raises(ReplayMiss):
        decide(example)
    assert backend.keys[2] == backend.keys[1]
    assert len(results) == 1
