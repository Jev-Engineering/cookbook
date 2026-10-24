"""Exercise the notebook's actual cache with changed evidence and a counting replay backend."""

import ast
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import Noul, ReplayMiss, get_backend, load_helpers, replay_key
from jev_cookbook.fixtures import load_inputs, responses_path
from jev_cookbook.vision import run_record

RECIPE = Path(__file__).resolve().parent.parent
helpers = load_helpers(RECIPE)


class CountingReplay:
    mode = "synthetic"

    def __init__(self):
        self.backend = get_backend(fixtures=responses_path(RECIPE))
        self.calls = 0

    def decide(self, state, questions, *, assets):
        self.calls += 1
        return self.backend.decide(state, questions, assets=assets)


def notebook_cache():
    """Run the committed functions themselves, without executing setup or duplicating their code."""
    notebook = json.loads((RECIPE / "notebook.ipynb").read_text("utf-8"))
    setup = next(cell for cell in notebook["cells"] if cell["id"] == "setup")
    tree = ast.parse("".join(setup["source"]))
    functions = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef)], type_ignores=[]
    )
    namespace = {
        "helpers": helpers,
        "questions": helpers.build_questions(),
        "backend": CountingReplay(),
        "results": {},
        "measurements": {},
        "evaluated_keys": {},
        "replay_key": replay_key,
        "perf_counter": perf_counter,
        "run_record": run_record,
    }
    exec(compile(functions, "recipe62-notebook-setup", "exec"), namespace)
    return namespace


def copied_example(tmp_path, *, ident="v02"):
    example = next(e for e in load_inputs(RECIPE) if e.id == ident)
    fields = dict(example.fields)
    for side in ("before", "after"):
        destination = tmp_path / f"{side}.png"
        destination.write_bytes((RECIPE / fields[f"{side}_path"]).read_bytes())
        fields[f"{side}_path"] = destination.name
    return SimpleNamespace(id=example.id, fields=fields)


def change_pixel(path):
    with Image.open(path) as stored:
        changed = stored.convert("RGB")
    red, green, blue = changed.getpixel((0, 0))
    changed.putpixel((0, 0), (red ^ 255, green, blue))
    changed.save(path)


@pytest.mark.parametrize("change", ["before", "after", "context", "questions"])
def test_same_id_cannot_reuse_an_accepted_judgment_after_evidence_changes(
    tmp_path, monkeypatch, change
):
    example = copied_example(tmp_path)
    monkeypatch.chdir(tmp_path)
    cache = notebook_cache()
    original = cache["decide"](example)
    assert helpers.route(helpers.assess(original), 0.75).outcome == "clear"
    original_key = cache["request_for"](example)[2]
    cache["evaluated_keys"][example.id] = original_key
    assert cache["evaluated_result"](example) is original
    assert cache["decide"](example) is original
    assert cache["backend"].calls == 1

    if change in ("before", "after"):
        change_pixel(tmp_path / example.fields[f"{change}_path"])
    elif change == "context":
        monkeypatch.setattr(helpers, "POLICY", helpers.POLICY + " Require the original accent.")
    else:
        cache["questions"]["missing"] = Noul(instructions="The main action is absent after.")

    assert cache["request_for"](example)[2] != original_key
    with pytest.raises(ReplayMiss):
        cache["decide"](example)
    assert cache["backend"].calls == 2
    assert cache["results"] == {original_key: original}
    assert set(cache["measurements"]) == {original_key}
    with pytest.raises(KeyError):
        cache["measurement_for"](example)
    with pytest.raises(ValueError, match="rerun evaluation"):
        cache["evaluated_result"](example)


def test_identical_requests_across_ids_share_one_result_and_measurement(tmp_path, monkeypatch):
    example = copied_example(tmp_path)
    monkeypatch.chdir(tmp_path)
    cache = notebook_cache()
    first = cache["decide"](example)
    renamed = SimpleNamespace(id="different-bookkeeping-id", fields=dict(example.fields))
    assert cache["decide"](renamed) is first
    key = cache["request_for"](renamed)[2]
    assert cache["backend"].calls == 1
    assert set(cache["results"]) == set(cache["measurements"]) == {key}
    assert cache["measurement_for"](renamed) == cache["measurement_for"](example)


def test_new_valid_evidence_gets_a_new_answer_without_relabelling_an_old_evaluation(monkeypatch):
    monkeypatch.chdir(RECIPE)
    examples = {example.id: example for example in load_inputs(RECIPE)}
    original = SimpleNamespace(id="unchanged-id", fields=examples["v02"].fields)
    replacement = SimpleNamespace(id=original.id, fields=examples["v05"].fields)
    cache = notebook_cache()
    clear = cache["decide"](original)
    cache["evaluated_keys"][original.id] = cache["request_for"](original)[2]
    flagged = cache["decide"](replacement)
    assert helpers.route(helpers.assess(clear), 0.75).outcome == "clear"
    assert helpers.route(helpers.assess(flagged), 0.75).outcome == "flag"
    assert cache["backend"].calls == 2
    assert len(cache["results"]) == len(cache["measurements"]) == 2
    with pytest.raises(ValueError, match="rerun evaluation"):
        cache["evaluated_result"](replacement)


@pytest.mark.parametrize("side", ["before", "after"])
def test_shared_reference_cannot_hide_a_changed_image(tmp_path, monkeypatch, side):
    example = copied_example(tmp_path, ident="v01")
    assert example.fields["before_ref"] == example.fields["after_ref"]
    monkeypatch.chdir(tmp_path)
    cache = notebook_cache()
    original = cache["decide"](example)
    assert helpers.route(helpers.assess(original), 0.75).outcome == "clear"
    change_pixel(tmp_path / example.fields[f"{side}_path"])
    with pytest.raises(ValueError, match="different before/after content"):
        cache["decide"](example)
    assert cache["backend"].calls == 1
    assert len(cache["results"]) == len(cache["measurements"]) == 1


def test_repeated_fixture_reports_keep_the_documented_26_request_budget(monkeypatch):
    monkeypatch.chdir(RECIPE)
    cache = notebook_cache()
    examples = load_inputs(RECIPE)
    for example in examples:
        result = cache["decide"](example)
        assert cache["decide"](example) is result
        cache["measurement_for"](example)
    assert cache["backend"].calls == 26
    assert len(cache["results"]) == len(cache["measurements"]) == 26
    assert all(row["input_tokens"] is None for row in cache["measurements"].values())
