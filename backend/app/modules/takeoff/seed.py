"""Demo seed data for the takeoff module.

Loaded on demand via ``await seed_takeoff_demo(session, project_ids)``.

Seeds a single uploaded PDF :class:`TakeoffDocument` plus a spread of
:class:`TakeoffMeasurement` annotations (area, length and count types) for the
flagship project so the PDF takeoff workspace arrives populated instead of
empty. A representative :class:`CadExtractionSession` is also created so the CAD
extraction history is not blank.

The seed is idempotent: it short-circuits and returns an empty dict when a
:class:`TakeoffDocument` already exists for the first project id. It never
touches a lazy relationship after a flush (every generated id is captured into
a local variable), and every non-nullable column receives a typed value.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.takeoff.models import (
    CadExtractionSession,
    TakeoffDocument,
    TakeoffMeasurement,
)
from app.modules.users.models import User

logger = logging.getLogger(__name__)

_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# (type, group_name, group_color, annotation, value, unit, perimeter, count)
# Eight measurements: 4 area, 2 length (distance), 2 count. Decimal columns get
# Decimal values; the count rows carry count_value (Integer) and leave the
# Numeric quantity columns None.
_MEASUREMENT_SPECS: list[tuple[str, str, str, str, Decimal | None, str, Decimal | None, int | None]] = [
    ("area", "Floor slabs", "#3B82F6", "Ground floor slab", Decimal("248.500000"), "m2", Decimal("64.200000"), None),
    ("area", "Floor slabs", "#3B82F6", "First floor slab", Decimal("236.750000"), "m2", Decimal("62.800000"), None),
    ("area", "Walls", "#10B981", "External wall elevation A", Decimal("96.400000"), "m2", Decimal("41.600000"), None),
    ("area", "Walls", "#10B981", "External wall elevation B", Decimal("88.250000"), "m2", Decimal("39.100000"), None),
    ("distance", "Skirting", "#F59E0B", "Skirting run room 101", Decimal("32.400000"), "m", None, None),
    ("distance", "Skirting", "#F59E0B", "Skirting run room 102", Decimal("28.900000"), "m", None, None),
    ("count", "Doors", "#EF4444", "Internal single doors", None, "pcs", None, 14),
    ("count", "Windows", "#8B5CF6", "Operable windows", None, "pcs", None, 22),
]


async def _resolve_owner_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve a valid owner user id for the takeoff document.

    Prefers the owner of the target project (the demo user installed alongside
    the flagship); falls back to any existing user. Returns None when the users
    table is empty, in which case the caller skips seeding.
    """
    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is not None:
        return owner_id
    return (await session.execute(select(User.id).limit(1))).scalar_one_or_none()


async def seed_takeoff_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed demo takeoff document, measurements and a CAD session.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects. The flagship project is always
            preferred; otherwise the first id is used.

    Returns:
        A dict of row counts per entity inserted, or an empty dict when nothing
        was seeded (already present, or no project / owner available).
    """
    if not project_ids:
        return {}

    # Prefer the flagship project so the document lands where users browse.
    target_id = _FLAGSHIP_ID if _FLAGSHIP_ID in project_ids else project_ids[0]

    # Idempotency guard: skip entirely when a document already exists for the
    # target project (the wiring site also guards, but this stays safe twice).
    existing = (
        await session.execute(select(TakeoffDocument.id).where(TakeoffDocument.project_id == target_id).limit(1))
    ).scalar_one_or_none()
    if existing is not None:
        return {}

    owner_id = await _resolve_owner_id(session, target_id)
    if owner_id is None:
        logger.info("takeoff seed skipped: no owner user available")
        return {}

    counts: dict[str, int] = {"documents": 0, "measurements": 0, "cad_sessions": 0}
    now = datetime.now(UTC)

    # --- 1 takeoff document backed by a REAL PDF on disk ---
    # The viewer streams the file from GET /takeoff/documents/{id}/download/,
    # which serves a 404 unless an actual PDF exists under the takeoff
    # documents directory (and inside the path allow-list). Copy the bundled
    # reference plan set there so the deep link from the markups hub - and the
    # document card itself - renders a real drawing instead of an empty
    # "file not found" viewer. The id is generated up front so the on-disk
    # file name matches the row, exactly like a real upload.
    from app.modules.takeoff.service import _TAKEOFF_DOCUMENTS_DIR

    doc_uuid = uuid.uuid4()
    source_pdf = Path(__file__).resolve().parents[2] / "scripts" / "flagship_assets" / "house_plans.pdf"
    pages = 1
    size_bytes = 0
    file_path = ""
    if source_pdf.exists():
        _TAKEOFF_DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        dest_pdf = _TAKEOFF_DOCUMENTS_DIR / f"{doc_uuid}.pdf"
        shutil.copyfile(source_pdf, dest_pdf)
        size_bytes = dest_pdf.stat().st_size
        file_path = str(dest_pdf)
        try:
            import fitz  # PyMuPDF - already a takeoff dependency

            with fitz.open(dest_pdf) as opened:
                pages = max(1, opened.page_count)
        except Exception:  # noqa: BLE001 - page count is cosmetic, never fatal
            pages = 1
    else:
        logger.warning("takeoff seed: reference PDF missing at %s", source_pdf)

    document = TakeoffDocument(
        id=doc_uuid,
        filename="ground-floor-plan.pdf",
        pages=pages,
        size_bytes=size_bytes,
        content_type="application/pdf",
        status="analyzed",
        project_id=target_id,
        owner_id=owner_id,
        file_path=file_path,
        extracted_text=(
            "Ground floor plan. Scale 1:100. Slab thickness 250mm. Door schedule and window schedule attached."
        ),
        page_data=[
            {"page": n, "text": "Ground floor plan" if n == 1 else f"Sheet {n}", "tables": []}
            for n in range(1, pages + 1)
        ],
        analysis={
            "summary": "Plan analysed for slab, wall, door and window quantities.",
            "trades": ["concrete", "doors", "windows"],
        },
        metadata_={"seed": True, "demo": True, "scale": "1:100"},
    )
    session.add(document)
    await session.flush()
    # Capture the generated id locally (never read document.measurements - a
    # lazy relationship would raise MissingGreenlet under async).
    document_id = str(document.id)
    counts["documents"] = 1

    # --- 8 measurements (area / length / count) ---
    owner_ref = str(owner_id)
    for idx, (
        m_type,
        group_name,
        group_color,
        annotation,
        value,
        unit,
        perimeter,
        count_value,
    ) in enumerate(_MEASUREMENT_SPECS):
        measurement = TakeoffMeasurement(
            project_id=target_id,
            document_id=document_id,
            # Keep every measurement on a page that actually exists in the
            # backing PDF so the overlay renders (the reference plan is a
            # single page; this still spreads them when a multi-page plan is
            # used in future).
            page=(idx % pages) + 1,
            type=m_type,
            group_name=group_name,
            group_color=group_color,
            annotation=annotation,
            points=[
                {"x": 100.0 + idx * 10, "y": 120.0 + idx * 5},
                {"x": 260.0 + idx * 10, "y": 120.0 + idx * 5},
                {"x": 260.0 + idx * 10, "y": 240.0 + idx * 5},
                {"x": 100.0 + idx * 10, "y": 240.0 + idx * 5},
            ],
            measurement_value=value,
            measurement_unit=unit,
            depth=Decimal("0.250000") if m_type == "area" else None,
            volume=(value * Decimal("0.250000")) if (m_type == "area" and value is not None) else None,
            perimeter=perimeter,
            count_value=count_value,
            scale_pixels_per_unit=37.795300,
            linked_boq_position_id=None,
            metadata_={"seed": True, "demo": True},
            created_by=owner_ref,
        )
        session.add(measurement)
        counts["measurements"] += 1

    # --- 1 optional CAD extraction session ---
    cad_session = CadExtractionSession(
        session_id=f"seed-cad-{target_id}",
        user_id=owner_ref,
        filename="structure.ifc",
        file_format="ifc",
        element_count=6,
        extraction_time=2.4,
        elements_data=[
            {"id": "elem_001", "category": "wall", "area_m2": 96.4},
            {"id": "elem_002", "category": "slab", "area_m2": 248.5},
        ],
        columns_metadata={"category": "string", "area_m2": "number"},
        project_id=str(target_id),
        display_name="Structure (IFC) extraction",
        is_permanent=True,
        expires_at=now + timedelta(days=7),
        created_by=owner_ref,
        session_ttl_days=7,
        is_persistent=True,
        bim_model_id=None,
    )
    session.add(cad_session)
    counts["cad_sessions"] = 1

    await session.flush()
    logger.info("takeoff demo seed inserted: %s", counts)
    return counts
