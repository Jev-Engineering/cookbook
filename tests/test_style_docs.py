"""docs/notebook-style.md must match the code it documents."""

import re
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np

from jev_cookbook import style

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "notebook-style.md"
FENCE = "`" * 3


def _blocks(language):
    pattern = FENCE + language + r"\n(.*?)" + FENCE
    return re.findall(pattern, DOC.read_text(encoding="utf-8"), flags=re.S)


def _text_block_after(marker):
    """The ```text``` fenced block that immediately follows ``marker`` in the doc, with its
    trailing newline stripped. Unlike `_blocks`, which returns every ```text``` block pooled
    together, this isolates one specific block by the heading that introduces it, so a check
    against it cannot be satisfied by a different block elsewhere in the file."""
    pattern = re.escape(marker) + r".*?" + FENCE + r"text\n(.*?)" + FENCE
    match = re.search(pattern, DOC.read_text(encoding="utf-8"), flags=re.S)
    assert match, f"no text block found after {marker!r} in {DOC.name}"
    return match.group(1).rstrip("\n")


def test_documented_header_texts_match_the_code():
    text = "\n".join(_blocks("text"))
    expected = [
        style.run_header_text(7, "Triage tickets", "synthetic"),
        style.run_header_text(
            7, "Triage tickets", "recorded", model="MODEL", recorded_on="2026-01-02"
        ).replace("2026-01-02", "DATE"),
        style.run_header_text(7, "Triage tickets", "live", model="MODEL"),
        style.run_header_text(7, "Triage tickets", "synthetic", n_examples=12),
    ]
    for header in expected:
        assert header in text


def test_documented_answer_view_matches_the_code():
    from dataclasses import dataclass

    @dataclass
    class Choice:
        choice: str
        probabilities: dict
        confidence: float
        provenance: str

    shown = style.format_answer(
        Choice("calm", {"calm": 0.7, "angry": 0.2, "excited": 0.1}, 0.9, "synthetic")
    )
    assert shown in "\n".join(_blocks("text"))


def test_documented_legend_wrap_before_and_after_match_the_code():
    from dataclasses import dataclass

    @dataclass
    class Score:
        score: float
        probabilities: dict
        confidence: float
        legend: dict
        provenance: str = "synthetic"

    legend = {
        "0": (
            "The reader cannot tell what happened to their request or what to do next, "
            "because the response omits the key fact, hides it behind an internal term or "
            "acronym the reader has no way to resolve, or states two things that contradict "
            "each other."
        )
    }
    answer = Score(0.60, {"0": 0.60}, 0.40, legend)
    before = style.format_answer(answer, width=None).splitlines()[1]
    after = "\n".join(style.format_answer(answer, width=style.LEGEND_WIDTH).splitlines()[1:-1])
    # Equality against each block in isolation, not containment against every ```text``` block
    # pooled together: the unwrapped `before` line is itself a substring of the wrapped `after`
    # block (its first wrapped line), so a containment check against the pooled text cannot
    # tell the Before rendering from the After rendering apart.
    assert _text_block_after("Before (one line, 300 columns and more") == before
    assert _text_block_after("After (the same level, default") == after


def test_the_documented_snippet_regenerates_every_linked_image(tmp_path, monkeypatch):
    snippet = _blocks("python")[-1]
    links = re.findall(r"\]\((assets/notebook-style/[^)]+\.png)\)", DOC.read_text(encoding="utf-8"))
    assert len(links) == 4
    monkeypatch.chdir(tmp_path)
    exec(compile(snippet, str(DOC), "exec"), {"__name__": "__docs__"})
    for link in links:
        image = mpimg.imread(tmp_path / "docs" / link)
        assert np.all(image[..., 3] == 1.0), f"{link} has transparent pixels"


def test_committed_example_images_exist_and_are_small():
    links = re.findall(r"\]\((assets/notebook-style/[^)]+\.png)\)", DOC.read_text(encoding="utf-8"))
    for link in links:
        path = ROOT / "docs" / link
        assert path.is_file(), f"missing {link}; run the snippet in {DOC.name}"
        assert path.stat().st_size < 60_000, f"{link} is larger than 60 kB"
