# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Link existing subcontractor contact persons to the contacts directory.

Each ``SubcontractorContact`` with an email and no ``contact_id`` is matched,
inside the tenant that owns its subcontractor (``Subcontractor.created_by``), to
the contact with the same email (case-insensitive), or gets a new
``natural_person`` contact tagged ``subcontractor``. Two existing contacts are
never merged. Rows without an email, or whose subcontractor has no owner, stay
unlinked. Safe to run again: linked rows are skipped.

Dry run by default; nothing is written without ``--apply``.

    python -m scripts.backfill_subcontractor_contact_links
    python -m scripts.backfill_subcontractor_contact_links --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402 - after the sys.path bootstrap above
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402


async def backfill(session: AsyncSession, *, apply: bool) -> dict[str, int]:
    """Link every unlinked contact person; returns counts. Flushes only when ``apply``."""
    from app.modules.contacts import bridge  # noqa: PLC0415
    from app.modules.contacts.models import Contact  # noqa: PLC0415
    from app.modules.subcontractors.models import Subcontractor, SubcontractorContact  # noqa: PLC0415

    counts = {"scanned": 0, "linked_existing": 0, "created": 0, "no_email": 0, "no_owner": 0}
    rows = (
        await session.execute(
            select(SubcontractorContact, Subcontractor.created_by)
            .join(Subcontractor, Subcontractor.id == SubcontractorContact.subcontractor_id)
            .where(SubcontractorContact.contact_id.is_(None))
            .order_by(SubcontractorContact.created_at)
        )
    ).all()
    # Within one run an email creates its contact once per tenant, also in a dry run.
    planned: set[tuple[str, str]] = set()
    for person, owner in rows:
        counts["scanned"] += 1
        email = (person.email or "").strip().lower()
        if not email:
            counts["no_email"] += 1
            continue
        if not owner:
            counts["no_owner"] += 1
            continue
        existing = await bridge.find_contact_by_email(session, email, tenant_id=owner)
        if existing is not None or (owner, email) in planned:
            counts["linked_existing"] += 1
        else:
            counts["created"] += 1
            planned.add((owner, email))
        if apply:
            contact: Contact | None = await bridge.ensure_contact_for_subcontractor_person(
                session, name=person.name, email=email, phone=person.phone, tenant_id=owner
            )
            person.contact_id = contact.id if contact is not None else None
    if apply:
        await session.flush()
    return counts


async def _run(apply: bool) -> int:
    from app.database import async_session_factory  # noqa: PLC0415

    async with async_session_factory() as session:
        counts = await backfill(session, apply=apply)
        if apply:
            await session.commit()
    mode = "applied" if apply else "dry run, nothing written"
    print(f"Subcontractor contact links ({mode}):")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_subcontractor_contact_links",
        description="Link subcontractor contact persons to the contacts directory. Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="write the links (default is a dry run)")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
