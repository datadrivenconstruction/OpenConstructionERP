# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A tax rate marked for local confirmation, end to end against PostgreSQL.

Created pending, it resolves to nothing and is left out of the rates a form
offers. Confirmed with a name and a source, it resolves and the confirmation is
in the audit log. Moving its rate afterwards sends it back to pending.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.audit import AuditEntry
from app.modules.i18n_foundation.service import I18nFoundationService

pytestmark = pytest.mark.asyncio

COUNTRY = "CD"


def _row(**kw) -> dict:
    return {
        "country_code": COUNTRY,
        "tax_name": "TVA",
        "tax_code": "TVA",
        "rate_pct": "16",
        "tax_type": "vat",
        "combination": "national",
        "effective_from": "2020-01-01",
        "is_default": True,
        "metadata": {"local_confirmation": {"required": True, "status": "confirmed"}},
        **kw,
    }


async def test_pending_then_confirmed_then_pending_again(pg_session) -> None:
    service = I18nFoundationService(pg_session)
    row = await service.create_tax_config(_row())
    assert row.metadata_["local_confirmation"] == {"required": True, "status": "pending"}

    pending = await service.resolve_tax_rate(COUNTRY, None, "2026-10-08")
    assert pending.status == "awaiting_confirmation"
    assert pending.combined_rate_pct is None
    assert row.id not in {r.id for r in await service.get_active_taxes_for_country(COUNTRY)}

    user = str(uuid.uuid4())
    await service.confirm_tax_config(
        row.id, user_id=user, accountant_name="Client accountant", source_reference="https://dgi.gouv.cd/"
    )
    confirmed = await service.resolve_tax_rate(COUNTRY, None, "2026-10-08")
    assert confirmed.combined_rate_pct == "16"
    entries = (await pg_session.execute(select(AuditEntry).where(AuditEntry.entity_id == str(row.id)))).scalars().all()
    assert [e.action for e in entries] == ["confirm"]
    assert entries[0].details["source_reference"] == "https://dgi.gouv.cd/"

    # A metadata patch cannot forge or erase the confirmation.
    await service.update_tax_config(row.id, {"metadata": {"local_confirmation": {"status": "pending"}}})
    assert (await service.resolve_tax_rate(COUNTRY, None, "2026-10-08")).combined_rate_pct == "16"

    await service.update_tax_config(row.id, {"rate_pct": "18"})
    again = await service.resolve_tax_rate(COUNTRY, None, "2026-10-08")
    assert again.status == "awaiting_confirmation"


async def test_a_row_never_marked_cannot_be_confirmed(pg_session) -> None:
    service = I18nFoundationService(pg_session)
    row = await service.create_tax_config(_row(metadata={}))
    with pytest.raises(HTTPException) as exc:
        await service.confirm_tax_config(row.id, user_id=str(uuid.uuid4()), accountant_name="A", source_reference="B")
    assert exc.value.status_code == 409
