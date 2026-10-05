#!/usr/bin/env python3
"""Check a directory of academy course files the way the trainer loader will.

For every ``course_*_v*.json`` in the directory (the loader's glob) it prints:

* the shape verdict of :class:`app.modules.trainer.spec.CourseSpec`, one line
  per error with its JSON path;
* a key map: every key path of the file (list indices folded to ``[]``),
  grouped by seed block or root section, counted as ``modelled`` (a field the
  spec types), ``opaque`` (inside a field the spec keeps as an untyped blob),
  ``stripped`` (``authoring`` or a ``_`` key, removed before storage) or
  ``rejected`` (no such field: the loader refuses the file); the rejected
  paths are listed;
* the verdict of every ``trainer_spec`` rule, with the element and reason of
  each failure.

Only ids, paths, refs and rule reasons are printed, never course text, so the
output can be pasted into a ticket: an answer is named by its position
(``answer_key[#2]``), because answer names can be descriptive prose. Pass
``--messages`` to add the translated rule messages, which do quote names and
values from the file and so are for the author's own terminal only.

No database is involved; the loader's pure part and the rule engine run as they
do at boot.

The verdict is ``VALID`` (the loader stores it ``active`` and offers it) or
``STORED AS INVALID`` (decision 26: the loader stores it with
``status="invalid"`` and its error list, and never offers it).

Exit codes:
    0  every file is valid
    1  at least one would be stored as invalid, or the directory holds no course file

Usage::

    .venv-run/Scripts/python.exe scripts/check_trainer_courses.py <dir> [--messages]
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import sys
import types
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Union, get_args, get_origin

_REPO = Path(__file__).resolve().parents[1]
_BACKEND = _REPO / "backend"

VERDICTS = ("modelled", "opaque", "stripped", "rejected")


def _model_candidates(annotation: Any) -> tuple[list[type], bool]:
    """BaseModel classes reachable in ``annotation``, and whether it has an untyped part."""
    from pydantic import BaseModel

    models: list[type] = []
    opaque = False

    def visit(tp: Any) -> None:
        nonlocal opaque
        if tp is Any:
            opaque = True
            return
        origin = get_origin(tp)
        if origin is Annotated:
            visit(get_args(tp)[0])
        elif origin in (Union, types.UnionType, list, tuple, set, frozenset):
            for arg in get_args(tp):
                visit(arg)
        elif origin is dict:
            if Any in get_args(tp):
                opaque = True
        elif isinstance(tp, type) and issubclass(tp, BaseModel):
            models.append(tp)

    visit(annotation)
    return models, opaque


def _probe_model(node: dict[str, Any]) -> type | None:
    from app.modules.trainer.spec import PROBE_MODELS

    return PROBE_MODELS.get(node.get("type")) if isinstance(node.get("type"), str) else None


def classify_keys(raw: dict[str, Any]) -> dict[str, str]:
    """Map every folded key path of a raw course dict to its verdict."""
    from app.modules.trainer.spec import LEGACY_SEED_KEYS, CourseSpec, SeedSpec, is_authoring_key

    out: dict[str, str] = {}

    def mark(path: str, verdict: str) -> None:
        # One path can be seen under several verdicts across list items; the
        # most severe one wins so a rejected occurrence is never hidden.
        if VERDICTS.index(verdict) > VERDICTS.index(out.get(path, "modelled")) or path not in out:
            out[path] = verdict

    def blob(node: Any, path: str, verdict: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else key
                mark(child, verdict)
                blob(value, child, verdict)
        elif isinstance(node, list):
            for value in node:
                blob(value, f"{path}[]", verdict)

    def walk(node: Any, model: type | None, path: str) -> None:
        if isinstance(node, list):
            for value in node:
                walk(value, model, f"{path}[]")
            return
        if not isinstance(node, dict) or model is None:
            return
        fields = {}
        for name, info in model.model_fields.items():
            fields[name] = info
            if info.alias:
                fields[info.alias] = info
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if (path == "" and key == "authoring") or is_authoring_key(key):
                mark(child, "stripped")
                blob(value, child, "stripped")
                continue
            if path == "seed" and key in LEGACY_SEED_KEYS:
                # Refused by name; its content is mapped against the canonical
                # list it must move to, so the report says what else changes.
                mark(child, "rejected")
                canonical = SeedSpec.model_fields[LEGACY_SEED_KEYS[key]].annotation
                walk(value, _model_candidates(canonical)[0][0], child)
                continue
            info = fields.get(key)
            if info is None:
                mark(child, "rejected")
                blob(value, child, "rejected")
                continue
            candidates, opaque = _model_candidates(info.annotation)
            if key == "probe" and isinstance(value, dict):
                candidates = [m for m in [_probe_model(value)] if m is not None]
            mark(child, "modelled")
            items = value if isinstance(value, list) else [value]
            for item in items:
                item_path = f"{child}[]" if isinstance(value, list) else child
                if isinstance(item, dict | list) and candidates:
                    walk(item, candidates[0] if len(candidates) == 1 else _pick(item, candidates), item_path)
                elif isinstance(item, dict | list) and opaque:
                    blob(item, item_path, "opaque")
                elif isinstance(item, dict | list):
                    blob(item, item_path, "modelled")

    walk(raw, CourseSpec, "")
    return out


def _pick(node: Any, candidates: list[type]) -> type | None:
    """The candidate model whose fields cover most of the node's keys."""
    if not isinstance(node, dict):
        return candidates[0]
    return max(candidates, key=lambda m: len(set(node) & set(m.model_fields)))


def _group(path: str) -> str:
    parts = path.replace("[]", "").split(".")
    if len(parts) == 1:
        return "(root keys)"
    if parts[0] == "seed":
        return ".".join(parts[:2])
    if parts[0] == "tasks":
        return f"tasks[].{parts[1]}" if len(parts) > 2 else "tasks[] (own keys)"
    return parts[0]


def _print_keys(keys: dict[str, str]) -> None:
    groups: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(VERDICTS, 0))
    for path, verdict in keys.items():
        groups[_group(path)][verdict] += 1
    print(f"  key map: {len(keys)} key paths")
    for group in sorted(groups):
        counts = groups[group]
        cells = "  ".join(f"{v} {counts[v]}" for v in VERDICTS if counts[v])
        print(f"    {group:<38} {cells}")
    rejected = sorted(p for p, v in keys.items() if v == "rejected")
    if rejected:
        print("  rejected keys:")
        for path in rejected:
            print(f"    {path}")


_ANSWER_REF_RE = re.compile(r"^(tasks\[(?P<task>[^\]]+)\]\.answer_key)\[(?P<name>[^\]]*)\]")


def _safe_ref(ref: str, data: dict[str, Any] | None) -> str:
    """Replace an answer name in a rule's element ref with its position."""
    match = _ANSWER_REF_RE.match(ref)
    if match is None:
        return ref
    index = "?"
    for task in (data or {}).get("tasks") or []:
        if isinstance(task, dict) and task.get("id") == match["task"]:
            answers = [a for key in ("answer_key", "optional_answer_key") for a in task.get(key) or []]
            names = [a.get("name") if isinstance(a, dict) else None for a in answers]
            if match["name"] in names:
                index = str(names.index(match["name"]))
    return f"{match[1]}[#{index}]{ref[match.end() :]}"


def _errors_behind_legacy_keys(data: dict[str, Any] | None) -> list[str]:
    """Seed errors a refused country-named key hides.

    The spec refuses ``progress_readings_<x>`` / ``variation_<x>`` style keys
    before it looks at the rest of ``seed``, so their presence hides every
    other seed error. This re-validates a copy with each block moved into its
    canonical list, so an author sees the whole bill at once.
    """
    from pydantic import ValidationError

    from app.modules.trainer.spec import LEGACY_SEED_KEYS, SeedSpec

    seed = (data or {}).get("seed")
    if not isinstance(seed, dict) or not set(seed) & set(LEGACY_SEED_KEYS):
        return []
    moved = copy.deepcopy(seed)
    for legacy, canonical in LEGACY_SEED_KEYS.items():
        if legacy in moved:
            moved.setdefault(canonical, []).append(moved.pop(legacy))
    try:
        SeedSpec.model_validate(moved)
    except ValidationError as exc:
        return [f"seed.{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
    return []


async def _check(path: Path, show_messages: bool) -> bool:
    from app.modules.trainer.loader import parse_course_bytes, validate_course
    from app.modules.trainer.validators import TRAINER_RULES

    raw_bytes = path.read_bytes()
    parsed = parse_course_bytes(raw_bytes, path.name)
    verdict = await validate_course(parsed)
    print(f"== {path.name}")
    print(f"  id {parsed.course_key}  version {parsed.version}  sha256 {parsed.sha256[:12]}")
    shape_ok = parsed.spec is not None
    print(f"  shape: {'OK' if shape_ok else f'{len(parsed.errors)} error(s)'}")
    for line in parsed.errors:
        print(f"    {line}")
    for line in _errors_behind_legacy_keys(parsed.data):
        print(f"    after the canonical renames: {line}")
    try:
        raw = json.loads(raw_bytes.decode("utf-8-sig"), parse_float=Decimal)
    except ValueError:
        raw = None
    if isinstance(raw, dict):
        _print_keys(classify_keys(raw))
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in verdict.report.get("results", []):
        rows[row["rule_id"]].append(row)
    print("  rules:")
    for rule in TRAINER_RULES:
        found = rows.get(rule.rule_id, [])
        if not found:
            print(f"    PASS  {rule.rule_id}")
            continue
        severities = sorted({r["severity"] for r in found})
        print(f"    {'/'.join(s.upper() for s in severities):<5} {rule.rule_id} ({len(found)})")
        for row in found:
            where = _safe_ref(row["element_ref"], parsed.data) if row["element_ref"] else "-"
            reason = "rule crashed" if row["engine_error"] else row["reason"]
            print(f"          {where}: {reason}")
            if show_messages and not row["engine_error"]:
                print(f"            {row['message']}")
    print(f"  verdict: {'VALID' if verdict.valid else 'STORED AS INVALID'}")
    print()
    return verdict.valid


def main(argv: list[str] | None = None) -> int:
    """Check every course file of a directory; see the module docstring."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--messages", action="store_true", help="also print the translated rule messages")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, str(_BACKEND))
    from app.modules.trainer.loader import COURSE_FILE_GLOB
    from app.modules.trainer.validators import register_trainer_rules

    register_trainer_rules()
    files = sorted(args.directory.glob(COURSE_FILE_GLOB))
    if not files:
        print(f"no {COURSE_FILE_GLOB} in {args.directory}")
        return 1
    results = [asyncio.run(_check(path, args.messages)) for path in files]
    print(f"{sum(results)} of {len(results)} course file(s) valid")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
