# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo seals for the four demo projects, one per market.

Each demo project gets its own bill sealed (the worked example only where the
project has no priced bill), a receipt, one closed opening with its attendees
and audit trail, and one change priced from a position of that sealed bill.
Idempotent: a project that already has a seal is skipped.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.estimate_archive import engine, fixtures
from app.modules.estimate_archive.models import (
    EstimateSeal,
    EstimateSealAttachment,
    EstimateSealReceipt,
    SealDerivation,
    SealEvent,
    SealOpening,
)

logger = logging.getLogger(__name__)

_DE_CHANGE: dict[str, Any] = {
    "quantity": "310",
    "changes": [{"code": "L-TRENCH", "consumption": "0.62", "note": "Deeper trench, more hand digging"}],
    "additions": [
        {
            "kind": "plant",
            "code": "SHORING",
            "description": "Trench shoring hire",
            "unit": "m3",
            "consumption": "1",
            "unit_cost": "3.40",
            "quote_ref": "Q-118",
            "price_date": "2026-11-03",
        }
    ],
    "current_unit_costs": {"L-TRENCH": "55.10"},
}
_UK_CHANGE: dict[str, Any] = {
    "quantity": "180",
    "changes": [{"code": "LAB", "consumption": "0.42", "note": "Wet ground, slower excavation"}],
    "additions": [
        {
            "kind": "plant",
            "code": "PUMP",
            "description": "Dewatering pump",
            "unit": "day",
            "consumption": "0.025",
            "unit_cost": "95.00",
            "quote_ref": "Plant schedule P4",
        }
    ],
}
_FIDIC_CHANGE: dict[str, Any] = {
    "quantity": "64",
    "changes": [{"code": "CONC", "unit_cost": "113.50", "note": "Higher grade, dated quote 2026-10-20"}],
}

#: demo id -> (fallback payload, profile, reference, attendees: (name, organisation, role, side))
_PLAN: dict[str, tuple[Any, str, str, list[tuple[str, str, str, str]]]] = {
    "residential-berlin": (
        fixtures.example_de_trench,
        "de",
        "Nachtrag N-07",
        [
            ("Jonas Weber", "Bauunternehmung", "Kalkulator", "internal"),
            ("Petra Lang", "Bauherr", "Projektsteuerung", "counterparty"),
        ],
    ),
    "office-london": (
        fixtures.example_uk_trench,
        "uk",
        "Variation V-012",
        [
            ("Sam Patel", "Main contractor", "Commercial manager", "internal"),
            ("Laura Hughes", "Employer's QS", "Quantity surveyor", "counterparty"),
        ],
    ),
    "warehouse-dubai": (
        fixtures.example_fidic_pipe_surround,
        "fidic",
        "Variation VO-04",
        [
            ("Omar Haddad", "Contractor", "Planning and cost lead", "internal"),
            ("Rachel Moore", "Engineer", "Engineer's representative", "counterparty"),
        ],
    ),
    "medical-us": (
        fixtures.example_fidic_pipe_surround,
        "us",
        "Change order CO-03",
        [
            ("Dana Brooks", "General contractor", "Senior estimator", "internal"),
            ("Mark Ellis", "Owner", "Owner's representative", "counterparty"),
        ],
    ),
}


#: The worked examples' changes, used when the sealed bill holds their position.
_KNOWN_CHANGES: tuple[tuple[str, dict[str, Any]], ...] = (
    ("02.03.0040", _DE_CHANGE),
    ("D20.1", _UK_CHANGE),
    ("4.07", _FIDIC_CHANGE),
)


def demo_change(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """A believable change to one position of the sealed bill, or None when it prices nothing.

    The worked example's change where the bill holds that position; otherwise a
    quarter more of the costliest coded resource on the first position with a
    breakdown; a position without one only changes quantity.
    """
    priced = [p for p in payload.get("positions") or [] if engine.is_priced(p)]
    if not priced:
        return None
    for ordinal, change in _KNOWN_CHANGES:
        position = engine.find_position(payload, ordinal)
        codes = {str(r.get("code") or "") for r in (position or {}).get("resources") or []}
        if position is not None and {str(c["code"]) for c in change.get("changes") or []} <= codes:
            return ordinal, change
    position = next((p for p in priced if any(r.get("code") for r in p.get("resources") or [])), priced[0])
    quantity = max(engine.dec(position.get("quantity")) / 4, Decimal(1)).quantize(Decimal(1))
    change: dict[str, Any] = {"quantity": engine.canon(quantity)}
    coded = [r for r in position.get("resources") or [] if r.get("code")]
    if coded:
        top = max(coded, key=lambda r: engine.dec(r.get("consumption")) * engine.dec(r.get("unit_cost")))
        more = engine.dec(top.get("consumption")) * Decimal("1.25")
        change["changes"] = [
            {"code": top["code"], "consumption": engine.canon(more), "note": "Harder conditions than tendered"}
        ]
    return str(position.get("ordinal")), change


async def seed_estimate_archive_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Seal one estimate per demo project that has none yet."""
    from app.modules.boq.models import BOQ
    from app.modules.contracts.models import Contract
    from app.modules.projects.models import Project

    pids = list(project_ids)
    if not pids:
        return {"seals": 0}
    rows = (
        await session.execute(select(Project.id, Project.metadata_, Project.owner_id).where(Project.id.in_(pids)))
    ).all()
    done = set(
        (await session.execute(select(EstimateSeal.project_id).where(EstimateSeal.project_id.in_(pids)))).scalars()
    )
    created = 0
    for pid, meta, owner_id in rows:
        demo_id = str((meta or {}).get("demo_id") or "") if isinstance(meta, dict) else ""
        plan = _PLAN.get(demo_id)
        if plan is None or pid in done:
            continue
        build, profile, reference, people = plan
        boq_id = (
            await session.execute(select(BOQ.id).where(BOQ.project_id == pid).order_by(BOQ.created_at).limit(1))
        ).scalar_one_or_none()
        contract = (
            (
                await session.execute(
                    select(Contract)
                    .where(Contract.project_id == pid, Contract.counterparty_type == "client")
                    .order_by(Contract.created_at)
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        payload, total = await _sealed_bill(session, boq_id, contract)
        if payload is None:
            payload, boq_id = build(), None
            total = engine.payload_totals(payload)["grand_total"]
        award = getattr(contract, "original_contract_value", None)
        if award is not None and abs(engine.dec(award) - total) > Decimal("0.01"):
            # Seal the bill as it stands; a contract whose award differs is not claimed as its basis.
            contract = None
        await _seal_one(session, pid, owner_id, boq_id, contract, payload, total, profile, reference, people)
        created += 1
    await session.flush()
    logger.info("seed_estimate_archive_demo: %d seals", created)
    return {"seals": created}


async def _sealed_bill(
    session: AsyncSession, boq_id: uuid.UUID | None, contract: Any
) -> tuple[dict[str, Any] | None, Decimal]:
    """The project's own bill as a seal payload with its total; None when it prices nothing."""
    if boq_id is None:
        return None, Decimal(0)
    from app.modules.estimate_archive.service import EstimateArchiveService

    svc = EstimateArchiveService(session)
    boq, positions, markups = await svc._bill(boq_id)
    project = await svc._project(boq.project_id)
    currency = str(getattr(contract, "currency", "") or getattr(project, "currency", "") or "")
    payload = await svc.build_payload(boq, positions, markups, [], currency)
    if demo_change(payload) is None:
        return None, Decimal(0)
    return payload, await svc._bill_total(boq_id, payload)


async def _seal_one(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID | None,
    boq_id: uuid.UUID | None,
    contract: Any,
    payload: dict[str, Any],
    total: Decimal,
    profile: str,
    reference: str,
    people: list[tuple[str, str, str, str]],
) -> None:
    from app.modules.estimate_archive import policy
    from app.modules.estimate_archive.service import add_years

    now = datetime.now(UTC).replace(microsecond=0)
    sealed_at = now - timedelta(days=120)
    digest = engine.seal_digest(payload)
    years = int(policy.policy_for(profile).get("retention_years") or 10)
    picked = demo_change(payload)
    if picked is None:
        return
    ordinal, change = picked
    currency = payload["estimate"].get("currency") or ""
    base = f"{contract.code} {contract.title}".strip() if contract is not None else payload["estimate"]["name"]
    seal = EstimateSeal(
        project_id=project_id,
        contract_id=getattr(contract, "id", None),
        source_boq_id=boq_id,
        label=f"{base} - {sealed_at.date().isoformat()}",
        schema_version=engine.SCHEMA,
        payload=payload,
        content_hash=digest,
        sealed_at=sealed_at,
        sealed_by=owner_id,
        award_total=Decimal(engine.money(total)),
        currency=currency,
        basis_kind="award",
        status="sealed",
        deposit_mode="platform",
        retention_until=add_years(sealed_at.date(), years).isoformat(),
        supersede_reason="",
        profile=profile,
        last_verified_at=now - timedelta(days=14),
        last_verified_ok=True,
        metadata_={"demo": True},
    )
    session.add(seal)
    await session.flush()

    def event(
        kind: str,
        at: datetime,
        *,
        opening: SealOpening | None = None,
        name: str = "",
        org: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            SealEvent(
                seal_id=seal.id,
                opening_id=opening.id if opening else None,
                event_type=kind,
                actor_id=owner_id if not name else None,
                actor_name=name or people[0][0],
                actor_organisation=org or people[0][1],
                detail=detail or {},
                created_at=at,
            )
        )

    attachment_name = "EFB 221.pdf" if profile == "de" else "Rate build-up.pdf"
    session.add(
        EstimateSealAttachment(
            seal_id=seal.id,
            name=attachment_name,
            kind="document",
            file_hash=engine.seal_digest({"demo_file": attachment_name}),
        )
    )
    session.add(
        EstimateSealReceipt(
            seal_id=seal.id,
            kind="external",
            external_reference=f"{reference} handover",
            acknowledged_hash=digest,
            status="external",
            signed_at=sealed_at + timedelta(days=2),
            created_by=owner_id,
        )
    )
    event("sealed", sealed_at, detail={"content_hash": digest})
    event("receipt_external", sealed_at + timedelta(days=2), detail={"reference": f"{reference} handover"})

    opened = now - timedelta(days=21)
    attendees = [{"name": n, "organisation": o, "role": r, "side": s, "present": True} for n, o, r, s in people]
    opening = SealOpening(
        seal_id=seal.id,
        requested_by=owner_id,
        reason="variation",
        reference_type="variation",
        reference_label=reference,
        scope="positions",
        scope_ordinals=[ordinal],
        attendees=attendees,
        one_party_reason="",
        status="closed",
        requested_at=opened - timedelta(days=3),
        opened_at=opened,
        closed_at=opened + timedelta(hours=2),
        hash_check="ok",
        hash_seen=digest,
        positions_viewed=[ordinal],
    )
    session.add(opening)
    await session.flush()
    event(
        "opening_requested",
        opening.requested_at,
        opening=opening,
        detail={"reason": "variation", "reference": reference},
    )
    event("opening_started", opened, opening=opening)
    for a in attendees:
        event(
            "attended",
            opened,
            opening=opening,
            name=a["name"],
            org=a["organisation"],
            detail={"role": a["role"], "side": a["side"]},
        )
    event("hash_check", opened, opening=opening, detail={"ok": True, "sealed": digest, "actual": digest})
    event("position_viewed", opened + timedelta(minutes=20), opening=opening, detail={"ordinal": ordinal})
    event("opening_closed", opened + timedelta(hours=2), opening=opening, detail={"positions_viewed": [ordinal]})

    result = engine.derive_rate(payload, ordinal, **change)
    rate = next(Decimal(m["rate"]) for m in result["methods"] if m["method"] == "original_basis")
    session.add(
        SealDerivation(
            seal_id=seal.id,
            position_ordinal=ordinal,
            reference_label=reference,
            description=str(result.get("description") or ""),
            quantity=Decimal(result["quantity"]),
            inputs=change,
            result=result,
            basis_method="original_basis",
            chosen_rate=rate,
            created_by=owner_id,
        )
    )
    event(
        "derivation_recorded",
        opened + timedelta(hours=1),
        opening=opening,
        detail={"ordinal": ordinal, "reference": reference, "basis_method": "original_basis"},
    )
