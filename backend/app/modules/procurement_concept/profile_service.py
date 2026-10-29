# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-instance confirmation of procurement profile values.

The shipped profiles stay unconfirmed. A person of the company checks a value
on its source and confirms it here; the confirmation names the exact value
(path + hash), so a profile update that changes the figure, the source or the
window makes it unconfirmed again. Revoking deletes the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement_concept import profile as pr
from app.modules.procurement_concept.errors import ProcurementError, conflict, forbidden, not_found
from app.modules.procurement_concept.models import ProfileConfirmation


@lru_cache(maxsize=1)
def shipped_profiles() -> dict[str, pr.ProcurementProfile]:
    """The shipped profiles, parsed once per process (they are package data)."""
    return pr.load_shipped()


class ProfileConfirmationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def confirmed_pairs(self, tenant_id: str | None, jurisdictions: list[str]) -> set[tuple[str, str]]:
        if not tenant_id or not jurisdictions:
            return set()
        rows = await self.session.execute(
            select(ProfileConfirmation.path, ProfileConfirmation.value_hash).where(
                ProfileConfirmation.tenant_id == tenant_id, ProfileConfirmation.jurisdiction.in_(jurisdictions)
            )
        )
        return {(p, h) for p, h in rows.all()}

    async def resolve(self, tenant_id: str | None, code: str, day: date) -> pr.ResolvedProfile:
        profiles = shipped_profiles()
        if code not in profiles:
            raise not_found("profile_not_found")
        chain = pr.chain_of(code, profiles)
        return pr.resolve(code, profiles, day, await self.confirmed_pairs(tenant_id, chain))

    async def resolve_legacy(
        self, tenant_id: str | None, legacy_code: str | None, day: date
    ) -> pr.ResolvedProfile | None:
        """The resolved profile for a v1 jurisdiction code, or ``None`` when no profile claims it."""
        code = pr.profile_for_legacy(legacy_code, shipped_profiles())
        return None if code is None else await self.resolve(tenant_id, code, day)

    async def list_values(self, tenant_id: str | None, code: str, day: date) -> dict[str, Any]:
        code = pr.profile_for_legacy(code, shipped_profiles()) or code
        resolved = await self.resolve(tenant_id, code, day)
        rows = {}
        if tenant_id:
            q = await self.session.execute(
                select(ProfileConfirmation).where(
                    ProfileConfirmation.tenant_id == tenant_id, ProfileConfirmation.jurisdiction.in_(resolved.chain)
                )
            )
            rows = {(r.path, r.value_hash): r for r in q.scalars().all()}
        values = []
        for v in resolved.values.values():
            body = v.as_json()
            c = rows.get((v.path, v.value_hash))
            body["confirmation"] = None if c is None else _confirmation_out(c)
            values.append(body)
        values.sort(key=lambda b: b["path"])
        return {
            "jurisdiction": code,
            "chain": list(resolved.chain),
            "day": day.isoformat(),
            "profiles": sorted(shipped_profiles()),
            "values": values,
        }

    async def confirm(
        self, tenant_id: str | None, code: str, data: dict[str, Any], *, actor_id: uuid.UUID, day: date
    ) -> ProfileConfirmation:
        if not tenant_id:
            raise forbidden("no_tenant")
        code = pr.profile_for_legacy(code, shipped_profiles()) or code
        resolved = await self.resolve(tenant_id, code, day)
        v = resolved.values.get(data["path"])
        if v is None or v.value_hash != data["value_hash"]:
            # Only the value the person saw can be confirmed; a changed profile needs a fresh look.
            raise ProcurementError("profile_value_changed", 409)
        if v.status == pr.STATUS_STALE:
            raise conflict("profile_value_stale")
        row = ProfileConfirmation(
            tenant_id=tenant_id,
            jurisdiction=v.origin,
            path=v.path,
            value_hash=v.value_hash,
            confirmed_by=actor_id,
            confirmed_at=datetime.now(UTC),
            source_checked=data["source_checked"].strip(),
            note=(data.get("note") or "").strip(),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise conflict("profile_value_already_confirmed") from exc
        return row

    async def revoke(self, tenant_id: str | None, confirmation_id: uuid.UUID) -> None:
        if not tenant_id:
            raise forbidden("no_tenant")
        res = await self.session.execute(
            delete(ProfileConfirmation).where(
                ProfileConfirmation.id == confirmation_id, ProfileConfirmation.tenant_id == tenant_id
            )
        )
        if not res.rowcount:
            raise not_found("profile_confirmation_not_found")
        await self.session.flush()


def _confirmation_out(c: ProfileConfirmation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "confirmed_by": str(c.confirmed_by) if c.confirmed_by else None,
        "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
        "source_checked": c.source_checked,
        "note": c.note,
    }


def confirmation_out(c: ProfileConfirmation) -> dict[str, Any]:
    return {"path": c.path, "jurisdiction": c.jurisdiction, "value_hash": c.value_hash, **_confirmation_out(c)}
