# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Locked legal blocks contributed by country packs.

A country pack may ship ``document_requirements.json`` beside its manifest::

    {"country": "DE",
     "kinds": {"finance.invoice": {"blocks": [
        {"id": "reverse_charge", "when": "doc.reverse_charge",
         "text": {"de": "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)", "en": "..."},
         "required_fields": ["recipient.vat_id"], "source": "UStG § 13b", "where": "invoice"}]}}}

The same file may carry the pack's clause library, read-only for every firm::

    {"clauses": [{"key": "de_vob_b_warranty", "category": "warranty",
                  "title": {"de": "Mängelansprüche", "en": "Claims for defects"},
                  "text": {"de": "Für Mängelansprüche gilt § 13 VOB/B.", "en": "..."},
                  "source": "VOB/B § 13"}]}

``required_fields`` entries may name alternatives, ``entity.vat_id|entity.tax_number``:
one of them filled satisfies the requirement. ``text`` may be omitted for a
data-only requirement.

Core holds no country values. A kind gets legal blocks only for the countries
the workspace's market profile names and whose pack carries the file; with no
pack nothing appears. Users cannot remove, hide or reorder these blocks: they
are not template blocks at all, the generator prints them in a fixed zone.
A required field that is empty raises ``doctpl.legal_data_missing``. It blocks issuing
unless the pack (or the block) sets ``"severity": "warning"``, then it only warns.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.doc_templates.markup import to_plain
from app.core.doc_templates.pdf import LegalNote
from app.core.doc_templates.resolve import normalise_locale
from app.core.doc_templates.rules import LEGAL_DATA_MISSING, Issue, filled

__all__ = [
    "LegalRequirement",
    "PackClause",
    "clear_cache",
    "legal_blocks_for_editor",
    "legal_notes",
    "pack_clauses",
    "pack_layout_locks",
    "requirements_for",
]

logger = logging.getLogger(__name__)

FILENAME = "document_requirements.json"


@dataclass(frozen=True)
class LegalRequirement:
    """One mandatory note for a kind in a country."""

    id: str
    kind: str
    country: str
    text: Mapping[str, str]
    source: str
    when: str | None = None
    required_fields: tuple[str, ...] = ()
    where: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)
    severity: str = "error"

    def text_in(self, locale: str) -> str:
        """The note in *locale*, else English, else the first one shipped."""
        lang = normalise_locale(locale)
        return self.text.get(lang) or self.text.get("en") or next(iter(self.text.values()), "")


def _parse(raw: object, country: str) -> list[LegalRequirement]:
    if not isinstance(raw, dict):
        return []
    out: list[LegalRequirement] = []
    for kind, spec in (raw.get("kinds") or {}).items():
        for block in (spec or {}).get("blocks") or []:
            if not isinstance(block, dict) or not isinstance(block.get("text", {}), dict) or not block.get("id"):
                continue
            out.append(
                LegalRequirement(
                    id=str(block["id"]),
                    kind=str(kind),
                    country=country,
                    text={str(k): str(v) for k, v in (block.get("text") or {}).items()},
                    source=str(block.get("source") or ""),
                    when=str(block["when"]) if block.get("when") else None,
                    required_fields=tuple(str(f) for f in block.get("required_fields") or ()),
                    where=str(block.get("where") or ""),
                    labels={str(k): str(v) for k, v in (block.get("labels") or {}).items()},
                    severity="warning" if (block.get("severity") or raw.get("severity")) == "warning" else "error",
                )
            )
    return out


def _pack_files() -> list[tuple[str, dict]]:
    """``(country, parsed file)`` of every pack that ships the file."""
    try:
        from app.core.partner_pack.discovery import discover_packs, read_pack_file
    except Exception:  # noqa: BLE001
        return []
    try:
        packs = discover_packs()
    except Exception:  # noqa: BLE001 - packs are optional
        logger.debug("doc_templates: pack discovery failed", exc_info=True)
        return []
    out: list[tuple[str, dict]] = []
    for pack in packs:
        try:
            data = read_pack_file(pack.slug, FILENAME)
            if not data:
                continue
            raw = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001 - one broken pack file costs only that pack
            logger.warning("doc_templates: unreadable %s in pack %s", FILENAME, getattr(pack, "slug", "?"))
            continue
        country = str(raw.get("country") or (pack.metadata or {}).get("country") or "").upper()
        if country and isinstance(raw, dict):
            out.append((country, raw))
    return out


@lru_cache(maxsize=1)
def _all_layout_locks() -> tuple[tuple[str, str, dict], ...]:
    out: list[tuple[str, str, dict]] = []
    for country, raw in _pack_files():
        for kind, spec in (raw.get("kinds") or {}).items():
            locks = (spec or {}).get("locks") if isinstance(spec, dict) else None
            if isinstance(locks, dict):
                out.append((country, str(kind), locks))
    return tuple(out)


def pack_layout_locks(
    kind_key: str, countries: Iterable[str], extra: Iterable[tuple[str, str, dict]] | None = None
) -> list[dict]:
    """``locks`` a pack declares for a document layout: sections, columns and fields that may not be hidden.

    File shape: ``{"kinds": {"procurement.purchase_order": {"locks": {"sections": [...],
    "columns": {"items": [...]}, "fields": [...], "source": "..."}}}}``.
    """
    wanted = {c.strip().upper() for c in countries if c and c.strip() and c != "*"}
    if not wanted:
        return []
    pool = tuple(extra) if extra is not None else _all_layout_locks()
    return [locks for country, kind, locks in pool if kind == kind_key and country in wanted]


@lru_cache(maxsize=1)
def _all_requirements() -> tuple[LegalRequirement, ...]:
    try:
        from app.core.partner_pack.discovery import discover_packs, read_pack_file
    except Exception:  # noqa: BLE001
        return ()
    out: list[LegalRequirement] = []
    try:
        packs = discover_packs()
    except Exception:  # noqa: BLE001 - packs are optional
        logger.debug("doc_templates: pack discovery failed", exc_info=True)
        return ()
    for pack in packs:
        try:
            data = read_pack_file(pack.slug, FILENAME)
            if not data:
                continue
            raw = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001 - one broken pack file costs only that pack
            logger.warning("doc_templates: unreadable %s in pack %s", FILENAME, getattr(pack, "slug", "?"))
            continue
        country = str(raw.get("country") or (pack.metadata or {}).get("country") or "").upper()
        if country:
            out.extend(_parse(raw, country))
    return tuple(out)


@dataclass(frozen=True)
class PackClause:
    """A clause a country pack ships: printed like a firm's clause, never edited by one."""

    key: str
    country: str
    category: str
    title: Mapping[str, str]
    text: Mapping[str, str]
    source: str = ""


def _texts(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k)[:10]: str(v)[:4000] for k, v in value.items() if isinstance(v, str) and v.strip()}


@lru_cache(maxsize=1)
def _all_pack_clauses() -> tuple[PackClause, ...]:
    import re

    key_re = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
    out: list[PackClause] = []
    for country, raw in _pack_files():
        for entry in raw.get("clauses") or []:
            if not isinstance(entry, dict) or not key_re.match(str(entry.get("key") or "")):
                continue
            text = _texts(entry.get("text"))
            if not text:
                continue
            out.append(
                PackClause(
                    key=str(entry["key"]),
                    country=country,
                    category=str(entry.get("category") or "")[:40],
                    title=_texts(entry.get("title")),
                    text=text,
                    source=str(entry.get("source") or "")[:120],
                )
            )
    return tuple(out)


def pack_clauses(countries: Iterable[str], extra: Iterable[PackClause] | None = None) -> list[PackClause]:
    """Clauses the packs of *countries* ship. ``extra`` lets tests inject pack data."""
    wanted = {c.strip().upper() for c in countries if c and c.strip() and c != "*"}
    if not wanted:
        return []
    pool = tuple(extra) if extra is not None else _all_pack_clauses()
    return [c for c in pool if c.country in wanted]


def clear_cache() -> None:
    """Forget the parsed pack files (tests, pack installed at runtime)."""
    _all_requirements.cache_clear()
    _all_layout_locks.cache_clear()
    _all_pack_clauses.cache_clear()


def requirements_for(
    kind_key: str, countries: Iterable[str], extra: Iterable[LegalRequirement] | None = None
) -> list[LegalRequirement]:
    """Requirements of *kind_key* in *countries*. ``extra`` lets tests inject pack data."""
    wanted = {c.strip().upper() for c in countries if c and c.strip() and c != "*"}
    if not wanted:
        return []
    pool = tuple(extra) if extra is not None else _all_requirements()
    return [r for r in pool if r.kind == kind_key and r.country in wanted]


def legal_notes(
    kind_key: str,
    countries: Iterable[str],
    values: Mapping[str, object],
    locale: str,
    extra: Iterable[LegalRequirement] | None = None,
) -> tuple[list[LegalNote], list[Issue]]:
    """Notes to print and the missing-data errors for one document.

    A requirement with ``when`` applies only when that value is truthy (e.g.
    ``doc.reverse_charge``). Its text is merged with the document values.
    """
    notes: list[LegalNote] = []
    issues: list[Issue] = []
    for req in requirements_for(kind_key, countries, extra):
        if req.when and not values.get(req.when):
            continue
        for path in req.required_fields:
            if not filled(values, path):
                issues.append(
                    Issue(
                        LEGAL_DATA_MISSING,
                        req.severity,
                        req.id,
                        {
                            "field": req.labels.get(path, path),
                            "country": req.country,
                            "source": req.source,
                            "where": req.where,
                        },
                    )
                )
        text = to_plain(req.text_in(locale), values)
        if text:
            notes.append(LegalNote(text, req.source))
    return notes, issues


def legal_blocks_for_editor(
    kind_key: str, countries: Iterable[str], locale: str = "en", extra: Iterable[LegalRequirement] | None = None
) -> list[dict[str, str]]:
    """Read-only legal blocks the editor shows with their reason.

    A requirement without printed text (data only) is shown as the list of data it asks for.
    """
    out = []
    for r in requirements_for(kind_key, countries, extra):
        text = r.text_in(locale) or ", ".join(r.labels.get(p, p) for p in r.required_fields)
        out.append({"id": r.id, "country": r.country, "text": text, "source": r.source, "when": r.when or ""})
    return out
