# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project-profile service — apply / read / recompute / retrofit.

Stateless; every method takes the AsyncSession explicitly. Presentation
-only gating: writing :class:`ProjectModule` rows never unloads a module
or blocks its API — it only feeds the sidebar's visual emphasis.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects import schemas
from app.modules.projects.models import ProjectModule, ProjectProfile
from app.modules.projects.profile_presets import PRESETS, preset_modules
from app.modules.projects.profile_scoring import (
    assign_ordinals,
    build_project_modules,
)


@lru_cache(maxsize=1)
def discover_module_names() -> tuple[str, ...]:
    """All real module folder ids (every ``app/modules/<id>/manifest.py``).

    Cached — the module set is fixed for a process lifetime. Falls back
    to the preset/always-on universe if the directory can't be read
    (defensive; should never happen in a normal deploy).
    """

    modules_dir = Path(__file__).resolve().parent.parent
    found: set[str] = set()
    try:
        for child in modules_dir.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            if (child / "manifest.py").exists():
                found.add(child.name)
    except OSError:
        pass
    if not found:
        # Defensive fallback — union every preset's modules.
        from app.modules.projects.profile_presets import ALWAYS_ON
        found = set(ALWAYS_ON)
        for p in PRESETS.values():
            found |= set(p["modules"])
    return tuple(sorted(found))


def list_presets() -> list[schemas.PresetRead]:
    out: list[schemas.PresetRead] = []
    for meta in PRESETS.values():
        mods = sorted(preset_modules(meta["id"]))
        out.append(
            schemas.PresetRead(
                id=meta["id"],
                icon=meta["icon"],
                label_key=meta["label_key"],
                label_en=meta["label_en"],
                blurb_en=meta["blurb_en"],
                modules=mods,
                module_count=len(mods),
            )
        )
    return out


def _to_module_read(row: ProjectModule) -> schemas.ProjectModuleRead:
    return schemas.ProjectModuleRead.model_validate(row)


def _to_profile_read(row: ProjectProfile) -> schemas.ProjectProfileRead:
    return schemas.ProjectProfileRead(
        project_id=row.project_id,
        preset=row.preset,
        activity=list(row.activity or []),
        phases=list(row.phases or []),
        role=row.role,
        size=row.size,
        region=row.region,
        language=row.language,
        extensions_enabled=list(row.extensions_enabled or []),
        focus_mode_enabled=row.focus_mode_enabled,
        setup_completion=dict(row.setup_completion or {}),
    )


async def _result(
    db: AsyncSession, project_id: uuid.UUID,
) -> schemas.ProjectProfileResult:
    prof = (
        await db.execute(
            select(ProjectProfile).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).scalar_one()
    mods = (
        await db.execute(
            select(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .order_by(ProjectModule.ordinal.is_(None), ProjectModule.ordinal)
        )
    ).scalars().all()
    enabled = [m for m in mods if m.enabled]
    return schemas.ProjectProfileResult(
        profile=_to_profile_read(prof),
        modules=[_to_module_read(m) for m in mods],
        enabled_count=len(enabled),
        must_count=len([m for m in mods if m.tier == "must"]),
    )


async def apply_profile(
    db: AsyncSession,
    project_id: uuid.UUID,
    spec: schemas.ProfileSpec,
    user_id: uuid.UUID | None,
) -> schemas.ProjectProfileResult:
    """Upsert the profile and replace the project's module assignments."""

    prof = (
        await db.execute(
            select(ProjectProfile).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if prof is None:
        prof = ProjectProfile(project_id=project_id, created_by=user_id)
        db.add(prof)
    prof.preset = spec.preset
    prof.activity = list(spec.activity)
    prof.phases = list(spec.phases)
    prof.role = spec.role
    prof.size = spec.size
    prof.region = spec.region
    prof.language = spec.language
    prof.extensions_enabled = list(spec.extensions_enabled)
    prof.focus_mode_enabled = spec.focus_mode_enabled
    prof.setup_completion = dict(spec.setup_completion)
    await db.flush()

    assignments = build_project_modules(
        all_modules=list(discover_module_names()),
        preset=spec.preset,
        activities=list(spec.activity),
        phases=list(spec.phases),
        role=spec.role or "",
        size=spec.size or "",
        region=spec.region or "",
    )

    # Manual overrides (doc §2.5 / wizard "uncheck a module") applied
    # AFTER scoring so the user always wins.
    by_name = {a.module_name: a for a in assignments}
    for mod, on in (spec.manual_overrides or {}).items():
        a = by_name.get(mod)
        if a is None:
            continue
        object.__setattr__(a, "enabled", bool(on))
        object.__setattr__(a, "source", "manual")
        object.__setattr__(
            a, "why", "Manually enabled" if on else "Manually disabled",
        )

    ordinals = assign_ordinals(assignments)

    # Replace the project's module rows wholesale — simplest correct
    # semantics; the table is tiny (≤88 rows/project).
    await db.execute(
        delete(ProjectModule).where(ProjectModule.project_id == project_id)
    )
    now = datetime.now(UTC)
    for a in assignments:
        db.add(
            ProjectModule(
                project_id=project_id,
                module_name=a.module_name,
                enabled=a.enabled,
                tier=a.tier,
                score=a.score,
                phase=a.phase,
                source=a.source,
                ordinal=ordinals.get(a.module_name),
                why=a.why,
                updated_at=now,
            )
        )
    await db.flush()
    return await _result(db, project_id)


async def get_profile(
    db: AsyncSession, project_id: uuid.UUID,
) -> schemas.ProjectProfileResult | None:
    prof = (
        await db.execute(
            select(ProjectProfile.id).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).first()
    if prof is None:
        return None
    return await _result(db, project_id)


async def recompute(
    db: AsyncSession, project_id: uuid.UUID,
) -> schemas.ProjectProfileResult:
    """Re-run scoring with the stored profile (after a module is added
    to the platform, or weights are recalibrated)."""

    prof = (
        await db.execute(
            select(ProjectProfile).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if prof is None:
        raise LookupError(f"No profile for project {project_id}")
    spec = schemas.ProfileSpec(
        preset=prof.preset,
        activity=list(prof.activity or []),
        phases=list(prof.phases or []),
        role=prof.role,
        size=prof.size,
        region=prof.region,
        language=prof.language,
        extensions_enabled=list(prof.extensions_enabled or []),
        focus_mode_enabled=prof.focus_mode_enabled,
        setup_completion=dict(prof.setup_completion or {}),
    )
    return await apply_profile(db, project_id, spec, prof.created_by)


async def set_focus_mode(
    db: AsyncSession, project_id: uuid.UUID, enabled: bool,
) -> schemas.ProjectProfileResult:
    prof = (
        await db.execute(
            select(ProjectProfile).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if prof is None:
        # Retrofit a default profile first so the toggle has something
        # to write to.
        await ensure_default_profile(db, project_id)
        prof = (
            await db.execute(
                select(ProjectProfile).where(
                    ProjectProfile.project_id == project_id,
                )
            )
        ).scalar_one()
    prof.focus_mode_enabled = enabled
    await db.flush()
    return await _result(db, project_id)


async def ensure_default_profile(
    db: AsyncSession, project_id: uuid.UUID,
) -> schemas.ProjectProfileResult:
    """Retrofit path (doc §3.6 / user: "applying the wizard to an old
    project"). Existing projects get a ``custom`` profile with
    ``focus_mode_enabled=False`` so the sidebar keeps showing every
    module ungreyed until the owner deliberately runs the wizard. Every
    module is recorded enabled/must so nothing disappears.
    """

    existing = (
        await db.execute(
            select(ProjectProfile.id).where(
                ProjectProfile.project_id == project_id,
            )
        )
    ).first()
    if existing is not None:
        return await _result(db, project_id)

    prof = ProjectProfile(
        project_id=project_id,
        preset="custom",
        focus_mode_enabled=False,  # legacy view until they opt in
    )
    db.add(prof)
    await db.flush()
    now = datetime.now(UTC)
    for i, name in enumerate(discover_module_names(), start=1):
        db.add(
            ProjectModule(
                project_id=project_id,
                module_name=name,
                enabled=True,
                tier="must",
                score=100,
                phase="setup",
                source="core",
                ordinal=i,
                why="Retrofit default — all modules (focus mode off)",
                updated_at=now,
            )
        )
    await db.flush()
    return await _result(db, project_id)
