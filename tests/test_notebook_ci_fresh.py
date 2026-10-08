"""tools/check_notebook_fresh.py: the staleness check, with probes that change one thing.

The reference is the real template notebook executed once by tools/execute_notebook.py. Every
probe edits a copy of that run (the stand-in for the committed notebook) and must be rejected;
the controls (a run with different pixels but the same figure) must pass.
"""

import base64
import copy
import importlib.util
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from jev_cookbook.style import (
    apply_style,
    plot_answer_probabilities,
    plot_confusion_matrix,
    plot_threshold_sweep,
)

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "recipes" / "_template"
TOOL = REPO / "tools" / "check_notebook_fresh.py"

spec = importlib.util.spec_from_file_location("check_notebook_fresh_for_test", TOOL)
fresh_tool = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fresh_tool
spec.loader.exec_module(fresh_tool)

ANSWER = {"billing": 0.62, "tech": 0.25, "sales": 0.08, "other": 0.05}
MATRIX = [[8, 1, 0], [1, 7, 1], [0, 2, 6]]


def png_of(figure, dpi=100):
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight", dpi=dpi)
    return base64.b64encode(buffer.getvalue()).decode("ascii") + "\n"


def bars(probabilities=ANSWER, highlight="billing", title="One answer", dpi=100):
    apply_style()
    return png_of(plot_answer_probabilities(probabilities, highlight=highlight, title=title), dpi)


def heatmap(matrix=MATRIX, title="Test split, 27 examples", dpi=100):
    apply_style()
    labels = ["billing", "bug", "account"]
    return png_of(plot_confusion_matrix(matrix, labels=labels, title=title), dpi)


def sweep(chosen=0.5):
    apply_style()
    thresholds = [i / 20 for i in range(1, 20)]
    metrics = {
        "precision": np.linspace(0.6, 0.98, 19),
        "recall": np.linspace(0.97, 0.4, 19),
        "f1": np.linspace(0.7, 0.6, 19),
    }
    return png_of(plot_threshold_sweep(thresholds, metrics, chosen=chosen, title="Sweep"))


def shifted(delta):
    return {
        "billing": 0.62 - delta,
        "tech": 0.25 + delta,
        "sales": 0.08,
        "other": 0.05,
    }


# -- the figure comparison on its own ------------------------------------------------------------


def test_same_figure_at_another_pixel_size_matches():
    for dpi in (72, 100, 131, 200):
        same, detail = fresh_tool.compare_png(bars(), bars(dpi=dpi))
        assert same, (dpi, detail)
        same, detail = fresh_tool.compare_png(heatmap(), heatmap(dpi=dpi))
        assert same, (dpi, detail)


def test_identical_bytes_match_without_decoding():
    same, detail = fresh_tool.compare_png("not a png at all", "not a png at all")
    assert same and detail == "identical bytes"


@pytest.mark.parametrize("delta", [0.05, 0.08, 0.15, 0.3])
def test_a_bar_that_moves_is_a_different_figure(delta):
    same, detail = fresh_tool.compare_png(bars(), bars(probabilities=shifted(delta)))
    assert not same, detail


def test_a_different_highlighted_option_is_a_different_figure():
    same, _ = fresh_tool.compare_png(bars(), bars(highlight="tech"))
    assert not same


@pytest.mark.parametrize(
    "matrix",
    [
        [[8, 0, 1], [1, 7, 1], [0, 2, 6]],  # one count moved to another cell
        [[4, 1, 0], [1, 7, 1], [0, 2, 6]],  # a diagonal count fell
        [[8, 1, 0], [1, 7, 1], [2, 0, 6]],  # an error moved
    ],
)
def test_a_changed_heatmap_is_a_different_figure(matrix):
    same, detail = fresh_tool.compare_png(heatmap(), heatmap(matrix=matrix))
    assert not same, detail


def test_a_different_chart_type_is_a_different_figure():
    same, _ = fresh_tool.compare_png(bars(), heatmap())
    assert not same


def test_garbage_and_truncated_images_are_different():
    good = bars()
    for bad in ("", "AAAA", good[: len(good) // 2], "!!not base64!!"):
        same, detail = fresh_tool.compare_png(good, bad)
        assert not same, (bad[:10], detail)


def test_known_limits_small_changes_are_not_seen():
    # Documented in docs/notebook-ci.md: what the comparison cannot see. If one of these starts
    # to fail the comparison got stricter; update the documented limits with it.
    assert fresh_tool.compare_png(bars(), bars(title="Another answer"))[0]
    assert fresh_tool.compare_png(bars(), bars(probabilities=shifted(0.02)))[0]


def test_known_limits_a_moved_threshold_line_is_not_seen():
    # Documented in docs/notebook-ci.md: a thin line (a threshold or reference line, a curve, a
    # marker) is narrower than the comparison's 2 by 2 block, so moving it passes. The text outputs
    # are what guard such a chart. If this starts to fail the comparison got stricter.
    same, detail = fresh_tool.compare_png(sweep(0.5), sweep(0.6))
    assert same, detail


# -- whole notebooks -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference(tmp_path_factory):
    """The template notebook after one real execution, as parsed JSON."""
    folder = tmp_path_factory.mktemp("fresh") / "_template"
    shutil.copytree(TEMPLATE, folder, ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run(
        [sys.executable, str(REPO / "tools" / "execute_notebook.py"), str(folder)],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads((folder / "notebook.ipynb").read_text(encoding="utf-8"))


@pytest.fixture
def nb(reference):
    return copy.deepcopy(reference)


def problems_for(committed, fresh):
    return fresh_tool.check(committed, fresh)[0]


def png_outputs(notebook):
    return [
        output
        for cell in notebook["cells"]
        for output in cell.get("outputs", [])
        if "image/png" in output.get("data", {})
    ]


def cell_with(notebook, cell_id):
    return next(cell for cell in notebook["cells"] if cell.get("id") == cell_id)


def test_committed_notebook_equal_to_the_fresh_run_passes(nb, reference):
    problems, notes = fresh_tool.check(nb, reference)
    assert problems == []
    assert len(notes) == len(png_outputs(nb)) == 2


def test_template_committed_in_the_repository_matches_a_fresh_run(reference):
    committed = json.loads((TEMPLATE / "notebook.ipynb").read_text(encoding="utf-8"))
    assert problems_for(committed, reference) == []


def test_other_renderer_pixels_pass(reference):
    # The same two charts drawn at another resolution: the bytes and the pixel size differ, the
    # figures do not.
    committed, fresh = copy.deepcopy(reference), copy.deepcopy(reference)
    for notebook, dpi in ((committed, 100), (fresh, 131)):
        first, second = png_outputs(notebook)
        first["data"]["image/png"] = bars(dpi=dpi)
        second["data"]["image/png"] = heatmap(dpi=dpi)
    assert (
        png_outputs(committed)[0]["data"]["image/png"] != png_outputs(fresh)[0]["data"]["image/png"]
    )
    problems, notes = fresh_tool.check(committed, fresh)
    assert problems == [] and len(notes) == 2 and all("matches" in n for n in notes)


def test_source_edit_is_stale(nb, reference):
    cell = cell_with(nb, "python-rule")
    cell["source"] = [line.replace("0.5", "0.6") for line in cell["source"]]
    assert any("source" in p for p in problems_for(nb, reference))


def test_text_output_edit_is_stale(nb, reference):
    for cell in nb["cells"]:
        for output in cell.get("outputs", []):
            if output.get("output_type") == "stream":
                output["text"] = [line.replace("2", "3") for line in output["text"]]
    found = problems_for(nb, reference)
    assert found and all("committed" in p for p in found)


def test_table_like_text_plain_edit_is_stale(nb, reference):
    output = png_outputs(nb)[0]
    output["data"]["text/plain"] = "<Figure size 800x400 with 1 Axes>"
    assert any("text/plain" in p for p in problems_for(nb, reference))


def test_execution_count_edit_is_stale(nb, reference):
    cell_with(nb, "answer")["execution_count"] = 99
    assert any("execution_count" in p for p in problems_for(nb, reference))


def test_metadata_edit_is_stale(nb, reference):
    nb["metadata"]["kernelspec"]["name"] = "elsewhere"
    assert any("metadata" in p for p in problems_for(nb, reference))


def test_missing_outputs_are_stale(nb, reference):
    cell_with(nb, "answer")["outputs"] = []
    assert problems_for(nb, reference)


def test_a_cell_added_or_removed_is_stale(nb, reference):
    nb["cells"].pop()
    assert any("items committed" in p for p in problems_for(nb, reference))


def test_png_present_only_in_one_notebook_is_stale(nb, reference):
    del png_outputs(nb)[0]["data"]["image/png"]
    assert problems_for(nb, reference)


def test_other_image_types_are_not_normalised(nb, reference):
    png_outputs(nb)[0]["data"]["image/jpeg"] = "AAAA"
    assert any("image/jpeg" in p for p in problems_for(nb, reference))


def test_stale_figure_probe_changes_only_the_chart(nb, reference):
    # The probe the issue asks for: replace a committed teaching chart by a different one while
    # the cell source, the figure's text/plain, the execution counts and the text around it stay
    # exactly as they were. A comparison that ignores image/png would pass this.
    target = png_outputs(nb)[0]
    plain_before = target["data"]["text/plain"]
    target["data"]["image/png"] = bars(probabilities=shifted(0.15))
    assert target["data"]["text/plain"] == plain_before
    found = problems_for(nb, reference)
    assert len(found) == 1
    assert "answer-plot" in found[0] and "stale" in found[0]


def test_stale_heatmap_probe(nb, reference):
    target = png_outputs(nb)[1]
    target["data"]["image/png"] = heatmap(matrix=[[8, 1, 0], [1, 7, 1], [0, 2, 6]])
    found = problems_for(nb, reference)
    assert len(found) == 1 and "evaluation-matrix" in found[0]


def test_error_output_from_a_raises_exception_cell_fails_even_when_both_match(nb):
    error = {
        "output_type": "error",
        "ename": "ValueError",
        "evalue": "boom",
        "traceback": ["ValueError: boom"],
    }
    cell_with(nb, "answer")["outputs"].append(error)
    cell_with(nb, "answer")["metadata"]["tags"] = ["raises-exception"]
    twin = copy.deepcopy(nb)  # committed and fresh are identical, error included
    found = problems_for(nb, twin)
    assert len(found) == 2
    assert all("error output (ValueError)" in p for p in found)


def test_stderr_output_fails_even_when_both_match(nb):
    cell_with(nb, "answer")["outputs"].append(
        {"output_type": "stream", "name": "stderr", "text": ["warning\n"]}
    )
    found = problems_for(nb, copy.deepcopy(nb))
    assert len(found) == 2 and all("stderr" in p for p in found)


def test_skip_execution_cell_fails_even_when_both_match(nb):
    # nbclient's default never runs a cell tagged "skip-execution" (tools/execute_notebook.py does
    # not override it), so a fabricated output survives verbatim into the fresh run too: committed
    # and fresh end up identical, which is exactly why a presence-only comparison would miss it.
    target = cell_with(nb, "answer")
    target["metadata"]["tags"] = ["skip-execution"]
    target["outputs"] = [
        {
            "output_type": "stream",
            "name": "stdout",
            "text": ["Jev answered 100% of the hard cases correctly.\n"],
        }
    ]
    twin = copy.deepcopy(nb)
    found = problems_for(nb, twin)
    assert len(found) == 2
    assert all("skip-execution" in p for p in found)


def test_skip_execution_tag_matches_nbclients_actual_default():
    # SKIP_EXECUTION_TAGS hardcodes nbclient's own default rather than importing it (importing
    # would run the pinned version's own import-time side effects just to read one constant), so
    # a future bump of the pin that changes the default would otherwise go unnoticed.
    from nbclient import NotebookClient

    assert {NotebookClient.skip_cells_with_tag.default_value} == set(fresh_tool.SKIP_EXECUTION_TAGS)


def test_skip_execution_tag_on_a_markdown_cell_is_not_flagged(nb):
    # nbclient only ever skips a code cell; a markdown cell has no outputs to fabricate, so the
    # tag carries no meaning there and must not be flagged.
    target = cell_with(nb, "intro")
    assert target["cell_type"] == "markdown"
    target.setdefault("metadata", {})["tags"] = ["skip-execution"]
    twin = copy.deepcopy(nb)
    found = problems_for(nb, twin)
    assert not any("skip-execution" in p for p in found), found


def test_cli_exit_status_and_messages(reference, tmp_path):
    fresh_path = tmp_path / "fresh.ipynb"
    fresh_path.write_text(json.dumps(reference), encoding="utf-8")
    good = tmp_path / "good.ipynb"
    good.write_text(json.dumps(reference), encoding="utf-8")
    run = [sys.executable, str(TOOL)]
    ok = subprocess.run([*run, str(good), str(fresh_path)], capture_output=True, text=True)
    assert ok.returncode == 0 and "matches a fresh offline run" in ok.stdout

    stale = copy.deepcopy(reference)
    cell_with(stale, "answer")["execution_count"] = 99
    bad = tmp_path / "bad.ipynb"
    bad.write_text(json.dumps(stale), encoding="utf-8")
    result = subprocess.run([*run, str(bad), str(fresh_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "STALE:" in result.stdout and "not fresh" in result.stderr

    junk = tmp_path / "junk.ipynb"
    junk.write_text("not json", encoding="utf-8")
    result = subprocess.run([*run, str(junk), str(fresh_path)], capture_output=True, text=True)
    assert result.returncode == 2
    result = subprocess.run(
        [*run, str(tmp_path / "absent.ipynb"), str(fresh_path)], capture_output=True, text=True
    )
    assert result.returncode == 2


def test_differences_helper_names_the_path():
    found = fresh_tool.differences({"a": [1, {"b": "x"}]}, {"a": [1, {"b": "y"}]})
    assert found == ["notebook.a[1].b: committed 'x', fresh 'y'"]
    assert fresh_tool.differences({"a": 1}, {"a": True}) != []  # 1 and True are different types
