# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Deterministic demo seed for the HSE Advanced module.

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
    1-2  incident investigations per project, opened on real safety incidents

All randomness is seeded with ``random.Random(42)`` for reproducible runs.

Idempotent: if any HSE-Advanced table already holds rows the bulk seed is a
no-op. Investigations are the exception and are guarded on their own, per
project - see :func:`_seed_investigations` for why a whole-module sentinel
cannot reach them.
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
_INVESTIGATION_METHODS: tuple[str, ...] = ("5_whys", "fishbone", "timeline", "swot")
# Lifecycle mix for the seeded investigations, cycled per row: most are closed
# out, one is still running, and one was dropped once the incident turned out
# not to need root-cause work.
_INVESTIGATION_STATUSES: tuple[str, ...] = ("completed", "in_progress", "completed", "abandoned")
# Findings and recommendations per method, so a reader opening two
# investigations sees two pieces of work rather than the same sentence twice.
_INVESTIGATION_NOTES: dict[str, tuple[str, str]] = {
    "5_whys": (
        "The five-why chain ended at a permit issued before the pre-start check had been signed.",
        "Make the pre-start signature a hard stop in the permit workflow and re-brief the issuing supervisors.",
    ),
    "fishbone": (
        "Cause and effect review put the weight on method and machine: the task sheet did not cover the plant in use.",
        "Rewrite the task sheet around the plant actually on site and re-issue it to the crew.",
    ),
    "timeline": (
        "Reconstructing the timeline showed the exclusion zone was reopened before the lift was confirmed complete.",
        "Hold the exclusion zone until the lift supervisor signs it off, and brief the banksmen on the change.",
    ),
    "swot": (
        "The controls read as sound on paper and were thinly supervised on the night shift.",
        "Extend the supervision roster to the night shift and re-audit the controls in one month.",
    ),
}
_TOPIC_TITLES: tuple[str, ...] = (
    "Working at height - fall protection basics",
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
    "Steelworks Ltd",
    "Greenline Civils",
    "Apex Mechanical",
    "Northern Electric",
    "Highland Painters",
)

# How many of each register the bulk seed writes, and how each row is named.
# The seeder builds its rows from these and ``seeded_row_ids`` recognises the
# rows by the same helpers, so the demo cleanup cannot drift from the seed.
_JSA_COUNT = 50
_PERMIT_COUNT = 40
_PPE_COUNT = 80
_JSA_TASKS: tuple[str, ...] = ("Cast slab", "Erect scaffold", "Install ductwork", "Pour foundation", "Install glazing")
_PERMIT_CONDITIONS = "Comply with site SOP and applicable PPE matrix."


def _jsa_task_description(idx: int, task: str) -> str:
    return f"Task {idx + 1}: {task}"


def _jsa_location(idx: int) -> str:
    return f"Block {chr(65 + (idx % 6))} - Level {(idx % 5) + 1}"


def _permit_number(idx: int) -> str:
    return f"PTW-{2026}-{idx + 1:04d}"


def _permit_type(idx: int) -> str:
    return _PERMIT_TYPES[idx % len(_PERMIT_TYPES)]


def _permit_description(idx: int) -> str:
    return f"{_permit_type(idx).replace('_', ' ').title()} permit for routine site activity #{idx + 1}"


def _permit_location(idx: int) -> str:
    return f"Zone {chr(65 + (idx % 5))}"


def _ppe_serial(idx: int) -> str:
    return f"SN-{idx + 1000:05d}"


async def _table_has_rows(session: AsyncSession, model: type) -> bool:
    """Return True if the given ORM model already has any rows."""
    stmt = select(func.count()).select_from(model)
    total = (await session.execute(stmt)).scalar_one()
    return int(total or 0) > 0


async def _incidents_by_project(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Map each project to the ids of the safety incidents recorded against it.

    An investigation carries no project column: it is reachable from a project
    only through ``incident_ref``, and ``InvestigationRepository.list_for_project``
    resolves scope by exactly this join. So the incidents a project owns are the
    only ids a seeded investigation may reference, and a project with none of
    them gets no investigation rather than an unreachable one.
    """
    if not project_ids:
        return {}
    try:
        from app.modules.safety.models import SafetyIncident
    except ImportError:
        logger.debug("Safety module not loaded; HSE investigations skipped")
        return {}

    stmt = (
        select(SafetyIncident.project_id, SafetyIncident.id)
        .where(SafetyIncident.project_id.in_(list(project_ids)))
        .order_by(SafetyIncident.project_id, SafetyIncident.incident_number)
    )
    try:
        # A SAVEPOINT around the read: on PostgreSQL a failed statement aborts
        # the whole transaction, so an absent safety table would take the rest
        # of the HSE seed down with it instead of costing only this block.
        async with session.begin_nested():
            rows = (await session.execute(stmt)).all()
    except Exception:
        logger.debug("Safety incidents unavailable; HSE investigations skipped", exc_info=True)
        return {}

    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for project_id, incident_id in rows:
        out.setdefault(project_id, []).append(incident_id)
    return out


async def _seed_investigations(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID],
) -> int:
    """Open a root-cause investigation on real incidents, one project at a time.

    Guarded on the investigations a project can actually reach rather than on
    the module as a whole. That distinction is the whole point: this is the only
    block here reachable exclusively through another module's rows, and the
    whole-module sentinel cannot express it. On a database seeded before this
    block referenced real incidents, eight populated tables make the sentinel
    return first, so the tab the module opens on stays empty for good - and the
    ten unreachable rows already in the table would satisfy a table-wide count
    just as permanently.

    Args:
        session: Active async session (the caller commits).
        project_ids: Projects to cover. Each is skipped when one of its own
            incidents already carries an investigation, and when it has no
            incidents to investigate.

    Returns:
        The number of investigations written.
    """
    incidents = await _incidents_by_project(session, project_ids)
    if not incidents:
        return 0

    now = datetime.now(UTC)
    written = 0
    seen: set[uuid.UUID] = set()
    for project_id in project_ids:
        if project_id in seen:
            continue
        seen.add(project_id)
        incident_ids = incidents.get(project_id) or []
        if not incident_ids:
            continue

        already = (
            (
                await session.execute(
                    select(HSEIncidentInvestigation.id)
                    .where(HSEIncidentInvestigation.incident_ref.in_(incident_ids))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if already is not None:
            continue

        # Not every incident is taken to root cause - about half of them are,
        # and never fewer than one, so no project's tab opens empty while a
        # project with a single incident does not look over-investigated.
        wanted = max(1, (len(incident_ids) + 1) // 2)
        for idx, incident_id in enumerate(incident_ids[:wanted]):
            method = _INVESTIGATION_METHODS[idx % len(_INVESTIGATION_METHODS)]
            status_choice = _INVESTIGATION_STATUSES[(written + idx) % len(_INVESTIGATION_STATUSES)]
            findings, recommendations = _INVESTIGATION_NOTES[method]
            started_at = now - timedelta(days=14 + idx * 9)
            session.add(
                HSEIncidentInvestigation(
                    id=uuid.uuid4(),
                    incident_ref=incident_id,
                    investigation_lead=None,
                    started_at=started_at,
                    completed_at=(started_at + timedelta(days=6)) if status_choice == "completed" else None,
                    method=method,
                    findings=findings,
                    recommendations=recommendations,
                    status=status_choice,
                    report_url=None,
                    created_by=None,
                )
            )
            written += 1

    if written:
        await session.flush()
    return written


async def seed_hse_advanced_demo(
    session: AsyncSession,
    project_ids: Sequence[uuid.UUID] | None = None,
) -> dict[str, int]:
    """Idempotently populate the HSE Advanced tables with demo data.

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

    # Ahead of the sentinel and outside it: an investigation is reachable only
    # through a safety incident, so it needs its own per-project guard to land
    # on a database whose other HSE tables are already full.
    investigations = await _seed_investigations(session, project_pool)

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
                "HSE Advanced demo seed: bulk tables skipped (table %s already populated), investigations=%d",
                model.__tablename__,
                investigations,
            )
            return {"skipped": 1, "investigations": investigations}

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
    for idx in range(_JSA_COUNT):
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
            task_description=_jsa_task_description(idx, rng.choice(list(_JSA_TASKS))),
            location=_jsa_location(idx),
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
    for idx in range(_PERMIT_COUNT):
        project_id = project_pool[idx % len(project_pool)]
        permit_type = _permit_type(idx)
        status_choice = _PERMIT_STATUSES[idx % len(_PERMIT_STATUSES)]
        # Spread windows from -10d to +20d around today
        start_offset = rng.randint(-10, 20)
        work_start = now + timedelta(days=start_offset, hours=rng.randint(0, 8))
        work_end = work_start + timedelta(hours=rng.randint(2, 12))
        permit = PermitToWork(
            id=uuid.uuid4(),
            project_id=project_id,
            permit_number=_permit_number(idx),
            permit_type=permit_type,
            description=_permit_description(idx),
            location=_permit_location(idx),
            work_start=work_start,
            work_end=work_end,
            applicant_id=None,
            supervisor_id=None,
            jsa_id=jsas[idx % len(jsas)].id if jsas else None,
            status=status_choice,
            conditions=_PERMIT_CONDITIONS,
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
    for idx in range(_PPE_COUNT):
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
            brand=rng.choice(["Wendlow", "Hulvert", "Kvindal", "Zerbholt", "Vaucrey", None]),
            serial=_ppe_serial(idx),
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

    # ── Audit findings (300) - 6 per audit × 50 audits ───────────────────
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

    # Investigations were written before the sentinel above, on real incidents.
    counts["investigations"] = investigations

    logger.info("HSE Advanced demo seed completed: %s", counts)
    return counts


__all__ = ["seed_hse_advanced_demo"]


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Job safety analyses and permits in ``project_ids`` exactly as the bulk seed wrote them.

    A row is matched against the seed row with the same index, field by field:
    a JSA on its numbered task text and its block and level, a permit on its
    number, type, description, zone and conditions, both with nobody recorded
    as author. A person's permit that reuses a seeded number but describes
    other work is not matched.

    Permits go first: they point at JSAs, with SET NULL, and a permit written
    against a seeded JSA should not lose its link before it is itself checked.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []

    jsa_specs = {
        (_jsa_task_description(idx, task), _jsa_location(idx)) for idx in range(_JSA_COUNT) for task in _JSA_TASKS
    }
    jsa_rows = (
        await session.execute(
            select(
                JobSafetyAnalysis.id,
                JobSafetyAnalysis.task_description,
                JobSafetyAnalysis.location,
                JobSafetyAnalysis.created_by,
                JobSafetyAnalysis.prepared_by,
            ).where(JobSafetyAnalysis.project_id.in_(project_ids))
        )
    ).all()
    jsas = [
        r.id
        for r in jsa_rows
        if (r.task_description, r.location) in jsa_specs and r.created_by is None and r.prepared_by is None
    ]

    permit_specs = {
        (_permit_number(idx), _permit_type(idx), _permit_description(idx), _permit_location(idx))
        for idx in range(_PERMIT_COUNT)
    }
    permit_rows = (
        await session.execute(
            select(
                PermitToWork.id,
                PermitToWork.permit_number,
                PermitToWork.permit_type,
                PermitToWork.description,
                PermitToWork.location,
                PermitToWork.conditions,
                PermitToWork.created_by,
            ).where(PermitToWork.project_id.in_(project_ids))
        )
    ).all()
    permits = [
        r.id
        for r in permit_rows
        if (r.permit_number, r.permit_type, r.description, r.location) in permit_specs
        and r.conditions == _PERMIT_CONDITIONS
        and r.created_by is None
    ]
    return [(PermitToWork, permits, "hse_permits_to_work"), (JobSafetyAnalysis, jsas, "hse_job_safety_analyses")]


async def seeded_ppe_ids(session: AsyncSession) -> list[uuid.UUID]:
    """PPE issues exactly as the bulk seed wrote them.

    The PPE register belongs to the company, not to a project, so this takes no
    project list. A row matches on recipient, firm, PPE type and serial of the
    seed row with the same index, with no linked recipient account and nobody
    recorded as issuer.
    """
    specs = {
        (
            _NAMES[idx % len(_NAMES)],
            _COMPANIES[idx % len(_COMPANIES)],
            _PPE_TYPES[idx % len(_PPE_TYPES)],
            _ppe_serial(idx),
        )
        for idx in range(_PPE_COUNT)
    }
    rows = (
        await session.execute(
            select(
                PPEIssue.id,
                PPEIssue.recipient_name,
                PPEIssue.recipient_company,
                PPEIssue.ppe_type,
                PPEIssue.serial,
                PPEIssue.recipient_user_id,
                PPEIssue.issued_by,
            )
        )
    ).all()
    return [
        r.id
        for r in rows
        if (r.recipient_name, r.recipient_company, r.ppe_type, r.serial) in specs
        and r.recipient_user_id is None
        and r.issued_by is None
    ]
