"""Demo seed data for the markups module.

Creates a small, realistic set of drawing annotations for the first few
projects so the markups viewer has something to render out of the box:

    - 1 ScaleConfig (pixel-to-real-world calibration for a document page)
    - 2 StampTemplate rows (an Approved and a Revise stamp)
    - 6 Markup rows with different shapes, pages, and types
    - 1 to 2 MarkupComment rows per markup

Markups attach to a document via the plain ``document_id`` String column
(no hard FK to a takeoff or PDF document table). The seed binds every
annotation to a REAL CDE document with a PDF on disk - reusing an existing
one for the project or dropping in a copy of the bundled reference plan -
so the markups hub deep link opens an actual drawing instead of a blank
"file not found" viewer.

Loaded on demand via ``await seed_markups(session, project_ids)``. Safe to
call repeatedly: if a seed markup already exists for the first project the
function returns immediately without inserting anything.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document
from app.modules.markups.models import (
    Markup,
    MarkupComment,
    ScaleConfig,
    StampTemplate,
)
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

_FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")
_SEED_AUTHOR = "demo-seed"
_SEED_LAYER = "seed-demo"
# The bundled reference plan (house_plans.pdf) the seed binds markups to is a
# single sheet. Markup specs that nominate a higher page are clamped so the
# overlay always lands on a page that exists in the PDF and stays visible.
_REFERENCE_PLAN_PAGES = 1

# (type, page, geometry, color, label, text, measurement value/unit)
# Geometry is intentionally schema-light - the viewer reads ``type`` plus
# whatever shape coordinates a given markup carries.
_MARKUP_SPECS = [
    (
        "rectangle",
        1,
        {"x": 120.0, "y": 80.0, "width": 240.0, "height": 160.0},
        "#ef4444",
        "Clash zone",
        "Reinforcement clashes with duct run here, please coordinate.",
        None,
        None,
    ),
    (
        "cloud",
        1,
        {"points": [[400.0, 120.0], [560.0, 120.0], [560.0, 260.0], [400.0, 260.0]]},
        "#f97316",
        "Revision A",
        "Cloud added during revision A review cycle.",
        None,
        None,
    ),
    (
        "arrow",
        2,
        {"start": [80.0, 320.0], "end": [260.0, 200.0]},
        "#3b82f6",
        "Check level",
        "Confirm the finished floor level against the section drawing.",
        None,
        None,
    ),
    (
        "text",
        2,
        {"x": 300.0, "y": 400.0},
        "#22c55e",
        "Note",
        "Approved finish: exposed concrete, sealed.",
        None,
        None,
    ),
    (
        # ``distance`` is the schema-valid measurement type (schemas.py
        # MarkupCreate.type pattern). The viewer renders it as a length
        # measurement; an earlier ``measure_length`` value was rejected by
        # the validator and silently coerced to ``other`` on the client.
        "distance",
        3,
        {"start": [50.0, 50.0], "end": [50.0, 650.0]},
        "#8b5cf6",
        "Wall length",
        "Measured wall length used for the BOQ takeoff.",
        Decimal("6.000000"),
        "m",
    ),
    (
        # ``area`` is the schema-valid measurement type (see note above);
        # the previous ``measure_area`` value failed validation on edit.
        "area",
        3,
        {"polygon": [[100.0, 100.0], [500.0, 100.0], [500.0, 400.0], [100.0, 400.0]]},
        "#0ea5e9",
        "Slab area",
        "Floor slab area for concrete quantity estimate.",
        Decimal("48.000000"),
        "m2",
    ),
]

# Two comments per markup index; the second is optional (None = skip).
_COMMENT_SPECS = [
    ("reviewer-anna", "Confirmed with the structural engineer, rerouting the duct."),
    ("reviewer-ben", "Agreed, will update the model in the next revision."),
    ("reviewer-anna", "Level looks correct against drawing S-204."),
    ("reviewer-ben", "Finish approved by the client on the last site walk."),
    ("reviewer-anna", "Length matches the as-built tape measurement."),
    ("reviewer-ben", "Area used in BOQ line 3.02, all good."),
]


async def _ensure_real_document(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """Return the id of a real, renderable CDE PDF document for the project.

    Markups attach to a ``document_id`` that the inline annotator streams from
    ``GET /v1/documents/{id}/download/``. A synthetic id renders a blank
    "file not found" viewer, so bind to an actual document instead: reuse an
    existing PDF for the project when one is present (e.g. the flagship plan
    set), otherwise drop a copy of the bundled reference plan into the uploads
    store and register it. Returns ``None`` only when no owner user or source
    asset is available, in which case the caller skips that project.
    """
    existing = (
        await session.execute(
            select(Document.id)
            .where(Document.project_id == project_id)
            .where(Document.mime_type == "application/pdf")
            .where(Document.file_path != "")
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return str(existing)

    owner_id = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner_id is None:
        owner_id = (await session.execute(select(User.id).limit(1))).scalar_one_or_none()
    if owner_id is None:
        return None

    source_pdf = Path(__file__).resolve().parents[2] / "scripts" / "flagship_assets" / "house_plans.pdf"
    if not source_pdf.exists():
        logger.warning("markups seed: reference PDF missing at %s", source_pdf)
        return None

    from app.modules.documents.service import UPLOAD_BASE

    doc_id = uuid.uuid4()
    upload_dir = Path(UPLOAD_BASE) / str(project_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    data = source_pdf.read_bytes()
    dest = upload_dir / f"{doc_id.hex[:12]}_floor-plans.pdf"
    dest.write_bytes(data)
    session.add(
        Document(
            id=doc_id,
            project_id=project_id,
            name="Floor plans.pdf",
            description="Reference floor plan set for markups and takeoff.",
            category="drawing",
            file_size=len(data),
            mime_type="application/pdf",
            file_path=str(dest),
            version=1,
            is_current_revision=True,
            uploaded_by=str(owner_id),
            metadata_={"source": "markups_seed", "seed": True, "demo": True},
        )
    )
    await session.flush()
    return str(doc_id)


async def seed_markups(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed demo scale config, stamp templates, markups, and comments.

    Args:
        session: Active async SQLAlchemy session.
        project_ids: Candidate project ids. At most the first three are
            seeded, but the flagship project id is always included when
            present. Each seeded project gets its own document scope.

    Returns:
        A mapping of entity name to the number of rows inserted. Returns an
        empty dict when the seed has already run (idempotent short-circuit).
    """
    if not project_ids:
        logger.info("Markups seed skipped: no project ids supplied")
        return {}

    # Build the target list: first three projects, flagship always included.
    targets: list[uuid.UUID] = list(project_ids[:3])
    if _FLAGSHIP_PROJECT_ID in project_ids and _FLAGSHIP_PROJECT_ID not in targets:
        targets.append(_FLAGSHIP_PROJECT_ID)

    # Idempotency guard: bail out if our marker layer already exists for the
    # first project id. The wiring site also guards, but this keeps the
    # function safe to call twice on its own.
    marker_project = project_ids[0]
    existing = await session.execute(
        select(Markup.id).where(Markup.project_id == marker_project).where(Markup.layer == _SEED_LAYER).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Markups seed skipped: already present for %s", marker_project)
        return {}

    counts: dict[str, int] = {
        "scale_configs": 0,
        "stamp_templates": 0,
        "markups": 0,
        "comments": 0,
    }

    for project_id in targets:
        # Bind every seeded annotation to a REAL CDE document so the markups
        # hub deep link (/markups?openDoc=<id>&markup=<id>) opens an actual
        # PDF instead of a blank viewer. Skip the project when no document can
        # be provided rather than fall back to a synthetic id that 404s.
        document_id = await _ensure_real_document(session, project_id)
        if document_id is None:
            logger.info("Markups seed: no document available for %s, skipping", project_id)
            continue

        # --- 1 scale config for page 1 of the document ---
        scale = ScaleConfig(
            document_id=document_id,
            page=1,
            pixels_per_unit=Decimal("100.000000"),
            unit_label="m",
            calibration_points={
                "start": [50.0, 50.0],
                "end": [150.0, 50.0],
            },
            real_distance=Decimal("1.000000"),
            created_by=_SEED_AUTHOR,
        )
        session.add(scale)
        counts["scale_configs"] += 1

        # --- 2 stamp templates scoped to this project ---
        stamp_approved = StampTemplate(
            project_id=project_id,
            owner_id=_SEED_AUTHOR,
            name="Approved",
            # ``predefined`` is the only schema-valid category besides
            # ``custom`` (schemas.py StampTemplateCreate.category pattern).
            # The old ``approval`` value violated that contract and could
            # not be re-saved through the API.
            category="predefined",
            text="APPROVED",
            color="#22c55e",
            background_color="#dcfce7",
            icon="check",
            include_date=True,
            include_name=True,
            is_active=True,
            metadata_={"seed": True},
        )
        stamp_revise = StampTemplate(
            project_id=project_id,
            owner_id=_SEED_AUTHOR,
            name="Revise and resubmit",
            # See the note above: ``predefined`` is schema-valid, the old
            # ``rejection`` value was not.
            category="predefined",
            text="REVISE & RESUBMIT",
            color="#ef4444",
            background_color="#fee2e2",
            icon="alert",
            include_date=True,
            include_name=True,
            is_active=True,
            metadata_={"seed": True},
        )
        session.add(stamp_approved)
        session.add(stamp_revise)
        counts["stamp_templates"] += 2
        await session.flush()

        # --- 6 markups with 1-2 comments each ---
        for idx, spec in enumerate(_MARKUP_SPECS):
            mk_type, page, geometry, color, label, text, m_value, m_unit = spec
            markup = Markup(
                project_id=project_id,
                document_id=document_id,
                page=min(page, _REFERENCE_PLAN_PAGES),
                type=mk_type,
                geometry=dict(geometry),
                text=text,
                color=color,
                line_width=2,
                opacity=1.0,
                author_id=_SEED_AUTHOR,
                status="active",
                label=label,
                measurement_value=m_value,
                measurement_unit=m_unit,
                linked_boq_position_id=None,
                layer=_SEED_LAYER,
                metadata_={"seed": True, "demo": True},
                created_by=_SEED_AUTHOR,
            )
            session.add(markup)
            await session.flush()
            # Capture the generated id locally; never read a lazy
            # ``markup.comments`` relationship under async (MissingGreenlet).
            markup_id = markup.id
            counts["markups"] += 1

            # Always one comment; even markup indexes get a second comment.
            primary_user, primary_body = _COMMENT_SPECS[idx]
            session.add(
                MarkupComment(
                    markup_id=markup_id,
                    user_id=primary_user,
                    body=primary_body,
                )
            )
            counts["comments"] += 1
            if idx % 2 == 0:
                session.add(
                    MarkupComment(
                        markup_id=markup_id,
                        user_id="reviewer-ben",
                        body="Thanks, noted and tracked for follow-up.",
                    )
                )
                counts["comments"] += 1

    await session.flush()
    logger.info("Markups seed inserted: %s", counts)
    return counts
