# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Provincial fee programmes (计费程序) of the China pack.

The arithmetic is :mod:`app.core.fee_programme`; the data is the pack's
``fee_schedules/*.json`` (one file per province and edition, every rate with
its document number and URL). This module only answers the Chinese questions:
which jurisdiction a site is in (Shenzhen issues its own standard inside
Guangdong), which schedule is in force on the tender date, how a stored bill
splits into labour, materials and plant, and what moving a project to the
GB/T 50500-2024 edition would change.

No province is named in code. A site outside every listed jurisdiction gets no
fee programme, and the screen shows nothing.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.fee_programme import FeeSchedule, compute, in_force, resolve, schedule_from_dict
from app.core.line_tax import parse_date, to_decimal

logger = logging.getLogger(__name__)

PACK_SLUG = "china-gbt50500"
_PACKAGE = "openconstructionerp_china_gbt50500"
_ZERO = Decimal(0)

# Resource kinds of a stored position, onto the terms of a fee programme.
_KIND_TERM = {
    "labor": "labour",
    "labour": "labour",
    "material": "material",
    "materials": "material",
    "machinery": "plant",
    "machine": "plant",
    "plant": "plant",
    "equipment": "equipment",
}
_OTHER_ITEM_KINDS = {"daywork", "main_contractor_service"}
_SOURCE_KEYS = ("source", "price_source", "price_period", "cost_item_id", "code")


def schedule_dir() -> Path | None:
    """Where the pack's fee schedules live in this installation, if anywhere."""
    from app.core.partner_pack.discovery import _packs_dir  # noqa: PLC0415

    root = _packs_dir()
    if root is None:
        return None
    folder = root / PACK_SLUG / "src" / _PACKAGE / "fee_schedules"
    return folder if folder.is_dir() else None


@lru_cache(maxsize=4)
def _load(folder: str) -> dict[str, Any]:
    path = Path(folder)
    meta = json.loads((path / "jurisdictions.json").read_text(encoding="utf-8"))
    schedules: dict[str, dict[str, Any]] = {}
    for file in sorted(path.glob("*.json")):
        if file.name == "jurisdictions.json":
            continue
        row = json.loads(file.read_text(encoding="utf-8"))
        schedules[str(row["key"])] = row
    return {
        "sources": meta.get("sources") or {},
        "jurisdictions": meta.get("jurisdictions") or {},
        "schedules": schedules,
    }


def catalogue() -> dict[str, Any]:
    """Sources, jurisdictions and raw schedules; empty when the pack carries none."""
    folder = schedule_dir()
    if folder is None:
        return {"sources": {}, "jurisdictions": {}, "schedules": {}}
    try:
        return _load(str(folder))
    except (OSError, ValueError, KeyError):
        logger.warning("china fee schedules unreadable at %s", folder, exc_info=True)
        return {"sources": {}, "jurisdictions": {}, "schedules": {}}


def jurisdiction_for(subdivision: str | None, city: str | None) -> str | None:
    """The fee jurisdiction of a site: a city override first, then the province."""
    juris = catalogue()["jurisdictions"]
    sub = (subdivision or "").strip().upper()
    wanted = (city or "").strip()
    if wanted:
        for key, row in juris.items():
            if wanted in (row.get("cities") or []) and (not sub or row.get("subdivision") == sub):
                return key
    if sub in juris and not juris[sub].get("cities"):
        return sub
    return None


def schedules_for(jurisdiction: str | None) -> list[FeeSchedule]:
    """Every schedule of one jurisdiction, oldest first."""
    cat = catalogue()
    row = cat["jurisdictions"].get(jurisdiction or "") or {}
    return [schedule_from_dict(cat["schedules"][k]) for k in row.get("schedules") or [] if k in cat["schedules"]]


def project_date(profile: dict[str, Any]) -> date | None:
    """The date that picks the schedule: tender issue, else contract."""
    return parse_date(profile.get("tender_date")) or parse_date(profile.get("contract_date"))


def components_from_positions(positions: list[Any]) -> dict[str, Any]:
    """Split stored leaf positions into the terms a fee programme reads.

    Resources are per-unit norms (see ``price_breakdown.mapping``), so each is
    multiplied by the position quantity. A position without resources adds its
    total to ``other``. Lines of 其他项目 and lump-sum measures sit outside the
    measured works.
    """
    parents = {p.parent_id for p in positions if p.parent_id is not None}
    sums: dict[str, Decimal] = {}
    unsourced: list[str] = []
    material_positions = 0

    def add(term: str, amount: Decimal) -> None:
        sums[term] = sums.get(term, _ZERO) + amount

    for pos in positions:
        meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
        if pos.id in parents or meta.get("type") == "section":
            continue
        total = to_decimal(pos.total)
        kind = str(meta.get("cn_item_kind") or "")
        if kind == "provisional_sum":
            add("provisional_sum", total)
            continue
        if kind == "specialist_pc_sum":
            add("tax_inclusive", total)
            continue
        if kind in _OTHER_ITEM_KINDS:
            add("other_items", total)
            continue
        if str(meta.get("cn_measure_basis") or "") == "lump_sum":
            add("lump_sum_measures", total)
            continue
        resources = [r for r in meta.get("resources") or [] if isinstance(r, dict)]
        if not resources:
            add("other", total)
            continue
        qty = to_decimal(pos.quantity) if pos.quantity is not None else Decimal(1)
        has_material = False
        sourced = any(meta.get(k) for k in _SOURCE_KEYS)
        for res in resources:
            per_unit = to_decimal(res.get("total")) or to_decimal(res.get("quantity") or 1) * to_decimal(
                res.get("unit_rate")
            )
            term = _KIND_TERM.get(str(res.get("type") or res.get("resource_type") or "").lower(), "other")
            add(term, per_unit * qty)
            if term == "material":
                has_material = True
                sourced = sourced or any(res.get(k) for k in _SOURCE_KEYS)
        if has_material:
            material_positions += 1
            if not sourced:
                unsourced.append(str(pos.id))
    return {
        "components": {k: str(v) for k, v in sums.items()},
        "material_positions": material_positions,
        "unsourced_material": unsourced,
    }


def _line_meta(raw: dict[str, Any], sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in raw.get("lines") or []:
        src = sources.get(str(row.get("source") or "")) or {}
        out[str(row["code"])] = {
            "name_zh": row.get("name_zh"),
            "name_en": row.get("name_en"),
            "kind": row.get("kind"),
            "band": row.get("band"),
            "non_competitive": bool(row.get("non_competitive")),
            "user_input": bool(row.get("user_input")),
            "needs_confirmation": bool(row.get("needs_confirmation")),
            "reference_rates": row.get("reference_rates") or [],
            "base": row.get("base") or {},
            "excludes": row.get("excludes") or [],
            "source_id": row.get("source"),
            "doc": src.get("doc"),
            "url": src.get("url"),
            "secondary": bool(src.get("secondary")),
        }
    return out


def schedule_summary(key: str) -> dict[str, Any] | None:
    """Name, dates, options and documented lines of one schedule."""
    cat = catalogue()
    raw = cat["schedules"].get(key)
    if raw is None:
        return None
    src = cat["sources"].get(str(raw.get("source") or "")) or {}
    return {
        "key": key,
        "jurisdiction": raw.get("jurisdiction"),
        "edition": raw.get("edition"),
        "name_zh": raw.get("name_zh"),
        "name_en": raw.get("name_en"),
        "effective_from": raw.get("effective_from"),
        "effective_to": raw.get("effective_to"),
        "superseded_by": raw.get("superseded_by"),
        "labour_factor": raw.get("labour_factor"),
        "bases_verified": raw.get("bases_verified", True),
        "doc": src.get("doc"),
        "url": src.get("url"),
        "options": raw.get("options") or [],
        "lines": _line_meta(raw, cat["sources"]),
    }


def with_bases(schedule: FeeSchedule, bases: dict[str, Any]) -> FeeSchedule:
    """The schedule with the user's base for some lines, where a source left the base open."""
    if not bases:
        return schedule
    lines = tuple(
        dataclasses.replace(line, base={str(k): to_decimal(v) for k, v in bases[line.code].items()})
        if isinstance(bases.get(line.code), dict)
        else line
        for line in schedule.lines
    )
    return dataclasses.replace(schedule, lines=lines)


def effective_bases(block: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Line code to the base actually used: the user's where given, else the source's."""
    overrides = (block.get("settings") or {}).get("bases") or {}
    lines = ((block.get("schedule") or {}).get("lines")) or {}
    return {
        code: {str(k): str(v) for k, v in (overrides.get(code) or meta.get("base") or {}).items()}
        for code, meta in lines.items()
    }


def fee_block(
    profile: dict[str, Any],
    settings: dict[str, Any] | None,
    components: dict[str, Any],
    *,
    markup_names: list[str] | None = None,
) -> dict[str, Any] | None:
    """The ``fee`` part of a ``cn_vat_check`` record, or ``None`` outside every jurisdiction."""
    settings = settings or {}
    jurisdiction = jurisdiction_for(profile.get("site_subdivision"), profile.get("site_city"))
    if jurisdiction is None:
        return None
    schedules = schedules_for(jurisdiction)
    on = project_date(profile)
    override = settings.get("schedule_key")
    by_key = {s.key: s for s in schedules}
    resolved = resolve(schedules, on)
    chosen: FeeSchedule | None = by_key.get(override) if override else resolved
    juris = catalogue()["jurisdictions"][jurisdiction]
    block: dict[str, Any] = {
        "jurisdiction": jurisdiction,
        "jurisdiction_name_zh": juris.get("name_zh"),
        "jurisdiction_name_en": juris.get("name_en"),
        "date": on.isoformat() if on else None,
        "guifei_abolished_from": juris.get("guifei_abolished_from"),
        "price_station_url": juris.get("price_station_url"),
        "price_publication": juris.get("price_publication"),
        "labour_index": juris.get("labour_index"),
        "schedules": [schedule_summary(s.key) for s in schedules],
        "resolved_key": resolved.key if resolved else None,
        "schedule": None,
        "in_force": None,
        "successor": None,
        "result": None,
        "settings": settings,
        "markup_names": list(markup_names or []),
        "components": components.get("components") or {},
    }
    if chosen is None:
        return block
    chosen = with_bases(chosen, settings.get("bases") or {})
    successor = resolved.key if resolved and resolved.key != chosen.key else chosen.superseded_by
    labour_si = bool(settings.get("labour_includes_social_insurance"))
    apply_factor = settings.get("apply_labour_factor")
    if apply_factor is None:
        apply_factor = not labour_si
    comp = block["components"]
    result = compute(
        chosen,
        comp,
        rates=settings.get("rates") or {},
        options=settings.get("options") or {},
        apply_labour_factor=bool(apply_factor),
        tax_method=str(profile.get("tax_method") or "general"),
        tax_inclusive=comp.get("tax_inclusive"),
    )
    block.update(
        {
            "schedule": schedule_summary(chosen.key),
            "in_force": in_force(chosen, on),
            "successor": successor if successor != chosen.key else None,
            "labour_includes_social_insurance": labour_si,
            "result": result.as_dict(),
        }
    )
    return block


def settings_dict(row: Any) -> dict[str, Any]:
    """A stored fee profile as the plain settings :func:`fee_block` reads."""
    if row is None:
        return {}
    return {
        "schedule_key": row.schedule_key,
        "rates": dict(row.rates or {}),
        "options": dict(row.options or {}),
        "bases": dict(row.bases or {}),
        "labour_includes_social_insurance": bool(row.labour_includes_social_insurance),
        "apply_labour_factor": row.apply_labour_factor,
    }


def edition_move_preview(record: dict[str, Any]) -> dict[str, Any]:
    """What moving a project from GB 50500-2013 to GB/T 50500-2024 changes, before anything is written.

    Applied: the profile edition, and 规费 markups switched off. Listed for a
    person to move by hand: bill lines under the 规费 head (their social
    insurance goes into labour, the rest into management fee) and item codes
    the 2024 patterns do not accept.
    """
    from app.core.item_codes import code_patterns, shared_code_patterns  # noqa: PLC0415
    from app.core.line_tax import check_item_codes  # noqa: PLC0415
    from app.modules.china_pack.service import EDITION_2013, EDITION_2024  # noqa: PLC0415

    profile = record.get("profile") or {}
    current = str(profile.get("standard_edition") or "")
    lines = record.get("lines") or []
    entries = [(str(li.get("ref") or ""), str(li.get("code") or ""), str(li.get("sub_project") or "")) for li in lines]
    patterns = code_patterns("gb50500", EDITION_2024, profile.get("site_subdivision"))
    codes = [
        {"ref": f.ref, "code": f.code}
        for f in check_item_codes(entries, patterns, shared_code_patterns("gb50500"))
        if f.kind == "format"
    ]
    fee = record.get("fee") or {}
    return {
        "from": current or None,
        "to": EDITION_2024,
        "needed": current in ("", EDITION_2013),
        "guifei_lines": [str(li.get("ref") or "") for li in lines if li.get("head") == "guifei"],
        "guifei_markups": [n for n in record.get("markup_names") or [] if "规费" in str(n)],
        "codes_to_review": codes[:200],
        "codes_to_review_count": len(codes),
        "fee_schedule_from": (fee.get("schedule") or {}).get("key"),
        "fee_schedule_to": fee.get("resolved_key"),
    }
