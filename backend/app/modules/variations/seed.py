# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic seed data for the variations module."""

from __future__ import annotations

import functools
import logging
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_showcase import GERMAN_SHOWCASE_DEMO_IDS
from app.modules.projects.models import Project
from app.modules.variations.models import (
    DayworkSheet,
    DayworkSheetLine,
    DisruptionClaim,
    ExtensionOfTimeClaim,
    FinalAccount,
    Notice,
    SiteMeasurement,
    VariationCostImpact,
    VariationOrder,
    VariationRequest,
    VariationScheduleImpact,
)

logger = logging.getLogger(__name__)

_SEED = 42


def _date_offset(rng: random.Random, days_back_max: int = 180) -> str:
    delta = rng.randint(1, days_back_max)
    return (datetime.now(UTC) - timedelta(days=delta)).isoformat()


def _short_date_offset(rng: random.Random, days_back_max: int = 180) -> str:
    delta = rng.randint(1, days_back_max)
    return (datetime.now(UTC) - timedelta(days=delta)).date().isoformat()


_NOTICE_RECIPIENTS = ("owner", "contractor", "architect", "engineer")
_VR_STATUSES = ("draft", "submitted", "under_review", "approved", "rejected", "converted_to_vo")
_VR_CLASSIFICATIONS = (
    "scope_change",
    "unforeseen",
    "owner_change",
    "design_dev",
    "regulatory",
    "other",
)
_VO_STATUSES = ("issued", "in_progress", "completed", "voided")
_COST_CATEGORIES = (
    "labor",
    "material",
    "equipment",
    "subcontractor",
    "overhead",
    "profit",
)
_LINE_TYPES = ("labor", "material", "equipment")

# A daywork line is signed off on site, so it names the resource it is for and
# the operative who booked it.
_DAYWORK_DESCRIPTIONS = {
    "labor": "Site operative hours on instructed additional works",
    "material": "Materials drawn from stores for instructed works",
    "equipment": "Plant standing and operating time",
}

_WORKER_NAMES = (
    "P. Vogel",
    "M. Halvorsen",
    "S. Dubois",
    "T. Farkas",
    "A. Serrano",
    "J. Keller",
)
_DW_STATUSES = ("draft", "signed", "disputed", "billed")
_DISRUPTION_STATUSES = ("draft", "submitted", "under_review", "agreed", "rejected")
_EOT_CAUSES = ("employer_caused", "neutral", "contractor_caused", "concurrent")

# What a register row actually says. The earlier filler ("Seed VR #12",
# "Seed daywork sheet #59") put the word "Seed" on screen in every install;
# these read as records a commercial team would recognise.
_VR_DESCRIPTIONS = {
    "scope_change": "Scope adjusted after the coordination review; quantities and interfaces to be re-priced.",
    "unforeseen": "Conditions found on site differ from the contract documents; additional works are required.",
    "owner_change": "Change instructed by the owner's representative; pricing requested before execution.",
    "design_dev": "Design development detail issued after award; the affected packages are re-measured.",
    "regulatory": "Authority requirement recorded during inspection; compliance works to be added.",
    "other": "Commercial adjustment raised at the monthly progress meeting.",
}

_COST_IMPACT_DESCRIPTIONS = {
    "labor": "Additional crew hours on the varied works",
    "material": "Materials drawn for the varied works",
    "equipment": "Plant standing and operating time on the varied works",
    "subcontractor": "Subcontracted portion of the varied works",
    "overhead": "Site overhead allocation for the extended activity",
    "profit": "Margin on the varied works",
}

_DAYWORK_WORK_DESCRIPTIONS = (
    "Breaking out and reinstating around the revised service route",
    "Attendance on the specialist contractor during the instructed works",
    "Temporary protection and clean-up after the varied works",
    "Setting out and survey checks for the instructed change",
    "Additional handling and distribution of materials on site",
)

_DISRUPTION_DESCRIPTIONS = (
    "Out-of-sequence working after the instructed change interrupted the planned crew rotation.",
    "Trade stacking in the affected area reduced productivity against the measured baseline.",
    "Repeated remobilisation to the work front after late information releases.",
)

_EOT_DESCRIPTIONS = (
    "Delay event on the critical path following the instructed variation.",
    "Extended procurement lead time for the substituted material.",
    "Suspension of the affected work front pending the authority decision.",
)


async def _project_currencies(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Currency per project, so seeded money is in the unit the project uses.

    This seeder used to write EUR on every row. A variation order priced in
    EUR against a project that budgets in AED is not a display problem, it is
    two numbers that must not be added, and the demo estate offered them in one
    list. Projects that never set a currency keep the old default.
    """
    rows = await session.execute(select(Project.id, Project.currency).where(Project.id.in_(project_ids)))
    return {pid: (currency or "EUR") for pid, currency in rows.all()}


#: Demo projects whose variations register is hand-authored in German by
#: :func:`seed_variations_showcase_de`. The generic English sprinkle below
#: must not reach them: a German showcase project with "Notice of variation
#: 12" in its Anzeigen tab is the defect the showcase audit filed. The list
#: is shared with the other localised registers - see
#: :mod:`app.core.demo_showcase` for why it has one home.
_GERMAN_SHOWCASE_IDS = GERMAN_SHOWCASE_DEMO_IDS


async def _demo_ids_by_project(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Map project id -> its demo marker (empty string for real projects)."""
    rows = await session.execute(select(Project.id, Project.metadata_).where(Project.id.in_(project_ids)))
    out: dict[uuid.UUID, str] = {}
    for pid, meta in rows.all():
        out[pid] = str(meta.get("demo_id") or "").strip() if isinstance(meta, dict) else ""
    return out


async def seed_variations_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate variations tables with deterministic demo data.

    Distribution (per spec):
      * 30 Notices
      * 40 Variation Requests
      * 25 Variation Orders
      * 60 cost-impact lines
      * 35 schedule-impact lines
      * 50 Site Measurements
      * 80 Daywork Sheets
      * 10 Disruption Claims
      * 5 EOT Claims
      * 2 closed Final Accounts

    Returns a counts dict for caller-side logging/asserts.
    """
    projects = list(project_ids)
    if not projects:
        return {"projects": 0}

    # The German showcase projects carry a hand-authored German register
    # (seed_variations_showcase_de) instead of this generic English sprinkle.
    # Filtered before the already-seeded guard on purpose: German rows on
    # those projects must not read as "the sprinkle already ran" for the
    # rest of the estate.
    demo_ids = await _demo_ids_by_project(session, projects)
    projects = [pid for pid in projects if demo_ids.get(pid, "") not in _GERMAN_SHOWCASE_IDS]
    if not projects:
        return {"projects": 0}

    # Guarded as a whole rather than row by row. This seeder writes one
    # connected estate - notices, then the requests and orders that reference
    # them - so skipping individual duplicates would leave the later rows
    # pointing at nothing. Notice codes are unique per project, so a second
    # pass used to abort on ``NOT-0001`` instead of doing nothing. Callers
    # carried this check externally; holding it here means a direct call is
    # safe too, which is what a re-seed of the demo box actually does.
    already_seeded = (await session.execute(select(Notice.id).where(Notice.project_id.in_(projects)).limit(1))).first()
    if already_seeded is not None:
        logger.info("seed_variations_demo: variations already present, skipping")
        return {
            "notices": 0,
            "variation_requests": 0,
            "variation_orders": 0,
            "cost_impact_lines": 0,
            "schedule_impact_lines": 0,
            "site_measurements": 0,
            "daywork_sheets": 0,
            "daywork_lines": 0,
            "disruption_claims": 0,
            "eot_claims": 0,
            "final_accounts": 0,
        }

    rng = random.Random(_SEED)
    currencies = await _project_currencies(session, projects)

    # ── Notices ───────────────────────────────────────────────────────────
    notices: list[Notice] = []
    for i in range(30):
        pid = rng.choice(projects)
        recipient = rng.choice(_NOTICE_RECIPIENTS)
        notice = Notice(
            project_id=pid,
            code=f"NOT-{i + 1:04d}",
            title=f"Notice of variation {i + 1}",
            description=f"Notice served on the {recipient} regarding a change to the works.",
            raised_at=_date_offset(rng),
            raised_by=None,
            recipient_type=recipient,
            recipient_name=f"{recipient.title()} contact",
            target_response_date=_short_date_offset(rng, days_back_max=30),
            status=rng.choice(["issued", "acknowledged", "responded", "closed"]),
        )
        session.add(notice)
        notices.append(notice)
    await session.flush()

    # ── Variation Requests ────────────────────────────────────────────────
    vrs: list[VariationRequest] = []
    for i in range(40):
        pid = rng.choice(projects)
        notice_id = rng.choice(notices).id if notices and rng.random() < 0.4 else None
        classification = rng.choice(_VR_CLASSIFICATIONS)
        vr = VariationRequest(
            project_id=pid,
            notice_id=notice_id,
            code=f"VR-{i + 1:04d}",
            title=f"Variation request {i + 1}",
            description=_VR_DESCRIPTIONS.get(classification, _VR_DESCRIPTIONS["other"]),
            requested_at=_date_offset(rng),
            classification=classification,
            urgency=rng.choice(["low", "med", "high"]),
            estimated_cost_impact=Decimal(str(rng.randint(500, 50000))),
            estimated_schedule_days=rng.randint(0, 30),
            currency=currencies.get(pid, "EUR"),
            status=rng.choice(_VR_STATUSES),
        )
        session.add(vr)
        vrs.append(vr)
    await session.flush()

    # ── Variation Orders ──────────────────────────────────────────────────
    vos: list[VariationOrder] = []
    for i in range(25):
        pid = rng.choice(projects)
        source_vr = (
            rng.choice([v for v in vrs if v.project_id == pid]) if any(v.project_id == pid for v in vrs) else None
        )
        vo = VariationOrder(
            project_id=pid,
            variation_request_id=source_vr.id if source_vr else None,
            code=f"VO-{i + 1:04d}",
            title=f"Variation order {i + 1}",
            final_cost_impact=Decimal(str(rng.randint(1000, 80000))),
            final_schedule_days=rng.randint(0, 21),
            currency=currencies.get(pid, "EUR"),
            agreed_at=_date_offset(rng),
            status=rng.choice(_VO_STATUSES),
        )
        session.add(vo)
        vos.append(vo)
    await session.flush()

    # ── Cost-impact lines (60) ────────────────────────────────────────────
    if vos:
        for _ in range(60):
            vo = rng.choice(vos)
            qty = Decimal(str(rng.randint(1, 100)))
            rate = Decimal(str(rng.randint(20, 500)))
            category = rng.choice(_COST_CATEGORIES)
            line = VariationCostImpact(
                variation_order_id=vo.id,
                category=category,
                description=_COST_IMPACT_DESCRIPTIONS.get(category, "Varied works"),
                quantity=qty,
                unit=rng.choice(["m2", "m3", "h", "pcs"]),
                unit_rate=rate,
                total=qty * rate,
                # Follows the order it belongs to, not the loop it sits in.
                currency=currencies.get(vo.project_id, "EUR"),
                source=rng.choice(["manual", "from_bom", "from_estimate"]),
            )
            session.add(line)

    # ── Schedule-impact lines (35) ────────────────────────────────────────
    if vos:
        for i in range(35):
            vo = rng.choice(vos)
            si = VariationScheduleImpact(
                variation_order_id=vo.id,
                affected_activity_ref=f"Task #{i + 1}",
                original_finish_date=_short_date_offset(rng),
                revised_finish_date=_short_date_offset(rng),
                days_added=rng.randint(0, 14),
                is_critical_path=rng.random() < 0.3,
                justification="Follow-on trades resequenced around the varied works.",
            )
            session.add(si)
    await session.flush()

    # ── Site Measurements (50) ────────────────────────────────────────────
    for i in range(50):
        pid = rng.choice(projects)
        sm = SiteMeasurement(
            project_id=pid,
            recorded_at=_date_offset(rng),
            location=f"Block {chr(65 + (i % 6))} - L{i % 5}",
            item_description=f"Quantity #{i + 1}",
            unit=rng.choice(["m2", "m3", "m", "pcs"]),
            measured_quantity=Decimal(str(rng.randint(5, 500))),
            owner_signature_ref=f"sig-{i + 1:04d}",
            # No invented image links: a URL on a host that does not exist is
            # a broken image the moment any screen renders this list.
            photos=[],
            notes="Joint measurement agreed with the owner's representative on site.",
            variation_order_id=rng.choice(vos).id if vos and rng.random() < 0.4 else None,
        )
        session.add(sm)
    await session.flush()

    # ── Daywork Sheets (80) ───────────────────────────────────────────────
    sheets: list[DayworkSheet] = []
    for i in range(80):
        pid = rng.choice(projects)
        ds = DayworkSheet(
            project_id=pid,
            sheet_number=f"DW-{i + 1:04d}",
            work_date=_short_date_offset(rng),
            description=_DAYWORK_WORK_DESCRIPTIONS[i % len(_DAYWORK_WORK_DESCRIPTIONS)],
            total_amount=Decimal("0"),
            currency=currencies.get(pid, "EUR"),
            status=rng.choice(_DW_STATUSES),
            owner_signature_ref=f"dw-sig-{i + 1:04d}" if rng.random() < 0.5 else "",
        )
        session.add(ds)
        sheets.append(ds)
    await session.flush()

    # Two lines per sheet (160 lines) + recompute totals.
    for sheet in sheets:
        sheet_total = Decimal("0")
        for _ in range(2):
            qty = Decimal(str(rng.randint(1, 12)))
            rate = Decimal(str(rng.randint(20, 200)))
            total = qty * rate
            line_type = rng.choice(_LINE_TYPES)
            line = DayworkSheetLine(
                sheet_id=sheet.id,
                line_type=line_type,
                description=_DAYWORK_DESCRIPTIONS.get(line_type, "Additional works"),
                quantity=qty,
                unit=rng.choice(["h", "m2", "pcs"]),
                unit_rate=rate,
                total=total,
                worker_name=rng.choice(_WORKER_NAMES),
            )
            session.add(line)
            sheet_total += total
        sheet.total_amount = sheet_total
    await session.flush()

    # ── Disruption Claims (10) ────────────────────────────────────────────
    for i in range(10):
        pid = rng.choice(projects)
        amount = Decimal(str(rng.randint(2000, 100_000)))
        st = rng.choice(_DISRUPTION_STATUSES)
        claim = DisruptionClaim(
            project_id=pid,
            raised_at=_date_offset(rng),
            claim_period_start=_short_date_offset(rng, days_back_max=200),
            claim_period_end=_short_date_offset(rng, days_back_max=60),
            description=_DISRUPTION_DESCRIPTIONS[i % len(_DISRUPTION_DESCRIPTIONS)],
            root_cause="Access to the work area was released later than programmed.",
            cost_amount=amount,
            schedule_days=rng.randint(0, 30),
            currency=currencies.get(pid, "EUR"),
            evidence_refs=[f"diary-{i + 1}", f"rfi-{i + 1}"],
            status=st,
            decided_amount=amount if st == "agreed" else None,
            decision_at=_date_offset(rng) if st in {"agreed", "rejected"} else None,
        )
        session.add(claim)

    # ── EOT Claims (5) ────────────────────────────────────────────────────
    for i in range(5):
        pid = rng.choice(projects)
        st = rng.choice(["draft", "submitted", "under_review", "granted", "rejected"])
        requested = rng.randint(5, 60)
        claim = ExtensionOfTimeClaim(
            project_id=pid,
            raised_at=_date_offset(rng),
            claim_period_start=_short_date_offset(rng, days_back_max=200),
            claim_period_end=_short_date_offset(rng, days_back_max=60),
            description=_EOT_DESCRIPTIONS[i % len(_EOT_DESCRIPTIONS)],
            root_cause_category=rng.choice(_EOT_CAUSES),
            requested_days=requested,
            granted_days=requested if st == "granted" else None,
            critical_path_impact=rng.random() < 0.5,
            status=st,
            decision_at=_date_offset(rng) if st in {"granted", "rejected"} else None,
        )
        session.add(claim)
    await session.flush()

    # ── Final Accounts (2 closed) ─────────────────────────────────────────
    closed = 0
    for pid in projects:
        if closed >= 2:
            break
        fa = FinalAccount(
            project_id=pid,
            original_contract_value=Decimal("1500000"),
            variations_total=Decimal("125000"),
            daywork_total=Decimal("35000"),
            claims_total=Decimal("18000"),
            retention_held=Decimal("75000"),
            retention_released=Decimal("75000"),
            final_value=Decimal("1678000"),
            currency=currencies.get(pid, "EUR"),
            status="closed",
            agreed_at=_date_offset(rng),
            closed_at=_date_offset(rng),
        )
        session.add(fa)
        closed += 1
    await session.flush()

    return {
        "notices": 30,
        "variation_requests": 40,
        "variation_orders": 25,
        "cost_impact_lines": 60,
        "schedule_impact_lines": 35,
        "site_measurements": 50,
        "daywork_sheets": 80,
        "daywork_lines": 160,
        "disruption_claims": 10,
        "eot_claims": 5,
        "final_accounts": closed,
    }


# ---------------------------------------------------------------------------
# German showcase estates (case: a Nachtrag proven from the record)
# ---------------------------------------------------------------------------
#
# Hand-authored German variations registers for the four German showcase
# projects. Each project gets a coherent Nachtrag story: a Mehrkostenanzeige
# served against a contractual response deadline and answered on the record, a
# Nachtragsangebot citing the notice and the VOB/B clause it rests on, and the
# beauftragte Nachtrag with its cost build-up, joint site measurement and
# Regieberichte. The lead chain of every project also carries the custody
# hand-offs and dated activity trail the claims-evidence provability engine
# grades, so at least one chain per project scores as provable instead of the
# all-weak estate the showcase audit measured.
#
# Codes use the VN- / VR- / VO- prefixes the reconciliation correlator parses
# (its tracked-code set), and the German texts cite each other's codes, so the
# evidence-thread reconstruction can stitch notice, request and order into one
# component instead of returning the subject alone.
#
# Day offsets count from the project's head-contract start date; entries with
# ``from_now`` set count from today instead, so the open items a viewer should
# act on stay current however old the install is.

_DE_PARTY_SITE = "Bauleitung"
_DE_PARTY_OWNER = "Bauherrenvertretung"
_DE_PARTY_SUB = "Nachunternehmer"

_DE_SHOWCASE: dict[str, dict[str, Any]] = {
    "office-frankfurt": {
        "anchor_co": "CO-001",
        "notices": [
            {
                "code": "VN-101",
                "title": "Mehrkostenanzeige Baugrund - nicht tragfähige Auffüllungen Baufeld West",
                "description": (
                    "Beim Aushub der Baugrube wurden im Baufeld West organische Auffüllungen unterhalb des "
                    "Gründungsniveaus angetroffen, die im Baugrundgutachten nicht ausgewiesen sind. Mehrkosten "
                    "und Bauzeitverzug werden gemäß § 2 Abs. 6 und § 6 Abs. 1 VOB/B angezeigt; das "
                    "Nachtragsangebot VR-101 folgt nach gemeinsamem Aufmaß."
                ),
                "day": 24,
                "due_days": 14,
                "ack_day": 26,
                "response_day": 33,
                "response_summary": (
                    "Bauherrenvertretung bestätigt die Prüfung dem Grunde nach; gemeinsames Aufmaß und "
                    "prüffähiges Nachtragsangebot angefordert."
                ),
                "status": "responded",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
            },
            {
                "code": "VN-102",
                "title": "Anzeige Umplanung Lüftungszentrale Dachgeschoss",
                "description": (
                    "Die fortgeschriebene TGA-Planung (Planindex C) ändert Geräteaufstellung und Kanalführung "
                    "der Lüftungszentrale. Mehr- und Minderkosten werden dem Grunde nach angezeigt; Angebot "
                    "VR-102 in Aufstellung."
                ),
                "day": 62,
                "due_days": 14,
                "ack_day": 65,
                "status": "acknowledged",
                "recipient_type": "engineer",
                "recipient_name": "Fachplanung TGA",
            },
            {
                "code": "VN-103",
                "title": "Anzeige Mehraufwand Brandschutzertüchtigung Tiefgaragendecke",
                "description": (
                    "Auflage aus der Bauzustandsbesichtigung: ergänzender Brandschutz an der "
                    "Tiefgaragendecke im Bereich der Trassenführung. Mehrkosten werden gemäß "
                    "§ 2 Abs. 6 VOB/B angezeigt; Kostenermittlung läuft."
                ),
                "day": -6,
                "from_now": True,
                "due_days": 14,
                "status": "issued",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "requests": [
            {
                "code": "VR-101",
                "notice": "VN-101",
                "title": "Nachtragsangebot 1 - Bodenaustausch Baufeld West",
                "description": (
                    "Nachtragsangebot auf Grundlage der Mehrkostenanzeige VN-101: Aushub und Entsorgung der "
                    "organischen Auffüllungen, Bodenaustausch mit verdichtungsfähigem Material 0/45, "
                    "Mehrdicke der Sauberkeitsschicht. Preisermittlung auf Basis der Urkalkulation gemäß "
                    "§ 2 Abs. 6 VOB/B; Beauftragung vorgesehen als Nachtrag VO-101."
                ),
                "day": 33,
                "submitted_day": 35,
                "due_days": 14,
                "decision_day": 47,
                "decision_notes": (
                    "Dem Grunde nach anerkannt; Beauftragung als Nachtrag VO-101 auf Basis des gemeinsamen "
                    "Aufmaßes vom Baufeld West."
                ),
                "classification": "unforeseen",
                "urgency": "high",
                "estimated_cost_impact": 48600,
                "estimated_schedule_days": 6,
                "status": "converted_to_vo",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
            },
            {
                "code": "VR-102",
                "notice": "VN-102",
                "title": "Nachtragsangebot 2 - Umstellung Lüftungsgeräte und Kanalführung",
                "description": (
                    "Angebot zur Anzeige VN-102: geänderte Geräteaufstellung, Kanalumführung Achse C-D und "
                    "angepasste Brandschutzklappen nach Planindex C. Saldierte Mehrkosten gemäß "
                    "§ 2 Abs. 5 VOB/B."
                ),
                "day": -14,
                "from_now": True,
                "submitted_day": -12,
                "due_days": 19,
                "classification": "design_dev",
                "urgency": "med",
                "estimated_cost_impact": 23400,
                "estimated_schedule_days": 0,
                "status": "under_review",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 5 VOB/B",
                "ball_in_court": _DE_PARTY_OWNER,
            },
            {
                "code": "VR-103",
                "notice": None,
                "title": "Nachtragsangebot 3 - Erweiterte Pförtneranlage Eingang Ost",
                "description": (
                    "Auftraggeberwunsch aus der Nutzerabstimmung: Erweiterung der Pförtneranlage am Eingang "
                    "Ost um Vereinzelungsanlage und zweite Sprechstelle. Angebot gemäß § 2 Abs. 6 VOB/B."
                ),
                "day": -5,
                "from_now": True,
                "submitted_day": -4,
                "due_days": 14,
                "classification": "owner_change",
                "urgency": "low",
                "estimated_cost_impact": 12600,
                "estimated_schedule_days": 0,
                "status": "submitted",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "orders": [
            {
                "code": "VO-101",
                "request": "VR-101",
                "title": "Nachtrag 1 - Bodenaustausch Baufeld West",
                "agreed_day": 50,
                "due_days": 7,
                "started_day": 52,
                "completed_day": 66,
                "final_cost_impact": 48600,
                "final_schedule_days": 6,
                "status": "completed",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "use_anchor_co": True,
                "ball_in_court": _DE_PARTY_SITE,
                "cost_impacts": [
                    {
                        "category": "labor",
                        "description": "Handschachtung im Leitungsbereich, Mehrstunden Erdbaukolonne",
                        "quantity": 120,
                        "unit": "h",
                        "unit_rate": 58,
                        "source": "from_estimate",
                    },
                    {
                        "category": "material",
                        "description": "Liefern und lagenweise verdichtet einbauen Austauschmaterial 0/45",
                        "quantity": 620,
                        "unit": "m3",
                        "unit_rate": 39,
                        "source": "from_estimate",
                    },
                    {
                        "category": "equipment",
                        "description": "Vorhaltung Kettenbagger 21 t und Verdichtungstechnik",
                        "quantity": 9,
                        "unit": "d",
                        "unit_rate": 1220,
                        "source": "manual",
                    },
                    {
                        "category": "subcontractor",
                        "description": "Abfuhr und Entsorgung organische Auffüllungen (AVV 17 05 04)",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 6480,
                        "source": "manual",
                    },
                ],
                "schedule_impact": {
                    "affected_activity_ref": "Baugrube / Erdbau",
                    "days_added": 6,
                    "is_critical_path": True,
                    "justification": (
                        "Bodenaustausch verlängert die Erdbauphase; Beginn der Gründungsarbeiten "
                        "verschiebt sich entsprechend."
                    ),
                },
            },
            {
                "code": "VO-102",
                "request": None,
                "title": "Nachtrag 2 - Geänderte Medienführung Achse D",
                "agreed_day": 88,
                "due_days": 7,
                "started_day": 95,
                "final_cost_impact": 19800,
                "final_schedule_days": 0,
                "status": "in_progress",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 5 VOB/B",
                "ball_in_court": _DE_PARTY_SUB,
            },
            {
                "code": "VO-103",
                "request": None,
                "title": "Nachtrag 3 - Zusätzliche Kernbohrungen Bestandsdecke UG",
                "agreed_day": 118,
                "due_days": 7,
                "final_cost_impact": 8400,
                "final_schedule_days": 0,
                "status": "issued",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_SITE,
            },
        ],
        "measurement": {
            "day": 47,
            "location": "Baufeld West, Achsen 1-4",
            "item_description": "Bodenaustausch Mehrtiefe unter Gründungsniveau, gemeinsames Aufmaß",
            "unit": "m3",
            "measured_quantity": 620,
            "owner_signature_ref": "aufmass-2026-101",
            "notes": "Gemeinsames Aufmaß mit der Bauherrenvertretung; Grundlage für Nachtrag VO-101.",
        },
        "dayworks": [
            {
                "sheet_number": "RB-2026-01",
                "day": 53,
                "description": (
                    "Regiearbeiten Bodenaustausch Baufeld West: Handschachtung im Bereich der "
                    "Bestandsleitungen, Laden und Fördern des Aushubs"
                ),
                "status": "billed",
                "markup_percent": 12,
                "lines": [
                    {
                        "line_type": "labor",
                        "description": "Facharbeiter Tiefbau, Handschachtung Leitungsgraben",
                        "quantity": 24,
                        "unit": "h",
                        "unit_rate": 62,
                        "worker_name": "J. Keller",
                    },
                    {
                        "line_type": "equipment",
                        "description": "Minibagger 5 t inkl. Fahrer",
                        "quantity": 8,
                        "unit": "h",
                        "unit_rate": 95,
                        "equipment_code": "BAG-05",
                    },
                    {
                        "line_type": "material",
                        "description": "Austauschmaterial 0/45 für Handbereich",
                        "quantity": 40,
                        "unit": "m3",
                        "unit_rate": 39,
                    },
                ],
            },
            {
                "sheet_number": "RB-2026-02",
                "day": 58,
                "description": (
                    "Regiearbeiten Wasserhaltung: Pumpensumpf umsetzen und Vorhaltung während des Bodenaustauschs"
                ),
                "status": "signed",
                "markup_percent": 12,
                "lines": [
                    {
                        "line_type": "labor",
                        "description": "Baufacharbeiter, Umsetzen Pumpensumpf und Schlauchleitungen",
                        "quantity": 10,
                        "unit": "h",
                        "unit_rate": 58,
                        "worker_name": "P. Vogel",
                    },
                    {
                        "line_type": "equipment",
                        "description": "Schmutzwasserpumpe 4 kW, Vorhaltung",
                        "quantity": 6,
                        "unit": "d",
                        "unit_rate": 48,
                        "equipment_code": "PMP-04",
                    },
                ],
            },
        ],
        "eot": {
            "day": 40,
            "period_start_day": 24,
            "period_end_day": 66,
            "description": (
                "Bauzeitverlängerung infolge Bodenaustausch Baufeld West (Nachtrag VO-101); "
                "Behinderung gemäß § 6 Abs. 1 VOB/B angezeigt."
            ),
            "root_cause_category": "employer_caused",
            "requested_days": 6,
            "granted_days": 6,
            "status": "granted",
            "decision_day": 62,
            "affected_activity_ref": "Baugrube / Erdbau",
            "critical_path_impact": True,
        },
    },
    "retail-market-heidelberg": {
        "anchor_co": None,
        "notices": [
            {
                "code": "VN-101",
                "title": "Mehrkostenanzeige Schadstofffund im Bestandsabbruch",
                "description": (
                    "Beim Rückbau des Bestandsgebäudes wurden asbesthaltige Kleberreste und künstliche "
                    "Mineralfasern angetroffen, die im Rückbaukonzept nicht ausgewiesen sind. Mehrkosten "
                    "werden gemäß § 2 Abs. 6 VOB/B angezeigt; Sanierungskonzept und Nachtragsangebot "
                    "VR-101 folgen."
                ),
                "day": 18,
                "due_days": 14,
                "ack_day": 20,
                "response_day": 27,
                "response_summary": (
                    "Prüfung bestätigt; Freigabe der Schadstoffsanierung dem Grunde nach, Angebot angefordert."
                ),
                "status": "responded",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
            },
            {
                "code": "VN-102",
                "title": "Anzeige Auflage Fettabscheider-Anbindung Anlieferung",
                "description": (
                    "Auflage des Entwässerungsbetriebs aus der Genehmigung: separater Fettabscheider-"
                    "Anschluss für die Backvorbereitung. Mehrkosten werden gemäß § 2 Abs. 6 VOB/B "
                    "angezeigt; Abstimmung mit dem Netzbetreiber läuft."
                ),
                "day": -8,
                "from_now": True,
                "due_days": 14,
                "status": "issued",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "requests": [
            {
                "code": "VR-101",
                "notice": "VN-101",
                "title": "Nachtragsangebot 1 - Schadstoffsanierung vor Abbruch",
                "description": (
                    "Angebot auf Grundlage der Anzeige VN-101: Einhausung Schwarzbereich, Ausbau und "
                    "Entsorgung asbesthaltiger Kleberreste und KMF nach TRGS 519/521, Freimessung. "
                    "Beauftragung vorgesehen als Nachtrag VO-101, § 2 Abs. 6 VOB/B."
                ),
                "day": 27,
                "submitted_day": 29,
                "due_days": 14,
                "decision_day": 38,
                "decision_notes": "Anerkannt; Beauftragung als Nachtrag VO-101 vor Fortführung des Rückbaus.",
                "classification": "unforeseen",
                "urgency": "high",
                "estimated_cost_impact": 36400,
                "estimated_schedule_days": 8,
                "status": "converted_to_vo",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
            },
            {
                "code": "VR-102",
                "notice": "VN-102",
                "title": "Nachtragsangebot 2 - Anpassung Entwässerung Anlieferung",
                "description": (
                    "Angebot zur Anzeige VN-102: Fettabscheider NS 4 mit Probenahmeschacht, "
                    "Leitungsanpassung der Grundleitung Anlieferung. § 2 Abs. 6 VOB/B."
                ),
                "day": -6,
                "from_now": True,
                "submitted_day": -5,
                "due_days": 14,
                "classification": "regulatory",
                "urgency": "med",
                "estimated_cost_impact": 14800,
                "estimated_schedule_days": 0,
                "status": "under_review",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "orders": [
            {
                "code": "VO-101",
                "request": "VR-101",
                "title": "Nachtrag 1 - Schadstoffsanierung Bestand",
                "agreed_day": 40,
                "due_days": 7,
                "started_day": 42,
                "completed_day": 54,
                "final_cost_impact": 36400,
                "final_schedule_days": 8,
                "status": "completed",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_SITE,
                "cost_impacts": [
                    {
                        "category": "subcontractor",
                        "description": "Fachbetrieb Schadstoffsanierung nach TRGS 519, Schwarzbereich",
                        "quantity": 720,
                        "unit": "m2",
                        "unit_rate": 41,
                        "source": "from_estimate",
                    },
                    {
                        "category": "overhead",
                        "description": "Bauleitung und Koordination Freimessung, verlängerte Vorhaltung",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 6880,
                        "source": "manual",
                    },
                ],
                "schedule_impact": {
                    "affected_activity_ref": "Rückbau Bestand",
                    "days_added": 8,
                    "is_critical_path": True,
                    "justification": "Sanierung vor Abbruch verschiebt Erdbau und Gründung um acht Arbeitstage.",
                },
            },
            {
                "code": "VO-102",
                "request": None,
                "title": "Nachtrag 2 - Zusätzliche Bodeneinläufe Backvorbereitung",
                "agreed_day": 96,
                "due_days": 7,
                "started_day": 104,
                "final_cost_impact": 9600,
                "final_schedule_days": 0,
                "status": "in_progress",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 5 VOB/B",
                "ball_in_court": _DE_PARTY_SUB,
            },
        ],
        "measurement": {
            "day": 37,
            "location": "Bestandsgebäude, Verkaufsfläche Alt",
            "item_description": "Belagsflächen mit asbesthaltigen Kleberresten, gemeinsames Aufmaß",
            "unit": "m2",
            "measured_quantity": 720,
            "owner_signature_ref": "aufmass-2026-101",
            "notes": "Gemeinsames Aufmaß vor Einrichtung des Schwarzbereichs; Grundlage für Nachtrag VO-101.",
        },
        "dayworks": [
            {
                "sheet_number": "RB-2026-01",
                "day": 44,
                "description": "Regiearbeiten Einhausung Schwarzbereich und Schleusenbetrieb Schadstoffsanierung",
                "status": "billed",
                "markup_percent": 10,
                "lines": [
                    {
                        "line_type": "labor",
                        "description": "Fachpersonal Sanierung, Auf- und Umbau Einhausung",
                        "quantity": 18,
                        "unit": "h",
                        "unit_rate": 64,
                        "worker_name": "S. Dubois",
                    },
                    {
                        "line_type": "material",
                        "description": "Folien, Klebebänder und Filtermaterial Schleuse",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 740,
                    },
                ],
            },
        ],
        "eot": None,
    },
    "retail-market-karlsruhe": {
        "anchor_co": None,
        "notices": [
            {
                "code": "VN-101",
                "title": "Mehrkostenanzeige Umlegung Fernwärmetrasse Zufahrt",
                "description": (
                    "Bei den Erdarbeiten in der Zufahrt wurde eine nicht kartierte Fernwärmeleitung "
                    "angetroffen. Der Netzbetreiber verlangt eine Umlegung außerhalb der Fahrgasse. "
                    "Mehrkosten und Verzug werden gemäß § 2 Abs. 6 und § 6 Abs. 1 VOB/B angezeigt; "
                    "Angebot VR-101 folgt."
                ),
                "day": 22,
                "due_days": 14,
                "ack_day": 24,
                "response_day": 31,
                "response_summary": (
                    "Umlegung dem Grunde nach freigegeben; Trassenführung mit dem Netzbetreiber "
                    "abgestimmt, Angebot angefordert."
                ),
                "status": "responded",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
            },
            {
                "code": "VN-102",
                "title": "Anzeige drohende Behinderung - Lieferverzug Kühlmöbel",
                "description": (
                    "Der Hersteller der Kühlmöbel meldet drei Wochen Lieferverzug. Eine Behinderung der "
                    "Ausbaufolge wird gemäß § 6 Abs. 1 VOB/B angezeigt; Taktplan wird angepasst, "
                    "Mehrkosten bleiben vorbehalten."
                ),
                "day": -9,
                "from_now": True,
                "due_days": 10,
                "status": "issued",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "requests": [
            {
                "code": "VR-101",
                "notice": "VN-101",
                "title": "Nachtragsangebot 1 - Umlegung Fernwärmetrasse",
                "description": (
                    "Angebot auf Grundlage der Anzeige VN-101: Tiefbau für 46 m neue Trasse, "
                    "Netzbetreiberleistungen als durchlaufender Posten, Wiederherstellung der Zufahrt. "
                    "Beauftragung vorgesehen als Nachtrag VO-101, § 2 Abs. 6 VOB/B."
                ),
                "day": 31,
                "submitted_day": 33,
                "due_days": 14,
                "decision_day": 44,
                "decision_notes": "Anerkannt; Beauftragung als Nachtrag VO-101, Ausführung vor Deckenschluss Zufahrt.",
                "classification": "unforeseen",
                "urgency": "high",
                "estimated_cost_impact": 28900,
                "estimated_schedule_days": 4,
                "status": "converted_to_vo",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
            },
            {
                "code": "VR-102",
                "notice": None,
                "title": "Nachtragsangebot 2 - Überdachung Einkaufswagenbox",
                "description": (
                    "Auftraggeberwunsch aus dem Betreiberstandard: Überdachung der Einkaufswagenbox "
                    "mit Seitenwindschutz. Angebot gemäß § 2 Abs. 6 VOB/B."
                ),
                "day": -7,
                "from_now": True,
                "submitted_day": -6,
                "due_days": 14,
                "classification": "owner_change",
                "urgency": "low",
                "estimated_cost_impact": 11200,
                "estimated_schedule_days": 0,
                "status": "submitted",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "orders": [
            {
                "code": "VO-101",
                "request": "VR-101",
                "title": "Nachtrag 1 - Umlegung Fernwärmetrasse Zufahrt",
                "agreed_day": 46,
                "due_days": 7,
                "started_day": 50,
                "completed_day": 61,
                "final_cost_impact": 28900,
                "final_schedule_days": 4,
                "status": "completed",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_SITE,
                "cost_impacts": [
                    {
                        "category": "labor",
                        "description": "Tiefbau Trassengraben 46 m inkl. Verbau und Wiederverfüllung",
                        "quantity": 46,
                        "unit": "m",
                        "unit_rate": 315,
                        "source": "from_estimate",
                    },
                    {
                        "category": "subcontractor",
                        "description": "Netzbetreiber: Rohrverlegung und Einbindung (durchlaufender Posten)",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 14410,
                        "source": "manual",
                    },
                ],
                "schedule_impact": {
                    "affected_activity_ref": "Außenanlagen / Zufahrt",
                    "days_added": 4,
                    "is_critical_path": False,
                    "justification": "Umlegung vor Deckenschluss der Zufahrt; Restarbeiten außerhalb des kritischen Wegs.",
                },
            },
            {
                "code": "VO-102",
                "request": None,
                "title": "Nachtrag 2 - Verstärkte Rampenplatte Anlieferung",
                "agreed_day": 92,
                "due_days": 7,
                "started_day": 99,
                "final_cost_impact": 13900,
                "final_schedule_days": 0,
                "status": "in_progress",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 5 VOB/B",
                "ball_in_court": _DE_PARTY_SUB,
            },
        ],
        "measurement": {
            "day": 43,
            "location": "Zufahrt Nord, Station 0+00 bis 0+46",
            "item_description": "Trassenlänge Umlegung Fernwärme, gemeinsames Aufmaß mit Netzbetreiber",
            "unit": "m",
            "measured_quantity": 46,
            "owner_signature_ref": "aufmass-2026-101",
            "notes": "Gemeinsames Aufmaß mit Bauherrenvertretung und Netzbetreiber; Grundlage für Nachtrag VO-101.",
        },
        "dayworks": [
            {
                "sheet_number": "RB-2026-01",
                "day": 52,
                "description": "Regiearbeiten Suchschachtung und Sicherung der Fernwärmeleitung in der Zufahrt",
                "status": "signed",
                "markup_percent": 12,
                "lines": [
                    {
                        "line_type": "labor",
                        "description": "Facharbeiter Tiefbau, Suchschachtung von Hand",
                        "quantity": 14,
                        "unit": "h",
                        "unit_rate": 60,
                        "worker_name": "T. Farkas",
                    },
                    {
                        "line_type": "equipment",
                        "description": "Saugbagger-Einsatz zur Freilegung",
                        "quantity": 4,
                        "unit": "h",
                        "unit_rate": 260,
                        "equipment_code": "SBG-01",
                    },
                ],
            },
        ],
        "eot": None,
    },
    "retail-market-heilbronn": {
        "anchor_co": None,
        "notices": [
            {
                "code": "VN-101",
                "title": "Mehrkostenanzeige Leerrohrtrasse Werbepylon",
                "description": (
                    "Für den Werbepylon an der Zufahrt fehlt die Leerrohrtrasse in der beauftragten "
                    "Außenanlagenplanung. Mehrkosten werden gemäß § 2 Abs. 6 VOB/B angezeigt; Angebot "
                    "VR-101 mit Trassenführung entlang der Stellplatzreihe folgt."
                ),
                "day": 26,
                "due_days": 14,
                "ack_day": 28,
                "response_day": 34,
                "response_summary": "Trassenführung freigegeben; Angebot zur Beauftragung angefordert.",
                "status": "responded",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
            },
            {
                "code": "VN-102",
                "title": "Anzeige geänderte Anlieferzeiten Innenstadtlage",
                "description": (
                    "Die Stadt begrenzt Anlieferungen während der Rohbauphase auf 07-19 Uhr. Auswirkungen "
                    "auf Betonagen und Fertigteilmontage werden gemäß § 6 Abs. 1 VOB/B angezeigt; "
                    "Taktplan in Abstimmung."
                ),
                "day": 58,
                "due_days": 10,
                "ack_day": 61,
                "status": "acknowledged",
                "recipient_type": "owner",
                "recipient_name": "Bauherrenvertretung",
            },
        ],
        "requests": [
            {
                "code": "VR-101",
                "notice": "VN-101",
                "title": "Nachtragsangebot 1 - Leerrohrtrasse und Fundament Werbepylon",
                "description": (
                    "Angebot auf Grundlage der Anzeige VN-101: 85 m Leerrohrtrasse DN 110 entlang der "
                    "Stellplatzreihe, Köcherfundament für den Werbepylon. Beauftragung vorgesehen als "
                    "Nachtrag VO-101, § 2 Abs. 6 VOB/B."
                ),
                "day": 34,
                "submitted_day": 36,
                "due_days": 14,
                "decision_day": 45,
                "decision_notes": "Anerkannt; Beauftragung als Nachtrag VO-101 zur Ausführung mit den Außenanlagen.",
                "classification": "owner_change",
                "urgency": "med",
                "estimated_cost_impact": 7800,
                "estimated_schedule_days": 0,
                "status": "converted_to_vo",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
            },
            {
                "code": "VR-102",
                "notice": None,
                "title": "Nachtragsangebot 2 - Zusätzliche Rammschutzbügel Backstation",
                "description": (
                    "Betreiberstandard: zusätzliche Rammschutzbügel an Backstation und Pfandraumzufahrt. "
                    "Angebot gemäß § 2 Abs. 6 VOB/B."
                ),
                "day": -6,
                "from_now": True,
                "submitted_day": -5,
                "due_days": 14,
                "classification": "owner_change",
                "urgency": "low",
                "estimated_cost_impact": 4600,
                "estimated_schedule_days": 0,
                "status": "submitted",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_OWNER,
            },
        ],
        "orders": [
            {
                "code": "VO-101",
                "request": "VR-101",
                "title": "Nachtrag 1 - Leerrohrtrasse und Fundament Werbepylon",
                "agreed_day": 47,
                "due_days": 7,
                "started_day": 74,
                "completed_day": 80,
                "final_cost_impact": 7800,
                "final_schedule_days": 0,
                "status": "completed",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 6 VOB/B",
                "ball_in_court": _DE_PARTY_SITE,
                "cost_impacts": [
                    {
                        "category": "material",
                        "description": "Leerrohr DN 110 mit Zugdraht, Sandbett und Warnband",
                        "quantity": 85,
                        "unit": "m",
                        "unit_rate": 36,
                        "source": "from_estimate",
                    },
                    {
                        "category": "labor",
                        "description": "Köcherfundament Werbepylon inkl. Schalung und Bewehrung",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 4740,
                        "source": "from_estimate",
                    },
                ],
                "schedule_impact": {
                    "affected_activity_ref": "Außenanlagen",
                    "days_added": 0,
                    "is_critical_path": False,
                    "justification": "Ausführung im Zuge der Außenanlagen ohne Auswirkung auf den kritischen Weg.",
                },
            },
            {
                "code": "VO-102",
                "request": None,
                "title": "Nachtrag 2 - Erweiterte Sockelschienen Kühlregalzeile",
                "agreed_day": 112,
                "due_days": 7,
                "final_cost_impact": 5200,
                "final_schedule_days": 0,
                "status": "issued",
                "contract_standard": "VOB_B",
                "contract_clause_ref": "§ 2 Abs. 5 VOB/B",
                "ball_in_court": _DE_PARTY_SITE,
            },
        ],
        "measurement": {
            "day": 44,
            "location": "Außenanlagen, Stellplatzreihe Ost",
            "item_description": "Leerrohrtrasse Werbepylon, Länge gemeinsam aufgemessen",
            "unit": "m",
            "measured_quantity": 85,
            "owner_signature_ref": "aufmass-2026-101",
            "notes": "Gemeinsames Aufmaß mit der Bauherrenvertretung; Grundlage für Nachtrag VO-101.",
        },
        "dayworks": [
            {
                "sheet_number": "RB-2026-01",
                "day": 76,
                "description": "Regiearbeiten Anpassung Bordanlage und Wiederherstellung Pflaster an der Pylontrasse",
                "status": "billed",
                "markup_percent": 10,
                "lines": [
                    {
                        "line_type": "labor",
                        "description": "Pflasterer, Rückbau und Wiederherstellung Stellplatzreihe",
                        "quantity": 12,
                        "unit": "h",
                        "unit_rate": 56,
                        "worker_name": "A. Serrano",
                    },
                    {
                        "line_type": "material",
                        "description": "Bettungsmaterial und Fugensand",
                        "quantity": 1,
                        "unit": "lsum",
                        "unit_rate": 180,
                    },
                ],
            },
        ],
        "eot": None,
    },
}


def _de_at(day: date, hour: int, minute: int = 0) -> datetime:
    """An aware business-hours timestamp on ``day`` (stored as UTC)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def _de_day(anchor: date, today: date, entry: dict[str, Any], key: str = "day") -> date | None:
    """Resolve a spec day offset to a date (anchor- or today-relative)."""
    value = entry.get(key)
    if value is None:
        return None
    base = today if entry.get("from_now") else anchor
    return base + timedelta(days=int(value))


#: One step of a lead chain's recorded history:
#: (when, action, entity_type, entity_id, code, from_status, to_status, reason).
_TrailStep = tuple[datetime, str, str, uuid.UUID, str, str | None, str | None, str | None]


def _trail_step(
    trail: list[_TrailStep],
    when: datetime,
    entity_type: str,
    entity_id: uuid.UUID,
    code: str,
    action: str,
    from_status: str | None,
    to_status: str | None,
    reason: str | None,
) -> None:
    """Append one activity-trail step for the lead chain.

    Every ``status_changed`` step must share its timestamp with an
    ``ownership_handoff`` step: the ownership-chain engine reads a transition
    strictly inside a custody segment as "the change advanced but nobody
    picked it up" and downgrades the chain to ambiguous.
    """
    trail.append((when, action, entity_type, entity_id, code, from_status, to_status, reason))


async def seed_variations_showcase_de(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Hand-authored German Nachtrag estates for the German showcase projects.

    For every demo project whose ``demo_id`` is in :data:`_DE_SHOWCASE`, writes
    the German variations register described there: Mehrkostenanzeigen with
    contractual response deadlines and recorded answers, Nachtragsangebote
    citing their notice and VOB/B clause, beauftragte Nachträge with cost
    build-up, a joint site measurement, Regieberichte supplied through the
    head contract, and - for the lead chain - the ``ownership_handoff`` /
    ``status_changed`` activity trail the claims-evidence provability engine
    grades. Every date is derived from the project's own head-contract start
    (open items from today), and record ``created_at`` values are backdated to
    the business dates so evidence packs show the site's chronology rather
    than the seeding minute.

    Chronology is coherent by construction: a request never predates its
    notice, an order never predates its request's decision, and no order hangs
    off a rejected request.

    Self-guards per project on its own lead notice code, so a re-run (boot,
    pack apply, force reinstall backfill) never duplicates. Callers pass demo
    projects only.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: Candidate projects; non-German or non-demo ids are
            ignored.

    Returns:
        Counts dict (projects, notices, requests, orders, dayworks, ...).
    """
    candidates = list(project_ids)
    if not candidates:
        return {"projects": 0}

    rows = await session.execute(
        select(Project.id, Project.metadata_, Project.currency, Project.owner_id).where(Project.id.in_(candidates))
    )
    targets: list[tuple[uuid.UUID, str, str, uuid.UUID | None]] = []
    for pid, meta, currency, owner_id in rows.all():
        demo_id = str(meta.get("demo_id") or "").strip() if isinstance(meta, dict) else ""
        if demo_id in _DE_SHOWCASE:
            targets.append((pid, demo_id, currency or "EUR", owner_id))
    if not targets:
        return {"projects": 0}

    # Per-project self-guard: the lead notice code is written first and only
    # here, so its presence marks the whole estate as seeded.
    seeded_rows = await session.execute(
        select(Notice.project_id).where(Notice.project_id.in_([t[0] for t in targets])).where(Notice.code == "VN-101")
    )
    already = set(seeded_rows.scalars().all())

    today = datetime.now(UTC).date()
    counts = {
        "projects": 0,
        "notices": 0,
        "requests": 0,
        "orders": 0,
        "cost_impact_lines": 0,
        "schedule_impact_lines": 0,
        "site_measurements": 0,
        "daywork_sheets": 0,
        "daywork_lines": 0,
        "eot_claims": 0,
        "activity_rows": 0,
    }

    for pid, demo_id, currency, owner_id in targets:
        if pid in already:
            continue
        spec = _DE_SHOWCASE[demo_id]
        actor = owner_id

        # The head contract anchors the calendar and receives the Nachtrag
        # and Regiebericht links. Its absence degrades to today-based dates
        # and unlinked rows rather than skipping the project.
        main_contract_id: uuid.UUID | None = None
        anchor = today - timedelta(days=120)
        try:
            from app.modules.contracts.models import Contract

            contract_row = (
                await session.execute(
                    select(Contract.id, Contract.start_date)
                    .where(Contract.project_id == pid)
                    .where(Contract.code == f"{demo_id}-MAIN")
                )
            ).first()
            if contract_row is not None:
                main_contract_id = contract_row[0]
                parsed = None
                if contract_row[1]:
                    try:
                        parsed = datetime.fromisoformat(str(contract_row[1])).date()
                    except ValueError:
                        parsed = None
                if parsed is not None and parsed < today:
                    anchor = parsed
        except Exception:  # contracts module optional in stripped installs
            logger.debug("Head contract lookup failed for %s", demo_id, exc_info=True)

        anchor_co_id: uuid.UUID | None = None
        if spec.get("anchor_co"):
            try:
                from app.modules.changeorders.models import ChangeOrder

                anchor_co_id = (
                    await session.execute(
                        select(ChangeOrder.id)
                        .where(ChangeOrder.project_id == pid)
                        .where(ChangeOrder.code == spec["anchor_co"])
                    )
                ).scalar_one_or_none()
            except Exception:  # changeorders module optional in stripped installs
                anchor_co_id = None

        trail: list[_TrailStep] = []
        # Bound eagerly so no closure over loop state survives the iteration.
        _record_trail = functools.partial(_trail_step, trail)

        # ── Notices (Anzeigen) ────────────────────────────────────────────
        notices_by_code: dict[str, Notice] = {}
        for n_idx, n_spec in enumerate(spec["notices"]):
            raised_day = _de_day(anchor, today, n_spec)
            assert raised_day is not None
            raised_ts = _de_at(raised_day, 9, 15)
            due_day = raised_day + timedelta(days=int(n_spec.get("due_days", 14)))
            ack_day = _de_day(anchor, today, n_spec, "ack_day")
            response_day = _de_day(anchor, today, n_spec, "response_day")
            notice = Notice(
                # Assigned up front: the trail below records the id before the
                # flush that would otherwise mint it.
                id=uuid.uuid4(),
                project_id=pid,
                code=n_spec["code"],
                title=n_spec["title"],
                description=n_spec["description"],
                raised_at=raised_ts.isoformat(),
                raised_by=str(actor) if actor else None,
                recipient_type=n_spec["recipient_type"],
                recipient_name=n_spec["recipient_name"],
                target_response_date=due_day.isoformat(),
                response_due_date=due_day.isoformat(),
                response_received_at=(_de_at(response_day, 14).isoformat() if response_day else None),
                response_summary=n_spec.get("response_summary", ""),
                status=n_spec["status"],
                reference_change_order_id=(anchor_co_id if n_idx == 0 else None),
                ball_in_court=n_spec.get("ball_in_court"),
                metadata_={"demo_id": demo_id},
                created_at=raised_ts,
                updated_at=_de_at(response_day or ack_day or raised_day, 16),
            )
            session.add(notice)
            notices_by_code[n_spec["code"]] = notice
            counts["notices"] += 1

            if n_idx == 0:
                _record_trail(
                    raised_ts,
                    "variation_notice",
                    notice.id,
                    notice.code,
                    "created",
                    None,
                    "issued",
                    "Anzeige zugestellt, Frist gemäß Vertrag vermerkt.",
                )
                _record_trail(
                    raised_ts,
                    "variation_notice",
                    notice.id,
                    notice.code,
                    "ownership_handoff",
                    None,
                    _DE_PARTY_SITE,
                    "Anzeige erstellt; Nachverfolgung bei der Bauleitung.",
                )
                if ack_day:
                    ack_ts = _de_at(ack_day, 11)
                    _record_trail(
                        ack_ts,
                        "variation_notice",
                        notice.id,
                        notice.code,
                        "status_changed",
                        "issued",
                        "acknowledged",
                        "Zugang durch die Bauherrenvertretung bestätigt.",
                    )
                    _record_trail(
                        ack_ts,
                        "variation_notice",
                        notice.id,
                        notice.code,
                        "ownership_handoff",
                        _DE_PARTY_SITE,
                        _DE_PARTY_OWNER,
                        "Prüfung liegt beim Auftraggeber.",
                    )
                if response_day:
                    resp_ts = _de_at(response_day, 14)
                    _record_trail(
                        resp_ts,
                        "variation_notice",
                        notice.id,
                        notice.code,
                        "status_changed",
                        "acknowledged",
                        "responded",
                        "Antwort des Auftraggebers im Register vermerkt.",
                    )
                    _record_trail(
                        resp_ts,
                        "variation_notice",
                        notice.id,
                        notice.code,
                        "ownership_handoff",
                        _DE_PARTY_OWNER,
                        _DE_PARTY_SITE,
                        "Weiterführung nach Antwort wieder bei der Bauleitung.",
                    )

        await session.flush()

        # ── Requests (Nachtragsangebote) ──────────────────────────────────
        requests_by_code: dict[str, VariationRequest] = {}
        for r_idx, r_spec in enumerate(spec["requests"]):
            request_day = _de_day(anchor, today, r_spec)
            assert request_day is not None
            submitted_day = _de_day(anchor, today, r_spec, "submitted_day")
            decision_day = _de_day(anchor, today, r_spec, "decision_day")
            due_day = (submitted_day or request_day) + timedelta(days=int(r_spec.get("due_days", 14)))
            source_notice = notices_by_code.get(r_spec.get("notice") or "")
            request_ts = _de_at(request_day, 10)
            vr = VariationRequest(
                id=uuid.uuid4(),
                project_id=pid,
                notice_id=source_notice.id if source_notice else None,
                code=r_spec["code"],
                title=r_spec["title"],
                description=r_spec["description"],
                requested_by=str(actor) if actor else None,
                requested_at=request_ts.isoformat(),
                classification=r_spec["classification"],
                urgency=r_spec["urgency"],
                estimated_cost_impact=Decimal(str(r_spec["estimated_cost_impact"])),
                estimated_schedule_days=int(r_spec["estimated_schedule_days"]),
                currency=currency,
                status=r_spec["status"],
                submitted_at=(_de_at(submitted_day, 11).isoformat() if submitted_day else None),
                decision_at=(_de_at(decision_day, 15).isoformat() if decision_day else None),
                decision_notes=r_spec.get("decision_notes", ""),
                decided_by=(str(actor) if actor and decision_day else None),
                contract_standard=r_spec.get("contract_standard", ""),
                contract_clause_ref=r_spec.get("contract_clause_ref", ""),
                ball_in_court=r_spec.get("ball_in_court"),
                response_due_date=due_day.isoformat(),
                metadata_={"demo_id": demo_id},
                created_at=request_ts,
                updated_at=_de_at(decision_day or submitted_day or request_day, 16),
            )
            session.add(vr)
            requests_by_code[r_spec["code"]] = vr
            counts["requests"] += 1

            if r_idx == 0:
                _record_trail(
                    request_ts,
                    "variation_request",
                    vr.id,
                    vr.code,
                    "created",
                    None,
                    "draft",
                    "Nachtragsangebot auf Basis der Urkalkulation aufgestellt.",
                )
                _record_trail(
                    request_ts,
                    "variation_request",
                    vr.id,
                    vr.code,
                    "ownership_handoff",
                    None,
                    _DE_PARTY_SITE,
                    "Angebotsaufstellung bei der Bauleitung.",
                )
                if submitted_day:
                    sub_ts = _de_at(submitted_day, 11)
                    _record_trail(
                        sub_ts,
                        "variation_request",
                        vr.id,
                        vr.code,
                        "status_changed",
                        "draft",
                        "submitted",
                        "Angebot eingereicht, Prüffrist läuft.",
                    )
                    _record_trail(
                        sub_ts,
                        "variation_request",
                        vr.id,
                        vr.code,
                        "ownership_handoff",
                        _DE_PARTY_SITE,
                        _DE_PARTY_OWNER,
                        "Prüfung des Angebots beim Auftraggeber.",
                    )
                if decision_day:
                    dec_ts = _de_at(decision_day, 15)
                    _record_trail(
                        dec_ts,
                        "variation_request",
                        vr.id,
                        vr.code,
                        "status_changed",
                        "submitted",
                        "approved",
                        "Angebot dem Grunde nach anerkannt.",
                    )
                    _record_trail(
                        dec_ts,
                        "variation_request",
                        vr.id,
                        vr.code,
                        "ownership_handoff",
                        _DE_PARTY_OWNER,
                        _DE_PARTY_SITE,
                        "Beauftragung und Umsetzung wieder bei der Bauleitung.",
                    )

        await session.flush()

        # ── Orders (Nachträge) ────────────────────────────────────────────
        for o_idx, o_spec in enumerate(spec["orders"]):
            agreed_day = _de_day(anchor, today, o_spec, "agreed_day")
            assert agreed_day is not None
            started_day = _de_day(anchor, today, o_spec, "started_day")
            completed_day = _de_day(anchor, today, o_spec, "completed_day")
            due_day = agreed_day + timedelta(days=int(o_spec.get("due_days", 7)))
            source_vr = requests_by_code.get(o_spec.get("request") or "")
            agreed_ts = _de_at(agreed_day, 10, 30)
            vo = VariationOrder(
                id=uuid.uuid4(),
                project_id=pid,
                variation_request_id=source_vr.id if source_vr else None,
                code=o_spec["code"],
                title=o_spec["title"],
                final_cost_impact=Decimal(str(o_spec["final_cost_impact"])),
                final_schedule_days=int(o_spec["final_schedule_days"]),
                currency=currency,
                agreed_at=agreed_ts.isoformat(),
                signed_by=str(actor) if actor else None,
                status=o_spec["status"],
                reference_change_order_id=(anchor_co_id if o_spec.get("use_anchor_co") else None),
                affected_contract_id=main_contract_id,
                contract_standard=o_spec.get("contract_standard", ""),
                contract_clause_ref=o_spec.get("contract_clause_ref", ""),
                implementation_started_at=(_de_at(started_day, 7).isoformat() if started_day else None),
                implementation_completed_at=(_de_at(completed_day, 16).isoformat() if completed_day else None),
                ball_in_court=o_spec.get("ball_in_court"),
                response_due_date=due_day.isoformat(),
                metadata_={"demo_id": demo_id},
                created_at=agreed_ts,
                updated_at=_de_at(completed_day or started_day or agreed_day, 17),
            )
            session.add(vo)
            counts["orders"] += 1
            await session.flush()

            for ci_spec in o_spec.get("cost_impacts", ()):
                qty = Decimal(str(ci_spec["quantity"]))
                rate = Decimal(str(ci_spec["unit_rate"]))
                session.add(
                    VariationCostImpact(
                        variation_order_id=vo.id,
                        category=ci_spec["category"],
                        description=ci_spec["description"],
                        quantity=qty,
                        unit=ci_spec["unit"],
                        unit_rate=rate,
                        total=qty * rate,
                        currency=currency,
                        source=ci_spec.get("source", "manual"),
                        created_at=agreed_ts,
                        updated_at=agreed_ts,
                    )
                )
                counts["cost_impact_lines"] += 1

            si_spec = o_spec.get("schedule_impact")
            if si_spec:
                original_finish = (completed_day or agreed_day) - timedelta(days=int(si_spec["days_added"]))
                session.add(
                    VariationScheduleImpact(
                        variation_order_id=vo.id,
                        affected_activity_ref=si_spec["affected_activity_ref"],
                        original_finish_date=original_finish.isoformat(),
                        revised_finish_date=(completed_day or agreed_day).isoformat(),
                        days_added=int(si_spec["days_added"]),
                        is_critical_path=bool(si_spec["is_critical_path"]),
                        justification=si_spec["justification"],
                        created_at=agreed_ts,
                        updated_at=agreed_ts,
                    )
                )
                counts["schedule_impact_lines"] += 1

            if o_idx == 0:
                _record_trail(
                    agreed_ts,
                    "variation_order",
                    vo.id,
                    vo.code,
                    "created",
                    None,
                    "issued",
                    "Nachtrag beauftragt; Gegenzeichnung vermerkt.",
                )
                _record_trail(
                    agreed_ts,
                    "variation_order",
                    vo.id,
                    vo.code,
                    "ownership_handoff",
                    None,
                    _DE_PARTY_SITE,
                    "Beauftragter Nachtrag zur Umsetzung bei der Bauleitung.",
                )
                if started_day:
                    start_ts = _de_at(started_day, 7)
                    _record_trail(
                        start_ts,
                        "variation_order",
                        vo.id,
                        vo.code,
                        "status_changed",
                        "issued",
                        "in_progress",
                        "Ausführung der Nachtragsleistung begonnen.",
                    )
                    _record_trail(
                        start_ts,
                        "variation_order",
                        vo.id,
                        vo.code,
                        "ownership_handoff",
                        _DE_PARTY_SITE,
                        _DE_PARTY_SUB,
                        "Ausführung beim Nachunternehmer.",
                    )
                if completed_day:
                    done_ts = _de_at(completed_day, 16)
                    _record_trail(
                        done_ts,
                        "variation_order",
                        vo.id,
                        vo.code,
                        "status_changed",
                        "in_progress",
                        "completed",
                        "Leistung fertiggestellt; Aufmaß und Abrechnung folgen.",
                    )
                    _record_trail(
                        done_ts,
                        "variation_order",
                        vo.id,
                        vo.code,
                        "ownership_handoff",
                        _DE_PARTY_SUB,
                        _DE_PARTY_SITE,
                        "Fertigstellung gemeldet; Abrechnung bei der Bauleitung.",
                    )

                m_spec = spec.get("measurement")
                if m_spec:
                    m_day = _de_day(anchor, today, m_spec)
                    assert m_day is not None
                    m_ts = _de_at(m_day, 13)
                    session.add(
                        SiteMeasurement(
                            project_id=pid,
                            recorded_at=m_ts.isoformat(),
                            recorded_by=str(actor) if actor else None,
                            location=m_spec["location"],
                            item_description=m_spec["item_description"],
                            unit=m_spec["unit"],
                            measured_quantity=Decimal(str(m_spec["measured_quantity"])),
                            agreed_with_owner_at=m_ts.isoformat(),
                            owner_signature_ref=m_spec["owner_signature_ref"],
                            notes=m_spec["notes"],
                            variation_order_id=vo.id,
                            created_at=m_ts,
                            updated_at=m_ts,
                        )
                    )
                    counts["site_measurements"] += 1

        # ── Regieberichte (daywork sheets) ────────────────────────────────
        for dw_spec in spec.get("dayworks", ()):
            work_day = _de_day(anchor, today, dw_spec)
            assert work_day is not None
            work_ts = _de_at(work_day, 16, 30)
            markup = Decimal(str(dw_spec.get("markup_percent", 0)))
            subtotal = Decimal("0")
            sheet = DayworkSheet(
                project_id=pid,
                sheet_number=dw_spec["sheet_number"],
                work_date=work_day.isoformat(),
                description=dw_spec["description"],
                subtotal_amount=Decimal("0"),
                markup_percent=markup,
                total_amount=Decimal("0"),
                currency=currency,
                status=dw_spec["status"],
                signed_by=str(actor) if actor else None,
                signed_at=(
                    _de_at(work_day + timedelta(days=1), 9).isoformat() if dw_spec["status"] != "draft" else None
                ),
                owner_signature_ref=f"rb-sig-{dw_spec['sheet_number'].lower()}",
                supplied_via_contract_id=main_contract_id,
                created_at=work_ts,
                updated_at=work_ts,
            )
            session.add(sheet)
            await session.flush()
            for line_spec in dw_spec.get("lines", ()):
                qty = Decimal(str(line_spec["quantity"]))
                rate = Decimal(str(line_spec["unit_rate"]))
                total = qty * rate
                subtotal += total
                session.add(
                    DayworkSheetLine(
                        sheet_id=sheet.id,
                        line_type=line_spec["line_type"],
                        description=line_spec["description"],
                        quantity=qty,
                        unit=line_spec["unit"],
                        unit_rate=rate,
                        total=total,
                        worker_name=line_spec.get("worker_name"),
                        equipment_code=line_spec.get("equipment_code"),
                        created_at=work_ts,
                        updated_at=work_ts,
                    )
                )
                counts["daywork_lines"] += 1
            sheet.subtotal_amount = subtotal
            sheet.total_amount = (subtotal * (Decimal("100") + markup) / Decimal("100")).quantize(Decimal("0.01"))
            counts["daywork_sheets"] += 1

        # ── Bauzeitverlängerung (EOT) ─────────────────────────────────────
        eot_spec = spec.get("eot")
        if eot_spec:
            raised_day = _de_day(anchor, today, eot_spec)
            decision_day = _de_day(anchor, today, eot_spec, "decision_day")
            assert raised_day is not None
            raised_ts = _de_at(raised_day, 10)
            session.add(
                ExtensionOfTimeClaim(
                    project_id=pid,
                    raised_at=raised_ts.isoformat(),
                    raised_by=str(actor) if actor else None,
                    claim_period_start=(anchor + timedelta(days=int(eot_spec["period_start_day"]))).isoformat(),
                    claim_period_end=(anchor + timedelta(days=int(eot_spec["period_end_day"]))).isoformat(),
                    description=eot_spec["description"],
                    root_cause_category=eot_spec["root_cause_category"],
                    requested_days=int(eot_spec["requested_days"]),
                    granted_days=(int(eot_spec["granted_days"]) if eot_spec.get("granted_days") is not None else None),
                    critical_path_impact=bool(eot_spec["critical_path_impact"]),
                    status=eot_spec["status"],
                    decision_at=(_de_at(decision_day, 15).isoformat() if decision_day else None),
                    decision_notes="Bauzeitverlängerung anerkannt; Vertragstermine fortgeschrieben.",
                    affected_activity_ref=eot_spec["affected_activity_ref"],
                    tia_delta_days=int(eot_spec["requested_days"]),
                    created_at=raised_ts,
                    updated_at=raised_ts,
                )
            )
            counts["eot_claims"] += 1

        # ── Activity trail (custody + dated record for the lead chain) ────
        try:
            from app.core.audit_log import ActivityLog

            for when, action, entity_type, entity_id, code, from_status, to_status, reason in trail:
                session.add(
                    ActivityLog(
                        actor_id=actor,
                        entity_type=entity_type,
                        entity_id=str(entity_id),
                        action=action,
                        from_status=from_status,
                        to_status=to_status,
                        reason=reason,
                        metadata_={"code": code, "demo_id": demo_id},
                        module="variations",
                        parent_entity_type="project",
                        parent_entity_id=str(pid),
                        created_at=when,
                        updated_at=when,
                    )
                )
                counts["activity_rows"] += 1
        except Exception:  # audit log optional in stripped installs
            logger.debug("Activity trail skipped for %s", demo_id, exc_info=True)

        counts["projects"] += 1

    await session.flush()
    if counts["projects"]:
        logger.info("seed_variations_showcase_de: %s", counts)
    return counts
