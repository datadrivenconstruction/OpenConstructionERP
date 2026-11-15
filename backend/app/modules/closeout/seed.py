# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout demo seed - a populated handover checklist per demo project.

Closeout shipped routed, permissioned and empty, so the page opened on a
"create a package" prompt on every demo project. This gives each of them the
package a project actually assembles on its way to handover: the checklist for
its project type, extended with the deliverables a real dossier carries, with
the evidence that has already landed attached to the slots it belongs to.

What a reader sees on the screen afterwards is a handover part way through.
Some rows carry a document from the project's own CDE and a green sign-off,
some carry a document that has been attached but not yet checked by anyone,
some are proposals the matcher put forward and nobody has confirmed, and some
are still outstanding. The completeness bar reads a real fraction rather than
0% or a suspicious 100%.

The arithmetic is derived, never asserted. After the bindings are written the
seeder calls :meth:`CloseoutService.recompute_completeness`, the same method the
API calls on every bind and verify, so ``delivered_slot_count`` and
``completeness_pct`` are whatever the module's own rule says they are. A slot
counts as delivered only when a human verified its evidence; a generated
artifact (COBie export, punch-closure report, inspection certificate) is
produced by the package build and no build has run, so those slots read as
outstanding - which is the honest state and is why no seeded package reaches
``ready``.

Evidence is only ever bound to a document that really exists in the project.
A binding to a missing document renders as a bare fallback label, and a binding
to an unrelated file is the kind of thing a careful reader spots immediately, so
a slot with no plausible document in the project is left outstanding instead.

Dates are anchored to the run date, never hardcoded.

Idempotent per project: the table allows one package per project and a project
that already has one is left untouched, so a re-run never doubles anything.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.closeout import checklist_templates as templates
from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot
from app.modules.closeout.seed_text import closeout_text
from app.modules.closeout.service import CloseoutService

logger = logging.getLogger(__name__)

_SEED = 42

# Checklist template per project, by the project's position in the seeding call.
# The demo projects do not carry a ``project_type``, so the estate would
# otherwise show the same commercial checklist ten times over. Rotating the
# position gives a reader flipping between projects four genuinely different
# dossiers, and a project that does declare its type keeps it.
_TEMPLATE_ROTATION = ("commercial", "residential", "infrastructure", "fitout")

# ``Project.metadata_["building_type"]`` where the demo template sets one.
_BUILDING_TYPE_TO_TEMPLATE = {
    "hospital": "commercial",
    "office": "commercial",
    "retail": "commercial",
    "residential": "residential",
    "apartment": "residential",
    "school": "commercial",
    "warehouse": "infrastructure",
    "industrial": "infrastructure",
    "bridge": "infrastructure",
    "road": "infrastructure",
    "fitout": "fitout",
}

#: Extra slots appended to the template checklist, so the register reads as a
#: dossier somebody keeps rather than as a nine-line template. Each entry is
#: ``(slot_key, title, category, discipline, is_required)``. ``is_required`` is
#: always explicit: the model defaults it to False and a package whose required
#: count reaches zero reports 100% complete with no evidence at all.
_EXTRA_SLOTS: tuple[tuple[str, str, str, str | None, bool], ...] = (
    (
        "as_built_mep",
        "As-built drawings - mechanical and electrical",
        templates.CATEGORY_AS_BUILT,
        "mechanical",
        True,
    ),
    (
        "as_built_structural",
        "As-built drawings - structural",
        templates.CATEGORY_AS_BUILT,
        "structural",
        True,
    ),
    (
        "om_manual_mep",
        "O&M manual - building services",
        templates.CATEGORY_OM,
        "mechanical",
        True,
    ),
    (
        "spare_parts_schedule",
        "Spare parts and consumables schedule",
        templates.CATEGORY_OM,
        None,
        True,
    ),
    (
        "training_records",
        "Operator training records",
        templates.CATEGORY_OM,
        None,
        True,
    ),
    (
        "warranty_register",
        "Warranty register with start and expiry dates",
        templates.CATEGORY_WARRANTY,
        None,
        True,
    ),
    (
        "statutory_certificates",
        "Statutory certificates - electrical, gas and lifting",
        templates.CATEGORY_INSPECTION,
        None,
        True,
    ),
    (
        "fire_strategy_record",
        "Fire strategy and fire stopping record",
        templates.CATEGORY_HS,
        None,
        True,
    ),
    (
        "test_certificates",
        "Test and balancing certificates",
        templates.CATEGORY_COMMISSIONING,
        "mechanical",
        True,
    ),
    (
        "keys_access_register",
        "Keys, access cards and lock suite register",
        templates.CATEGORY_OTHER,
        None,
        False,
    ),
    (
        "bim_model_handover",
        "Federated BIM model issued for record",
        templates.CATEGORY_ASSET_REGISTER,
        None,
        False,
    ),
    (
        "waste_transfer_notes",
        "Waste transfer and site clearance notes",
        templates.CATEGORY_OTHER,
        None,
        False,
    ),
)

# Where a slot's evidence comes from in the project's own document register.
# Each slot key maps to the document keywords that make a binding plausible, in
# preference order. A slot with no match in the project stays outstanding rather
# than being bound to something unrelated: the document name is printed on the
# screen next to the slot title, so a wrong pairing is visible immediately.
_SLOT_DOCUMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "as_built_drawings": ("architectural drawing", "drawing set", "as-built", "as built", "revision"),
    "as_built_mep": ("shop drawing", "tga", "mep", "services", "revision"),
    "as_built_structural": ("structural", "shop drawing"),
    "om_manual": ("o&m", "operation", "maintenance", "manual", "wartung"),
    "om_manual_mep": ("maintenance", "manual", "wartung", "specification"),
    "hs_file": ("health and safety", "safety plan", "hse", "sige", "sicherheit"),
    "fire_strategy_record": ("fire", "brandschutz", "safety plan"),
    "commissioning_certs": ("commissioning", "abnahme", "test", "protokoll"),
    "test_certificates": ("test", "protokoll", "abnahme", "method statement"),
    "statutory_certificates": ("permit", "genehmigung", "authority", "certificate"),
    "warranty": ("warranty", "guarantee", "gewaehrleistung", "vertrag", "contract"),
    "warranty_register": ("contract", "vertrag", "warranty"),
    "geotechnical_records": ("geotechnical", "survey", "soil", "baugrund"),
    "epc_certificate": ("energy", "epc", "energieausweis"),
    "spare_parts_schedule": ("specification", "spezifikation", "product data"),
    "training_records": ("method statement", "training", "schulung"),
    "keys_access_register": ("security", "access", "schliess"),
    "bim_model_handover": ("model", "bim", "ifc"),
    "waste_transfer_notes": ("waste", "entsorgung", "clearance"),
}

# How a bound slot ends up on the screen, by the binding's position in the
# package. Verified rows are the delivered ones; an attached-but-unchecked row
# is waiting on the reviewer; a proposal is what the matcher put forward and
# nobody has confirmed yet, which is the AI-suggests-human-confirms state.
_VERIFIED = "verified"
_ATTACHED = "attached"
_PROPOSED = "proposed"
_BINDING_PLAN = (_VERIFIED, _VERIFIED, _ATTACHED, _VERIFIED, _PROPOSED, _VERIFIED, _ATTACHED, _VERIFIED, _PROPOSED)

# Confidence stamped on a proposed binding. A string column, and deliberately
# short of certainty: a proposal nobody confirmed is not evidence.
_AI_CONFIDENCE = ("0.72", "0.64", "0.81")


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the package."""
    return random.Random(f"{_SEED}:{project_id}")


def _iso(moment: datetime) -> str:
    """ISO-8601 with the microseconds dropped (the columns are String(40))."""
    return moment.replace(microsecond=0).isoformat()


def _template_key(project_type: str | None, metadata: dict | None, ordinal: int) -> str:
    """Pick the checklist template for a project.

    A project that declares its own type keeps it. Otherwise the demo template's
    ``building_type`` decides, and failing that the project's position in the
    seeding call rotates through the four full templates - the demo estate does
    not set ``project_type``, and ten identical commercial checklists teach a
    reader nothing about the module being configurable.
    """
    if project_type and project_type in templates.CHECKLIST_TEMPLATES:
        return project_type
    building_type = str((metadata or {}).get("building_type") or "").strip().lower()
    if building_type in _BUILDING_TYPE_TO_TEMPLATE:
        return _BUILDING_TYPE_TO_TEMPLATE[building_type]
    return _TEMPLATE_ROTATION[ordinal % len(_TEMPLATE_ROTATION)]


async def _project_documents(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """Return ``(document_id, searchable_text)`` for the project's own documents."""
    try:
        from app.modules.documents.models import Document

        stmt = (
            select(Document.id, Document.name, Document.description, Document.category, Document.tags)
            .where(Document.project_id == project_id)
            .order_by(Document.name)
        )
        rows = (await session.execute(stmt)).all()
    except Exception:
        logger.debug("Document lookup unavailable for project=%s", project_id)
        return []
    out: list[tuple[uuid.UUID, str]] = []
    for doc_id, name, description, category, tags in rows:
        tag_text = " ".join(str(t) for t in (tags or []) if t)
        out.append((doc_id, f"{name or ''} {description or ''} {category or ''} {tag_text}".lower()))
    return out


def _match_document(
    slot_key: str,
    documents: Sequence[tuple[uuid.UUID, str]],
    used: set[uuid.UUID],
) -> uuid.UUID | None:
    """The best unused document for a slot, or None when nothing plausible fits.

    Walks the slot's keywords in preference order and takes the first document
    that has not already been attached elsewhere in the package. One document
    backs at most one slot: the same file appearing against three different
    requirements is the tell that a register was filled rather than kept.
    """
    for keyword in _SLOT_DOCUMENT_KEYWORDS.get(slot_key, ()):
        for doc_id, haystack in documents:
            if doc_id not in used and keyword in haystack:
                return doc_id
    return None


async def _actors(session: AsyncSession, owner_id: uuid.UUID) -> str:
    """The account that signs a slot off. Falls back to the project owner."""
    try:
        from app.modules.users.models import User

        rows = (await session.execute(select(User.id, User.role).order_by(User.email))).all()
    except Exception:
        logger.debug("User lookup unavailable; closeout sign-offs recorded against the project owner")
        return str(owner_id)
    by_role: dict[str, str] = {}
    for uid, role in rows:
        by_role.setdefault(str(role or ""), str(uid))
    return by_role.get("manager") or by_role.get("admin") or str(owner_id)


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    project_type: str | None,
    metadata: dict | None,
    owner_id: uuid.UUID,
    ordinal: int,
    locale: str | None = None,
) -> dict[str, int]:
    """Seed one project's closeout package. Returns per-entity counts."""
    empty = {"projects": 0, "packages": 0, "slots": 0, "bindings": 0, "verified": 0}

    service = CloseoutService(session)
    if await service.get_package_for_project(project_id) is not None:
        return empty

    rng = _rng_for(project_id)
    template_key = _template_key(project_type, metadata, ordinal)
    verifier = await _actors(session, owner_id)
    now = datetime.now(UTC)

    package = CloseoutPackage(
        project_id=project_id,
        title=closeout_text(locale, "Handover & Closeout Package"),
        project_type=template_key,
        checklist_template=template_key,
        status="draft",
        metadata_={},
    )
    session.add(package)
    await session.flush()

    slots: list[CloseoutSlot] = []
    # The template checklist first, built exactly as ``create_package`` builds
    # it, so a seeded package and a hand-created one carry the same spine.
    for slot_def in templates.template_for(template_key):
        slot = CloseoutSlot(
            package_id=package.id,
            slot_key=slot_def["slot_key"],
            title=closeout_text(locale, slot_def["title"]),
            category=slot_def.get("category", "other"),
            discipline=slot_def.get("discipline"),
            is_required=bool(slot_def.get("is_required", True)),
            source_kind=slot_def.get("source_kind", "cde_document"),
            generated_artifact=slot_def.get("generated_artifact"),
            ordinal=int(slot_def.get("ordinal", 0)),
            metadata_={},
        )
        slots.append(slot)

    known_keys = {s.slot_key for s in slots}
    ordinal_cursor = 200
    for slot_key, title, category, discipline, is_required in _EXTRA_SLOTS:
        if slot_key in known_keys:
            continue
        ordinal_cursor += 10
        slots.append(
            CloseoutSlot(
                package_id=package.id,
                slot_key=slot_key,
                title=closeout_text(locale, title),
                category=category,
                discipline=discipline,
                is_required=is_required,
                source_kind="cde_document",
                generated_artifact=None,
                ordinal=ordinal_cursor,
                metadata_={},
            )
        )
    session.add_all(slots)
    await session.flush()

    documents = await _project_documents(session, project_id)
    used_documents: set[uuid.UUID] = set()
    bindings = 0
    verified = 0
    plan_index = 0

    for slot in slots:
        if slot.source_kind != "cde_document":
            # A generated artifact is produced by the package build, not bound.
            continue
        document_id = _match_document(slot.slot_key, documents, used_documents)
        if document_id is None:
            continue
        used_documents.add(document_id)
        state = _BINDING_PLAN[plan_index % len(_BINDING_PLAN)]
        plan_index += 1
        is_verified = state == _VERIFIED
        proposed = state == _PROPOSED
        session.add(
            CloseoutBinding(
                slot_id=slot.id,
                document_id=document_id,
                external_url=None,
                is_verified=is_verified,
                verified_by=verifier if is_verified else None,
                verified_at=(
                    _iso(now - timedelta(days=rng.randint(3, 45), hours=rng.randrange(9))) if is_verified else None
                ),
                suggested_by_ai=proposed,
                ai_confidence=(rng.choice(_AI_CONFIDENCE) if proposed else None),
                metadata_={},
            )
        )
        bindings += 1
        verified += int(is_verified)

    await session.flush()
    # Counters and status come from the module's own rule, applied to the rows
    # just written - never from arithmetic restated here. A package that claims
    # a completeness its slots do not support is the first thing a reader spots.
    await service.recompute_completeness(package)

    return {
        "projects": 1,
        "packages": 1,
        "slots": len(slots),
        "bindings": bindings,
        "verified": verified,
    }


async def seed_closeout_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the closeout package for the given demo projects.

    Afterwards the Closeout page of every seeded demo project shows a handover
    checklist of roughly fifteen to twenty requirements with a real completeness
    figure: rows signed off against a document from the project's own register,
    rows attached and waiting on a reviewer, rows the matcher proposed that
    nobody has confirmed, and rows still outstanding - including the generated
    artifacts, which stay outstanding until the package is actually built.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider. A project is skipped when it is not a
            demo project, or when it already has a closeout package, so a
            customer's live project is never written to and a re-run never
            doubles the checklist.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "packages": 0, "slots": 0, "bindings": 0, "verified": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.owner_id, Project.project_type, Project.metadata_, Project.locale).where(
                Project.id.in_(ids)
            )
        )
    ).all()
    # ``enrich_all`` hands this seeder every project in the database, which on a
    # real installation means a customer's own work. Only the demo estate is
    # ours to fill, and the demo project seeder marks its rows.
    #
    # The marker is ``demo_id`` and not ``is_demo``. The ten template projects
    # stamp both, but the flagship reference project is installed from its own
    # baked fixture and carries only ``demo_id``, so a gate on ``is_demo`` skips
    # the one project users actually land on.
    demo = {
        pid: (owner, ptype, meta)
        for pid, owner, ptype, meta, _locale in rows
        if isinstance(meta, dict) and str(meta.get("demo_id") or "").strip()
    }
    # Numbered within the demo estate, not within the caller's list. The list is
    # every project in the database, so on an installation that also carries a
    # customer's own work the same demo project would otherwise land on a
    # different position - and therefore a different checklist - than on a fresh
    # one.
    demo_ids = [pid for pid in ids if pid in demo]
    locales = {row[0]: row[4] for row in rows}

    for ordinal, project_id in enumerate(demo_ids):
        owner_id, project_type, metadata = demo[project_id]
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded
            # costs only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(
                    session, project_id, project_type, metadata, owner_id, ordinal, locales.get(project_id)
                )
        except Exception:
            logger.warning("Closeout demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals
