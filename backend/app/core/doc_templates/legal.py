# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Locked legal blocks contributed by country packs.

A country pack may ship ``document_requirements.json`` beside its manifest::

    {"country": "DE",
     "kinds": {"finance.invoice": {"blocks": [
        {"id": "reverse_charge", "when": "doc.reverse_charge",
         "text": {"de": "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG)", "en": "..."},
         "required_fields": ["recipient.vat_id"], "source": "UStG § 13b", "where": "invoice"}]}}}

``required_fields`` entries may name alternatives, ``entity.vat_id|entity.tax_number``:
one of them filled satisfies the requirement. ``text`` may be omitted for a
data-only requirement.

Core holds no country values. A kind gets legal blocks only for the countries
the workspace's market profile names and whose pack carries the file; with no
pack nothing appears. Users cannot remove, hide or reorder these blocks: they
are not template blocks at all, the generator prints them in a fixed zone.
A required field that is empty raises ``doctpl.legal_data_missing``, which
blocks issuing the document.
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
    "clear_cache",
    "legal_blocks_for_editor",
    "legal_notes",
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
                )
            )
    return out


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


def clear_cache() -> None:
    """Forget the parsed pack files (tests, pack installed at runtime)."""
    _all_requirements.cache_clear()


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
                        "error",
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
