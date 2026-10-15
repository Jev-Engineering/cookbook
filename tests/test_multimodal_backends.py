"""Image contracts and Box answers; every image and response here is synthetic."""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import (
    Box,
    BoxAnswer,
    BudgetExceeded,
    DecisionResult,
    FixtureError,
    LiveBackend,
    LiveConfigError,
    LiveResponseError,
    Noul,
    NoulAnswer,
    Provenance,
    ReplayBackend,
    ReplayMiss,
    ScriptedBackend,
    answer_from_dict,
    get_backend,
    question_from_dict,
    record,
    replay_key,
)
from jev_cookbook import live as live_module

REF = "image-fixture-main"
STATE = {"photo": REF}
QUESTIONS = {"target": Box(instructions="The pink rectangle in `photo`.")}
EDGES = {"top": 0.1, "bottom": 0.6, "left": 0.2, "right": 0.8}
SYNTHETIC = Provenance.synthetic()


def image_assets(color="pink", fmt="PNG", size=(280, 280)):
    data = io.BytesIO()
    Image.new("RGB", size, color).save(data, format=fmt)
    return {
        REF: {
            "type": "image",
            "format": "png" if fmt == "PNG" else "jpeg",
            "data_base64": base64.b64encode(data.getvalue()).decode("ascii"),
        }
    }


def box_result(confidence=0.9):
    return DecisionResult({"target": BoxAnswer(EDGES, confidence, SYNTHETIC)}, "synthetic")


def response(confidence=0.9):
    return {
        "model": "jev-1.14.0",
        "answers": {"target": {"type": "box", "box": dict(EDGES), "confidence": confidence}},
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


class Client:
    def __init__(self, body=None):
        self.body = body or response()
        self.calls = []

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        return self.body


@pytest.fixture
def fake_sdk(monkeypatch):
    # The SDK is optional for all offline and fake-client tests.
    monkeypatch.setattr(
        live_module, "_import_sdk", lambda: SimpleNamespace(Image=lambda data: data)
    )


def test_box_question_has_no_criteria():
    assert question_from_dict(QUESTIONS["target"].to_dict()) == QUESTIONS["target"]
    assert "criteria" not in QUESTIONS["target"].to_dict()
    with pytest.raises(TypeError):
        Box(criteria={})
    with pytest.raises(ValueError, match="unknown question keys"):
        question_from_dict({"type": "box", "instructions": "Find it.", "criteria": None})


@pytest.mark.parametrize("confidence", [None, 0, 0.75, 1])
def test_box_round_trip_and_unknown_confidence(confidence):
    answer = BoxAnswer(EDGES, confidence, SYNTHETIC)
    restored = answer_from_dict(answer.to_dict())
    assert restored == answer
    if confidence is None:
        del (stored := answer.to_dict())["confidence"]
        assert answer_from_dict(stored).confidence is None
    assert box_result(confidence).boxes == {"target": answer}


@pytest.mark.parametrize("bad", [True, "0.2", float("nan"), float("inf"), -0.01, 1.01])
def test_box_rejects_bad_coordinates_and_confidence(bad):
    with pytest.raises(ValueError):
        BoxAnswer({**EDGES, "top": bad}, 0.9, SYNTHETIC)
    with pytest.raises(ValueError):
        BoxAnswer(EDGES, bad, SYNTHETIC)


@pytest.mark.parametrize(
    "edges",
    [
        {**EDGES, "left": 0.8},
        {**EDGES, "top": 0.6},
        {**EDGES, "right": 0.1},
        {k: v for k, v in EDGES.items() if k != "top"},
        {**EDGES, "width": 0.6},
    ],
)
def test_box_requires_complete_positive_geometry(edges):
    with pytest.raises(ValueError):
        BoxAnswer(edges, 0.9, SYNTHETIC)


def test_box_coordinates_are_defensively_copied():
    edges = dict(EDGES)
    answer = BoxAnswer(edges, None, SYNTHETIC)
    edges["left"] = 1.0
    answer.to_dict()["box"]["left"] = 1.0
    assert answer.box == EDGES
    with pytest.raises(TypeError):
        answer.box["left"] = 0.3


def test_asset_content_changes_keys_but_empty_assets_preserve_text_keys():
    questions = {"visible": Noul(instructions="The target is visible.")}
    expected = replay_key("ordinary text", questions)
    assert replay_key("ordinary text", questions, assets=None) == expected
    assert replay_key("ordinary text", questions, assets={}) == expected
    pink, blue = image_assets(), image_assets("blue")
    assert replay_key(STATE, QUESTIONS, assets=pink) != replay_key(STATE, QUESTIONS, assets=blue)
    replay = ReplayBackend({replay_key(STATE, QUESTIONS, assets=pink): box_result().to_dict()})
    assert replay.decide(STATE, QUESTIONS, assets=pink) == box_result()
    with pytest.raises(ReplayMiss):
        replay.decide(STATE, QUESTIONS, assets=blue)
    with pytest.raises(ValueError, match="requires at least one image"):
        replay.decide(STATE, QUESTIONS)
    text_result = DecisionResult({"visible": NoulAnswer(0.9, SYNTHETIC)}, "synthetic")
    replay = ReplayBackend({replay_key(STATE, questions, assets=pink): text_result.to_dict()})
    with pytest.raises(ReplayMiss):
        replay.decide(STATE, questions)


def test_asset_order_is_stable_and_image_refs_work_only_in_values():
    assets = image_assets()
    assets["image-reference-other"] = image_assets("blue")[REF]
    questions = {
        "visible": Noul(
            instructions=f"Compare {REF} to image-reference-other.",
            criteria={"true": {"examples": [REF]}, "false": "different"},
        )
    }
    key = replay_key("state text", questions, assets=assets)
    assert key == replay_key("state text", questions, assets=dict(reversed(list(assets.items()))))
    with pytest.raises(ValueError, match="not referenced"):
        replay_key({REF: "text"}, {"n": Noul()}, assets=image_assets())
    with pytest.raises(ValueError, match="not referenced"):
        replay_key("text", {REF: Noul()}, assets=image_assets())


@pytest.mark.parametrize(
    "change",
    [
        {"type": "audio"},
        {"format": "gif"},
        {"format": "jpg"},
        {"data_base64": "not base64"},
        {"data_base64": ""},
        {"data_base64": base64.b64encode(b"not an image").decode()},
        {"part": "file"},
    ],
)
def test_invalid_assets_are_rejected(change):
    assets = image_assets()
    assets[REF].update(change)
    with pytest.raises((ValueError, TypeError)):
        replay_key(STATE, QUESTIONS, assets=assets)


def test_image_dimensions_and_reference_limits():
    with pytest.raises(ValueError):
        replay_key(STATE, QUESTIONS, assets=image_assets(size=(256, 256)))
    for ref in ["", " ", "x" * 1025, "🖼" * 257]:
        with pytest.raises(ValueError):
            replay_key(ref, {"n": Noul()}, assets={ref: image_assets()[REF]})
    with pytest.raises(TypeError, match="assets must be a mapping"):
        replay_key(STATE, QUESTIONS, assets=[])


def test_scripted_box_and_mismatched_answers():
    assets = image_assets()
    backend = ScriptedBackend(lambda state, questions, rng: box_result().answers)
    assert backend.decide(STATE, QUESTIONS, assets=assets) == box_result()
    assert (
        backend.rng_for(STATE, QUESTIONS, assets=assets).random()
        != backend.rng_for(STATE, QUESTIONS, assets=image_assets("blue")).random()
    )
    wrong = DecisionResult({"target": NoulAnswer(0.9, SYNTHETIC)}, "synthetic")
    replay = ReplayBackend({replay_key(STATE, QUESTIONS, assets=assets): wrong.to_dict()})
    with pytest.raises(FixtureError, match="box but the stored answer is noul"):
        replay.decide(STATE, QUESTIONS, assets=assets)
    with pytest.raises(ValueError, match="Box script must return"):
        ScriptedBackend(lambda *args: {"target": EDGES}).decide(STATE, QUESTIONS, assets=assets)


def test_offline_model_and_experimental_options_do_not_change_mode(monkeypatch):
    monkeypatch.delenv("JEV_COOKBOOK_LIVE", raising=False)
    assets = image_assets()
    backend = get_backend(
        fixtures={replay_key(STATE, QUESTIONS, assets=assets): box_result().to_dict()},
        model="jev-1.14.0",
        images=True,
        long_context=True,
    )
    assert backend.mode == "synthetic" and backend.model == "synthetic"
    assert backend.decide(STATE, QUESTIONS, assets=assets) == box_result()


def test_live_headers_sdk_conversion_and_budget(fake_sdk):
    client = Client()
    assets = image_assets()
    backend = LiveBackend(
        "jev-1.14.0", client=client, images=True, long_context=True, max_requests=1
    )
    result = backend.decide(STATE, QUESTIONS, assets=assets)
    assert result["target"].box == EDGES and result.source == "recorded"
    sent = client.calls[0]
    assert sent["extra_headers"] == {
        "TypeSafe-Danger-Zone-Images": "true",
        "TypeSafe-Danger-Zone-Long-Context": "true",
    }
    assert sent["assets"] == {REF: base64.b64decode(assets[REF]["data_base64"])}
    assert sent["state"] == STATE and sent["questions"]["target"] == QUESTIONS["target"].to_dict()
    assert sent["model"] == "jev-1.14.0"
    assert backend.records[0].replay_key == replay_key(STATE, QUESTIONS, assets=assets)
    with pytest.raises(BudgetExceeded):
        backend.decide(STATE, QUESTIONS, assets=assets)
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "model,images", [("jev-1.13.0", True), ("jev-latest", True), ("jev-1.14.0", False)]
)
def test_unsupported_live_box_rejected_before_spending(model, images):
    client = Client()
    backend = LiveBackend(model, client=client, images=images)
    with pytest.raises(LiveConfigError):
        backend.decide(STATE, QUESTIONS, assets=image_assets())
    assert backend.requests_made == 0 and client.calls == []


@pytest.mark.parametrize("confidence", [None, 0.0, "absent"])
def test_live_missing_confidence_is_never_promoted_to_certainty(fake_sdk, confidence):
    body = response(confidence)
    if confidence == "absent":
        del body["answers"]["target"]["confidence"]
    backend = LiveBackend("jev-preview", client=Client(body), images=True)
    answer = backend.decide(STATE, QUESTIONS, assets=image_assets())["target"]
    assert answer.confidence == (None if confidence == "absent" else confidence)


def test_absent_target_still_returns_box_and_requires_a_separate_presence_gate(fake_sdk):
    body = response(None)
    body["answers"]["present"] = {"type": "noul", "noul": 0.01}
    backend = LiveBackend("jev-1.14.0", client=Client(body), images=True)
    result = backend.decide(
        STATE,
        {**QUESTIONS, "present": Noul(instructions="The target is present.")},
        assets=image_assets(),
    )
    assert result["present"].noul < 0.5
    assert result["target"].confidence is None and result["target"].box == EDGES


def test_invalid_live_box_is_counted_and_never_recorded(fake_sdk):
    body = response()
    body["answers"]["target"]["box"]["left"] = 0.9
    backend = LiveBackend("jev-1.14.0", client=Client(body), images=True)
    with pytest.raises(LiveResponseError, match="left < right"):
        backend.decide(STATE, QUESTIONS, assets=image_assets())
    assert backend.requests_made == 1 and backend.records == ()


def test_recording_distinguishes_assets_and_replays_them(fake_sdk, tmp_path):
    pink, blue = image_assets(), image_assets("blue")
    requests = [(STATE, QUESTIONS, pink), (STATE, QUESTIONS, blue)]
    backend = LiveBackend("jev-1.14.0", client=Client(), images=True)
    path, ledger = tmp_path / "responses.json", tmp_path / "ledger.json"
    report = record(backend, requests, path, ledger_path=ledger)
    assert report.requests == 2 and len(report.written) == 2
    assert set(json.loads(ledger.read_text())) == set(report.written)
    replay = ReplayBackend.from_json(path)
    for assets in (pink, blue):
        assert replay.decide(STATE, QUESTIONS, assets=assets)["target"].box == EDGES
    assert record(backend, requests, path).requests == 0
    assert backend.requests_made == 2


def test_image_metadata_fixtures_validate_box_answers(tmp_path):
    from jev_cookbook.fixtures import load_inputs, validate_recipe

    folder = tmp_path / "fixtures"
    folder.mkdir()
    (tmp_path / "assets").mkdir()
    inputs, labels, responses = [], [], {}
    for ident, split, color in [("v01", "validation", "pink"), ("t01", "test", "blue")]:
        assets = image_assets(color)
        relative = f"assets/{ident}.png"
        (tmp_path / relative).write_bytes(base64.b64decode(assets[REF]["data_base64"]))
        key = replay_key(STATE, QUESTIONS, assets=assets)
        inputs.append(
            {"id": ident, "split": split, "fields": {"image": relative}, "replay_keys": [key]}
        )
        labels.append({"id": ident, "label": {"present": True, "box": EDGES}})
        responses[key] = box_result(None).to_dict()
    (folder / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in inputs))
    (folder / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels))
    (folder / "responses.json").write_text(json.dumps(responses))
    assert validate_recipe(tmp_path) == []
    examples = load_inputs(tmp_path)
    assert examples[0].fields["image"] == "assets/v01.png"
    responses[examples[0].replay_keys[0]]["answers"]["target"]["box"]["left"] = 1.0
    (folder / "responses.json").write_text(json.dumps(responses))
    assert any("left < right" in str(problem) for problem in validate_recipe(tmp_path))
