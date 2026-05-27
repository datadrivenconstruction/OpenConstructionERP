# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Deterministic demo seed for the HSE Advanced module.

Generates realistic volumes per PRD scope:

    30   toolbox topics (catalogue / library)
    50   JSAs (mix of statuses, varied risk scores)
    40   permits-to-work across types/statuses
    200  toolbox talks
    2000 toolbox attendance rows
    80   PPE issues
    50   safety audits with 300 audit findings
    80   CAPAs (mix overdue / open / closed)
    30   worker safety certifications

All randomness is seeded with ``random.Random(42)`` for reproducible runs.
Idempotent: if any HSE-Advanced table already holds rows the seed is a no-op.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hse_advanced.models import (
    CorrectiveAction,
    HSEIncidentInvestigation,
    JobSafetyAnalysis,
    PermitToWork,
    PPEIssue,
    SafetyAudit,
    SafetyAuditFinding,
    SafetyCertification,
    ToolboxAttendance,
    ToolboxTalk,
    ToolboxTopic,
)

logger = logging.getLogger(__name__)


_TOPIC_CATEGORIES: tuple[str, ...] = ("general", "hazard_specific", "regulatory")
_LANGUAGES: tuple[str, ...] = ("en", "de", "es", "ru", "fr")
_PERMIT_TYPES: tuple[str, ...] = (
    "hot_work",
    "confined_space",
    "work_at_height",
    "electrical",
    "excavation",
    "lifting",
    "lockout_tagout",
    "other",
)
_PERMIT_STATUSES: tuple[str, ...] = (
    "requested",
    "approved",
    "active",
    "suspended",
    "closed",
    "cancelled",
)
_JSA_STATUSES: tuple[str, ...] = (
    "draft",
    "under_review",
    "approved",
    "active",
    "archived",
)
_PPE_TYPES: tuple[str, ...] = (
    "hard_hat",
    "safety_boots",
    "gloves",
    "harness",
    "respirator",
    "hi_vis",
    "glasses",
    "other",
)
_PPE_STATUSES: tuple[str, ...] = ("issued", "in_use", "returned", "lost", "damaged")
_AUDIT_TYPES: tuple[str, ...] = ("internal", "external", "regulatory", "site_walk")
_AUDIT_STATUSES: tuple[str, ...] = (
    "scheduled",
    "in_progress",
    "completed",
    "cancelled",
)
_FINDING_CATEGORIES: tuple[str, ...] = (
    "PPE",
    "permit",
    "housekeeping",
    "electrical",
    "fire",
    "environmental",
    "other",
)
_FINDING_SEVERITIES: tuple[str, ...] = ("low", "med", "high", "critical")
_CAPA_SOURCE_TYPES: tuple[str, ...] = (
    "incident",
    "jsa",
    "audit",
    "observation",
    "permit",
)
_CAPA_STATUSES: tuple[str, ...] = (
    "open",
    "in_progress",
    "completed",
    "overdue",
    "cancelled",
)
_ROOT_CAUSES: tuple[str, ...] = (
    "manpower",
    "method",
    "material",
    "machine",
    "environment",
    "management",
    "other",
)
_CERT_TYPES: tuple[str, ...] = (
    "working_at_height",
    "first_aid",
    "confined_space",
    "scaffold_inspector",
    "forklift_operator",
    "crane_operator",
    "fire_warden",
    "hot_work",
    "rigger",
    "electrical_low_voltage",
)
_CERT_STATUSES: tuple[str, ...] = ("valid", "expired", "revoked")
_TOPIC_TITLES: tuple[str, ...] = (
    "Working at height — fall protection basics",
    "Hot work permit walk-through",
    "Confined space entry procedures",
    "Electrical hazards on site",
    "Excavation and trenching safety",
    "Lifting operations and rigging",
    "Lockout / tagout fundamentals",
    "PPE inspection daily checklist",
    "Hand and power tool safety",
    "Manual handling and ergonomics",
    "Slips, trips and falls prevention",
    "Fire prevention on site",
    "Emergency evacuation drills",
    "First aid and CPR basics",
    "Heat stress prevention",
    "Cold-weather working hazards",
    "Working near live traffic",
    "Mobile elevated work platforms",
    "Scaffold inspection requirements",
    "Hazard communication and SDS",
    "Asbestos awareness",
    "Silica dust controls",
    "Welding fume protection",
    "Crane signalling refresher",
    "Working safely with cranes",
    "Behavioural safety observations",
    "Near-miss reporting culture",
    "Environmental spill response",
    "Site housekeeping standards",
    "Toolbox feedback and lessons learned",
)
_NAMES: tuple[str, ...] = (
    "Alice Anderson",
    "Bob Brown",
    "Carlos Costa",
    "Diana Davis",
    "Eric Esteban",
    "Frank Faber",
    "Greta Geier",
    "Hugo Hoffmann",
    "Iris Ibrahim",
    "Jonas Jensen",
    "Kira Kowalski",
    "Liam Larsson",
    "Marta Müller",
    "Niko Novak",
    "Olga Orlov",
    "Pavel Petrov",
    "Quinn Quartermain",
    "Rosa Rivera",
    "Sven Schmidt",
    "Tara Tanaka",
    "Uri Ueda",
    "Vera Vidal",
    "Will Wagner",
    "Xenia Xu",
    "Yusuf Yıldız",
    "Zane Zhukov",
)
_COMPANIES: tuple[str, ...] = (
    "Acme Construction",
    "BuildCo",
    "Steelworks Ltd",
    "Greenline Civils",
    "Apex Mechanical",
    "Northern Electric",
    "Highland Painters",
)


async def _table_has_rows(session: AsyncSession, model: type) -> bool:
    """‌⁠‍Return True if the given ORM model already has any rows."""
    stmt = select(func.count()).select_from(model)
    total = (await session.execute(stmt)).scalar_one()
    return int(total or 0) > 0


async def seed_hse_advanced_demo(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID] | None = None,
) -> dict[str, int]:
    """‌⁠‍Idempotently populate the HSE Advanced tables with demo data.

    Args:
        session: an active :class:`AsyncSession`.
        project_ids: list of real project UUIDs to attach scoped rows to.
            When empty, deterministic synthetic UUIDs are used.

    Returns:
        Counts dict with one key per seeded table.
    """
    rng = random.Random(42)

    project_pool: list[uuid.UUID] = list(project_ids or [])
    if not project_pool:
        project_pool = [uuid.uuid4() for _ in range(5)]

    # Idempotency: if any HSE-Advanced primary table has data, skip everything.
    sentinel_models = (
        JobSafetyAnalysis,
        PermitToWork,
        ToolboxTalk,
        ToolboxTopic,
        SafetyAudit,
        CorrectiveAction,
        PPEIssue,
        SafetyCertification,
    )
    for model in sentinel_models:
        if await _table_has_rows(session, model):
            logger.info(
                "HSE Advanced demo seed: skipped (table %s already populated)",
                model.__tablename__,
            )
            return {"skipped": 1}

    now = datetime.now(UTC)
    today = date.today()
    counts: dict[str, int] = {}

    # ── Toolbox topics (30) ──────────────────────────────────────────────
    topics: list[ToolboxTopic] = []
    for idx in range(30):
        title = _TOPIC_TITLES[idx % len(_TOPIC_TITLES)]
        topic = ToolboxTopic(
            id=uuid.uuid4(),
            code=f"TBX-{idx + 1:03d}",
            title=title,
            content=f"Detailed talk content for {title}. Covers hazards, controls, and PPE requirements.",
            category=_TOPIC_CATEGORIES[idx % len(_TOPIC_CATEGORIES)],
            language=_LANGUAGES[idx % len(_LANGUAGES)],
            duration_minutes=rng.choice([5, 10, 15, 20]),
            version="1.0",
            is_active=(idx % 7 != 0),
        )
        session.add(topic)
        topics.append(topic)
    await session.flush()
    counts["topics"] = len(topics)

    # ── JSAs (50) ────────────────────────────────────────────────────────
    jsas: list[JobSafetyAnalysis] = []
    for idx in range(50):
        project_id = project_pool[idx % len(project_pool)]
        hazard_count = rng.randint(2, 6)
        hazards = [
            {
                "step": f"Step {h + 1}",
                "hazard": rng.choice(
                    [
                        "Falling object",
                        "Pinch point",
                        "Slip hazard",
                        "Exposed wiring",
                        "Sharp edge",
                        "Hot surface",
                        "Suspended load",
                    ]
                ),
                "severity": rng.randint(1, 5),
                "likelihood": rng.randint(1, 5),
                "controls": "Use PPE, sign work area, supervisor sign-off",
            }
            for h in range(hazard_count)
        ]
        max_score = max((h["severity"] * h["likelihood"]) for h in hazards)
        status_choice = _JSA_STATUSES[idx % len(_JSA_STATUSES)]
        jsa = JobSafetyAnalysis(
            id=uuid.uuid4(),
            project_id=project_id,
            task_description=f"Task {idx + 1}: {rng.choice(['Cast slab', 'Erect scaffold', 'Install ductwork', 'Pour foundation', 'Install glazing'])}",
            location=f"Block {chr(65 + (idx % 6))} - Level {(idx % 5) + 1}",
            work_date=(today + timedelta(days=(idx % 30) - 5)).isoformat(),
            prepared_by=None,
            status=status_choice,
            hazards=hazards,
            required_ppe=rng.sample(list(_PPE_TYPES), k=rng.randint(2, 4)),
            risk_score=max_score,
            created_by=None,
        )
        if status_choice in {"approved", "active", "archived"}:
            jsa.approved_at = now - timedelta(days=rng.randint(1, 30))
        session.add(jsa)
        jsas.append(jsa)
    await session.flush()
    counts["jsas"] = len(jsas)

    # ── Permits (40) ─────────────────────────────────────────────────────
    permits: list[PermitToWork] = []
    for idx in range(40):
        project_id = project_pool[idx % len(project_pool)]
        permit_type = _PERMIT_TYPES[idx % len(_PERMIT_TYPES)]
        status_choice = _PERMIT_STATUSES[idx % len(_PERMIT_STATUSES)]
        # Spread windows from -10d to +20d around today
        start_offset = rng.randint(-10, 20)
        work_start = now + timedelta(days=start_offset, hours=rng.randint(0, 8))
        work_end = work_start + timedelta(hours=rng.randint(2, 12))
        permit = PermitToWork(
            id=uuid.uuid4(),
            project_id=project_id,
            permit_number=f"PTW-{2026}-{idx + 1:04d}",
            permit_type=permit_type,
            description=(f"{permit_type.replace('_', ' ').title()} permit for routine site activity #{idx + 1}"),
            location=f"Zone {chr(65 + (idx % 5))}",
            work_start=work_start,
            work_end=work_end,
            applicant_id=None,
            supervisor_id=None,
            jsa_id=jsas[idx % len(jsas)].id if jsas else None,
            status=status_choice,
            conditions="Comply with site SOP and applicable PPE matrix.",
            closure_checklist_passed=(status_choice == "closed"),
            closure_notes=(
                "Area cleared, debris removed, post-work inspection signed." if status_choice == "closed" else ""
            ),
            created_by=None,
        )
        if status_choice in {"approved", "active", "closed"}:
            permit.approved_at = now - timedelta(days=rng.randint(1, 10))
        session.add(permit)
        permits.append(permit)
    await session.flush()
    counts["permits"] = len(permits)

    # ── Toolbox talks (200) + attendance (2000) ──────────────────────────
    talks: list[ToolboxTalk] = []
    attendances: list[ToolboxAttendance] = []
    for idx in range(200):
        project_id = project_pool[idx % len(project_pool)]
        topic = topics[idx % len(topics)]
        conducted_at = now - timedelta(days=rng.randint(0, 90), hours=rng.randint(0, 8))
        talk = ToolboxTalk(
            id=uuid.uuid4(),
            project_id=project_id,
            topic_code=topic.code,
            topic_title=topic.title,
            conducted_at=conducted_at,
            conducted_by=None,
            language=topic.language,
            attendance_count=10,
            notes=f"Talk #{idx + 1}: workforce engaged; questions noted.",
            library_topic_ref=topic.id,
            created_by=None,
        )
        session.add(talk)
        talks.append(talk)
    await session.flush()

    # 2000 attendance rows ⇒ exactly 10 per talk × 200 talks.
    for talk in talks:
        for j in range(10):
            attendance = ToolboxAttendance(
                id=uuid.uuid4(),
                toolbox_talk_id=talk.id,
                attendee_name=_NAMES[rng.randint(0, len(_NAMES) - 1)],
                attendee_company=_COMPANIES[rng.randint(0, len(_COMPANIES) - 1)],
                attendee_role=rng.choice(["worker", "foreman", "visitor"]),
                signature_ref=None,
                signed_at=talk.conducted_at + timedelta(minutes=j),
                attendance_status=rng.choice(["present"] * 8 + ["late", "absent"]),
            )
            session.add(attendance)
            attendances.append(attendance)
    await session.flush()
    counts["talks"] = len(talks)
    counts["attendances"] = len(attendances)

    # ── PPE issues (80) ──────────────────────────────────────────────────
    ppe_issues: list[PPEIssue] = []
    for idx in range(80):
        status_choice = _PPE_STATUSES[idx % len(_PPE_STATUSES)]
        ppe = PPEIssue(
            id=uuid.uuid4(),
            recipient_user_id=None,
            recipient_name=_NAMES[idx % len(_NAMES)],
            recipient_company=_COMPANIES[idx % len(_COMPANIES)],
            issued_at=now - timedelta(days=rng.randint(0, 180)),
            issued_by=None,
            ppe_type=_PPE_TYPES[idx % len(_PPE_TYPES)],
            size=rng.choice(["S", "M", "L", "XL", "XXL", None]),
            brand=rng.choice(["3M", "MSA", "Honeywell", "Uvex", "Bollé", None]),
            serial=f"SN-{idx + 1000:05d}",
            valid_until=today + timedelta(days=rng.randint(30, 720)),
            status=status_choice,
            returned_at=(now - timedelta(days=rng.randint(1, 30)))
            if status_choice in {"returned", "lost", "damaged"}
            else None,
        )
        session.add(ppe)
        ppe_issues.append(ppe)
    await session.flush()
    counts["ppe_issues"] = len(ppe_issues)

    # ── Audits (50) ──────────────────────────────────────────────────────
    audits: list[SafetyAudit] = []
    for idx in range(50):
        project_id = project_pool[idx % len(project_pool)]
        status_choice = _AUDIT_STATUSES[idx % len(_AUDIT_STATUSES)]
        audit = SafetyAudit(
            id=uuid.uuid4(),
            project_id=project_id,
            audit_type=_AUDIT_TYPES[idx % len(_AUDIT_TYPES)],
            conducted_at=now - timedelta(days=rng.randint(0, 120)),
            conducted_by=None,
            score_total=None,
            max_score=None,
            status=status_choice,
            summary=f"Routine audit #{idx + 1}; six categories inspected.",
            checklist_template_ref=None,
            created_by=None,
        )
        session.add(audit)
        audits.append(audit)
    await session.flush()

    # ── Audit findings (300) — 6 per audit × 50 audits ───────────────────
    findings: list[SafetyAuditFinding] = []
    for audit in audits:
        for j in range(6):
            finding = SafetyAuditFinding(
                id=uuid.uuid4(),
                audit_id=audit.id,
                item_description=rng.choice(
                    [
                        "PPE worn correctly",
                        "Permit on site",
                        "Walkways unobstructed",
                        "Fire extinguishers tagged",
                        "Cables not damaged",
                        "MSDS available",
                        "Edge protection intact",
                        "Tools inspected",
                    ]
                ),
                category=_FINDING_CATEGORIES[j % len(_FINDING_CATEGORIES)],
                severity=rng.choice(_FINDING_SEVERITIES),
                is_passed=(rng.random() > 0.25),
                evidence_url=None,
            )
            session.add(finding)
            findings.append(finding)
    await session.flush()
    counts["audits"] = len(audits)
    counts["findings"] = len(findings)

    # ── CAPAs (80) ───────────────────────────────────────────────────────
    capas: list[CorrectiveAction] = []
    for idx in range(80):
        project_id = project_pool[idx % len(project_pool)]
        # Distribution: 25% overdue (target in past, status overdue),
        # 50% open / in_progress, 25% closed (completed or cancelled).
        bucket = idx % 4
        if bucket == 0:
            status_choice = "overdue"
            target_date = today - timedelta(days=rng.randint(1, 60))
        elif bucket == 3:
            status_choice = rng.choice(["completed", "cancelled"])
            target_date = today + timedelta(days=rng.randint(-30, 30))
        else:
            status_choice = rng.choice(["open", "in_progress"])
            target_date = today + timedelta(days=rng.randint(1, 90))

        capa = CorrectiveAction(
            id=uuid.uuid4(),
            project_id=project_id,
            source_type=_CAPA_SOURCE_TYPES[idx % len(_CAPA_SOURCE_TYPES)],
            source_ref=audits[idx % len(audits)].id if audits else None,
            title=f"CAPA #{idx + 1}: address finding from audit",
            description=("Verify control measures, retrain crew, and report back to safety officer."),
            owner_user_id=None,
            target_date=target_date,
            status=status_choice,
            completed_at=(now - timedelta(days=rng.randint(1, 60))) if status_choice == "completed" else None,
            verification_notes="Verified on site walk-down." if status_choice == "completed" else "",
            root_cause_category=rng.choice(_ROOT_CAUSES + (None,)),
            created_by=None,
        )
        session.add(capa)
        capas.append(capa)
    await session.flush()
    counts["capas"] = len(capas)

    # ── Certifications (30) ──────────────────────────────────────────────
    certs: list[SafetyCertification] = []
    for idx in range(30):
        status_choice = _CERT_STATUSES[idx % len(_CERT_STATUSES)]
        if status_choice == "valid":
            valid_until = today + timedelta(days=rng.randint(30, 730))
        elif status_choice == "expired":
            valid_until = today - timedelta(days=rng.randint(1, 180))
        else:
            valid_until = today + timedelta(days=rng.randint(-90, 365))

        cert = SafetyCertification(
            id=uuid.uuid4(),
            owner_user_id=None,
            owner_name=_NAMES[idx % len(_NAMES)],
            owner_company=_COMPANIES[idx % len(_COMPANIES)],
            cert_type=_CERT_TYPES[idx % len(_CERT_TYPES)],
            issued_by=rng.choice(["OSHA", "IOSH", "NEBOSH", "TÜV", "BG BAU", "City & Guilds"]),
            issue_date=valid_until - timedelta(days=730),
            valid_until=valid_until,
            document_url=None,
            status=status_choice,
        )
        session.add(cert)
        certs.append(cert)
    await session.flush()
    counts["certifications"] = len(certs)

    # ── Incident investigations (10) — light demo set ────────────────────
    investigations: list[HSEIncidentInvestigation] = []
    for idx in range(10):
        inv = HSEIncidentInvestigation(
            id=uuid.uuid4(),
            incident_ref=uuid.uuid4(),
            investigation_lead=None,
            started_at=now - timedelta(days=rng.randint(1, 90)),
            method=rng.choice(["5_whys", "fishbone", "timeline", "swot"]),
            findings="Root cause traced to procedural gap.",
            recommendations="Update SOP, retrain crew, schedule follow-up audit.",
            status=rng.choice(["in_progress", "completed", "abandoned"]),
            report_url=None,
            created_by=None,
        )
        session.add(inv)
        investigations.append(inv)
    await session.flush()
    counts["investigations"] = len(investigations)

    logger.info("HSE Advanced demo seed completed: %s", counts)
    return counts


__all__ = ["seed_hse_advanced_demo"]
