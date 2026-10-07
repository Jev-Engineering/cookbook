"""Fixture files of a recipe: load them, and validate them.

A recipe's ``fixtures/`` folder holds three files (specification: ``docs/fixtures.md``):

* ``inputs.jsonl``: one example per line (``id``, ``split``, ``state`` or ``fields``,
  ``replay_keys``);
* ``labels.jsonl``: one gold label per line (``id``, ``label``);
* ``responses.json``: ``{replay_key: stored response}``, the format ``ReplayBackend`` reads.

Every helper takes the recipe directory explicitly and defaults to the current working
directory, which is where a recipe's notebook runs::

    from jev_cookbook import get_backend
    from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

    examples = load_inputs()
    labels = load_labels()
    backend = get_backend(fixtures=responses_path())

Check a recipe from the command line with
``python -m jev_cookbook.fixtures validate recipes/NN-slug``.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..answers import RECORDED_SOURCE, SYNTHETIC_SOURCE, DecisionResult
from ._scan import scan_text
from ._schema import check, load_schema

__all__ = [
    "FIXTURES_DIR",
    "INPUTS_FILE",
    "LABELED_SPLITS",
    "LABELS_FILE",
    "REQUIRED_SPLITS",
    "RESPONSES_FILE",
    "SPLITS",
    "Example",
    "FixtureFileError",
    "Problem",
    "fixtures_dir",
    "load_inputs",
    "load_labels",
    "load_responses",
    "load_schema",
    "responses_path",
    "select_split",
    "validate_all",
    "validate_recipe",
]

FIXTURES_DIR = "fixtures"
INPUTS_FILE = "inputs.jsonl"
LABELS_FILE = "labels.jsonl"
RESPONSES_FILE = "responses.json"

SPLITS = ("train", "validation", "test", "demo")
REQUIRED_SPLITS = ("validation", "test")
LABELED_SPLITS = ("train", "validation", "test")  # every example in these needs a gold label

PathLike = str | os.PathLike[str]


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a fixture folder. ``str()`` names the file, line and id."""

    file: str
    message: str
    line: int | None = None
    ident: str | None = None

    def __str__(self) -> str:
        where = self.file + (f":{self.line}" if self.line else "")
        who = f" (id {self.ident!r})" if self.ident else ""
        return f"{where}{who}: {self.message}"


class FixtureFileError(ValueError):
    """A fixture file is missing or malformed. ``.problems`` lists every ``Problem``."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


@dataclass(frozen=True)
class Example:
    """One input example. Exactly one of ``state`` and ``fields`` is not ``None``."""

    id: str
    split: str
    replay_keys: tuple[str, ...]
    state: Any = None
    fields: Mapping[str, Any] | None = None


def fixtures_dir(recipe_dir: PathLike | None = None) -> Path:
    """The ``fixtures/`` folder of ``recipe_dir`` (default: the current directory)."""
    return Path(recipe_dir if recipe_dir is not None else ".") / FIXTURES_DIR


def responses_path(recipe_dir: PathLike | None = None) -> Path:
    """Path of the responses file, for ``get_backend(fixtures=...)``."""
    return fixtures_dir(recipe_dir) / RESPONSES_FILE


# --------------------------------------------------------------------------- reading


def _display(path: Path) -> str:
    return path.as_posix()


def _read(path: Path) -> tuple[str | None, list[Problem]]:
    """Read UTF-8 text (a leading byte order mark is dropped)."""
    name = _display(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, [Problem(name, "file is missing")]
    except OSError as exc:
        return None, [Problem(name, f"cannot read the file: {exc.strerror or exc}")]
    try:
        return raw.decode("utf-8-sig"), []
    except UnicodeDecodeError as exc:
        return None, [Problem(name, f"not valid UTF-8 (byte {exc.start}): {exc.reason}")]


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)


def _lines(text: str) -> list[str]:
    """Split on newlines only: ``str.splitlines()`` also splits on characters JSON allows."""
    return [line.rstrip("\r") for line in text.split("\n")]


def _read_jsonl(path: Path) -> tuple[list[tuple[int, Any]], list[Problem]]:
    """Parse JSON Lines: ``(line number, value)`` rows. Blank lines are skipped."""
    text, problems = _read(path)
    rows: list[tuple[int, Any]] = []
    if text is None:
        return rows, problems
    name = _display(path)
    for number, line in enumerate(_lines(text), start=1):
        if not line.strip():
            continue
        try:
            rows.append((number, _loads(line)))
        except ValueError as exc:
            problems.append(Problem(name, f"invalid JSON: {exc}", number))
    return rows, problems


def _schema_problems(
    rows: list[tuple[int, Any]], def_name: str, name: str
) -> tuple[list[tuple[int, dict[str, Any]]], list[Problem]]:
    schema = load_schema()
    good: list[tuple[int, dict[str, Any]]] = []
    problems: list[Problem] = []
    for number, value in rows:
        found = check(value, {"$ref": f"#/$defs/{def_name}"}, schema)
        ident = value.get("id") if isinstance(value, dict) else None
        ident = ident if isinstance(ident, str) else None
        for path, message in found:
            field = f"field {path!r}: " if path else ""
            problems.append(Problem(name, field + message, number, ident))
        if not found:
            good.append((number, value))
    return good, problems


def _read_inputs(path: Path) -> tuple[list[Example], list[Problem]]:
    name = _display(path)
    rows, problems = _read_jsonl(path)
    good, more = _schema_problems(rows, "input", name)
    problems += more
    examples: list[Example] = []
    seen: dict[str, int] = {}
    for number, row in good:
        if row["id"] in seen:
            msg = f"duplicate id (first used on line {seen[row['id']]})"
            problems.append(Problem(name, msg, number, row["id"]))
            continue
        seen[row["id"]] = number
        examples.append(
            Example(
                id=row["id"],
                split=row["split"],
                replay_keys=tuple(row["replay_keys"]),
                state=row.get("state"),
                fields=row.get("fields"),
            )
        )
    return examples, problems


def _read_labels(path: Path) -> tuple[dict[str, Any], dict[str, int], list[Problem]]:
    name = _display(path)
    rows, problems = _read_jsonl(path)
    good, more = _schema_problems(rows, "label", name)
    problems += more
    labels: dict[str, Any] = {}
    lines: dict[str, int] = {}
    for number, row in good:
        if row["id"] in labels:
            msg = f"duplicate id (first used on line {lines[row['id']]})"
            problems.append(Problem(name, msg, number, row["id"]))
            continue
        labels[row["id"]] = row["label"]
        lines[row["id"]] = number
    return labels, lines, problems


def _read_responses(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, DecisionResult], list[Problem]]:
    name = _display(path)
    text, problems = _read(path)
    raw: dict[str, dict[str, Any]] = {}
    parsed: dict[str, DecisionResult] = {}
    if text is None:
        return raw, parsed, problems
    try:
        data = _loads(text)
    except ValueError as exc:
        line = getattr(exc, "lineno", None)
        return raw, parsed, [Problem(name, f"invalid JSON: {exc}", line)]
    if not isinstance(data, dict):
        return raw, parsed, [Problem(name, "must be a JSON object of replay_key -> response")]
    if not data:
        return raw, parsed, [Problem(name, "has no responses")]
    for key, stored in data.items():
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            msg = f"replay key must be 64 lowercase hex characters: {key!r}"
            problems.append(Problem(name, msg))
            continue
        if not isinstance(stored, dict):
            problems.append(Problem(name, "response must be a JSON object", ident=key))
            continue
        try:
            parsed[key] = DecisionResult.from_dict(stored)
        except (ValueError, TypeError) as exc:
            problems.append(Problem(name, f"bad stored response: {exc}", ident=key))
            continue
        raw[key] = stored
    return raw, parsed, problems


def _raise(problems: list[Problem]) -> None:
    if problems:
        raise FixtureFileError(problems)


def load_inputs(recipe_dir: PathLike | None = None) -> list[Example]:
    """Read ``fixtures/inputs.jsonl`` as a list of ``Example`` in file order.

    Raises ``FixtureFileError`` (naming the file, the line and the id) if the file is
    missing, is not UTF-8 JSON Lines, breaks the schema, or repeats an id.
    """
    examples, problems = _read_inputs(fixtures_dir(recipe_dir) / INPUTS_FILE)
    _raise(problems)
    return examples


def load_labels(recipe_dir: PathLike | None = None) -> dict[str, Any]:
    """Read ``fixtures/labels.jsonl`` as ``{id: label}`` in file order."""
    labels, _, problems = _read_labels(fixtures_dir(recipe_dir) / LABELS_FILE)
    _raise(problems)
    return labels


def load_responses(recipe_dir: PathLike | None = None) -> dict[str, dict[str, Any]]:
    """Read ``fixtures/responses.json`` as ``{replay_key: stored response}``.

    Every stored response is parsed with ``DecisionResult.from_dict``, so a response that
    ``ReplayBackend`` would reject fails here, naming its key. Use ``responses_path`` with
    ``get_backend`` to replay them.
    """
    raw, _, problems = _read_responses(fixtures_dir(recipe_dir) / RESPONSES_FILE)
    _raise(problems)
    return raw


def select_split(examples: list[Example], split: str) -> list[Example]:
    """The examples of one split, in file order. An unknown split name is an error."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; the splits are {list(SPLITS)}")
    return [e for e in examples if e.split == split]


# ------------------------------------------------------------------------- validating


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def _check_cross_references(
    examples: list[Example],
    labels: dict[str, Any],
    label_lines: dict[str, int],
    responses: Mapping[str, Any],
    names: tuple[str, str, str],
) -> list[Problem]:
    inputs_name, labels_name, responses_name = names
    problems: list[Problem] = []
    for split in REQUIRED_SPLITS:
        if not any(e.split == split for e in examples):
            problems.append(Problem(inputs_name, f"no example has the required split {split!r}"))
    ids = {e.id for e in examples}
    for e in examples:
        if e.split in LABELED_SPLITS and e.id not in labels:
            msg = f"no label for the {e.split} example"
            problems.append(Problem(labels_name, msg, ident=e.id))
    for ident in labels:
        if ident not in ids:
            msg = "label for an id that is not in the inputs"
            problems.append(Problem(labels_name, msg, label_lines[ident], ident))
    referenced: set[str] = set()
    for e in examples:
        for key in e.replay_keys:
            referenced.add(key)
            if key not in responses:
                msg = f"no response for replay key {key} of this example"
                problems.append(Problem(responses_name, msg, ident=e.id))
    for key in responses:
        if key not in referenced:
            msg = "response that no input lists in replay_keys"
            problems.append(Problem(responses_name, msg, ident=key))
    # The same state in two splits leaks the test set into the choices made on validation.
    where: dict[str, list[Example]] = defaultdict(list)
    for e in examples:
        if e.state is not None and e.split != "demo":
            where[_canonical(e.state)].append(e)
    for same in where.values():
        first = same[0]
        for other in same[1:]:
            if other.split != first.split:
                msg = (
                    f"same state as {first.id!r} ({first.split}) in a different split "
                    f"({other.split})"
                )
                problems.append(Problem(inputs_name, msg, ident=other.id))
    return problems


def _check_provenance_agreement(parsed: Mapping[str, DecisionResult], name: str) -> list[Problem]:
    problems: list[Problem] = []
    synthetic = [k for k, r in parsed.items() if r.source == SYNTHETIC_SOURCE]
    recorded = [k for k, r in parsed.items() if r.source == RECORDED_SOURCE]
    if synthetic and recorded:
        msg = (
            f"mixes recorded answers ({len(recorded)} response(s)) with synthetic answers "
            f"({len(synthetic)} response(s), for example {synthetic[0]}); a responses file "
            "is all recorded or all synthetic"
        )
        problems.append(Problem(name, msg))
    models = sorted({r.model for r in parsed.values()})
    if len(models) > 1:
        problems.append(Problem(name, f"responses come from more than one model: {models}"))
    return problems


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [t for k, v in node.items() for t in [k, *_strings(v)]]
    if isinstance(node, list):
        return [t for v in node for t in _strings(v)]
    return []


def _scan_file(path: Path) -> list[Problem]:
    """Key-shaped strings in one fixture file.

    The raw text is scanned (it gives line numbers), and so is every decoded JSON string,
    because JSON escapes quotes: ``api_key = \\"...\\"`` inside a string is invisible to a scan
    of the raw line.
    """
    text, _ = _read(path)
    if text is None:
        return []
    name = _display(path)
    found: list[tuple[int | None, str | None, str, str]] = []  # line, id, rule, snippet
    raw_hits = scan_text(text)
    found.extend((line, None, rule, snip) for line, rule, snip in raw_hits)
    seen = {(line, rule) for line, rule, _ in raw_hits}
    seen_rules = {rule for _, rule, _ in raw_hits}
    if path.suffix == ".jsonl":
        for number, line in enumerate(_lines(text), start=1):
            try:
                value = _loads(line) if line.strip() else None
            except ValueError:
                continue
            for string in _strings(value):
                for _, rule, snip in scan_text(string):
                    if (number, rule) not in seen:
                        seen.add((number, rule))
                        found.append((number, None, rule, snip))
    else:
        try:
            data = _loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key, stored in data.items():
                for string in _strings(stored):
                    for _, rule, snip in scan_text(string):
                        if rule not in seen_rules:
                            seen_rules.add(rule)
                            found.append((None, key, rule, snip))
    return [
        Problem(name, f"looks like a key or token [{rule}]: {snip}", line, ident)
        for line, ident, rule, snip in found
    ]


def validate_recipe(recipe_dir: PathLike | None = None) -> list[Problem]:
    """Every problem in a recipe's ``fixtures/`` folder; an empty list means it is valid."""
    folder = fixtures_dir(recipe_dir)
    if not folder.is_dir():
        return [Problem(_display(folder), "fixtures folder is missing")]
    paths = (folder / INPUTS_FILE, folder / LABELS_FILE, folder / RESPONSES_FILE)
    names = tuple(_display(p) for p in paths)
    examples, problems = _read_inputs(paths[0])
    labels, label_lines, more = _read_labels(paths[1])
    problems += more
    raw, parsed, more = _read_responses(paths[2])
    problems += more
    # Cross-checks need all three files to have been read, or they would only restate a
    # missing file as many misleading problems.
    unreadable = {p.file for p in problems if p.line is None and p.ident is None}
    if not raw:
        unreadable.add(names[2])
    if not unreadable & set(names):
        problems += _check_cross_references(examples, labels, label_lines, raw, names)
    problems += _check_provenance_agreement(parsed, names[2])
    for path in paths:
        problems += _scan_file(path)
    return problems


def validate_all(recipes_dir: PathLike = "recipes") -> dict[str, list[Problem]]:
    """Validate ``<recipes_dir>/*/fixtures`` for every recipe that has such a folder.

    Returns ``{recipe directory: problems}``; a recipe without a ``fixtures`` folder is
    not checked (the recipe contract, not this validator, requires the folder).
    """
    root = Path(recipes_dir)
    results: dict[str, list[Problem]] = {}
    if root.is_dir():
        for recipe in sorted(p for p in root.iterdir() if (p / FIXTURES_DIR).is_dir()):
            results[_display(recipe)] = validate_recipe(recipe)
    return results
