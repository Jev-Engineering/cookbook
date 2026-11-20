"""Check the column alignment readers see in published notebook stdout (#217).

The notebook freshness check separately verifies that committed outputs reproduce offline.
Right-aligned tables have column labels above their counts. Lists, raw arrays, and plots
have no such header to compare.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RECIPES = REPO / "recipes"
PIPELINE_CHECK = " (a pipeline check, not a Jev result)"
PREDICTED = re.compile(r"\s*predicted ->(?=\s|$)")
MATRIX_TITLE = re.compile(r"^(?:\w+, )?(?:test )?confusion matrix\b", re.IGNORECASE)
BRACKETED = re.compile(r"""(?:^|\s)\[\s*(?:[0-9'"\[]|\])""")
GOLD = re.compile(r"\s*gold\s+")
# Two or more spaces separate layout columns. A single space can be part of a label.
FIELD = re.compile(r"\S+(?: \S+)*")


def _load_test_support(filename):
    # The test directory is not a package under pytest's importlib mode.
    path = Path(__file__).with_name(f"{filename}.py")
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEMPLATE_HARNESS = _load_test_support("test_template_matrix_alignment")
KNOWN_FAILURES = _load_test_support("recipe_guard_known_failures").KNOWN_FAILURES


def _published_notebooks():
    catalog = json.loads((REPO / "catalog" / "recipes.json").read_text("utf-8"))
    for recipe in catalog["recipes"]:
        slug = recipe["slug"]
        path = RECIPES / slug / "notebook.ipynb"
        if path.is_file():
            reason = KNOWN_FAILURES.get((slug, "matrix_column_alignment"))
            marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
            yield pytest.param(path, id=slug, marks=marks)


def _matrix_headers(lines):
    for index, line in enumerate(lines):
        leader = PREDICTED.match(line)
        if leader:
            yield index, leader.end()
        elif MATRIX_TITLE.match(line.strip()):
            # Some tables print only column names on their own header line.
            for following_index in range(index + 1, len(lines)):
                following = lines[following_index]
                if following.strip():
                    if not (PREDICTED.match(following) or BRACKETED.search(following)):
                        yield following_index, 0
                    break


def _count_edges(row):
    counts = list(FIELD.finditer(row))[1:]
    if counts and all(count.group().isascii() and count.group().isdecimal() for count in counts):
        return [count.end() for count in counts]
    return []


def _matrix_alignment_errors(lines):
    # Ignore the disclosure words while retaining the table's indentation and padding.
    lines = [line.removesuffix(PIPELINE_CHECK) for line in lines]
    for index, leader_end in _matrix_headers(lines):
        header = lines[index]
        if GOLD.match(header) and _count_edges(header):
            yield f"line {index + 1}: missing column labels before {header.strip()!r}"
            continue
        edges = [leader_end + field.end() for field in FIELD.finditer(header[leader_end:])]
        if not edges:
            yield f"line {index + 1}: matrix header has no column labels"
            continue

        row_count = 0
        for row_index in range(index + 1, len(lines)):
            row = lines[row_index]
            actual = _count_edges(row)
            if not actual and not GOLD.match(row):
                break
            row_count += 1
            if edges != actual:
                yield (
                    f"line {row_index + 1}: {row.strip()!r} has count right edges {actual}, "
                    f"expected {edges} under {header.strip()!r}"
                )
        if not row_count:
            yield f"line {index + 1}: no count rows under {header.strip()!r}"


def _notebook_alignment_errors(path):
    cells = json.loads(path.read_text("utf-8"))["cells"]
    for cell in cells:
        stdout = "".join(
            "".join(output["text"])
            for output in cell.get("outputs", ())
            if output.get("output_type") == "stream" and output.get("name") == "stdout"
        )
        for error in _matrix_alignment_errors(stdout.splitlines()):
            yield f"{path.parent.name} cell {cell['id']} stdout {error}"


@pytest.mark.parametrize("notebook", list(_published_notebooks()))
def test_printed_matrix_rows_align_under_their_header(notebook):
    assert not (errors := list(_notebook_alignment_errors(notebook))), "\n".join(errors)


def test_count_wider_than_every_label_passes_only_with_the_corrected_width(capsys):
    labels, per_cell = TEMPLATE_HARNESS.CASES["count wider than every label"]
    source = TEMPLATE_HARNESS.matrix_cell_source()
    lines = TEMPLATE_HARNESS.run_cell(source, labels, per_cell, capsys)
    assert list(_matrix_alignment_errors(lines)) == []

    old_width = source.replace(
        "column = max(width, len(str(matrix.matrix.max())))", "column = width"
    )
    assert old_width != source
    lines = TEMPLATE_HARNESS.run_cell(old_width, labels, per_cell, capsys)
    errors = list(_matrix_alignment_errors(lines))
    assert len(errors) == len(labels)
    assert all("has count right edges" in error for error in errors)


@pytest.mark.parametrize(
    "lines",
    [
        [
            "confusion matrix, gold rows by predicted columns",
            "        left  right",
            "first      1      0",
        ],
        [
            "confusion matrix, gold content by final decision",
            "        left  right",
            "gold a     1      0",
        ],
    ],
    ids=["bare-row-label", "gold-row-label"],
)
def test_a_column_header_can_omit_the_predicted_leader(lines):
    assert list(_matrix_alignment_errors(lines)) == []
    lines[-1] = " " + lines[-1]
    assert len(list(_matrix_alignment_errors(lines))) == 1


def test_a_label_list_is_not_a_visually_aligned_header():
    lines = [
        "confusion matrix rows = gold, columns = predicted, in this order:",
        "['left', 'right']",
        "[[1 2]",
        " [2 1]]",
    ]
    assert list(_matrix_alignment_errors(lines)) == []


def test_the_template_matrix_with_multiword_labels_aligns(capsys):
    labels = ["some label", "other label", "none"]
    source = TEMPLATE_HARNESS.matrix_cell_source()
    lines = TEMPLATE_HARNESS.run_cell(source, labels, 7, capsys)
    assert list(_matrix_alignment_errors(lines)) == []

    # Moving the last row one character shifts all three counts under multiword headers.
    lines[-1] = " " + lines[-1]
    (error,) = list(_matrix_alignment_errors(lines))
    assert "count right edges [32, 45, 58], expected [31, 44, 57]" in error
