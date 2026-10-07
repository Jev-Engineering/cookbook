"""A small JSON Schema checker for the fixture row schemas.

``jsonschema`` is not a dependency of this package, so this implements only the keywords
``schema.json`` uses: ``type``, ``enum``, ``pattern``, ``minLength``, ``minItems``,
``uniqueItems``, ``items``, ``required``, ``properties``, ``additionalProperties`` (false),
``oneOf`` and ``$ref`` into ``#/$defs``. A schema that uses any other validating keyword is
rejected, so a later edit to ``schema.json`` cannot silently become unenforced.
"""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

_KNOWN = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "enum", "pattern",
    "minLength", "minItems", "uniqueItems", "items", "required", "properties",
    "additionalProperties", "oneOf",
}  # fmt: skip
_TYPES = {
    "string": lambda v: isinstance(v, str),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def load_schema() -> dict[str, Any]:
    """The packaged ``schema.json`` as a dict."""
    text = resources.files(__package__).joinpath("schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def kind(value: Any) -> str:
    for name in ("null", "boolean", "string", "object", "array", "integer", "number"):
        if _TYPES[name](value):
            return name
    return type(value).__name__


def check(
    value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = ""
) -> list[tuple[str, str]]:
    """Return ``(path, message)`` for every way ``value`` breaks ``schema``."""
    unknown = set(schema) - _KNOWN
    if unknown:
        raise ValueError(f"schema keyword not supported by the fixture checker: {sorted(unknown)}")
    if "$ref" in schema:
        prefix = "#/$defs/"
        if not schema["$ref"].startswith(prefix):
            raise ValueError(f"unsupported $ref {schema['$ref']!r}")
        return check(value, root["$defs"][schema["$ref"][len(prefix) :]], root, path)
    problems: list[tuple[str, str]] = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            return [(path, f"must be {' or '.join(types)}, found {kind(value)}")]
    if "enum" in schema and value not in schema["enum"]:
        problems.append((path, f"must be one of {schema['enum']}, found {value!r}"))
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            problems.append((path, f"{value!r} does not match the pattern {schema['pattern']}"))
        if len(value) < schema.get("minLength", 0):
            problems.append((path, "must not be empty"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problems.append((path, f"must have at least {schema['minItems']} item(s)"))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) < len(
            value
        ):
            problems.append((path, "must not repeat an item"))
        if "items" in schema:
            for i, item in enumerate(value):
                problems.extend(check(item, schema["items"], root, f"{path}[{i}]"))
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                problems.append((path, f"missing required field {name!r}"))
        props = schema.get("properties", {})
        for name, item in value.items():
            sub = f"{path}.{name}" if path else name
            if name in props:
                problems.extend(check(item, props[name], root, sub))
            elif schema.get("additionalProperties") is False:
                problems.append((sub, f"unknown field {name!r}"))
    if "oneOf" in schema:
        matching = [s for s in schema["oneOf"] if not check(value, s, root, path)]
        if len(matching) != 1:
            titles = ", ".join(repr(s.get("title", "?")) for s in schema["oneOf"])
            problems.append((path, f"must have exactly one of {titles}, found {len(matching)}"))
    return problems
