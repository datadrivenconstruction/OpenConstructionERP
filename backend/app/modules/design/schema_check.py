"""JSON Schema (draft 2020-12) checking for the keyword subset the contract schemas use.

The ERP environment ships no JSON Schema library, so the module carries this one. It refuses a
schema that uses a keyword it does not implement (``unsupported_keywords``), and the contract
test suite checks its verdicts against the reference implementation on a corpus of documents.
Pure Python: no ERP imports.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs", "$comment", "default", "examples"}
ASSERTIONS = {
    "type",
    "const",
    "enum",
    "$ref",
    "properties",
    "required",
    "additionalProperties",
    "propertyNames",
    "items",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "format",
}
FORMATS = {"date-time"}

_DATE_TIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-](\d{2}):(\d{2}))$")


@lru_cache(maxsize=8)
def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def unsupported_keywords(schema: Any, path: str = "") -> list[str]:
    """Every keyword or format in ``schema`` this checker would not enforce."""
    found: list[str] = []
    if isinstance(schema, dict):
        for key, sub in schema.items():
            here = f"{path}/{key}"
            if key in ("properties", "$defs"):
                for name, child in sub.items():
                    found += unsupported_keywords(child, f"{here}/{name}")
            elif key in ("additionalProperties", "items", "propertyNames"):
                found += unsupported_keywords(sub, here)
            elif key == "format" and sub not in FORMATS:
                found.append(f"{here}={sub}")
            elif key not in ANNOTATIONS | ASSERTIONS:
                found.append(here)
    elif not isinstance(schema, bool):
        found.append(f"{path} (not a schema)")
    return found


def _ptr(parts: list) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts) or ""


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if name == "number":
        return isinstance(value, (int, float))
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    raise ValueError(f"unknown type {name}")


def json_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _date_time_ok(value: str) -> bool:
    m = _DATE_TIME.match(value)
    if not m:
        return False
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12 and 1 <= day <= days[month - 1] and hour <= 23 and minute <= 59 and second <= 60):
        return False
    if m.group(9) is not None and (int(m.group(9)) > 23 or int(m.group(10)) > 59):
        return False
    return True


def _resolve(root: dict, ref: str) -> Any:
    if not ref.startswith("#"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node: Any = root
    for part in [p for p in ref[1:].split("/") if p]:
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _check(root: dict, schema: Any, value: Any, at: list, errors: list[dict]) -> None:
    if schema is True:
        return
    if schema is False:
        errors.append({"pointer": _ptr(at), "message": "is not allowed"})
        return

    def fail(message: str) -> None:
        errors.append({"pointer": _ptr(at), "message": message})

    if "$ref" in schema:
        _check(root, _resolve(root, schema["$ref"]), value, at, errors)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            fail(f"must be of type {' or '.join(names)}")
            return
    if "const" in schema and not json_equal(value, schema["const"]):
        fail(f"must equal {json.dumps(schema['const'])}")
    if "enum" in schema and not any(json_equal(value, e) for e in schema["enum"]):
        fail("must be one of " + ", ".join(json.dumps(e) for e in schema["enum"]))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            fail(f"must have at least {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            fail(f"must have at most {schema['maxLength']} characters")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            fail(f"must match {schema['pattern']}")
        if schema.get("format") == "date-time" and not _date_time_ok(value):
            fail("must be an RFC 3339 date-time")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            fail(f"must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            fail(f"must be <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            fail(f"must be > {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            fail(f"must be < {schema['exclusiveMaximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            fail(f"must have at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            fail(f"must have at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _check(root, schema["items"], item, [*at, i], errors)
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append({"pointer": _ptr([*at, name]), "message": "is required"})
        props = schema.get("properties", {})
        for name, item in value.items():
            if "propertyNames" in schema:
                before = len(errors)
                _check(root, schema["propertyNames"], name, [*at, name], errors)
                for e in errors[before:]:
                    e["message"] = "property name " + e["message"]
            if name in props:
                _check(root, props[name], item, [*at, name], errors)
            elif "additionalProperties" in schema:
                extra = schema["additionalProperties"]
                if extra is False:
                    errors.append({"pointer": _ptr([*at, name]), "message": "is not an allowed property"})
                else:
                    _check(root, extra, item, [*at, name], errors)


def validate(document: Any, schema: dict) -> list[dict]:
    """All violations as ``{"pointer", "message"}``; empty when the document is valid."""
    errors: list[dict] = []
    _check(schema, schema, document, [], errors)
    return errors
