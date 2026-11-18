# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠China regional pack API routes.

Endpoints:
    GET  /config/                          - the full China regional configuration
    GET  /tax/                             - VAT categories, elections, editions, structures
    POST /tender-summary/                  - head totals, VAT base, VAT, tender total of posted lines
    POST /check/                           - run the cn_vat rules over a posted record
    GET  /projects/{project_id}/check/     - summary and cn_vat findings of a stored project
    GET  /invoices/{invoice_id}/fapiao/    - 数电票 data (JSON or XML) for import into a channel
    POST /prepayment/                      - 预缴 schedule at the pack's rates
    GET  /fee-schedules/                   - provincial fee jurisdictions and schedules with sources
    POST /fee-calc/                        - run a provincial fee programme over posted sums
    GET  /projects/{project_id}/fees/      - the project's fee programme over its bills, with findings
    PUT  /projects/{project_id}/fees/      - save rates, options and bases picked inside the programme
    GET  /projects/{project_id}/edition-move/ - preview of moving the project to GB/T 50500-2024
    POST /projects/{project_id}/edition-move/ - apply the confirmed move
"""

import logging
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_id,
    verify_project_access,
)
from app.modules.china_pack import fapiao, fees, repository, service
from app.modules.china_pack.config import CN_TAX, PACK_CONFIG
from app.modules.china_pack.models import ChinaFeeProfile
from app.modules.china_pack.schemas import FeeCalcRequest, FeeSettings
from app.modules.china_pack.validators import RULE_IDS, evaluate

router = APIRouter(dependencies=[Depends(get_current_user_id)], tags=["china_pack"])
logger = logging.getLogger(__name__)


class SummaryRequest(BaseModel):
    """Bill lines and the settings to total them under."""

    lines: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)
    edition: str | None = None
    tax_method: Literal["general", "simplified", "exempt"] = "general"
    taxpayer_size: Literal["general", "small"] = "general"
    on: date | None = None


class CheckRequest(BaseModel):
    """A ``cn_vat_check`` record without the database: profile, lines, invoices, 预缴, contract."""

    profile: dict[str, Any] = Field(default_factory=dict)
    lines: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)
    invoices: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    prepayment: dict[str, Any] = Field(default_factory=dict)
    contract: dict[str, Any] = Field(default_factory=dict)
    markup_names: list[str] = Field(default_factory=list)


def _findings(results: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "rule_id": r.rule_id,
            "severity": str(r.severity.value if hasattr(r.severity, "value") else r.severity),
            "message": r.message,
            "element_ref": r.element_ref,
            "details": dict(r.details or {}),
        }
        for r in results
    ]


def _summary_for(record: dict[str, Any]) -> dict[str, Any]:
    profile = record.get("profile") or {}
    return service.tender_summary(
        record.get("lines") or [],
        service.SummaryInput(
            edition=profile.get("standard_edition"),
            tax_method=str(profile.get("tax_method") or "general"),
            taxpayer_size=str(profile.get("taxpayer_size") or "general"),
            on=None,
        ),
    )


@router.get("/config/")
async def get_config() -> dict:
    """Return the China regional pack configuration."""
    return PACK_CONFIG


@router.get("/tax/")
async def get_tax() -> dict:
    """VAT categories with dates, simplified elections, editions and bill structures."""
    return CN_TAX


@router.post("/tender-summary/")
async def post_tender_summary(body: SummaryRequest) -> dict:
    """Head totals, VAT base, VAT and tender total of the posted lines."""
    return service.tender_summary(
        body.lines,
        service.SummaryInput(
            edition=body.edition, tax_method=body.tax_method, taxpayer_size=body.taxpayer_size, on=body.on
        ),
    )


@router.post("/check/")
async def post_check(body: CheckRequest) -> dict:
    """Run the cn_vat rules over a posted record."""
    record = service.build_record(
        profile=body.profile,
        lines=body.lines,
        invoices=body.invoices,
        prepayment=body.prepayment,
        contract=body.contract,
        markup_names=body.markup_names,
    )
    return {"summary": _summary_for(record), "findings": _findings(await evaluate(record))}


@router.get("/projects/{project_id}/check/")
async def get_project_check(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """Tender summary and cn_vat findings of a stored project's bills and receivable invoices."""
    await verify_project_access(project_id, user_id, session)
    try:
        record = await service.project_record(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    return {
        "profile": record["profile"],
        "summary": _summary_for(record),
        "lines": len(record["lines"]),
        "invoices": len(record["invoices"]),
        "findings": _findings(await evaluate(record)),
    }


@router.get("/invoices/{invoice_id}/fapiao/")
async def get_fapiao(
    invoice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: Literal["json", "xml"] = Query("json", alias="format"),
) -> Response:
    """The 数电票 data of one invoice, to import into the taxpayer's certified channel."""
    from app.modules.finance.models import Invoice  # noqa: PLC0415

    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    await verify_project_access(invoice.project_id, user_id, session)
    try:
        data = await fapiao.load_fapiao_data(session, invoice_id)
    except fapiao.FapiaoDataError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if fmt == "xml":
        return Response(fapiao.to_xml(data), media_type="application/xml; charset=utf-8")
    return Response(fapiao.to_json(data), media_type="application/json; charset=utf-8")


class PrepaymentRequest(BaseModel):
    """预缴 periods; the rates follow the tax method from the pack."""

    tax_method: Literal["general", "simplified"] = "general"
    periods: list[dict[str, Any]] = Field(..., min_length=1, max_length=240)
    carried_in: str | None = None


@router.post("/prepayment/")
async def post_prepayment(body: PrepaymentRequest) -> dict:
    """预缴 per period: (receipts - subcontract paid) / (1 + rate) x prepayment rate."""
    from app.core.line_tax import to_decimal  # noqa: PLC0415
    from app.modules.china_pack.validators import prepayment_rates  # noqa: PLC0415
    from app.modules.tax_withholding.place_of_supply import (  # noqa: PLC0415
        PrepaymentPeriod,
        prepayment_schedule,
    )

    tax_rate, prepay_rate = prepayment_rates(body.tax_method)
    schedule = prepayment_schedule(
        [
            PrepaymentPeriod(
                period=str(p.get("period") or i + 1),
                receipts=to_decimal(p.get("receipts")),
                subcontract_paid=to_decimal(p.get("subcontract_paid")),
                recorded_prepaid=None if p.get("recorded_prepaid") in (None, "") else to_decimal(p["recorded_prepaid"]),
            )
            for i, p in enumerate(body.periods)
        ],
        tax_rate_pct=tax_rate,
        prepay_rate_pct=prepay_rate,
        carried_in=to_decimal(body.carried_in),
    )
    return {
        "tax_rate_pct": str(tax_rate),
        "prepay_rate_pct": str(prepay_rate),
        "verified": bool(CN_TAX["prepayment"].get("verified")),
        "periods": [
            {
                "period": r.period,
                "receipts": str(r.receipts),
                "subcontract_paid": str(r.subcontract_paid),
                "carried_in": str(r.carried_in),
                "base_net": str(r.base_net),
                "prepaid": str(r.prepaid),
                "carried_out": str(r.carried_out),
                "recorded_prepaid": None if r.recorded_prepaid is None else str(r.recorded_prepaid),
                "matches": r.matches,
            }
            for r in schedule
        ],
    }


# ── Provincial fee programmes ────────────────────────────────────────────────


@router.get("/fee-schedules/")
async def get_fee_schedules(subdivision: str | None = None, city: str | None = None) -> dict:
    """The fee jurisdictions and schedules; filtered to one site when a province or city is given."""
    cat = fees.catalogue()
    keys = list(cat["jurisdictions"])
    if subdivision or city:
        found = fees.jurisdiction_for(subdivision, city)
        keys = [found] if found else []
    return {
        "jurisdictions": {
            k: {**cat["jurisdictions"][k], "schedules": [fees.schedule_summary(s.key) for s in fees.schedules_for(k)]}
            for k in keys
        },
        "sources": cat["sources"],
    }


@router.post("/fee-calc/")
async def post_fee_calc(body: FeeCalcRequest) -> dict:
    """Run the site's fee programme over posted component sums and check it."""
    profile = {
        "site_subdivision": body.subdivision,
        "site_city": body.city,
        "tender_date": body.tender_date.isoformat() if body.tender_date else None,
        "contract_date": body.contract_date.isoformat() if body.contract_date else None,
        "tax_method": body.tax_method,
    }
    fee = fees.fee_block(
        profile, body.settings.model_dump(), {"components": body.components}, markup_names=body.markup_names
    )
    if fee is None:
        return {"fee": None, "findings": []}
    record = service.build_record(profile=profile, fee=fee, markup_names=body.markup_names)
    return {"fee": fee, "findings": _findings(await evaluate(record))}


async def _fee_view(session: Any, project_id: uuid.UUID) -> dict:
    try:
        record = await service.project_record(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    fee_rule_ids = {r for r in RULE_IDS if r.startswith(("cn.fee.", "cn.labour.", "cn.sc.", "cn.price."))}
    findings = [f for f in _findings(await evaluate(record)) if f["rule_id"] in fee_rule_ids]
    return {"fee": record.get("fee") or None, "prices": record.get("prices") or {}, "findings": findings}


@router.get("/projects/{project_id}/fees/")
async def get_project_fees(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """The project's provincial fee programme computed over its bills, with the fee findings."""
    await verify_project_access(project_id, user_id, session)
    return await _fee_view(session, project_id)


@router.put(
    "/projects/{project_id}/fees/",
    dependencies=[Depends(RequirePermission("project_tax.write"))],
)
async def put_project_fees(
    project_id: uuid.UUID, payload: FeeSettings, session: SessionDep, user_id: CurrentUserId
) -> dict:
    """Save the rates, options and bases a person picked, then recompute."""
    await verify_project_access(project_id, user_id, session)
    row = await repository.get_fee_profile(session, project_id)
    if row is None:
        row = ChinaFeeProfile(project_id=project_id)
    row.schedule_key = payload.schedule_key or None
    row.rates = dict(payload.rates)
    row.options = dict(payload.options)
    row.bases = {k: dict(v) for k, v in payload.bases.items()}
    row.labour_includes_social_insurance = payload.labour_includes_social_insurance
    row.apply_labour_factor = payload.apply_labour_factor
    row.updated_by = user_id
    await repository.save_fee_profile(session, row)
    await session.commit()
    return await _fee_view(session, project_id)


@router.get("/projects/{project_id}/edition-move/")
async def get_edition_move(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """Preview of moving the project to GB/T 50500-2024: what is applied and what to move by hand."""
    await verify_project_access(project_id, user_id, session)
    try:
        record = await service.project_record(session, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
    return fees.edition_move_preview(record)


@router.post(
    "/projects/{project_id}/edition-move/",
    dependencies=[Depends(RequirePermission("project_tax.write"))],
)
async def post_edition_move(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """Apply the move a person confirmed: the profile edition, and 规费 markups switched off."""
    from app.modules.boq.models import BOQ  # noqa: PLC0415
    from app.modules.project_tax import repository as tax_repo  # noqa: PLC0415
    from app.modules.project_tax import service as tax_service  # noqa: PLC0415
    from app.modules.project_tax.schemas import ProfileUpdate  # noqa: PLC0415
    from app.modules.projects.models import Project  # noqa: PLC0415

    await verify_project_access(project_id, user_id, session)
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    current = tax_service.to_response(project, await tax_repo.get_for_project(session, project_id))
    fields = current.model_dump(include=set(ProfileUpdate.model_fields))
    fields["standard_edition"] = service.EDITION_2024
    await tax_service.save_profile(session, project, ProfileUpdate(**fields), user_id=user_id)
    switched: list[str] = []
    bills = (await session.execute(select(BOQ).where(BOQ.project_id == project_id))).scalars().all()
    for bill in bills:
        for markup in bill.markups:
            if markup.is_active and "规费" in str(markup.name):
                markup.is_active = False
                switched.append(str(markup.name))
    await session.commit()
    record = await service.project_record(session, project_id)
    return {
        "applied": {"standard_edition": service.EDITION_2024, "markups_switched_off": switched},
        **fees.edition_move_preview(record),
    }
