"""The recipe contract carries the request-design rules of #658 in all three files."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section3() -> str:
    text = _read("CONTRIBUTING.md")
    start = text.index("### 3. Questions are narrow and typed")
    end = text.index("### 4. ", start)
    return text[start:end]


# One marker per rule: (name, regex that the CONTRIBUTING section 3 bullet must match).
RULES = {
    "dependent request": r"cannot build the second request until it has the first answer",
    "same request": r"can all be built before that answer, goes in the same request",
    "counting": r"Count in code.*one question per candidate",
    "numeric": r"Convert numeric representations in code.*named bucket",
    "score": r"Never read an exact magnitude out of a `Score`",
    "date": r"Compare dates and times in code",
    "noul direction": r"high `noul` means the condition the code acts on holds.*free of",
    "state size": r"Send only the `state` the question needs.*full-context arm.*README",
}


def test_every_rule_is_in_contributing_section_3():
    body = _section3()
    for name, pattern in RULES.items():
        assert re.search(pattern, body, re.S), name


def test_each_new_bullet_cites_s02_or_s07():
    bullets = [
        b
        for b in _section3().split("\n- ")
        if re.search(
            r"Count in code|Convert numeric|exact magnitude|Compare dates|Word a `Noul`|Send only the `state`",
            b,
        )
    ]
    assert len(bullets) == 6
    for b in bullets:
        assert "https://docs.typesafe.ai/model-jaggedness" in b, b[:40]
    noul = next(b for b in bullets if b.startswith("Word a `Noul`"))
    assert "https://docs.typesafe.ai/primitives/noul" in noul


def test_old_undefined_dependency_sentence_is_gone():
    old = "A question that depends on an earlier answer goes in a later request."
    for rel in ("CONTRIBUTING.md", "docs/glossary.md"):
        assert old not in _read(rel), rel


def test_template_and_glossary_carry_the_rules():
    for rel in ("docs/recipe-template.md", "docs/glossary.md"):
        text = " ".join(_read(rel).split())
        assert "high value means the condition" in text, rel
        assert "S07" in text and "S02" in text, rel
    assert "full-context arm" in " ".join(_read("docs/recipe-template.md").split())


def test_no_typesafe_figure_in_the_new_rules():
    body = _section3()
    assert not re.search(r"\d+(\.\d+)?\s*%", body)
