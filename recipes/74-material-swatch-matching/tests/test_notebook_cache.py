"""Exercise the notebook's actual cache function against changed evidence."""

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
        self.requests = []

    def decide(self, state, questions, *, assets):
        self.requests.append(replay_key(state, questions, assets=assets))
        return self.backend.decide(state, questions, assets=assets)


def notebook_decider(root):
    """Compile production setup bindings/function, without executing notebook inference."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    setup = next(c for c in notebook["cells"] if c["id"] == "setup")
    tree = ast.parse("".join(setup["source"]))
    selected = [
        node
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name == "decide")
        or (
            isinstance(node, ast.Assign)
            and any(isinstance(n, ast.Name) and n.id == "results" for n in ast.walk(node))
        )
    ]
    assert any(isinstance(node, ast.FunctionDef) for node in selected)
    context = {}

    def current_request(fields):
        state, questions, assets = helpers.build_request(fields, root)
        return {**state, **context}, questions, assets

    backend = CountingReplay()
    namespace = {
        "helpers": SimpleNamespace(build_request=current_request),
        "backend": backend,
        "replay_key": replay_key,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "notebook-cache", "exec"), namespace)
    return namespace, backend, context


@pytest.mark.parametrize("changed", ["query", "reference", "context"])
def test_same_example_id_rebuilds_request_before_cache_lookup(tmp_path, changed):
    shutil.copytree(RECIPE / "assets", tmp_path / "assets")
    namespace, backend, context = notebook_decider(tmp_path)
    decide = namespace["decide"]
    example = next(e for e in load_inputs(RECIPE) if e.id == "d01")
    first = decide(example)
    assert helpers.route(first, 0.8).outcome == "accepted"
    assert decide(example) is first
    assert len(backend.requests) == 1

    if changed == "context":
        context["task"] = "Match only exact illumination and orientation."
    else:
        path = tmp_path / (
            example.fields["image"] if changed == "query" else "assets/reference-28.png"
        )
        with Image.open(path) as source:
            image = source.copy()
        image.putpixel((0, 0), (255, 0, 0))
        image.save(path)

    with pytest.raises(ReplayMiss):
        decide(example)
    assert len(backend.requests) == 2
    assert backend.requests[0] != backend.requests[1]
    assert example.id not in namespace["answers"]
    assert example.id not in namespace["result_keys"]
    assert len(namespace["results"]) == 1
    assert set(namespace["results"]) == {backend.requests[0]}


def test_unchanged_requests_share_cache_across_ids_and_preserve_26_call_budget():
    namespace, backend, _ = notebook_decider(RECIPE)
    decide = namespace["decide"]
    examples = load_inputs(RECIPE)
    for example in examples:
        first = decide(example)
        assert decide(example) is first
    assert len(backend.requests) == 26
    assert len(namespace["results"]) == 26
    alias = SimpleNamespace(id="same-evidence-another-id", fields=examples[0].fields)
    assert decide(alias) is namespace["answers"][examples[0].id]
    assert len(backend.requests) == 26
