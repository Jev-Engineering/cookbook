"""Image decode reuse with an injected client and SDK: no credential or network is used."""

from __future__ import annotations

import base64
import io
from collections import Counter
from types import SimpleNamespace

import pytest
from PIL import Image

from jev_cookbook import LiveBackend, Noul, vision
from jev_cookbook import live as live_module

MODEL = "jev-1.14.0"
QUESTIONS = {"visible": Noul(instructions="The target is visible.")}
IMAGES_HEADER = "TypeSafe-Danger-Zone-Images"
CONTEXT_HEADER = "TypeSafe-Danger-Zone-Long-Context"


def image_asset(fmt="PNG", *, width=280):
    buffer = io.BytesIO()
    Image.new("RGB", (width, 280), "pink").save(buffer, format=fmt)
    data = buffer.getvalue()
    return {
        "type": "image",
        "format": fmt.lower(),
        "data_base64": base64.b64encode(data).decode("ascii"),
    }, data


class FakeImage:
    """Hold exactly the file bytes supplied to the SDK image constructor."""

    def __init__(self, data):
        assert isinstance(data, bytes)
        self.data = data


class FakeClient:
    def __init__(self, retries=0):
        self.retries = retries
        self.calls = []

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.retries:
            raise TimeoutError("synthetic retry")
        return {
            "model": MODEL,
            "answers": {"visible": {"type": "noul", "noul": 0.9}},
        }


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "0")

    def refuse_client(*args, **kwargs):
        raise AssertionError("these tests must inject their fake client")

    monkeypatch.setattr(LiveBackend, "_build_client", refuse_client)
    monkeypatch.setattr(live_module, "_read_key", refuse_client)
    monkeypatch.setattr(live_module, "_import_sdk", lambda: SimpleNamespace(Image=FakeImage))


@pytest.mark.parametrize("retries", [0, 1])
def test_each_asset_is_decoded_once_and_the_original_file_bytes_are_sent(monkeypatch, retries):
    png, png_bytes = image_asset()
    jpeg, jpeg_bytes = image_asset("JPEG")
    assets = {"<png>": png, "<jpeg>": jpeg}
    state = {"photo": "<png>", "again": "<png> <jpeg>"}
    questions = {"visible": Noul(instructions="Compare <png> and <jpeg>.")}
    decode_calls = []
    validated = []
    real_decode = base64.b64decode
    real_validate = vision.validate_image_asset

    def count_decode(encoded, *args, **kwargs):
        decode_calls.append(encoded)
        return real_decode(encoded, *args, **kwargs)

    def capture_validated(asset):
        data = real_validate(asset)
        validated.append((asset["data_base64"], data))
        return data

    monkeypatch.setattr(base64, "b64decode", count_decode)
    monkeypatch.setattr(vision, "validate_image_asset", capture_validated)
    client = FakeClient(retries)
    sleeps = []
    backend = LiveBackend(
        MODEL,
        client=client,
        images=True,
        max_retries=retries,
        sleep=sleeps.append,
        today=lambda: "2026-11-18",
    )
    result = backend.decide(state, questions, assets=assets)

    assert result["visible"].noul == 0.9
    assert backend.requests_made == len(client.calls) == retries + 1
    assert len(sleeps) == retries
    assert len(backend.last_retried) == retries
    assert {encoded: data for encoded, data in validated} == {
        png["data_base64"]: png_bytes,
        jpeg["data_base64"]: jpeg_bytes,
    }
    for sent in client.calls:
        assert sent["state"] == state
        assert sent["questions"]["visible"] == {
            "type": "noul",
            "instructions": "Compare <png> and <jpeg>.",
        }
        assert sent["extra_headers"] == {IMAGES_HEADER: "true"}
        assert all(isinstance(image, FakeImage) for image in sent["assets"].values())
        assert {ref: image.data for ref, image in sent["assets"].items()} == {
            "<png>": png_bytes,
            "<jpeg>": jpeg_bytes,
        }
    # Count the whole decide call, including request validation, key construction and retries.
    # Repeated reference occurrences do not require another decoding of that asset.
    assert Counter(decode_calls) == Counter({png["data_base64"]: 1, jpeg["data_base64"]: 1})


@pytest.mark.parametrize("long_context", [False, True])
def test_image_header_stays_per_call_when_validated_bytes_are_reused(long_context):
    asset, original = image_asset()
    client = FakeClient()
    backend = LiveBackend(MODEL, client=client, images=True, long_context=long_context)
    backend.decide("plain text", QUESTIONS)
    backend.decide("<image>", QUESTIONS, assets={"<image>": asset})
    backend.decide("plain text again", QUESTIONS, assets={})

    context = {CONTEXT_HEADER: "true"} if long_context else {}
    first, image, last = client.calls
    assert first.get("extra_headers", {}) == last.get("extra_headers", {}) == context
    assert "assets" not in first and "assets" not in last
    assert image["extra_headers"] == {**context, IMAGES_HEADER: "true"}
    assert image["assets"]["<image>"].data == original
    assert backend.requests_made == 3


@pytest.mark.parametrize("padding", ["=", "==", "===="])
def test_excess_padding_is_refused_before_sdk_images_or_send(monkeypatch, padding):
    # Use an unpadded, whole-group PNG and emulate older interpreters that allow extra '='
    # even in strict mode. The cookbook must enforce its padding rule on every interpreter.
    for width in range(280, 290):
        asset, original = image_asset(width=width)
        if len(original) % 3 == 0:
            break
    else:
        raise AssertionError("the synthetic PNG fixture needs a whole-group encoding")
    malformed = {**asset, "data_base64": asset["data_base64"] + padding}
    real_decode = base64.b64decode
    assert real_decode(malformed["data_base64"], validate=False) == original
    decode_calls = []

    def permissive_decode(encoded, *, validate):
        decode_calls.append(encoded)
        return real_decode(encoded, validate=False)

    monkeypatch.setattr(base64, "b64decode", permissive_decode)

    def refuse_image(data):
        raise AssertionError("invalid padding must be refused before SDK image construction")

    monkeypatch.setattr(live_module, "_import_sdk", lambda: SimpleNamespace(Image=refuse_image))
    client = FakeClient()
    backend = LiveBackend(MODEL, client=client, images=True)
    with pytest.raises(ValueError, match="base64"):
        backend.decide("<image>", QUESTIONS, assets={"<image>": malformed})
    assert decode_calls == []
    assert client.calls == []
    assert backend.requests_made == 0
    assert backend.records == ()
    assert backend.last_retried == ()
