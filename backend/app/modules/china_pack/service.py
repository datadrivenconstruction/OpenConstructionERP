# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Chinese tender totals, VAT checks and 预缴, composed from the neutral engines.

Nothing here does arithmetic of its own. The tax base comes from
:func:`app.core.line_tax.compute_tax_base`, the prepayment from
:func:`app.modules.tax_withholding.place_of_supply.prepayment_schedule`, and
item codes from :mod:`app.core.item_codes`. What this module adds is the
Chinese reading: which heads a GB 50500 bill has in each edition, which line of
其他项目 already carries its VAT, which rate a simplified project charges on a
given day, and how a stored bill and a project's invoices become one record
the ``cn_vat`` rules can check.

A bill line says what it is through its position metadata, all optional:

* ``cn_head``: ``fenbu`` / ``cuoshi`` / ``qita`` / ``guifei`` (2013 only);
  inherited from the nearest section that states one.
* ``cn_item_kind``: for 其他项目 lines, one of ``provisional_sum``,
  ``daywork``, ``main_contractor_service``, ``specialist_pc_sum``.
* ``tax_category``: a category code of the pack (``works``, ``goods``,
  ``goods_installed``, ``services``); works when absent.
* ``tax_inclusive``: the neutral flag the markup engine reads. The specialist
  prime-cost sum must carry it, and ``cn.vat_base_pc_sum`` says so when not.
* ``employer_supplied``: a 甲供 material line. It is priced in the bill and in
  the VAT base, and is deducted on the payment application rather than invoiced.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.core.line_tax import (
    TaxCategory,
    TaxLine,
    category_rate,
    compute_tax_base,
    parse_date,
    to_decimal,
)
from app.modules.china_pack.config import CN_TAX

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)

EDITION_2013 = "gb50500@2013"
EDITION_2024 = "gb50500@2024"
PC_SUM_KIND = "specialist_pc_sum"


def categories() -> list[TaxCategory]:
    """The pack's effective-dated tax categories."""
    return [TaxCategory.from_dict(row) for row in CN_TAX["tax_categories"]]


def simplified_rate(on: date, *, small_taxpayer: bool) -> Decimal:
    """The collection rate a simplified-method supply carries on ``on``.

    A small taxpayer pays the reduced 1% while it is in force and 3% outside it;
    a general taxpayer on the simplified method pays 3%.
    """
    cats = categories()
    if small_taxpayer:
        reduced = category_rate(cats, "small_taxpayer", on)
        if reduced is not None:
            return reduced
    rate = category_rate(cats, "simplified", on)
    return rate if rate is not None else Decimal(3)


def line_rate(category_code: str | None, on: date) -> Decimal | None:
    """The general-method rate of a line's category on ``on``; works when unstated."""
    return category_rate(categories(), category_code or "works", on)


def structure(edition: str | None) -> list[dict[str, Any]]:
    """The heads of a bill of this edition, newest edition when unknown."""
    structures = CN_TAX["estimate_structures"]
    return list(structures.get(edition or "") or structures[CN_TAX["default_edition_key"]])


def _is_pc_sum(line: dict[str, Any]) -> bool:
    return str(line.get("kind") or "") == PC_SUM_KIND


@dataclass(frozen=True)
class SummaryInput:
    """The settings a tender summary is computed under."""

    edition: str | None = None
    tax_method: str = "general"
    taxpayer_size: str = "general"
    on: date | None = None


def tender_summary(lines: list[dict[str, Any]], settings: SummaryInput) -> dict[str, Any]:
    """Head totals, VAT base, VAT and tender total of a bill.

    The specialist prime-cost sum is always kept out of the VAT base, whatever
    the line says, because it is priced VAT-inclusive (GB/T 50500-2024 2.0.18):
    this is the figure the bill should show, and ``cn.vat_base_pc_sum`` is what
    reports a bill that computed otherwise.
    """
    on = settings.on or date.today()
    heads = structure(settings.edition)
    by_head: dict[str, Decimal] = {h["key"]: _ZERO for h in heads if h.get("vat_base")}
    tax_lines: list[TaxLine] = []
    employer_net = _ZERO
    employer_tax = _ZERO
    for line in lines:
        amount = to_decimal(line.get("amount"))
        head = str(line.get("head") or "fenbu")
        by_head[head] = by_head.get(head, _ZERO) + amount
        if settings.tax_method == "exempt":
            rate: Decimal | None = _ZERO
        elif settings.tax_method == "simplified":
            rate = simplified_rate(on, small_taxpayer=settings.taxpayer_size == "small")
        else:
            rate = line_rate(line.get("tax_category"), on)
        inclusive = _is_pc_sum(line) or bool(line.get("tax_inclusive"))
        tax_lines.append(TaxLine(str(line.get("ref") or ""), amount, rate, inclusive))
        if line.get("employer_supplied") and not inclusive:
            employer_net += amount
            employer_tax += amount * (rate or _ZERO) / _HUNDRED
    base = compute_tax_base(tax_lines)
    employer_tax = employer_tax.quantize(_CENT, rounding=ROUND_HALF_UP)
    tender_total = base.total
    return {
        "edition": settings.edition or CN_TAX["default_edition_key"],
        "tax_method": settings.tax_method,
        "heads": [
            {
                "key": h["key"],
                "label_zh": h["label_zh"],
                "amount": str(base.tax if not h.get("vat_base") else by_head.get(h["key"], _ZERO)),
            }
            for h in heads
        ],
        "unplaced_heads": sorted(k for k in by_head if k not in {h["key"] for h in heads}),
        "vat_base": str(base.taxable_base),
        "vat": str(base.tax),
        "vat_by_rate": {k: {"base": str(v["base"]), "tax": str(v["tax"])} for k, v in base.by_rate.items()},
        "tax_inclusive_total": str(base.tax_inclusive_total),
        "tender_total": str(tender_total),
        "employer_supplied_net": str(employer_net),
        "employer_supplied_tax": str(employer_tax),
        "invoiceable_total": str(tender_total - employer_net - employer_tax),
    }


# ── Bill lines from stored positions ─────────────────────────────────────────


def lines_from_positions(positions: list[Any]) -> list[dict[str, Any]]:
    """Turn stored BOQ positions into the line dicts the summary and the rules read.

    Sections are skipped; a leaf inherits ``cn_head`` and ``sub_project`` from
    the nearest ancestor that states one.
    """
    by_id = {p.id: p for p in positions}
    parents = {p.parent_id for p in positions if p.parent_id is not None}

    def inherited(pos: Any, key: str) -> str:
        seen: set[Any] = set()
        current = pos
        while current is not None and current.id not in seen:
            seen.add(current.id)
            meta = current.metadata_ if isinstance(current.metadata_, dict) else {}
            if meta.get(key):
                return str(meta[key])
            current = by_id.get(current.parent_id)
        return ""

    out: list[dict[str, Any]] = []
    for pos in positions:
        meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
        if pos.id in parents or meta.get("type") == "section":
            continue
        classification = pos.classification if isinstance(pos.classification, dict) else {}
        out.append(
            {
                "ref": str(pos.id),
                "ordinal": pos.ordinal,
                "code": str(classification.get("gb50500") or classification.get("gbt50500") or ""),
                "sub_project": inherited(pos, "sub_project") or str(pos.boq_id),
                "head": inherited(pos, "cn_head") or "fenbu",
                "kind": str(meta.get("cn_item_kind") or ""),
                "tax_category": meta.get("tax_category"),
                "rate_pct": meta.get("vat_rate_pct"),
                "amount": str(pos.total or "0"),
                "tax_inclusive": bool(meta.get("tax_inclusive")),
                "employer_supplied": bool(meta.get("employer_supplied")),
            }
        )
    return out


def invoice_record(invoice: Any, lines: list[Any]) -> dict[str, Any]:
    """The invoice fields the 数电票 rules read, from a finance invoice."""
    meta = invoice.metadata_ if isinstance(getattr(invoice, "metadata_", None), dict) else {}
    ei = meta.get("einvoice") if isinstance(meta.get("einvoice"), dict) else {}
    site = ei.get("site_address") if isinstance(ei.get("site_address"), dict) else {}
    rates = sorted({str(to_decimal(li.vat_rate).normalize()) for li in lines if li.vat_rate is not None})
    return {
        "ref": str(invoice.id),
        "number": str(ei.get("issued_number") or ""),
        "date": str(invoice.invoice_date or "")[:10],
        "direction": invoice.invoice_direction,
        "construction": ei.get("construction", True) is not False,
        "site_location": str(site.get("city") or site.get("line1") or ei.get("site_location") or ""),
        "project_name": str(ei.get("project_name") or ""),
        "rates": rates,
    }


async def project_record(session: Any, project_id: uuid.UUID) -> dict[str, Any]:
    """Build the ``cn_vat_check`` record of one project from the database."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.boq.models import BOQ, Position  # noqa: PLC0415
    from app.modules.finance.models import Invoice, InvoiceLineItem  # noqa: PLC0415
    from app.modules.project_tax import repository as tax_repo  # noqa: PLC0415
    from app.modules.project_tax import service as tax_service  # noqa: PLC0415
    from app.modules.projects.models import Project  # noqa: PLC0415

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError("project not found")
    profile = tax_service.to_response(project, await tax_repo.get_for_project(session, project_id))
    bills = (
        (
            await session.execute(
                select(BOQ).where(
                    BOQ.project_id == project_id,
                    BOQ.variation_request_id.is_(None),
                    BOQ.branch_of_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    lines: list[dict[str, Any]] = []
    markup_names: list[str] = []
    all_positions: list[Any] = []
    for bill in bills:
        positions = (await session.execute(select(Position).where(Position.boq_id == bill.id))).scalars().all()
        lines.extend(lines_from_positions(list(positions)))
        all_positions.extend(positions)
        markup_names.extend(m.name for m in bill.markups if m.is_active)
    invoices = (
        (
            await session.execute(
                select(Invoice).where(Invoice.project_id == project_id, Invoice.invoice_direction == "receivable")
            )
        )
        .scalars()
        .all()
    )
    invoice_rows: list[dict[str, Any]] = []
    for inv in invoices:
        inv_lines = (
            (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))).scalars().all()
        )
        invoice_rows.append(invoice_record(inv, list(inv_lines)))
    from app.modules.china_pack import fees  # noqa: PLC0415
    from app.modules.china_pack.repository import get_fee_profile  # noqa: PLC0415

    profile_dict = profile.model_dump(mode="json")
    profile_dict["site_subdivision"] = profile_dict.get("site_subdivision") or getattr(
        project, "subdivision_code", None
    )
    split = fees.components_from_positions(all_positions)
    fee = fees.fee_block(
        profile_dict, fees.settings_dict(await get_fee_profile(session, project_id)), split, markup_names=markup_names
    )
    return build_record(
        profile=profile_dict,
        lines=lines,
        invoices=invoice_rows,
        markup_names=markup_names,
        currency_code=str(getattr(project, "currency", "") or "CNY"),
        project_subdivision=getattr(project, "subdivision_code", None),
        fee=fee,
        prices={k: split[k] for k in ("material_positions", "unsourced_material")},
    )


def build_record(
    *,
    profile: dict[str, Any],
    lines: list[dict[str, Any]] | None = None,
    invoices: list[dict[str, Any]] | None = None,
    prepayment: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
    markup_names: list[str] | None = None,
    currency_code: str = "CNY",
    project_subdivision: str | None = None,
    fee: dict[str, Any] | None = None,
    prices: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The plain dict the ``cn_vat`` rules read."""
    return {
        "record_type": "cn_vat_check",
        "currency_code": currency_code,
        "profile": {**profile, "site_subdivision": profile.get("site_subdivision") or project_subdivision},
        "lines": list(lines or []),
        "invoices": list(invoices or []),
        "prepayment": prepayment or {},
        "contract": contract or {},
        "markup_names": list(markup_names or []),
        "fee": fee or {},
        "prices": prices or {},
    }


def tender_switch_date(subdivision: str | None, city: str | None) -> date | None:
    """The day a province or city switched its tenders to GB/T 50500-2024, if a source states it."""
    province = CN_TAX["provinces"].get((subdivision or "").strip().upper()) or {}
    for name, row in (province.get("cities") or {}).items():
        wanted = (city or "").strip()
        if wanted and wanted in (name, row.get("name_zh")):
            found = parse_date(row.get("tender_switch_date"))
            if found:
                return found
    if not province and city:
        for prov in CN_TAX["provinces"].values():
            for name, row in (prov.get("cities") or {}).items():
                if city.strip() in (name, row.get("name_zh")):
                    return parse_date(row.get("tender_switch_date"))
    return parse_date(province.get("tender_switch_date"))


def national_switch_date() -> date | None:
    """The day GB/T 50500-2024 came into force nationally, from the editions data."""
    for row in CN_TAX["editions"]:
        if row.get("key") == EDITION_2024:
            return parse_date(row.get("in_force_from"))
    return None
