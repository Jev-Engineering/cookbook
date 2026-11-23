"""The pull-request template's baseline line is conditional (#222, gap 4).

CONTRIBUTING.md section 6 compares with the baseline the issue names "when there is one". The
template line must say so, or a builder of a recipe whose issue names no baseline has to tick
something inapplicable or hand-annotate it.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / ".github" / "pull_request_template.md"
GOLD_LINE_START = "- [ ] Evaluation against gold labels"


def _baseline_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(GOLD_LINE_START)]


def _is_conditional(line: str) -> bool:
    return "baseline the issue names" in line and line.rstrip().endswith(", if any")


def test_the_template_has_exactly_one_gold_label_evaluation_line():
    assert len(_baseline_lines(TEMPLATE.read_text("utf-8"))) == 1


def test_the_baseline_clause_is_conditional():
    (line,) = _baseline_lines(TEMPLATE.read_text("utf-8"))
    assert _is_conditional(line), line


def test_the_check_rejects_the_unconditional_wording():
    # mutation: the wording this change replaced must fail the same check
    assert not _is_conditional(
        "- [ ] Evaluation against gold labels, with the baseline the issue names"
    )
    assert _is_conditional(
        "- [ ] Evaluation against gold labels, with the baseline the issue names, if any"
    )
