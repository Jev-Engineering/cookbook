"""Pin the accounting examples in docs/vision.md and the table's cell-text rule.

All results and ledger lines here are invented test data, not measurements.
"""

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jev_cookbook import NoulAnswer, Provenance, vision

DOCS = (Path(__file__).resolve().parents[1] / "docs" / "vision.md").read_text("utf-8")
MODEL = "jev-1.13.0"
DAY = "2026-10-31"


def _answers(model=MODEL):
    return {"q": NoulAnswer(0.5, Provenance.recorded(model, DAY))}


def _python_block(marker):
    start = DOCS.index(marker)
    begin = DOCS.rindex("```python\n", 0, start) + len("```python\n")
    return DOCS[begin : DOCS.index("```", begin)], DOCS.index("```", begin)


def _text_block_after(offset):
    begin = DOCS.index("```text\n", offset) + len("```text\n")
    return DOCS[begin : DOCS.index("```", begin)]


def _result(model=MODEL, usage=True):
    return SimpleNamespace(
        source="recorded",
        model=model,
        usage=SimpleNamespace(input_tokens=61, output_tokens=0) if usage else None,
        answers=_answers(model),
    )


def _documented_row(tmp_path):
    code, end = _python_block("measured = load_ledger_latency(ledger, key, result=result)")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {"k": {"status": "recorded", "model": MODEL, "date": DAY, "latency_seconds": 0.8}}
        ),
        encoding="utf-8",
    )
    namespace = {"ledger": ledger, "key": "k", "result": _result()}
    exec(compile(code, "docs/vision.md", "exec"), namespace)
    return namespace["row"], _text_block_after(end)


def test_documented_run_record_row_matches_the_docs(tmp_path):
    row, printed = _documented_row(tmp_path)
    assert f"{row}\n" == printed


def test_documented_three_row_table_matches_the_docs(tmp_path, monkeypatch):
    row, _ = _documented_row(tmp_path)
    monkeypatch.setattr(
        vision, "context_size", lambda state, questions: {"characters": 123, "utf8_bytes": 123}
    )
    code, end = _python_block("size = context_size(state, questions)")
    namespace = {
        "state": None,
        "questions": None,
        "row": row,
        "run_record": vision.run_record,
        "synthetic_result": SimpleNamespace(source="synthetic"),
        "unreported": _result(usage=False),
    }
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        exec(compile(code, "docs/vision.md", "exec"), namespace)
    assert out.getvalue() == _text_block_after(end)


@pytest.mark.parametrize("column", ["label", "model", "capture_date"])
@pytest.mark.parametrize(
    "control", ["\n", "\r", "\t", "\x00", "\x1b", "\x7f", "\u200b", "\u2028", "\u2029"]
)
def test_a_control_character_in_a_cell_is_refused_naming_the_column(column, control):
    row = {"mode": "synthetic", "label": "ok"}
    if column == "label":
        row["label"] = f"a{control}b"
    else:
        row = {"mode": "live", column: f"jev-1.13.0{control}x"}
    with pytest.raises(ValueError, match=column):
        vision.comparison_table([row])


def test_ordinary_non_ascii_cell_text_still_renders():
    table = vision.comparison_table([{"mode": "synthetic", "label": "café 📷"}])
    assert len(table.splitlines()) == 3
    assert "café 📷" in table
