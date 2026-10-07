"""A cell ending with a returned Figure renders a PNG in a plain ipykernel session."""

import json
import sys

import matplotlib
import nbformat
import pytest
from nbclient import NotebookClient
from nbclient.exceptions import DeadKernelError

from jev_cookbook import style

SETUP = "from jev_cookbook.style import apply_style, plot_answer_probabilities\napply_style()"
WITHOUT_SETUP = "from jev_cookbook.style import plot_answer_probabilities"
CHART = 'plot_answer_probabilities({"billing": 0.2, "bug": 0.7, "feature": 0.1})'
HEADER = (
    "from jev_cookbook.style import run_header, show_answer\n"
    'run_header(7, "T", "synthetic", n_examples=3)'
)


@pytest.fixture
def kernel_name(tmp_path, monkeypatch):
    """A kernelspec that runs this session's interpreter, not whichever spec is found first."""
    spec = tmp_path / "kernels" / "jevtest"
    spec.mkdir(parents=True)
    argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
    (spec / "kernel.json").write_text(
        json.dumps({"argv": argv, "display_name": "jevtest", "language": "python"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JUPYTER_PATH", str(tmp_path))
    return "jevtest"


def _run(first_cell, second_cell, kernel_name, tmp_path):
    # Starting the kernel is retried once (never a cell): under load a kernel can lose a TCP
    # port race or exit before it answers, which nbclient reports as a start-up RuntimeError.
    for attempt in (1, 2):
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell(first_cell),
            nbformat.v4.new_code_cell(second_cell),
        ]
        client = NotebookClient(
            nb,
            kernel_name=kernel_name,
            timeout=120,
            startup_timeout=180,
            resources={"metadata": {"path": str(tmp_path)}},
        )
        try:
            client.execute()
        except RuntimeError as error:
            started = not any(m in str(error) for m in ("didn't respond", "died before replying"))
            if started or isinstance(error, DeadKernelError) or attempt == 2:
                raise
        else:
            return nb.cells[1].outputs


def test_a_returned_figure_renders_a_png_after_apply_style(kernel_name, tmp_path):
    outputs = _run(SETUP, CHART, kernel_name, tmp_path)
    assert [o.output_type for o in outputs] == ["execute_result"]
    assert outputs[0].data["image/png"].startswith("iVBORw0KGgo")  # PNG signature, base64


def test_negative_control_without_apply_style_shows_no_image(kernel_name, tmp_path):
    outputs = _run(WITHOUT_SETUP, CHART, kernel_name, tmp_path)
    assert [set(o.data) for o in outputs] == [{"text/plain"}]


def test_a_cell_ending_with_run_header_has_no_echoed_output(kernel_name, tmp_path):
    outputs = _run(SETUP, HEADER, kernel_name, tmp_path)
    assert [o.output_type for o in outputs] == ["stream"]


def test_apply_style_does_nothing_outside_ipython():
    import IPython

    assert IPython.get_ipython() is None  # a plain pytest process
    with matplotlib.rc_context():
        style.apply_style()


def test_apply_style_registers_one_png_formatter_and_twice_is_harmless(monkeypatch):
    import IPython
    from IPython.core.formatters import DisplayFormatter
    from matplotlib.figure import Figure

    display = DisplayFormatter()
    shell = type("Shell", (), {"display_formatter": display})()
    monkeypatch.setattr(IPython, "get_ipython", lambda: shell)
    assert display.formatters["image/png"].type_printers == {}
    with matplotlib.rc_context():
        style.apply_style()
        style.apply_style()
    assert list(display.formatters["image/png"].type_printers) == [Figure]
    data, _ = display.format(style.plot_answer_probabilities({"a": 0.4, "b": 0.6}))
    assert data["image/png"][:4] == b"\x89PNG"
