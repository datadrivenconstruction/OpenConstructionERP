# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A manual forecast outlives the document it cites.

``oe_costmodel_forecast_override.document_id`` is a real foreign key to
``oe_documents_document`` declared ``ON DELETE SET NULL``. Deleting the cited
document through the documents service clears the link inside the delete
transaction, and the forecast keeps its amount, its reason and the reference
the person typed. Without the key the row would keep pointing at a document
that is gone.

PG lane only (``OE_TEST_DB=pg``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_deleting_the_cited_document_clears_the_link_and_keeps_the_reason(pg_session) -> None:
    from app.modules.costmodel.models import CostForecastOverride, CostLine
    from app.modules.documents.models import Document
    from app.modules.documents.service import DocumentService
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"forecast-{uuid.uuid4().hex[:8]}@site.example",
        hashed_password="x",
        full_name="Cost Manager",
        role="admin",
    )
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(id=uuid.uuid4(), name="Forecast evidence", owner_id=owner.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()

    line = CostLine(project_id=project.id, code="350", description="Finishes", estimate_amount="50000", currency="EUR")
    document = Document(project_id=project.id, name="Tiles quote.pdf", uploaded_by=str(owner.id))
    pg_session.add_all([line, document])
    await pg_session.flush()

    override = CostForecastOverride(
        project_id=project.id,
        cost_line_id=line.id,
        amount=Decimal("55000"),
        reason="Tiles quote above estimate",
        document_id=document.id,
        document_ref="Offer 2026-10-12",
        created_by=str(owner.id),
    )
    pg_session.add(override)
    await pg_session.flush()
    override_id = override.id

    await DocumentService(pg_session).delete_document(document.id, str(owner.id))
    await pg_session.flush()
    pg_session.expire_all()

    kept = (
        await pg_session.execute(select(CostForecastOverride).where(CostForecastOverride.id == override_id))
    ).scalar_one_or_none()
    assert kept is not None, "deleting a cited document must not delete the forecast"
    assert kept.document_id is None
    assert kept.reason == "Tiles quote above estimate"
    assert kept.document_ref == "Offer 2026-10-12"
    assert kept.amount == Decimal("55000")
    assert kept.closed_at is None
    assert await pg_session.get(Document, document.id) is None
