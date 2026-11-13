"""Docs reachability and honesty (Refs #315): the multimodal pages stay linked, and three
sentences in the docs are pinned to what the code and the upstream pages say.

Offline: it reads markdown files and drives ``LiveBackend`` with a fake client. No key, no
network, no SDK.
"""

from __future__ import annotations

import functools
import json
import re
import sys
import types
from pathlib import Path

import pytest

from jev_cookbook import LiveBackend, Noul, NoulAnswer, Provenance

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

_FENCED = re.compile(r"^[ \t]*```.*?^[ \t]*```", re.S | re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_CODE_SPAN = re.compile(r"(`+).+?\1", re.S)
_LINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\)")
_REFERENCE = re.compile(r"^[ ]{0,3}\[[^\]]+\]:\s*<?([^>\s#]+)", re.M)


def prose(text: str) -> str:
    """``text`` without fenced code blocks, HTML comments and inline code spans, none of which
    GitHub renders as a link."""
    return _CODE_SPAN.sub("", _COMMENT.sub("", _FENCED.sub("", text)))


@functools.cache
def linked_pages(page: Path) -> frozenset[Path]:
    """The markdown files ``page`` links to (inline and reference-style links), resolved,
    ignoring fenced code, HTML comments, inline code and URLs."""
    text = prose(page.read_text("utf-8"))
    found: set[Path] = set()
    for target in _LINK.findall(text) + _REFERENCE.findall(text):
        if "://" in target or target.startswith("mailto:") or not target.endswith(".md"):
            continue
        found.add((page.parent / target).resolve())
    return frozenset(found)


def section(text: str, heading: str) -> str:
    """The body under ``heading`` (a full heading line such as ``## Name``), up to the next
    heading of level 1 to 3. Fenced code is removed first, so a ``# comment`` inside a code block
    is not taken for a heading."""
    text = _FENCED.sub("", text)
    match = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^#{{1,3}} |\Z)", text, re.S | re.M)
    assert match, f"no section {heading!r}"
    return match.group(1)


def squash(text: str) -> str:
    return " ".join(text.split())


# -- the link parser itself ------------------------------------------------------------------


def test_linked_pages_reads_fragments_and_skips_code_and_urls(tmp_path):
    (tmp_path / "page.md").write_text(
        "See [b](b.md) and [c](c.md#part) and [d](https://example.com/d.md) "
        "and [e](notes.txt) and [g](g.md 'title') and [h][ref].\n\n"
        "```\n[f](f.md)\n```\n\n  ```\n  [i](i.md)\n  ```\n\n"
        "Not links: `[j](j.md)` and <!-- [k](k.md) -->.\n\n[ref]: h.md#part\n",
        encoding="utf-8",
    )
    root = tmp_path.resolve()
    expected = {root / "b.md", root / "c.md", root / "g.md", root / "h.md"}
    assert linked_pages(tmp_path / "page.md") == expected


def test_section_ignores_a_comment_line_inside_fenced_code():
    text = "## A\n\nfirst\n\n```python\n# a comment\n```\n\nsecond\n\n## B\n\nthird\n"
    body = section(text, "## A")
    assert "first" in body and "second" in body and "third" not in body


# -- reachability -------------------------------------------------------------------------------

TRACK_PAGES = ["vision.md", "multimodal-track.md"]


@pytest.mark.parametrize("name", TRACK_PAGES)
def test_the_readme_links_the_multimodal_pages(name):
    assert (DOCS / name).resolve() in linked_pages(REPO / "README.md")


@pytest.mark.parametrize("name", TRACK_PAGES)
def test_another_docs_page_links_each_multimodal_page(name):
    target = (DOCS / name).resolve()
    others = [
        p.name for p in sorted(DOCS.glob("*.md")) if p.name != name and target in linked_pages(p)
    ]
    assert others, f"no other docs page links docs/{name}"


@pytest.mark.parametrize("page", ["backends.md", "fixtures.md"])
def test_backends_and_fixtures_link_the_vision_page(page):
    assert (DOCS / "vision.md").resolve() in linked_pages(DOCS / page)


# -- the experimental label in backends.md -----------------------------------------------------


def test_images_and_box_opens_with_the_experimental_label_and_upstream_links():
    body = section((DOCS / "backends.md").read_text("utf-8"), "## Images and Box")
    first = squash(body.strip().split("\n\n")[0])
    assert first.startswith("**Experimental.**")
    for needle in (
        "Dreamer-ready",
        "ready for production",
        "The request format, the answers, and the limits on this page can change between releases",
        "https://docs.typesafe.ai/images",
        "https://docs.typesafe.ai/primitives/box",
        "(vision.md)",
    ):
        assert needle in first, needle


# -- docs/live.md: the images header and compression -----------------------------------------------

LIVE_TEXT = (DOCS / "live.md").read_text("utf-8")


def test_live_md_says_the_flag_belongs_to_the_backend_not_to_the_call():
    body = squash(section(LIVE_TEXT, "### Experimental images and long context"))
    for needle in (
        "a backend built with `images=True` sends the images header on every call it makes",
        "including a call with no image or Box question",
        "a backend built with `long_context=True` does the same with the long-context header",
        "a backend built without a flag sends no header for it",
    ):
        assert needle in body, needle


def test_live_md_documents_the_sdk_default_compression():
    body = squash(section(LIVE_TEXT, "## What a call does"))
    for needle in (
        "Compression: the backend builds its own client without a `compression=` argument",
        "SDK 0.7.5 made it zstd",
        "request bodies of 1 KiB or more with zstd",
        "`typesafe-sdk[zstd]`",
        "`jev_cookbook[live]` does not install that extra",
        "Compression does not raise the 32 MiB request-body limit",
    ):
        assert needle in body, needle


def test_the_backend_builds_its_client_without_a_compression_argument(monkeypatch):
    """The compression sentence holds only while the backend leaves ``compression=`` to the SDK's
    default. A stub SDK records the constructor's arguments; no key is read and nothing is sent."""
    built = []

    class _SdkClient:
        def __init__(self, **kwargs):
            built.append(kwargs)

    sdk = types.ModuleType("typesafe_sdk")
    sdk.TypeSafeClient = _SdkClient
    sdk.RetryPolicy = lambda **kw: types.SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "typesafe_sdk", sdk)
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    monkeypatch.setenv("JEV_COOKBOOK_LIVE", "1")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-placeholder-not-a-key")
    LiveBackend("jev-1.13.0", sleep=lambda s: None)
    assert len(built) == 1
    assert "compression" not in built[0]


class _Resp:
    def __init__(self, body):
        self._body = body

    def model_dump_json(self):
        return json.dumps(self._body)

    @property
    def request_id(self):
        return "req-1"


class _Client:
    """Records every ``system_one`` call; answers one Noul question."""

    def __init__(self):
        self.calls = []

    def system_one(self, **kwargs):
        self.calls.append(kwargs)
        answer = NoulAnswer(0.9, Provenance.synthetic()).to_dict()
        del answer["provenance"]
        body = {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "answers": {"q": answer},
        }
        return _Resp(body)


IMAGES = {"TypeSafe-Danger-Zone-Images": "true"}
LONG_CONTEXT = {"TypeSafe-Danger-Zone-Long-Context": "true"}


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({}, None),
        ({"images": True}, IMAGES),
        ({"long_context": True}, LONG_CONTEXT),
        ({"images": True, "long_context": True}, {**IMAGES, **LONG_CONTEXT}),
    ],
)
def test_a_text_only_call_carries_the_headers_of_the_flags_the_backend_was_built_with(
    flags, expected
):
    client = _Client()
    backend = LiveBackend(
        "jev-1.13.0", client=client, today=lambda: "2026-10-31", sleep=lambda s: None, **flags
    )
    questions = {"q": Noul(instructions="The text mentions a refund.")}
    for _ in range(2):
        backend.decide({"text": "Please refund me."}, questions)
    assert [call.get("extra_headers") for call in client.calls] == [expected, expected]
