"""Fixture files of a recipe: load them, and validate them.

A recipe's ``fixtures/`` folder holds these files and no others (specification:
``docs/fixtures.md``):

* ``inputs.jsonl``: one example per line (``id``, ``split``, ``state`` or ``fields``,
  ``replay_keys``);
* ``labels.jsonl``: one gold label per line (``id``, ``label``);
* ``responses.json``: ``{replay_key: stored response}``, the format ``ReplayBackend`` reads;
  absent when no example lists a replay key (a scripted or simulated recipe);
* ``responses-<tag>.json``: optional, the same format, for a comparison recipe that replays
  a second model's answers to the same requests.

Every helper takes the recipe directory explicitly and defaults to the current working
directory, which is where a recipe's notebook runs::

    from jev_cookbook import get_backend
    from jev_cookbook.fixtures import load_inputs, load_labels, responses_path

    examples = load_inputs()
    labels = load_labels()
    backend = get_backend(fixtures=responses_path())

Check a recipe from the command line with
``python -m jev_cookbook.fixtures validate recipes/NN-slug``.

``stable_permutation`` and ``stable_shuffle`` (``.permutation``) give a deterministic,
documented-stable per-item order for things like option order and first-shown sides; see
``docs/fixtures.md``, "Per-item option order".
"""

from __future__ import annotations

import codecs
import json
import os
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._canonical import MAX_DEPTH
from ..answers import RECORDED_SOURCE, SYNTHETIC_SOURCE, DecisionResult
from ._scan import scan_text
from ._schema import check, load_schema
from .permutation import stable_permutation, stable_shuffle

__all__ = [
    "FIXTURES_DIR",
    "INPUTS_FILE",
    "LABELED_SPLITS",
    "LABELS_FILE",
    "REQUIRED_SPLITS",
    "MODES",
    "RESPONSES_FILE",
    "SPLITS",
    "Example",
    "FixtureFileError",
    "Problem",
    "Report",
    "fixtures_dir",
    "load_inputs",
    "load_labels",
    "load_responses",
    "load_schema",
    "responses_path",
    "select_split",
    "stable_permutation",
    "stable_shuffle",
    "validate_all",
    "validate_recipe",
]

FIXTURES_DIR = "fixtures"
INPUTS_FILE = "inputs.jsonl"
LABELS_FILE = "labels.jsonl"
RESPONSES_FILE = "responses.json"

MODES = ("replay", "scripted")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")  # the id rule of schema.json; tags use it too
_TAGGED_RESPONSES = re.compile(r"responses-(.+)[.]json")

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


class Report(list):  # a list of Problem; empty means valid
    """What ``validate_recipe`` returns: the ``Problem`` list, plus the recipe's ``mode``.

    ``mode`` is ``"replay"`` when some example lists a replay key, ``"scripted"`` when none
    does (the notebook then drives ``ScriptedBackend`` or a simulator and replays nothing), and
    ``None`` when ``inputs.jsonl`` could not be read so the mode is unknown.
    """

    def __init__(self, problems=(), mode: str | None = None) -> None:
        super().__init__(problems)
        self.mode = mode

    # Slicing, ``copy()`` and ``report + problems`` keep the mode; other list operations
    # (``sorted``, ``*``) return a plain list.
    def __getitem__(self, index):
        picked = super().__getitem__(index)
        return Report(picked, self.mode) if isinstance(index, slice) else picked

    def __add__(self, other):
        return Report(super().__add__(other), self.mode)

    def copy(self) -> Report:
        return Report(self, self.mode)

    def __repr__(self) -> str:
        return f"Report(mode={self.mode!r}, problems={list.__repr__(self)})"


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


def responses_file_name(tag: str | None = None) -> str:
    """``responses.json``, or ``responses-<tag>.json`` (the tag follows the id rule)."""
    if tag is None:
        return RESPONSES_FILE
    if not _ID.fullmatch(tag):
        raise ValueError(f"bad responses tag {tag!r}: use letters, digits, '_', '.' and '-'")
    if ".drift-" in tag:
        # the validator treats any name containing ".drift-" as a stray comparison file
        raise ValueError(f"bad responses tag {tag!r}: '.drift-' marks a comparison file, not a tag")
    return f"responses-{tag}.json"


def responses_path(recipe_dir: PathLike | None = None, tag: str | None = None) -> Path:
    """Path of a responses file, for ``get_backend(fixtures=...)``: the default or a tagged one."""
    return fixtures_dir(recipe_dir) / responses_file_name(tag)


# --------------------------------------------------------------------------- reading


def _display(path: Path) -> str:
    return path.as_posix()


def _read(path: Path, *, allow_bom: bool = True) -> tuple[str | None, list[Problem]]:
    """Read UTF-8 text. A leading byte order mark is dropped, unless ``allow_bom`` is false.

    Responses files refuse one: ``ReplayBackend.from_json`` opens them as plain UTF-8 and
    cannot parse a file that starts with it.
    """
    name = _display(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, [Problem(name, "file is missing")]
    except OSError as exc:
        return None, [Problem(name, f"cannot read the file: {exc.strerror or exc}")]
    if not allow_bom and raw.startswith(codecs.BOM_UTF8):
        msg = "starts with a UTF-8 byte order mark, which ReplayBackend cannot read; save the file without one"
        return None, [Problem(name, msg)]
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


# MAX_DEPTH (64): no JSON value in a fixture file nests deeper; see docs/fixtures.md. It is
# defined in _canonical so replay_key applies the same limit.
# A string (skipped) or a bracket. A string that never closes runs to the end of the text: the
# parser stops there, and it keeps the scan linear.
_TOKENS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?|[\[\]{}]', re.S)


class _TooDeep(ValueError):
    def __init__(self, line: int) -> None:
        super().__init__(f"nested deeper than {MAX_DEPTH} levels")
        self.lineno = line


def _check_depth(text: str) -> None:
    """Raise ``_TooDeep`` if brackets nest deeper than ``MAX_DEPTH`` outside strings.

    A scan, not a parse: it never recurses, so the answer is the same on every interpreter and
    stack size, and it runs before ``json.loads`` so the parser's own limit never decides.
    """
    depth = 0
    for match in _TOKENS.finditer(text):
        char = match.group()
        if char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise _TooDeep(text.count("\n", 0, match.start()) + 1)
        elif char in "]}":
            depth -= 1


def _loads(text: str) -> Any:
    """Strict ``json.loads``: no duplicate keys, no NaN, nesting at most ``MAX_DEPTH``.

    Failures are ``ValueError``, so callers report them instead of crashing. The
    ``RecursionError`` conversion is a backstop for a parser that overflows anyway.
    """
    _check_depth(text)
    try:
        return json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_reject_constant)
    except RecursionError:
        raise ValueError("nested too deeply to read") from None


def _lines(text: str) -> list[str]:
    """Split on newlines only: ``str.splitlines()`` also splits on characters JSON allows."""
    return [line.rstrip("\r") for line in text.split("\n")]


def _read_jsonl(path: Path) -> tuple[list[tuple[int, Any]], list[Problem], bool]:
    """Parse JSON Lines: ``(line number, value)`` rows, problems, and whether it was readable.

    Blank lines are skipped. A bad line is a problem with a line number; the file still counts
    as readable. Unreadable means missing, not UTF-8, or not a file.
    """
    text, problems = _read(path)
    rows: list[tuple[int, Any]] = []
    if text is None:
        return rows, problems, False
    name = _display(path)
    for number, line in enumerate(_lines(text), start=1):
        if not line.strip():
            continue
        try:
            rows.append((number, _loads(line)))
        except ValueError as exc:
            problems.append(Problem(name, f"invalid JSON: {exc}", number))
    return rows, problems, True


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


def _repeated_id(
    name: str, ident: str, number: int, seen: dict[str, tuple[str, int]]
) -> Problem | None:
    """A problem if ``ident`` repeats an earlier id exactly or differs from it only by case."""
    first = seen.get(ident.lower())
    if first is None:
        seen[ident.lower()] = (ident, number)
        return None
    other, line = first
    if other == ident:
        return Problem(name, f"duplicate id (first used on line {line})", number, ident)
    msg = f"id differs only by case from {other!r} (line {line}); ids become file names"
    return Problem(name, msg, number, ident)


def _read_inputs(path: Path) -> tuple[list[Example], list[Problem], bool]:
    name = _display(path)
    rows, problems, readable = _read_jsonl(path)
    good, more = _schema_problems(rows, "input", name)
    problems += more
    examples: list[Example] = []
    seen: dict[str, tuple[str, int]] = {}
    for number, row in good:
        repeat = _repeated_id(name, row["id"], number, seen)
        if repeat:
            problems.append(repeat)
            continue
        examples.append(
            Example(
                id=row["id"],
                split=row["split"],
                replay_keys=tuple(row["replay_keys"]),
                state=row.get("state"),
                fields=row.get("fields"),
            )
        )
    return examples, problems, readable


def _read_labels(path: Path) -> tuple[dict[str, Any], dict[str, int], list[Problem], bool]:
    name = _display(path)
    rows, problems, readable = _read_jsonl(path)
    good, more = _schema_problems(rows, "label", name)
    problems += more
    labels: dict[str, Any] = {}
    lines: dict[str, int] = {}
    seen: dict[str, tuple[str, int]] = {}
    for number, row in good:
        repeat = _repeated_id(name, row["id"], number, seen)
        if repeat:
            problems.append(repeat)
            continue
        labels[row["id"]] = row["label"]
        lines[row["id"]] = number
    return labels, lines, problems, readable


def _read_responses(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, DecisionResult], list[Problem], bool]:
    """The stored responses, their parsed form, problems, and whether the file was usable.

    Unusable (``False``) means the file as a whole cannot be trusted: it is missing, has a
    byte order mark, is not JSON, is not an object, or is empty. A bad single response or key
    is a problem, but the other responses are still checked.
    """
    name = _display(path)
    text, problems = _read(path, allow_bom=False)
    raw: dict[str, dict[str, Any]] = {}
    parsed: dict[str, DecisionResult] = {}
    if text is None:
        return raw, parsed, problems, False
    try:
        data = _loads(text)
    except ValueError as exc:
        line = getattr(exc, "lineno", None)
        return raw, parsed, [Problem(name, f"invalid JSON: {exc}", line)], False
    if not isinstance(data, dict):
        msg = "must be a JSON object of replay_key -> response"
        return raw, parsed, [Problem(name, msg)], False
    if not data:
        return raw, parsed, [Problem(name, "has no responses")], False
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
        except Exception as exc:  # any failure means ReplayBackend would reject it
            problems.append(Problem(name, f"bad stored response: {exc}", ident=key))
            continue
        raw[key] = stored
    return raw, parsed, problems, True


def _raise(problems: list[Problem]) -> None:
    if problems:
        raise FixtureFileError(problems)


def load_inputs(recipe_dir: PathLike | None = None) -> list[Example]:
    """Read ``fixtures/inputs.jsonl`` as a list of ``Example`` in file order.

    Raises ``FixtureFileError`` (naming the file, the line and the id) if the file is
    missing, is not UTF-8 JSON Lines, breaks the schema, or repeats an id.
    """
    examples, problems, _ = _read_inputs(fixtures_dir(recipe_dir) / INPUTS_FILE)
    _raise(problems)
    return examples


def load_labels(recipe_dir: PathLike | None = None) -> dict[str, Any]:
    """Read ``fixtures/labels.jsonl`` as ``{id: label}`` in file order."""
    labels, _, problems, _ = _read_labels(fixtures_dir(recipe_dir) / LABELS_FILE)
    _raise(problems)
    return labels


def load_responses(
    recipe_dir: PathLike | None = None, tag: str | None = None
) -> dict[str, dict[str, Any]]:
    """Read ``responses.json`` (or ``responses-<tag>.json``) as ``{replay_key: response}``.

    Every stored response is parsed with ``DecisionResult.from_dict``, so a response that
    ``ReplayBackend`` would reject fails here, naming its key; so does a file that
    ``ReplayBackend`` could not open (a byte order mark). Use ``responses_path`` with
    ``get_backend`` to replay them.
    """
    raw, _, problems, _ = _read_responses(responses_path(recipe_dir, tag))
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


def _content(e: Example) -> tuple[str, str]:
    """What an example is made of: its state, or its fields, in a comparable form."""
    if e.state is not None:
        return "state", _canonical(e.state)
    return "fields", _canonical(e.fields)


def _check_examples(
    examples: list[Example],
    labels: dict[str, Any] | None,
    label_lines: dict[str, int],
    names: tuple[str, str],
) -> list[Problem]:
    """Checks that need only the inputs, and the labels when they could be read."""
    inputs_name, labels_name = names
    problems: list[Problem] = []
    for split in REQUIRED_SPLITS:
        if not any(e.split == split for e in examples):
            problems.append(Problem(inputs_name, f"no example has the required split {split!r}"))
    if labels is not None:
        splits = {e.id: e.split for e in examples}
        for e in examples:
            if e.split in LABELED_SPLITS and e.id not in labels:
                msg = f"no label for the {e.split} example"
                problems.append(Problem(labels_name, msg, ident=e.id))
        for ident in labels:
            if ident not in splits:
                msg = "label for an id that is not in the inputs"
                problems.append(Problem(labels_name, msg, label_lines[ident], ident))
            elif splits[ident] == "demo":
                msg = "label for a demo example; demo examples are never scored, remove it"
                problems.append(Problem(labels_name, msg, label_lines[ident], ident))
    # The same content in two splits leaks the test set into the choices made on validation.
    where: dict[tuple[str, str], list[Example]] = defaultdict(list)
    for e in examples:
        if e.split in LABELED_SPLITS:
            where[_content(e)].append(e)
    for (what, _), same in where.items():
        first = same[0]
        for other in same[1:]:
            if other.split != first.split:
                msg = (
                    f"same {what} as {first.id!r} ({first.split}) in a different split "
                    f"({other.split})"
                )
                problems.append(Problem(inputs_name, msg, ident=other.id))
    # The content check above compares `state`/`fields`, which a `fields` example's build_state
    # can transform (dropping a Python-owned value) -- and never even looks at a `fields`
    # example's actual request -- so two examples can ask Jev the identical request without it
    # being noticed there. replay_keys is the hash of what Jev actually sees, so comparing it
    # directly catches that case too: the same *complete* set of keys (sorted, so listing them
    # out of order does not escape comparison) listed by an example of a different split among
    # train/validation/test is the identical set of requests asked once where it can be tuned on
    # and once where it is supposed to be held out -- whether that set is one key (recipe 14's
    # v17/t15: different fields, one byte-identical request) or several (recipe 23's two
    # independent, mirrored requests per example). Comparing the whole set, not one key alone,
    # is what keeps a legitimately shared *later* key legitimate ("examples whose later request
    # is the same" above): such an example keeps a distinguishing earlier key of its own, so its
    # complete set still differs from every other example's. demo is exempt, as it is above: it
    # is never scored or tuned on.
    by_keys: dict[tuple[str, ...], list[Example]] = defaultdict(list)
    for e in examples:
        if e.split in LABELED_SPLITS and e.replay_keys:
            by_keys[tuple(sorted(e.replay_keys))].append(e)
    for keys, who in by_keys.items():
        first = who[0]
        for other in who[1:]:
            if other.split != first.split:
                if len(keys) == 1:
                    msg = (
                        f"replay key {keys[0]} is also listed by {first.id!r} ({first.split}), "
                        f"a different split ({other.split}): the same request would be asked "
                        "(and scored) in both"
                    )
                else:
                    msg = (
                        f"replay keys {', '.join(keys)} are also listed, as the same complete "
                        f"set, by {first.id!r} ({first.split}), a different split "
                        f"({other.split}): the same requests would be asked (and scored) in both"
                    )
                problems.append(Problem(inputs_name, msg, ident=other.id))
    # Catches a key copied from another example. The key is the hash of what Jev sees, so only
    # an example with `state` and exactly one key makes a request the validator can see:
    # `fields` go through the recipe's build_state (it may drop Python-owned values), and a
    # later request of a multi-key example depends on an earlier answer.
    owners: dict[str, Example] = {}
    for e in examples:
        if e.state is None or len(e.replay_keys) != 1:
            continue
        key = e.replay_keys[0]
        first = owners.setdefault(key, e)
        if first is not e and _canonical(first.state) != _canonical(e.state):
            msg = (
                f"replay key {key} is also listed by {first.id!r}, whose state differs: "
                "a key belongs to one request"
            )
            problems.append(Problem(inputs_name, msg, ident=e.id))
    return problems


def _check_responses(
    examples: list[Example], responses: Mapping[str, Any], name: str
) -> list[Problem]:
    """Every listed key has a response in this file, and every response is listed."""
    problems: list[Problem] = []
    referenced: set[str] = set()
    for e in examples:
        for key in e.replay_keys:
            referenced.add(key)
            if key not in responses:
                msg = f"no response for replay key {key} of this example"
                problems.append(Problem(name, msg, ident=e.id))
    for key in responses:
        if key not in referenced:
            msg = "response that no input lists in replay_keys"
            problems.append(Problem(name, msg, ident=key))
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
    """Every string in a decoded JSON value, keys included (iterative: depth cannot overflow)."""
    out: list[str] = []
    pending = [node]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            for key, value in item.items():
                out.append(key)
                pending.append(value)
        elif isinstance(item, list):
            pending.extend(item)
    return out


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


def _layout(folder: Path) -> tuple[dict[str | None, Path], list[Problem]]:
    """The responses files present (by tag), and a problem for every entry that is not allowed."""
    responses: dict[str | None, Path] = {}
    problems: list[Problem] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        tagged = _TAGGED_RESPONSES.fullmatch(entry.name)
        if entry.name in (INPUTS_FILE, LABELS_FILE):
            continue
        if entry.name == RESPONSES_FILE:
            responses[None] = entry
        elif ".drift-" not in entry.name and tagged and _ID.fullmatch(tagged.group(1)):
            responses[tagged.group(1)] = entry
        else:
            msg = (
                f"unexpected entry in the fixtures folder; it holds only {INPUTS_FILE}, "
                f"{LABELS_FILE}, {RESPONSES_FILE} and responses-<tag>.json"
            )
            problems.append(Problem(_display(entry), msg))
    return responses, problems


def validate_recipe(recipe_dir: PathLike | None = None) -> Report:
    """Every problem in a recipe's ``fixtures/`` folder, and the recipe's mode.

    The result is a list of ``Problem`` (empty means valid) with a ``mode`` attribute:
    ``"replay"``, ``"scripted"``, or ``None`` when the inputs could not be read.
    """
    folder = fixtures_dir(recipe_dir)
    if not folder.is_dir():
        return Report([Problem(_display(folder), "fixtures folder is missing")])
    responses_files, problems = _layout(folder)
    inputs_path, labels_path = folder / INPUTS_FILE, folder / LABELS_FILE
    examples, more, inputs_ok = _read_inputs(inputs_path)
    problems += more
    labels, label_lines, more, labels_ok = _read_labels(labels_path)
    problems += more
    replays = any(e.replay_keys for e in examples)
    mode = ("replay" if replays else "scripted") if inputs_ok else None
    if inputs_ok:
        names = (_display(inputs_path), _display(labels_path))
        problems += _check_examples(examples, labels if labels_ok else None, label_lines, names)
    if replays and None not in responses_files:
        # Listed keys need the default file; with no key listed it is simply not needed.
        problems.append(Problem(_display(folder / RESPONSES_FILE), "file is missing"))
    scanned = [inputs_path, labels_path, *responses_files.values()]
    for path in responses_files.values():
        raw, parsed, more, usable = _read_responses(path)
        problems += more
        if usable:
            problems += _check_provenance_agreement(parsed, _display(path))
            if inputs_ok:
                problems += _check_responses(examples, raw, _display(path))
    for path in scanned:
        problems += _scan_file(path)
    return Report(problems, mode)


def validate_all(recipes_dir: PathLike = "recipes") -> dict[str, Report]:
    """Validate ``<recipes_dir>/*/fixtures`` for every recipe that has such a folder.

    Returns ``{recipe directory: report}``; a recipe without a ``fixtures`` folder is
    not checked (the recipe contract, not this validator, requires the folder).
    """
    root = Path(recipes_dir)
    results: dict[str, Report] = {}
    if root.is_dir():
        for recipe in sorted(p for p in root.iterdir() if (p / FIXTURES_DIR).is_dir()):
            results[_display(recipe)] = validate_recipe(recipe)
    return results
