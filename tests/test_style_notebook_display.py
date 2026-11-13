"""A cell ending with a returned Figure renders a PNG in a plain ipykernel session."""

import importlib.util
import json
import sys
from pathlib import Path

import matplotlib
import nbformat
import pytest
from nbclient import NotebookClient

from jev_cookbook import style


def _load_executor():
    path = Path(__file__).resolve().parent.parent / "tools" / "execute_notebook.py"
    spec = importlib.util.spec_from_file_location("execute_notebook_for_display_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


executor = _load_executor()

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
    # Starting the kernel is retried (never a cell) by the executor's own helper, so this file has
    # the executor's budgets and cannot drift from them: under load a kernel can lose a TCP port
    # race or exit before it answers, which nbclient reports as a start-up RuntimeError (#328).
    def attempt():
        nb = nbformat.v4.new_notebook()
        nb.cells = [
            nbformat.v4.new_code_cell(first_cell),
            nbformat.v4.new_code_cell(second_cell),
        ]
        client = NotebookClient(
            nb,
            kernel_name=kernel_name,
            timeout=120,
            startup_timeout=executor.START_WAIT,
            resources={"metadata": {"path": str(tmp_path)}},
        )
        client.execute()
        return nb.cells[1].outputs

    return executor.retry_failed_starts(attempt, kernel_name)


@pytest.mark.parametrize("message", sorted(executor.START_ATTEMPTS))
def test_the_kernel_start_budgets_are_the_executors(message, kernel_name, tmp_path, monkeypatch):
    """This file starts its own kernels, so its retries must be the executor's, not a copy: a start
    that fails with each of the executor's two messages is tried exactly as often as the executor
    tries it, and then fails."""
    budget = executor.START_ATTEMPTS[message]
    failure = f"{message} to kernel_info"
    starts = []

    def fail(self, *args, **kwargs):
        starts.append(1)
        raise RuntimeError(failure)

    monkeypatch.setattr(NotebookClient, "execute", fail)
    with pytest.raises(executor.KernelStartError, match=f"{budget} start attempts failed"):
        _run("1", "2", kernel_name, tmp_path)
    assert len(starts) == budget

    starts.clear()

    def fail_all_but_the_last(self, *args, **kwargs):
        starts.append(1)
        if len(starts) < budget:
            raise RuntimeError(failure)

    monkeypatch.setattr(NotebookClient, "execute", fail_all_but_the_last)
    assert _run("1", "2", kernel_name, tmp_path) == []  # no kernel ran, so the cell has no output
    assert len(starts) == budget


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


# --- #232: a figure that is not the cell's result is still shown, exactly once ---------------

PRINT_AFTER = CHART + '\nprint("printed after the chart")'


def _images(outputs):
    return [o for o in outputs if "image/png" in getattr(o, "data", {})]


def test_a_print_after_the_chart_no_longer_drops_the_figure(kernel_name, tmp_path):
    # The recipe 32 instance: the figure vanished because a print followed the plot call.
    outputs = _run(SETUP, PRINT_AFTER, kernel_name, tmp_path)
    assert [o.output_type for o in outputs] == ["stream", "display_data"]
    assert outputs[0].text == "printed after the chart\n"
    assert outputs[1].data["image/png"].startswith("iVBORw0KGgo")


def test_a_chart_that_is_the_cell_result_is_not_shown_twice(kernel_name, tmp_path):
    outputs = _run(SETUP, CHART + "\n" + CHART, kernel_name, tmp_path)
    # two charts: the first shown at the end of the cell, the second as the cell's result
    assert len(_images(outputs)) == 2
    outputs = _run(SETUP, "x = 1\n" + CHART, kernel_name, tmp_path)
    assert len(_images(outputs)) == 1


def test_an_explicitly_displayed_chart_is_not_shown_again(kernel_name, tmp_path):
    cell = "from IPython.display import display\ndisplay(" + CHART + ')\nprint("done")'
    outputs = _run(SETUP, cell, kernel_name, tmp_path)
    assert [o.output_type for o in outputs] == ["display_data", "stream"]


def test_negative_control_without_apply_style_a_print_after_still_drops_it(kernel_name, tmp_path):
    outputs = _run(WITHOUT_SETUP, PRINT_AFTER, kernel_name, tmp_path)
    assert _images(outputs) == []


def test_a_chart_from_an_earlier_cell_is_not_shown_in_a_later_one(kernel_name, tmp_path):
    outputs = _run(
        SETUP + "\nfig = " + CHART + "\nprint('setup')", "print('next')", kernel_name, tmp_path
    )
    assert [o.output_type for o in outputs] == ["stream"]


def test_registering_twice_installs_one_end_of_cell_hook(monkeypatch):
    import IPython
    from IPython.core.events import EventManager, available_events
    from IPython.core.formatters import DisplayFormatter

    events = EventManager(None, available_events)
    shell = type("Shell", (), {"display_formatter": DisplayFormatter(), "events": events})()
    monkeypatch.setattr(IPython, "get_ipython", lambda: shell)
    monkeypatch.setattr(style, "_DISPLAY_ACTIVE", False)
    with matplotlib.rc_context():
        style.apply_style()
        style.apply_style()
    assert events.callbacks["post_execute"].count(style._show_unshown) == 1
