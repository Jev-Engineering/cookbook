"""Docs reachability and honesty (Refs #315): the multimodal pages stay linked, and three
sentences in the docs are pinned to what the code and the upstream pages say.

Offline: it reads markdown files and drives ``LiveBackend`` with a fake client. No key, no
network, no SDK.
"""

from __future__ import annotations

import functools
import json
import sys
import types
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from markdown_it import MarkdownIt

from jev_cookbook import LiveBackend, Noul, NoulAnswer, Provenance

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

_MARKDOWN = MarkdownIt("commonmark")


@functools.cache
def linked_pages(page: Path) -> frozenset[Path]:
    """Resolve local Markdown targets from rendered link tokens."""
    found: set[Path] = set()
    for block in _MARKDOWN.parse(page.read_text("utf-8")):
        for inline in block.children or ():
            if inline.type != "link_open":
                continue
            href = inline.attrGet("href")
            if not isinstance(href, str):
                continue
            try:
                url = urlsplit(href)
            except ValueError:
                continue
            if url.scheme or url.netloc:
                continue
            target = unquote(url.path)
            if not target.endswith(".md") or "\0" in target:
                continue
            base = REPO if target.startswith("/") else page.parent
            found.add((base / target.lstrip("/")).resolve())
    return frozenset(found)


def section(text: str, heading: str) -> str:
    """Extract source below a top-level heading, up to the next heading of equal or higher level.

    The caller identifies a heading with its level and Markdown text (for example, ``## Name``).
    Code blocks and standalone comments are omitted so examples cannot satisfy prose assertions.
    """
    marker, _, title = heading.partition(" ")
    level = len(marker)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tokens = _MARKDOWN.parse(text)
    start = None
    stop = len(lines)
    ignored_lines: set[int] = set()
    for index, token in enumerate(tokens):
        if token.map is None:
            continue
        first_line, after_line = token.map
        if token.type == "heading_open" and token.level == 0:
            depth = int(token.tag[1:])
            if start is None and depth == level and tokens[index + 1].content == title:
                start = after_line
            elif start is not None and depth <= level:
                stop = first_line
                break
        elif start is not None and (
            token.type in {"code_block", "fence"}
            or (token.type == "html_block" and token.content.lstrip().startswith("<!--"))
        ):
            ignored_lines.update(range(first_line, after_line))
    assert start is not None, f"no section {heading!r}"
    return "\n".join(lines[index] for index in range(start, stop) if index not in ignored_lines)


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


def test_links_survive_a_comment_opener_in_code_and_a_stray_backtick(tmp_path):
    text = (
        "Use `<!--` to hide notes. See [a](a.md).\n\n"
        "Press ` to open the console.\n\nSee [b](b.md).\n\n"
        "````\n```\n[c](c.md)\n```\n````\n\n~~~\n[d](d.md)\n~~~\n\nSee [e](e.md) and `x`.\n"
    )
    assert _links(tmp_path, text) == {"a.md", "b.md", "e.md"}


def test_linked_pages_reads_root_relative_and_angle_targets_and_commonmark_fences(tmp_path):
    (tmp_path / "page.md").write_text(
        "See [r](/docs/vision.md) and [a](<b.md>).\n\n"
        "```\n```text\n[c](c.md)\n```\n\n"
        "```\n[d](d.md)\n",
        encoding="utf-8",
    )
    expected = {(REPO / "docs" / "vision.md").resolve(), (tmp_path / "b.md").resolve()}
    assert linked_pages(tmp_path / "page.md") == expected


def test_section_ignores_a_comment_line_inside_fenced_code():
    text = "## A\n\nfirst\n\n```python\n# a comment\n```\n\nsecond\n\n## B\n\nthird\n"
    body = section(text, "## A")
    assert "first" in body and "second" in body and "third" not in body


def _links(tmp_path, markdown):
    """The names of the pages a one-page markdown sample links to."""
    page = tmp_path / "page.md"
    page.write_text(markdown, encoding="utf-8")
    linked_pages.cache_clear()  # the cache is keyed by path, and every sample reuses page.md
    return {path.name for path in linked_pages(page)}


def test_a_code_span_closes_only_on_a_backtick_run_of_its_own_length(tmp_path):
    # GitHub: the double-backtick span holds a lone backtick, so [a](a.md) is code and [b](b.md)
    # is a link; the lone backtick in the second paragraph opens nothing (no closer of length 1).
    sample = "``x ` [a](a.md) ``  and [b](b.md)\n\nA ` stray, then ``y`` and [c](c.md).\n"
    assert _links(tmp_path, sample) == {"b.md", "c.md"}
    # a run of two is not the closer of a span opened by one: nothing closes it, so both are text
    assert _links(tmp_path, "`[d](d.md)`` and [e](e.md)\n") == {"d.md", "e.md"}
    # and a span of one skips the runs of two inside it and closes at its own length
    assert _links(tmp_path, "`a `` b` [f](f.md)\n") == {"f.md"}


def test_a_backtick_run_without_a_matching_closer_is_literal_text(tmp_path):
    sample = "Open with ``` here and [a](a.md), close with `` and [b](b.md).\n"
    assert _links(tmp_path, sample) == {"a.md", "b.md"}


def test_fences_nested_deep_in_list_items_hide_their_links(tmp_path):
    sample = (
        "- item\n\n    - nested\n\n      ~~~\n      [a](a.md)\n\n      [x](x.md)\n      ~~~\n\n"
        "1. step\n\n   ~~~~\n   ~~~\n   [b](b.md)\n\n   [y](y.md)\n   ~~~~\n\n[c](c.md)\n"
    )
    assert _links(tmp_path, sample) == {"c.md"}


def test_an_indented_code_block_hides_its_links_but_a_lazy_continuation_does_not(tmp_path):
    sample = (
        "Paragraph.\n\n    [a](a.md)\n    still code [b](b.md)\n\n\t[c](c.md)\n\n"
        "Text\n    [d](d.md) is a lazy continuation.\n\n"
        "- item\n\n  continued [e](e.md)\n\n      code [f](f.md)\n"
    )
    assert _links(tmp_path, sample) == {"d.md", "e.md"}


def test_a_section_runs_through_its_subheadings_and_ends_at_the_same_or_a_higher_level():
    text = "# T\n\n## A\n\nfirst\n\n### Sub\n\nsub text\n\n#### Deeper\n\ndeep\n\n## B\n\nthird\n"
    body = section(text, "## A")
    assert "sub text" in body and "deep" in body and "third" not in body
    assert "deep" in section(text, "### Sub") and "third" not in section(text, "### Sub")
    assert "third" not in section("## A\n\nx\n\n# Top\n\nthird\n", "## A")


def test_a_section_heading_may_carry_trailing_spaces_and_a_crlf():
    text = "## A  \r\n\r\nfirst\r\n\r\n## B \r\n\r\nsecond\r\n"
    body = section(text, "## A")
    assert "first" in body and "second" not in body
    assert "second" in section(text, "## B")


@pytest.mark.parametrize("boundary", ["  ## B", "##", "B\n---"])
def test_a_section_ends_at_any_top_level_heading_of_the_same_depth(boundary):
    text = f"## A\n\ninside\n\n{boundary}\n\noutside\n"
    body = section(text, "## A")
    assert "inside" in body and "outside" not in body


def test_subheadings_inside_containers_and_code_do_not_end_a_section():
    text = "  ## A ##\n\n> ## Quote\n\n```\n## Example\n```\n\ninside\n\n## B\n\noutside\n"
    body = section(text, "## A")
    assert "inside" in body and "outside" not in body and "Example" not in body


def test_a_reference_definition_counts_only_when_the_page_uses_its_label(tmp_path):
    sample = (
        "See [shown][Used Label], [again][] and [short], plus [inline](d.md).\n\n"
        "[used   label]: a.md\n[again]: b.md\n[SHORT]: c.md\n[orphan]: e.md\n"
    )
    assert _links(tmp_path, sample) == {"a.md", "b.md", "c.md", "d.md"}
    assert _links(tmp_path, "No link here.\n\n[orphan]: e.md\n") == set()


def test_an_escaped_backtick_opens_no_code_span(tmp_path):
    # GitHub: the escaped backtick is text, so [a](a.md) is a link and the real span is `[b](b.md)`.
    sample = "Cost is \\` 5 [a](a.md) and then `[b](b.md)` ends.\n"
    assert _links(tmp_path, sample) == {"a.md"}
    # a link inside a real span after the escape stays code, and an escaped backtick pair is text
    assert _links(tmp_path, "\\`x\\` [c](c.md) `[d](d.md)`\n") == {"c.md"}


def test_an_escaped_bracket_starts_no_link(tmp_path):
    assert _links(tmp_path, "Literal \\[a](a.md) and [b](b.md).\n") == {"b.md"}


@pytest.mark.parametrize(
    "sample",
    [
        "```\n    ```\n[sample](sample.md)\n```\n\n[real](real.md)",
        "- ```\n  [sample](sample.md)\n  ```\n\n[real](real.md)",
        "- ```\n  [sample](sample.md)\n[real](real.md)",
        "```\nexample\n```\n    [sample](sample.md)\n\n[real](real.md)",
        "Text\n    ```\nmore\n\n[real](real.md)",
        "<!--\n```\n-->\n[real](real.md)",
        "Paragraph\n* * *\n    [sample](sample.md)\n\n[real](real.md)",
    ],
)
def test_only_fences_valid_in_their_block_hide_links(tmp_path, sample):
    assert _links(tmp_path, sample) == {"real.md"}


@pytest.mark.parametrize(
    "sample",
    [
        "[ref]\n\n[REF]: real.md\n[ref]: sample.md",
        "[ref]\n\n[ref]:\n  real.md",
        "![ref] ![alt][ref] ![ref][] ![alt](sample.md) [real](real.md)\n\n[ref]: sample.md",
        "Paragraph\n[ref]: sample.md\n\n[ref] [real](real.md)",
        r"\[escaped](sample.md) \\[real](real.md) \\\[escaped](sample.md)",
        r"[visible][edge\]]" "\n\n" r"[edge\[]: sample.md" "\n" r"[edge\]]: real.md",
    ],
)
def test_only_rendered_links_count_as_reachable(tmp_path, sample):
    assert _links(tmp_path, sample) == {"real.md"}


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


@functools.cache
def live_text() -> str:
    return (DOCS / "live.md").read_text("utf-8")


def test_live_md_says_the_flag_belongs_to_the_backend_not_to_the_call():
    body = squash(section(live_text(), "### Experimental images and long context"))
    for needle in (
        "a backend built with `images=True` sends the images header on every call it makes",
        "including a call with no image or Box question",
        "a backend built with `long_context=True` does the same with the long-context header",
        "a backend built without a flag sends no header for it",
    ):
        assert needle in body, needle


def test_live_md_documents_the_sdk_default_compression():
    body = squash(section(live_text(), "## What a call does"))
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
    with LiveBackend("jev-1.13.0", sleep=lambda s: None):
        pass
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
