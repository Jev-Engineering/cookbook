"""Image contracts and Box answers; every image and response here is synthetic."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import string
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
PINNED_TEXT_KEY = "a2cdafc0867c6aaf2f2d9631f13c22d1ef7467c797834ead9558b224cb5d56ce"


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


def test_image_format_spelling_does_not_change_the_replay_key():
    jpeg = image_assets(fmt="JPEG")
    keys = {}
    for spelling in ("jpeg", "jpg", "JPEG", "JPG", "Jpeg"):
        keys[spelling] = replay_key(
            STATE, QUESTIONS, assets={REF: {**jpeg[REF], "format": spelling}}
        )
    assert len(set(keys.values())) == 1, keys
    png = image_assets()
    assert replay_key(STATE, QUESTIONS, assets={REF: {**png[REF], "format": "PNG"}}) == replay_key(
        STATE, QUESTIONS, assets=png
    )
    # A genuinely different format (other bytes) or other bytes of the same format is another key.
    assert replay_key(STATE, QUESTIONS, assets=png) != keys["jpeg"]
    other = image_assets("blue", fmt="JPEG")
    assert replay_key(STATE, QUESTIONS, assets=other) != keys["jpeg"]
    # Declaring the wrong format for the bytes is still refused, in any spelling.
    for wrong in ("jpg", "JPEG"):
        with pytest.raises(ValueError, match="does not match"):
            replay_key(STATE, QUESTIONS, assets={REF: {**png[REF], "format": wrong}})
    with pytest.raises(ValueError, match="png or jpeg"):
        replay_key(STATE, QUESTIONS, assets={REF: {**png[REF], "format": "gif"}})
    with pytest.raises(ValueError, match="png or jpeg"):
        replay_key(STATE, QUESTIONS, assets={REF: {**png[REF], "format": None}})


def test_a_recording_made_with_one_format_spelling_replays_with_another():
    jpeg = image_assets(fmt="JPEG")
    stored = {replay_key(STATE, QUESTIONS, assets=jpeg): box_result().to_dict()}
    replay = ReplayBackend(stored)
    for spelling in ("jpg", "JPEG"):
        assert (
            replay.decide(STATE, QUESTIONS, assets={REF: {**jpeg[REF], "format": spelling}})
            == box_result()
        )


def test_text_only_replay_keys_are_pinned_to_the_published_envelope():
    # Literal keys computed with origin/main's replay_key before images existed.
    questions = {"visible": Noul(instructions="The target is visible.")}
    assert replay_key("ordinary text", questions) == PINNED_TEXT_KEY
    assert replay_key("ordinary text", questions, assets={}) == PINNED_TEXT_KEY


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
        replay_key(STATE, QUESTIONS, assets=image_assets(size=(279, 400)))
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
    (tmp_path / "build_fixtures.py").write_text("def draw_scene(color):\n    ...\n", "utf-8")
    inputs, labels, responses, manifest = [], [], {}, []
    for ident, split, color in [("v01", "validation", "pink"), ("t01", "test", "blue")]:
        assets = image_assets(color)
        relative = f"assets/{ident}.png"
        data = base64.b64decode(assets[REF]["data_base64"])
        (tmp_path / relative).write_bytes(data)
        with Image.open(tmp_path / relative) as image:
            width, height = image.size
        manifest.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
                "format": "PNG",
                "width": width,
                "height": height,
                "origin": "generated",
                "generator": "build_fixtures.py:draw_scene",
                "parameters": {"color": color},
                "licence": "CC0-1.0",
                "description": f"A flat {color} picture.",
                "attestations": {
                    "synthetic": True,
                    "real_photo": False,
                    "real_brand": False,
                    "real_person": False,
                    "third_party_content": False,
                },
            }
        )
        key = replay_key(STATE, QUESTIONS, assets=assets)
        inputs.append(
            {"id": ident, "split": split, "fields": {"image": relative}, "replay_keys": [key]}
        )
        labels.append({"id": ident, "label": {"present": True, "box": EDGES}})
        responses[key] = box_result(None).to_dict()
    (folder / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in inputs))
    (folder / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in labels))
    (folder / "responses.json").write_text(json.dumps(responses))
    (tmp_path / "assets-manifest.json").write_text(json.dumps({"schema": 1, "assets": manifest}))
    assert validate_recipe(tmp_path) == []
    examples = load_inputs(tmp_path)
    assert examples[0].fields["image"] == "assets/v01.png"
    responses[examples[0].replay_keys[0]]["answers"]["target"]["box"]["left"] = 1.0
    (folder / "responses.json").write_text(json.dumps(responses))
    assert any("left < right" in str(problem) for problem in validate_recipe(tmp_path))


def _noncanonical_twin(asset):
    """Same decoded bytes, different base64 text (spare low bits set in the final group)."""
    encoded = asset["data_base64"]
    data = base64.b64decode(encoded)
    assert len(data) % 3 != 0, "need a padded encoding to vary its trailing bits"
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits + "+/"
    body = encoded.rstrip("=")
    pad = encoded[len(body) :]
    spare = 0b1111 if len(pad) == 2 else 0b11
    twin = body[:-1] + alphabet[alphabet.index(body[-1]) | spare] + pad
    assert twin != encoded and base64.b64decode(twin, validate=True) == data
    return {**asset, "data_base64": twin}


def _padded_png(size=(280, 280)):
    """A PNG whose length is not a multiple of 3, so its base64 ends in padding."""
    for extra in range(8):
        data = io.BytesIO()
        Image.new("RGB", size, "pink").save(data, format="PNG", comment=b"x" * extra)
        if len(data.getvalue()) % 3 != 0:
            return {
                "type": "image",
                "format": "png",
                "data_base64": base64.b64encode(data.getvalue()).decode("ascii"),
            }
    raise AssertionError("could not build a padded PNG")


def test_non_canonical_base64_of_identical_bytes_yields_one_replay_key():
    assert base64.b64decode("QQ==", validate=True) == base64.b64decode("QR==", validate=True)
    original = _padded_png()
    twin = _noncanonical_twin(original)
    assert twin["data_base64"] != original["data_base64"]
    assert replay_key(STATE, QUESTIONS, assets={REF: twin}) == replay_key(
        STATE, QUESTIONS, assets={REF: original}
    )


def test_a_recording_replays_for_non_canonical_base64_of_the_same_bytes():
    original = _padded_png()
    key = replay_key(STATE, QUESTIONS, assets={REF: original})
    replay = ReplayBackend({key: box_result().to_dict()})
    twin = _noncanonical_twin(original)
    assert replay.decide(STATE, QUESTIONS, assets={REF: twin}) == box_result()


def test_image_key_hashes_decoded_bytes_in_the_documented_envelope():
    # The documented envelope: {"v": 1, state, questions, "assets": {ref: {type, format,
    # sha256 of the decoded file bytes}}}, canonical JSON, SHA-256. Rebuilt here independently.
    assets = image_assets()
    data = base64.b64decode(assets[REF]["data_base64"])
    payload = {
        "v": 1,
        "state": STATE,
        "questions": {"target": QUESTIONS["target"].to_dict()},
        "assets": {
            REF: {"type": "image", "format": "png", "sha256": hashlib.sha256(data).hexdigest()}
        },
    }
    expected = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    assert replay_key(STATE, QUESTIONS, assets=assets) == expected
    # image_reference's digest is the same digest the key embeds.
    from jev_cookbook.vision import image_reference

    assert image_reference(assets[REF]) == "image:sha256:" + hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("size", [(279, 400), (400, 279)])
def test_replay_key_refuses_a_side_under_280_on_either_axis(size):
    with pytest.raises(ValueError, match="280 to 1568"):
        replay_key(STATE, QUESTIONS, assets=image_assets(size=size))
    replay_key(STATE, QUESTIONS, assets=image_assets(size=(280, 280)))


def test_image_replay_key_is_pinned_to_the_published_envelope(monkeypatch):
    # Fixed stand-in bytes (validation is bypassed so the literal does not depend on the
    # Pillow/zlib version that would encode a real PNG): this pins the envelope, the
    # field names and the decoded-bytes digest, so drift on both sides at once is caught.
    from jev_cookbook import vision

    monkeypatch.setattr(vision, "validate_image_asset", lambda asset: b"fixed image bytes")
    asset = {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(b"fixed image bytes").decode("ascii"),
    }
    assert replay_key(STATE, QUESTIONS, assets={REF: asset}) == (
        "00c4d3b2fcb92ce23200e54bed0dcc9c91a7bc134b7862838a1facaddf9acba8"
    )


# -- image request accounting (#313): copies versus distinct images, and the aggregate caps ------

MIB = 1024 * 1024


def sized(n):
    """An asset descriptor of ``n`` file bytes. The profile reads only the length of the base64
    text, so these need not be images; tests that go through ``decide`` patch the validator."""
    return {
        "type": "image",
        "format": "png",
        "data_base64": base64.b64encode(b"\x00" * n).decode("ascii"),
    }


def accepting_any_bytes(monkeypatch):
    from jev_cookbook import vision

    monkeypatch.setattr(
        vision, "validate_image_asset", lambda asset: base64.b64decode(asset["data_base64"])
    )


def test_a_reference_used_twice_in_one_string_is_two_copies_of_one_image():
    from jev_cookbook.vision import image_request_profile

    # Hand-computed: <ruler> is 3000 bytes and is placed twice in one sentence, so 2 copies,
    # 1 distinct asset, 3000 distinct bytes and 6000 expanded bytes.
    profile = image_request_profile(
        {"note": "compare <ruler> against <ruler> now"},
        {"fits": Noul(instructions="Does it fit?")},
        {"<ruler>": sized(3000)},
    )
    assert (profile.distinct_assets, profile.distinct_bytes) == (1, 3000)
    assert (profile.copies, profile.expanded_bytes) == (2, 6000)
    assert profile.state_copies == 2 and dict(profile.per_question) == {"fits": 0}


def test_an_instruction_image_shared_by_three_questions_is_three_copies():
    from jev_cookbook.vision import image_request_profile

    # Hand-computed: <chart> (2000 bytes, a padded base64 length) is in the instructions of three
    # questions, so it is sent three times; <photo> (300 bytes) is in the state once. 4 copies of 2
    # distinct assets: 2300 distinct bytes, 3 * 2000 + 300 = 6300 expanded bytes.
    questions = {
        name: Noul(instructions=f"Read <chart> and decide: {name}.") for name in ("a", "b", "c")
    }
    profile = image_request_profile(
        {"photo": "<photo>"}, questions, {"<chart>": sized(2000), "<photo>": sized(300)}
    )
    assert (profile.distinct_assets, profile.distinct_bytes) == (2, 2300)
    assert (profile.copies, profile.expanded_bytes) == (4, 6300)
    assert profile.state_copies == 1
    assert dict(profile.per_question) == {"a": 1, "b": 1, "c": 1}
    # The advice upstream gives: the shared image in the state once is one copy, not three.
    shared_once = image_request_profile(
        {"photo": "<photo>", "chart": "<chart>"},
        {name: Noul(instructions=f"Read `chart`: {name}.") for name in ("a", "b", "c")},
        {"<chart>": sized(2000), "<photo>": sized(300)},
    )
    assert (shared_once.copies, shared_once.expanded_bytes) == (2, 2300)
    assert shared_once.distinct_bytes == 2300


def test_references_count_only_where_a_reference_can_be_replaced():
    from jev_cookbook import Choice, Score
    from jev_cookbook.vision import image_request_profile

    assets = {"<a>": sized(10), "<b>": sized(20), "<unused>": sized(30)}
    questions = {
        "pick": Choice(criteria={"<a>": "like <b>", "other": "<a><a>"}, instructions="Pick <b>."),
        "level": Score(criteria=["low <a>", "high"], instructions=None),
    }
    profile = image_request_profile(["<a>", "no image"], questions, assets)
    # state: <a> 1.  pick: instructions <b> 1, criteria values <b> 1 + <a> 2 (the option NAME
    # "<a>" is text, not a place for an image).  level: criteria <a> 1.  <unused> is never placed.
    assert profile.state_copies == 1
    assert dict(profile.per_question) == {"pick": 4, "level": 1}
    assert profile.copies == 6
    assert profile.distinct_assets == 2 and profile.distinct_bytes == 30
    assert profile.expanded_bytes == 4 * 10 + 2 * 20
    keys_only = image_request_profile({"<a>": "text"}, {"q": Noul()}, assets)
    assert keys_only.copies == 0 and keys_only.distinct_assets == 0


def test_matches_never_overlap_and_the_longer_reference_wins_where_both_start():
    from jev_cookbook.vision import image_request_profile

    assets = {"img-1": sized(10), "img-10": sized(100)}
    profile = image_request_profile("img-10 then img-1 then img-100", {"q": Noul()}, assets)
    # "img-10" once, "img-1" once, then "img-100" is "img-10" followed by a plain "0": the longer
    # reference is taken where both start, and no character is replaced twice.
    assert profile.copies == 3 and profile.distinct_assets == 2
    assert profile.expanded_bytes == 100 + 10 + 100


def test_no_assets_is_a_zero_profile_and_bytes_come_from_the_length_alone():
    from jev_cookbook.vision import image_request_profile

    for assets in (None, {}):
        zero = image_request_profile("<a>", {"q": Noul()}, assets)
        assert (zero.distinct_assets, zero.distinct_bytes, zero.copies, zero.expanded_bytes) == (
            0,
            0,
            0,
            0,
        )
    for n in range(12):  # every padding shape
        profile = image_request_profile("<a>", {"q": Noul()}, {"<a>": sized(n)})
        assert profile.distinct_bytes == profile.expanded_bytes == n


def test_the_profile_is_pure_it_neither_reads_files_nor_decodes_nor_stores_bytes(monkeypatch):
    import builtins
    import pathlib

    from jev_cookbook import vision

    asset = sized(500)
    before = dict(asset)

    def refuse(*args, **kwargs):
        raise AssertionError("the profile must not read, decode or validate")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(pathlib.Path, "open", refuse)
    monkeypatch.setattr(pathlib.Path, "read_bytes", refuse)
    monkeypatch.setattr(base64, "b64decode", refuse)
    monkeypatch.setattr(vision, "validate_image_asset", refuse)
    monkeypatch.setattr(vision, "image_asset", refuse)
    profile = vision.image_request_profile("<a>", {"q": Noul()}, {"<a>": asset})
    assert asset == before and profile.copies == 1
    # No bytes or content are kept on the result.
    assert set(vars(profile)) == {
        "distinct_assets",
        "distinct_bytes",
        "copies",
        "expanded_bytes",
        "state_copies",
        "per_question",
    }
    with pytest.raises(AttributeError):
        profile.copies = 9
    with pytest.raises(TypeError):
        profile.per_question["q"] = 9


def test_the_profile_agrees_with_the_decoded_size_of_real_images():
    from jev_cookbook.vision import image_request_profile

    assets = image_assets()
    size = len(base64.b64decode(assets[REF]["data_base64"]))
    profile = image_request_profile({"a": REF, "b": f"{REF} {REF}"}, QUESTIONS, assets)
    assert profile.distinct_bytes == size and profile.expanded_bytes == 3 * size


def test_a_request_at_the_cap_is_allowed_and_one_byte_over_is_refused():
    from jev_cookbook.vision import (
        ImageRequestProfile,
        ImageRequestTooLarge,
        preflight_image_request,
    )

    cap = 32 * MIB
    preflight_image_request(ImageRequestProfile(1, cap, 1, cap, 1, {}))
    with pytest.raises(ImageRequestTooLarge, match="distinct image"):
        preflight_image_request(ImageRequestProfile(1, cap + 1, 1, cap + 1, 1, {}))
    with pytest.raises(ImageRequestTooLarge, match="expanded request"):
        preflight_image_request(ImageRequestProfile(1, cap, 2, cap + 1, 2, {}))
    assert issubclass(ImageRequestTooLarge, ValueError)


@pytest.fixture
def no_sdk(monkeypatch):
    """The preflight must come before the SDK is even imported, let alone called."""

    def refuse():
        raise AssertionError("the SDK was reached before the preflight refused the request")

    monkeypatch.setattr(live_module, "_import_sdk", refuse)


def test_expanded_copies_over_32_mib_are_refused_before_anything_is_spent(monkeypatch, no_sdk):
    from jev_cookbook.vision import ImageRequestTooLarge

    accepting_any_bytes(monkeypatch)
    client = Client()
    backend = LiveBackend("jev-1.14.0", client=client, images=True)
    # One 7 MiB image (well under 16 MiB and 32 MiB) used five times expands to 35 MiB.
    assets = {"<big>": sized(7 * MIB)}
    state = {"photo": "<big> <big> <big> <big> <big>"}
    questions = {"q": Noul(instructions="Fine?")}
    with pytest.raises(ImageRequestTooLarge, match="expanded request"):
        backend.decide(state, questions, assets=assets)
    assert backend.requests_made == 0 and client.calls == []
    assert backend.records == () and backend.requests_remaining == backend.max_requests
    # The message names the cure the page gives.
    with pytest.raises(ImageRequestTooLarge, match="state once"):
        backend.decide(state, questions, assets=assets)
    assert backend.requests_made == 0


def test_an_instruction_image_repeated_per_question_is_refused(monkeypatch, no_sdk):
    from jev_cookbook.vision import ImageRequestTooLarge

    accepting_any_bytes(monkeypatch)
    client = Client()
    backend = LiveBackend("jev-1.14.0", client=client, images=True)
    assets = {"<big>": sized(9 * MIB)}
    in_instructions = {name: Noul(instructions="Use <big>.") for name in "abcd"}  # 4 * 9 = 36 MiB
    with pytest.raises(ImageRequestTooLarge, match="'a': 1, 'b': 1, 'c': 1, 'd': 1"):
        backend.decide("x", in_instructions, assets=assets)
    assert backend.requests_made == 0 and client.calls == []


def test_distinct_images_over_32_mib_are_refused_before_anything_is_spent(monkeypatch, no_sdk):
    from jev_cookbook.vision import ImageRequestTooLarge

    accepting_any_bytes(monkeypatch)
    client = Client()
    backend = LiveBackend("jev-1.14.0", client=client, images=True)
    assets = {f"<img-{n}>": sized(7 * MIB) for n in range(5)}  # five distinct, 35 MiB, once each
    state = {f"slot{n}": f"<img-{n}>" for n in range(5)}
    with pytest.raises(ImageRequestTooLarge, match="5 distinct image.*all images in a request"):
        backend.decide(state, {"q": Noul(instructions="Fine?")}, assets=assets)
    assert backend.requests_made == 0 and client.calls == []


def test_requests_under_both_caps_are_still_sent(monkeypatch, fake_sdk):
    accepting_any_bytes(monkeypatch)
    client = Client()
    backend = LiveBackend("jev-1.14.0", client=client, images=True)
    assets = {f"<img-{n}>": sized(7 * MIB) for n in range(4)}  # 28 MiB distinct and expanded
    state = {f"slot{n}": f"<img-{n}>" for n in range(4)}
    backend.decide(state, {"target": Box(instructions="Find the target.")}, assets=assets)
    assert backend.requests_made == 1 and len(client.calls) == 1


def test_the_recorder_refuses_an_over_cap_request_without_spending(monkeypatch, no_sdk, tmp_path):
    from jev_cookbook.vision import ImageRequestTooLarge

    accepting_any_bytes(monkeypatch)
    backend = LiveBackend("jev-1.14.0", client=Client(), images=True)
    assets = {"<big>": sized(7 * MIB)}
    request = ({"photo": "<big> " * 5}, {"q": Noul(instructions="Fine?")}, assets)
    with pytest.raises(ImageRequestTooLarge):
        record(backend, [request], tmp_path / "r.json", ledger_path=tmp_path / "ledger.json")
    assert backend.requests_made == 0
    (line,) = json.loads((tmp_path / "ledger.json").read_text("utf-8")).values()
    assert line["status"] == "error" and line["attempts"] == 0


class RetryOnceClient(Client):
    """Fails its first call with a retryable 503 (request id ``req-retried-1``), then answers."""

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            error = RuntimeError("temporarily unavailable")
            error.status = 503
            error.request_id = "req-retried-1"
            raise error
        return self.body


def test_a_refused_request_does_not_inherit_the_previous_calls_retried_list(
    monkeypatch, fake_sdk, tmp_path
):
    from jev_cookbook.vision import ImageRequestTooLarge

    accepting_any_bytes(monkeypatch)
    backend = LiveBackend(
        "jev-1.14.0", client=RetryOnceClient(), images=True, sleep=lambda seconds: None
    )
    sent = (
        {"photo": "<small>"},
        {"target": Box(instructions="Find the target.")},
        {"<small>": sized(1000)},
    )
    refused = (
        {"photo": "<big> " * 5},
        {"q": Noul(instructions="Fine?")},
        {"<big>": sized(7 * MIB)},
    )
    ledger = tmp_path / "ledger.json"
    with pytest.raises(ImageRequestTooLarge):
        record(backend, [sent, refused], tmp_path / "r.json", ledger_path=ledger)
    lines = json.loads(ledger.read_text("utf-8"))
    (recorded,) = [entry for key, entry in lines.items() if "!failed-" not in key]
    (failed,) = [entry for key, entry in lines.items() if key.endswith("!failed-1")]
    # The first call retried once past a 503 and then succeeded.
    assert recorded["status"] == "recorded" and recorded["attempts"] == 2
    assert [attempt["request_id"] for attempt in recorded["retried"]] == ["req-retried-1"]
    # The refusal sent nothing, so it retried past nothing: its line must not repeat the 503.
    assert failed["status"] == "error" and failed["error_type"] == "ImageRequestTooLarge"
    assert failed["attempts"] == 0 and failed["retried"] == []
    assert backend.last_retried == ()


def test_a_backend_config_refusal_before_sending_writes_the_documented_error_line(
    monkeypatch, no_sdk, tmp_path
):
    accepting_any_bytes(monkeypatch)
    # images=False: the backend refuses image assets inside ``decide``, before the SDK or a spend.
    backend = LiveBackend("jev-1.14.0", client=Client())
    request = (
        {"photo": "<small>"},
        {"q": Noul(instructions="Fine?")},
        {"<small>": sized(1000)},
    )
    ledger = tmp_path / "ledger.json"
    with pytest.raises(LiveConfigError, match="images=True"):
        record(backend, [request], tmp_path / "r.json", ledger_path=ledger)
    assert backend.requests_made == 0
    ((key, line),) = json.loads(ledger.read_text("utf-8")).items()
    assert key.endswith("!failed-1")
    assert line["status"] == "error" and line["error_type"] == "LiveConfigError"
    assert line["http_status"] is None and line["request_id"] is None
    assert line["attempts"] == 0 and line["retried"] == []


def test_a_request_that_fails_validation_raises_from_record_and_gets_no_sidecar_line(
    monkeypatch, fake_sdk, tmp_path
):
    accepting_any_bytes(monkeypatch)
    backend = LiveBackend("jev-1.14.0", client=Client(), images=True)
    sent = (
        {"photo": "<small>"},
        {"target": Box(instructions="Find the target.")},
        {"<small>": sized(1000)},
    )
    # No value names ``<unused>``, so validation refuses the request inside ``replay_key``, which
    # ``record`` calls before it makes any ``decide`` call: nothing can be written for it.
    unused = (
        {"photo": "no reference here"},
        {"q": Noul(instructions="Fine?")},
        {"<unused>": sized(1000)},
    )
    ledger = tmp_path / "ledger.json"
    with pytest.raises(ValueError, match="not referenced"):
        record(backend, [sent, unused], tmp_path / "r.json", ledger_path=ledger)
    assert backend.requests_made == 1  # the first request's single attempt; the second added none
    lines = json.loads(ledger.read_text("utf-8"))
    assert [entry["status"] for entry in lines.values()] == ["recorded"]
    assert not any("!failed-" in key for key in lines)


def test_the_live_ledger_carries_image_counts_beside_the_token_fields(fake_sdk, tmp_path):
    backend = LiveBackend("jev-1.14.0", client=Client(), images=True)
    questions = {"target": Box(instructions=f"The pink rectangle in `photo`; ignore {REF}.")}
    state = {"photo": REF, "again": f"{REF} / {REF}"}
    path, ledger = tmp_path / "responses.json", tmp_path / "ledger.json"
    record(backend, [(state, questions, image_assets())], path, ledger_path=ledger)
    # Hand-computed: 1 + 2 in the state and 1 in the instructions = 4 copies of 1 asset.
    (line,) = json.loads(ledger.read_text("utf-8")).values()
    assert (line["images"], line["distinct_images"]) == (4, 1)
    assert line["input_tokens"] == 10 and line["output_tokens"] == 5
    assert backend.records[0].images == 4
    summary = backend.ledger()
    assert (summary["images"], summary["distinct_images"]) == (4, 1)
    # The counts say nothing about bytes, content or references.
    assert "data_base64" not in json.dumps([line, summary]) and REF not in json.dumps(line)
