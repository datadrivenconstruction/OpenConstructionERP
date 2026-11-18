# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The document template: a page setup and an ordered list of typed blocks.

A template is JSON a firm edits, imports and exports::

    {"schema": 1, "primary_locale": "en",
     "title": {"en": "Purchase order"}, "subject": {}, "show_subject": true,
     "page": {"size": "A4", "orientation": "portrait", "margin_side_mm": 20, ...},
     "branding": {"accent": "#16213e", "font": "sans", "letterhead": true},
     "watermark": {"draft": {"en": "DRAFT"}},
     "header": [{"text": {"en": "{{doc.number}}"}, "align": "right"}],
     "footer": [{"text": {"en": "Page {{page.number}} of {{page.total}}"}, "align": "center"}],
     "body": [{"id": "line_items", "type": "table", "collection": "items", "columns": [...]}, ...]}

Every block may be hidden, carry a condition (``field``, ``op``, ``value``) and
a style (alignment, font size, spacing). Text is per language with the markdown
subset of :mod:`app.core.doc_templates.markup`; merge fields are ``{{path}}``.
Computed values use :mod:`app.core.doc_templates.layout.expr`. Nothing a user
types is ever executed.

:func:`normalise` turns untrusted JSON into a template of known shape (unknown
keys and types dropped, numbers clamped, text capped). :func:`check` reports
what blocks publishing: a locked section, column or field hidden, an unknown
merge field, a malformed expression, too many blocks.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from app.core.doc_templates.layout.expr import ExprError, names_in, parse
from app.core.doc_templates.layout.spec import COLUMN_FORMATS, LayoutSpec
from app.core.doc_templates.markup import has_raw_html
from app.core.doc_templates.merge import unknown_fields
from app.core.doc_templates.rules import (
    BLOCK_TOO_LONG,
    MAX_BLOCK_CHARS,
    MAX_TEMPLATE_BYTES,
    RAW_HTML,
    TEMPLATE_TOO_LARGE,
    UNKNOWN_BLOCK,
    UNKNOWN_FIELD,
    Issue,
)

__all__ = [
    "BLOCK_TYPES",
    "CONDITION_OPS",
    "CUSTOM_BLOCK_LIMIT",
    "INVALID_EXPRESSION",
    "REQUIRED_COLUMN_HIDDEN",
    "REQUIRED_FIELD_REMOVED",
    "REQUIRED_SECTION_HIDDEN",
    "Locks",
    "check",
    "iter_blocks",
    "locks_for",
    "normalise",
    "text_in",
]

SCHEMA = 1
#: Blocks in one template, nested ones included.
MAX_BLOCKS = 60
CUSTOM_BLOCK_LIMIT = "doctpl.custom_block_limit"
REQUIRED_SECTION_HIDDEN = "doctpl.required_section_hidden"
REQUIRED_COLUMN_HIDDEN = "doctpl.required_column_hidden"
REQUIRED_FIELD_REMOVED = "doctpl.required_field_removed"
INVALID_EXPRESSION = "doctpl.invalid_expression"

BLOCK_TYPES: tuple[str, ...] = (
    "section",
    "heading",
    "text",
    "notes",
    "fields",
    "table",
    "totals",
    "signatures",
    "image",
    "clause",
    "columns",
    "spacer",
    "page_break",
    "qr",
)
#: Block types allowed inside a two-column container.
COLUMN_CHILD_TYPES = frozenset({"heading", "text", "notes", "fields", "image", "clause", "spacer", "qr", "totals"})
CONDITION_OPS: tuple[str, ...] = ("eq", "ne", "gt", "gte", "lt", "lte", "empty", "not_empty", "contains")
PAGE_SIZES: tuple[str, ...] = ("A4", "Letter", "Legal")
ALIGNS: tuple[str, ...] = ("left", "center", "right", "justify")
WIDTHS: tuple[str, ...] = ("auto", "S", "M", "L")

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")
_PATH_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}(?:\.[a-z][a-z0-9_]{0,40}){0,3}$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_SIGNATURE_CHARS = 420_000


# ── Locks ────────────────────────────────────────────────────────────────


class Locks:
    """What may not be hidden, with the reason, from the module's spec and the active packs."""

    def __init__(self) -> None:
        self.sections: dict[str, str] = {}
        self.columns: dict[str, dict[str, str]] = {}
        self.fields: dict[str, str] = {}

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form for the editor."""
        return {
            "sections": dict(self.sections),
            "columns": {k: dict(v) for k, v in self.columns.items()},
            "fields": dict(self.fields),
        }


def locks_for(spec: LayoutSpec, countries: Sequence[str] = ()) -> Locks:
    """Locks of *spec*: required sections, columns and fields, plus pack locks for *countries*."""
    locks = Locks()
    for section in spec.sections:
        if section.required:
            locks.sections[section.id] = section.source or "Platform standard"
    for collection in spec.collections:
        for column in collection.columns:
            if column.required:
                locks.columns.setdefault(collection.id, {})[column.id] = column.source or "Platform standard"
    locks.fields.update(spec.locked_fields)
    for pack_lock in _pack_locks(spec.key, countries):
        source = str(pack_lock.get("source") or "")
        for section_id in pack_lock.get("sections") or ():
            locks.sections[str(section_id)] = source
        for collection_id, column_ids in (pack_lock.get("columns") or {}).items():
            for column_id in column_ids or ():
                locks.columns.setdefault(str(collection_id), {})[str(column_id)] = source
        for path in pack_lock.get("fields") or ():
            locks.fields[str(path)] = source
    return locks


def _pack_locks(kind: str, countries: Sequence[str]) -> list[Mapping[str, Any]]:
    """``locks`` entries of the packs' ``document_requirements.json`` for *kind* in *countries*."""
    if not countries:
        return []
    try:
        from app.core.doc_templates.legal import pack_layout_locks
    except Exception:  # noqa: BLE001 - packs are optional
        return []
    return pack_layout_locks(kind, countries)


# ── Normalisation ────────────────────────────────────────────────────────


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n")[:MAX_BLOCK_CHARS]


def _i18n(value: Any) -> dict[str, str]:
    """``{lang: text}``; a bare string is taken as English."""
    if isinstance(value, str):
        return {"en": _clean_text(value)} if value else {}
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, str] = {}
    for lang, text in list(value.items())[:60]:
        key = str(lang).strip().lower()
        if _LANG_RE.match(key) and isinstance(text, str):
            out[key] = _clean_text(text)
    return out


def _num(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _path(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _PATH_RE.match(text) else ""


def _condition(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    field = _path(value.get("field"))
    op = str(value.get("op") or "")
    if not field or op not in CONDITION_OPS:
        return None
    return {"field": field, "op": op, "value": str(value.get("value") or "")[:200]}


def _style(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {}
    if value.get("align") in ALIGNS:
        out["align"] = value["align"]
    if value.get("font_size") not in (None, ""):
        out["font_size"] = _num(value.get("font_size"), 6, 24, 10)
    for key in ("space_before", "space_after"):
        if value.get(key) not in (None, ""):
            out[key] = _num(value.get(key), 0, 60, 0)
    return out or None


class _Ids:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def take(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not _ID_RE.match(text) or text in self.seen:
            text = f"b_{uuid.uuid4().hex[:10]}"
        self.seen.add(text)
        return text


def _block(raw: Any, ids: _Ids, *, nested: bool = False) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    kind = str(raw.get("type") or "")
    if kind not in BLOCK_TYPES or (nested and kind not in COLUMN_CHILD_TYPES):
        return None
    block: dict[str, Any] = {"id": ids.take(raw.get("id")), "type": kind, "hidden": bool(raw.get("hidden"))}
    condition = _condition(raw.get("condition"))
    if condition:
        block["condition"] = condition
    style = _style(raw.get("style"))
    if style:
        block["style"] = style
    title = _i18n(raw.get("title"))
    if title:
        block["title"] = title
    if kind == "section":
        block["section"] = str(raw.get("section") or block["id"])[:40]
    elif kind in {"heading", "text", "notes"}:
        block["text"] = _i18n(raw.get("text"))
        if kind == "heading":
            block["level"] = 2 if raw.get("level") == 2 else 1
    elif kind == "fields":
        entries = []
        for entry in (raw.get("fields") or [])[:40]:
            if not isinstance(entry, Mapping) or not _path(entry.get("field")):
                continue
            item: dict[str, Any] = {"field": _path(entry.get("field"))}
            label = _i18n(entry.get("label"))
            if label:
                item["label"] = label
            if entry.get("omit_empty"):
                item["omit_empty"] = True
            cond = _condition(entry.get("condition"))
            if cond:
                item["condition"] = cond
            entries.append(item)
        block["fields"] = entries
        block["layout"] = "rows" if raw.get("layout") == "rows" else "pairs"
    elif kind == "table":
        block["collection"] = str(raw.get("collection") or "")[:40]
        columns = []
        seen: set[str] = set()
        for entry in (raw.get("columns") or [])[:20]:
            if not isinstance(entry, Mapping):
                continue
            col_id = str(entry.get("id") or "").strip().lower()
            if not _ID_RE.match(col_id) or col_id in seen:
                continue
            seen.add(col_id)
            column: dict[str, Any] = {"id": col_id}
            label = _i18n(entry.get("label"))
            if label:
                column["label"] = label
            if entry.get("width") in WIDTHS and entry.get("width") != "auto":
                column["width"] = entry["width"]
            if entry.get("format") in COLUMN_FORMATS:
                column["format"] = entry["format"]
            if col_id.startswith("calc_"):
                column["expr"] = str(entry.get("expr") or "")[:300]
            if entry.get("hidden"):
                column["hidden"] = True
            columns.append(column)
        block["columns"] = columns
        group_by = str(raw.get("group_by") or "").strip().lower()
        if _ID_RE.match(group_by):
            block["group_by"] = group_by
            block["subtotals"] = bool(raw.get("subtotals"))
        empty = _i18n(raw.get("empty_text"))
        if empty:
            block["empty_text"] = empty
    elif kind == "totals":
        rows = []
        for entry in (raw.get("rows") or [])[:20]:
            if not isinstance(entry, Mapping):
                continue
            row: dict[str, Any] = {}
            if _path(entry.get("field")):
                row["field"] = _path(entry.get("field"))
            elif entry.get("expr"):
                row["expr"] = str(entry.get("expr"))[:300]
                row["format"] = entry.get("format") if entry.get("format") in COLUMN_FORMATS else "money"
            else:
                continue
            label = _i18n(entry.get("label"))
            if label:
                row["label"] = label
            cond = _condition(entry.get("condition"))
            if cond:
                row["condition"] = cond
            rows.append(row)
        block["rows"] = rows
    elif kind == "signatures":
        signers = []
        for entry in (raw.get("signers") or [])[:8]:
            if not isinstance(entry, Mapping):
                continue
            signer: dict[str, Any] = {"field": _path(entry.get("field"))}
            role = _i18n(entry.get("role"))
            if role:
                signer["role"] = role
            signers.append(signer)
        block["signers"] = signers
    elif kind == "image":
        block["source"] = "signature" if raw.get("source") == "signature" else "logo"
        block["width_mm"] = _num(raw.get("width_mm"), 10, 180, 40)
        data = raw.get("data")
        if block["source"] == "signature" and isinstance(data, str) and len(data) <= _MAX_SIGNATURE_CHARS:
            block["data"] = data
    elif kind == "clause":
        block["clause_id"] = str(raw.get("clause_id") or "")[:40]
        block["text"] = _i18n(raw.get("text"))
    elif kind == "columns":
        columns_raw = raw.get("columns") if isinstance(raw.get("columns"), Sequence) else []
        children = []
        for column_raw in list(columns_raw)[:3]:
            kids = [
                b
                for b in (
                    _block(c, ids, nested=True) for c in (column_raw if isinstance(column_raw, Sequence) else [])[:10]
                )
                if b
            ]
            children.append(kids)
        while len(children) < 2:
            children.append([])
        block["columns"] = children
        ratios = raw.get("ratios") if isinstance(raw.get("ratios"), Sequence) else []
        block["ratios"] = [_num(r, 0.2, 5, 1) for r in list(ratios)[: len(children)]] or [1.0] * len(children)
        if len(block["ratios"]) != len(children):
            block["ratios"] = [1.0] * len(children)
    elif kind == "spacer":
        block["height_mm"] = _num(raw.get("height_mm"), 1, 120, 6)
    elif kind == "qr":
        block["field"] = _path(raw.get("field"))
        block["size_mm"] = _num(raw.get("size_mm"), 12, 60, 22)
        block["caption"] = bool(raw.get("caption"))
    return block


def _lines(raw: Any) -> list[dict[str, Any]]:
    out = []
    for entry in (raw or [])[:3] if isinstance(raw, Sequence) else []:
        if not isinstance(entry, Mapping):
            continue
        text = _i18n(entry.get("text"))
        if text:
            out.append({"text": text, "align": entry.get("align") if entry.get("align") in ALIGNS else "left"})
    return out


def normalise(raw: Any) -> dict[str, Any]:
    """A template of known shape from untrusted JSON. Never raises."""
    data = raw if isinstance(raw, Mapping) else {}
    page_raw = data.get("page") if isinstance(data.get("page"), Mapping) else {}
    branding_raw = data.get("branding") if isinstance(data.get("branding"), Mapping) else {}
    page: dict[str, Any] = {
        "size": page_raw.get("size") if page_raw.get("size") in PAGE_SIZES else "A4",
        "orientation": "landscape" if page_raw.get("orientation") == "landscape" else "portrait",
    }
    for key, default in (("margin_side_mm", 20.0), ("margin_top_mm", 18.0), ("margin_bottom_mm", 18.0)):
        if page_raw.get(key) not in (None, ""):
            page[key] = _num(page_raw.get(key), 8, 40, default)
    if page_raw.get("first_page_header") is False:
        page["first_page_header"] = False
    if isinstance(page_raw.get("page_numbers"), bool):
        page["page_numbers"] = page_raw["page_numbers"]
    branding: dict[str, Any] = {}
    if isinstance(branding_raw.get("accent"), str) and _HEX_RE.match(branding_raw["accent"]):
        branding["accent"] = branding_raw["accent"]
    if branding_raw.get("font") == "serif":
        branding["font"] = "serif"
    if branding_raw.get("letterhead") is False:
        branding["letterhead"] = False
    watermark: dict[str, dict[str, str]] = {}
    if isinstance(data.get("watermark"), Mapping):
        for status, text in list(data["watermark"].items())[:12]:
            key = str(status).strip().lower()[:30]
            value = _i18n(text)
            if _ID_RE.match(key) and value:
                watermark[key] = value
    ids = _Ids()
    body = [b for b in (_block(raw_block, ids) for raw_block in list(data.get("body") or [])[: MAX_BLOCKS * 2]) if b]
    primary = str(data.get("primary_locale") or "en").strip().lower()
    return {
        "schema": SCHEMA,
        "primary_locale": primary if _LANG_RE.match(primary) else "en",
        "title": _i18n(data.get("title")),
        "subject": _i18n(data.get("subject")),
        "show_subject": data.get("show_subject") is not False,
        "page": page,
        "branding": branding,
        "watermark": watermark,
        "header": _lines(data.get("header")),
        "footer": _lines(data.get("footer")),
        "body": body,
    }


# ── Reading helpers ──────────────────────────────────────────────────────


def text_in(value: Mapping[str, str] | None, locale: str, primary: str = "en") -> str | None:
    """The text in *locale*, else its base language, else the template's primary language, else English.

    ``None`` when the template has no text at all for it (the standard wording prints).
    """
    if not value:
        return None
    lang = (locale or "en").lower()
    for key in (lang, lang.split("-")[0], primary, "en"):
        if key in value:
            return value[key]
    return next(iter(value.values()), None)


def iter_blocks(blocks: Sequence[Mapping[str, Any]]) -> Iterator[Mapping[str, Any]]:
    """Every block, nested column children included."""
    for block in blocks:
        yield block
        if block.get("type") == "columns":
            for column in block.get("columns") or []:
                yield from iter_blocks(column)


def _texts(template: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """``(where, text)`` for every piece of user wording in the template."""
    for key in ("title", "subject"):
        for text in (template.get(key) or {}).values():
            yield key, text
    for area in ("header", "footer"):
        for line in template.get(area) or []:
            for text in (line.get("text") or {}).values():
                yield area, text
    for status, value in (template.get("watermark") or {}).items():
        for text in value.values():
            yield f"watermark:{status}", text
    for block in iter_blocks(template.get("body") or []):
        where = str(block.get("id"))
        for key in ("title", "text", "empty_text"):
            for text in (block.get(key) or {}).values():
                yield where, text
        for entry in block.get("fields") or []:
            for text in (entry.get("label") or {}).values():
                yield where, text
        for entry in block.get("rows") or []:
            for text in (entry.get("label") or {}).values():
                yield where, text
        for entry in block.get("signers") or []:
            for text in (entry.get("role") or {}).values():
                yield where, text
        for entry in block.get("columns") or [] if block.get("type") == "table" else []:
            for text in (entry.get("label") or {}).values():
                yield where, text


def _condition_fields(block: Mapping[str, Any]) -> Iterator[str]:
    if block.get("condition"):
        yield block["condition"]["field"]
    for key in ("fields", "rows"):
        for entry in block.get(key) or []:
            if entry.get("condition"):
                yield entry["condition"]["field"]


def _visible(block: Mapping[str, Any]) -> bool:
    return not block.get("hidden") and not block.get("condition")


# ── Checks ───────────────────────────────────────────────────────────────


def check(
    template: Mapping[str, Any],
    spec: LayoutSpec,
    locks: Locks | None = None,
    *,
    clause_ids: set[str] | None = None,
) -> list[Issue]:
    """What is wrong with *template* for *spec*. Errors block publishing."""
    issues: list[Issue] = []
    known = spec.field_paths
    locks = locks or locks_for(spec)
    size = len(json.dumps(template, ensure_ascii=False, default=str).encode("utf-8"))
    if size > MAX_TEMPLATE_BYTES * 4:
        issues.append(Issue(TEMPLATE_TOO_LARGE, "error", "", {"size": str(size)}))
    blocks = list(iter_blocks(template.get("body") or []))
    if len(blocks) > MAX_BLOCKS:
        issues.append(Issue(CUSTOM_BLOCK_LIMIT, "error", "", {"count": str(len(blocks)), "limit": str(MAX_BLOCKS)}))
    for where, text in _texts(template):
        for path in unknown_fields(text, known):
            issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": path}))
        if has_raw_html(text):
            issues.append(Issue(RAW_HTML, "error", where, {}))
        if len(text) >= MAX_BLOCK_CHARS:
            issues.append(Issue(BLOCK_TOO_LONG, "error", where, {"limit": str(MAX_BLOCK_CHARS)}))
    by_id = {str(b.get("id")): b for b in blocks}
    for block in blocks:
        where = str(block.get("id"))
        kind = block.get("type")
        for path in _condition_fields(block):
            if path not in known:
                issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": path}))
        for path in [e.get("field") for e in block.get("fields") or []] + [block.get("field")]:
            if path and path not in known:
                issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": path}))
        for entry in block.get("rows") or []:
            if entry.get("field") and entry["field"] not in known:
                issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": entry["field"]}))
            if entry.get("expr"):
                issues.extend(_check_expr(entry["expr"], known, where))
        for entry in block.get("signers") or []:
            if entry.get("field") and entry["field"] not in known:
                issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": entry["field"]}))
        if kind == "section" and spec.section(str(block.get("section"))) is None:
            issues.append(Issue(UNKNOWN_BLOCK, "error", where, {"block": str(block.get("section"))}))
        if kind == "clause" and block.get("clause_id") and clause_ids is not None:
            if block["clause_id"] not in clause_ids:
                issues.append(Issue(UNKNOWN_BLOCK, "error", where, {"block": block["clause_id"]}))
        if kind == "table":
            issues.extend(_check_table(block, spec, locks, known))
    for section_id, source in locks.sections.items():
        block = by_id.get(section_id)
        if block is None or not _visible(block):
            issues.append(
                Issue(REQUIRED_SECTION_HIDDEN, "error", section_id, {"section": section_id, "source": source})
            )
    for path, source in locks.fields.items():
        present = any(
            e.get("field") == path and not e.get("condition")
            for b in blocks
            if b.get("type") == "fields" and _visible(b)
            for e in b.get("fields") or []
        )
        if not present:
            issues.append(Issue(REQUIRED_FIELD_REMOVED, "error", "", {"field": path, "source": source}))
    return issues


def _check_expr(text: str, known: frozenset[str] | set[str], where: str) -> list[Issue]:
    try:
        node = parse(text)
    except ExprError as exc:
        return [Issue(INVALID_EXPRESSION, "error", where, {"expr": text[:80], "reason": str(exc)})]
    return [Issue(UNKNOWN_FIELD, "error", where, {"field": n}) for n in sorted(names_in(node)) if n not in known]


def _check_table(block: Mapping[str, Any], spec: LayoutSpec, locks: Locks, known: frozenset[str]) -> list[Issue]:
    where = str(block.get("id"))
    collection = spec.collection(str(block.get("collection")))
    if collection is None:
        return [Issue(UNKNOWN_BLOCK, "error", where, {"block": str(block.get("collection"))})]
    issues: list[Issue] = []
    columns = block.get("columns") or []
    row_names = {c.id for c in collection.columns} | {c["id"] for c in columns}
    for column in columns:
        if column["id"].startswith("calc_"):
            issues.extend(_check_expr(column.get("expr") or "", set(known) | row_names, where))
        elif collection.column(column["id"]) is None:
            issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": f"{collection.id}.{column['id']}"}))
    if block.get("group_by") and block["group_by"] not in row_names:
        issues.append(Issue(UNKNOWN_FIELD, "error", where, {"field": f"{collection.id}.{block['group_by']}"}))
    shown = {c["id"] for c in columns if not c.get("hidden")}
    for column_id, source in (locks.columns.get(collection.id) or {}).items():
        if column_id not in shown:
            issues.append(Issue(REQUIRED_COLUMN_HIDDEN, "error", where, {"column": column_id, "source": source}))
    return issues
