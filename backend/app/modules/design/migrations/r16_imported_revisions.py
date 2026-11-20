"""R16: wrap existing converter-imported BIM models as revisions (contract §9a). Data only, no schema change.

    python -m app.modules.design.migrations.r16_imported_revisions up   [--project <uuid>]
    python -m app.modules.design.migrations.r16_imported_revisions down [--project <uuid>]

``up`` is idempotent (wrapped models are no candidates). ``down`` removes wrappers from the chain tip down while
they are still awaiting a decision and nothing builds on them; decided wrappers (a person's act) are kept.
Both print a report: what was done, what was skipped and why.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .. import imported
from ..models import DesignRevision

_RACE = "a parallel write conflicted; run up again"


async def _projects(session, only: uuid.UUID | None) -> list[uuid.UUID]:
    from app.modules.bim_hub.models import BIMModel

    if only is not None:
        return [only]
    return list((await session.execute(select(BIMModel.project_id).distinct())).scalars().all())


async def upgrade(session_factory, project_id: uuid.UUID | None = None) -> dict[str, Any]:
    from app.modules.projects.models import Project

    from ..imported_api import held_lock

    report: dict[str, Any] = {"wrapped": [], "skipped": []}
    async with session_factory() as s:
        projects = await _projects(s, project_id)
    for pid in projects:
        async with session_factory() as s:
            project = await s.get(Project, pid)
            models = await imported.candidates(s, pid)
            if not models or project is None:
                continue
            if await held_lock(s, pid) is not None:
                report["skipped"] += [{"bim_model_id": str(m.id), "reason": "project lock held"} for m in models]
                continue
            done: list[dict[str, Any]] = []
            for m in models:
                mid = str(m.id)
                try:
                    async with s.begin_nested():
                        rev = await imported.wrap(s, m, user_id=m.created_by or project.owner_id)
                    done.append({"bim_model_id": mid, "revision_id": str(rev.id), "number": rev.number})
                except imported.NotWrappable as exc:
                    report["skipped"].append({"bim_model_id": mid, "reason": str(exc)})
                except IntegrityError:  # a parallel upload or wrap took the number or the model
                    report["skipped"].append({"bim_model_id": mid, "reason": _RACE})
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                report["skipped"] += [{"bim_model_id": d["bim_model_id"], "reason": _RACE} for d in done]
                continue
            report["wrapped"] += done
    return report


async def downgrade(session_factory, project_id: uuid.UUID | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"unwrapped": [], "kept": []}
    async with session_factory() as s:
        q = select(DesignRevision.project_id).where(DesignRevision.source_kind == "imported").distinct()
        projects = [project_id] if project_id else list((await s.execute(q)).scalars().all())
    for pid in projects:
        async with session_factory() as s:
            rows = (
                (
                    await s.execute(
                        select(DesignRevision)
                        .where(DesignRevision.project_id == pid)
                        .order_by(DesignRevision.number.desc())
                    )
                )
                .scalars()
                .all()
            )
            removed: set[uuid.UUID] = set()
            for r in rows:  # newest first: a wrapper's children are handled before it
                if not imported.is_import_record(r.manifest):
                    continue
                if r.status != "shared":
                    report["kept"].append({"revision_id": str(r.id), "reason": f"decided ({r.status})"})
                elif any(x.parent_id == r.id and x.id not in removed for x in rows):
                    report["kept"].append({"revision_id": str(r.id), "reason": "another revision builds on it"})
                else:
                    report["unwrapped"].append({"revision_id": str(r.id), "bim_model_id": str(r.bim_model_id)})
                    removed.add(r.id)
                    await imported.unwrap(s, r)
            await s.commit()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("direction", choices=("up", "down"))
    ap.add_argument("--project", type=uuid.UUID)
    args = ap.parse_args()

    async def run() -> dict[str, Any]:
        from app.database import async_session_factory

        step = upgrade if args.direction == "up" else downgrade
        return await step(async_session_factory, args.project)

    print(json.dumps(asyncio.run(run()), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
