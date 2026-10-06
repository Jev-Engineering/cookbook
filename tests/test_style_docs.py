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


def test_documented_header_texts_match_the_code():
    text = "\n".join(_blocks("text"))
    expected = [
        style.run_header_text(7, "Triage tickets", "synthetic"),
        style.run_header_text(7, "Triage tickets", "recorded", model="MODEL", recorded_on="DATE"),
        style.run_header_text(7, "Triage tickets", "live", model="MODEL"),
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
