"""Rules for a ``ddc-brief/1`` document kept by the ERP. Pure Python: no ERP imports.

The ERP owns ``schema``, ``brief_id``, ``project_id`` and ``version``. A confirmation is made only
by ``confirm`` (a named person at a recorded time); a save may carry an existing confirmation over
unchanged, and a confirmation whose value changed falls back to ``proposed``.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from .schema_check import json_equal, load_schema, validate

SCHEMA_ID = "ddc-brief/1"
SCHEMA_FILE = "brief.schema.json"
_MISSING = object()


class BriefError(ValueError):
    """The document cannot be stored; ``errors`` are ``{"pointer", "message"}`` items."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(f"{e['pointer'] or '/'}: {e['message']}" for e in errors))
        self.errors = errors


def pointer_parts(pointer: str) -> list[str]:
    if not pointer.startswith("/") or pointer == "/":
        raise BriefError([{"pointer": pointer, "message": "is not a JSON Pointer to a value"}])
    return [p.replace("~1", "/").replace("~0", "~") for p in pointer[1:].split("/")]


def resolve(doc: Any, pointer: str) -> Any:
    """Value at ``pointer`` or the module-private ``_MISSING`` marker."""
    node = doc
    for part in pointer_parts(pointer):
        if isinstance(node, dict):
            if part not in node:
                return _MISSING
            node = node[part]
        elif isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node) or (part != "0" and part.startswith("0")):
                return _MISSING
            node = node[int(part)]
        else:
            return _MISSING
    return node


def exists(doc: Any, pointer: str) -> bool:
    return resolve(doc, pointer) is not _MISSING


def schema_errors(doc: Any) -> list[dict]:
    return validate(doc, load_schema(SCHEMA_FILE))


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def prepare_save(
    incoming: dict,
    previous: dict | None,
    *,
    project_id: uuid.UUID,
    brief_id: uuid.UUID,
    version: int,
    draft: bool = False,
) -> tuple[dict, list[str]]:
    """The document to store for a save, and the pointers whose confirmation was withdrawn."""
    if not isinstance(incoming, dict):
        raise BriefError([{"pointer": "", "message": "must be of type object"}])
    doc = copy.deepcopy(incoming)
    doc.update(schema=SCHEMA_ID, brief_id=str(brief_id), project_id=str(project_id), version=version)
    errors: list[dict] = []
    withdrawn: list[str] = []
    provenance = doc.get("provenance")
    old_prov = (previous or {}).get("provenance") or {}
    if isinstance(provenance, dict):
        for pointer, entry in provenance.items():
            here = "/provenance/" + pointer.replace("~", "~0").replace("/", "~1")
            try:
                value = resolve(doc, pointer)
            except BriefError:
                errors.append({"pointer": here, "message": "key is not a JSON Pointer to a value"})
                continue
            if value is _MISSING:
                errors.append({"pointer": here, "message": "points at a value the brief does not have"})
                continue
            if not isinstance(entry, dict):
                continue  # the schema reports it
            if entry.get("status") != "confirmed":
                if "confirmed_by" in entry or "confirmed_at" in entry:
                    errors.append({"pointer": here, "message": "confirmed_by/confirmed_at belong to a confirmation"})
                continue
            before = old_prov.get(pointer)
            was_confirmed = isinstance(before, dict) and before.get("status") == "confirmed"
            if not was_confirmed:
                errors.append({"pointer": here, "message": "a value is confirmed through the confirm action"})
                continue
            if json_equal(resolve(previous, pointer), value):
                for key in ("confirmed_by", "confirmed_at"):
                    if key in before:
                        entry[key] = before[key]
                    else:
                        entry.pop(key, None)
            else:
                entry["status"] = "proposed"
                entry.pop("confirmed_by", None)
                entry.pop("confirmed_at", None)
                withdrawn.append(pointer)
    if errors:
        raise BriefError(errors)
    errors = schema_errors(doc)
    if draft:
        # A draft may lack required values; every other violation still refuses the save.
        errors = [e for e in errors if e["message"] != "is required"]
    if errors:
        raise BriefError(errors)
    return doc, withdrawn


def apply_confirm(doc: dict, pointers: list[str], *, user_id: uuid.UUID, at: datetime, version: int) -> dict:
    """A copy of ``doc`` with ``pointers`` confirmed by ``user_id``; answered questions removed."""
    out = copy.deepcopy(doc)
    errors = []
    for pointer in pointers:
        try:
            if not exists(out, pointer):
                errors.append({"pointer": pointer, "message": "the brief has no value here to confirm"})
        except BriefError as exc:
            errors += exc.errors
    if errors:
        raise BriefError(errors)
    provenance = out.setdefault("provenance", {})
    for pointer in pointers:
        entry = dict(provenance.get(pointer) or {})
        entry.update(status="confirmed", confirmed_by=str(user_id), confirmed_at=_stamp(at))
        provenance[pointer] = entry
    if out.get("questions"):
        done = set(pointers)
        out["questions"] = [q for q in out["questions"] if q.get("pointer") not in done]
    out["version"] = version
    # A saved draft may lack required values; confirming what it has keeps exactly those gaps, nothing else.
    gaps = {e["pointer"] for e in schema_errors(doc) if e["message"] == "is required"}
    errors = [e for e in schema_errors(out) if not (e["message"] == "is required" and e["pointer"] in gaps)]
    if errors:
        raise BriefError(errors)
    return out
