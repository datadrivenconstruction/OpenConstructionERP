"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``POST /options/{option_id}/attach-model/``.

The heavy CAD upload and conversion belongs to the BIM hub; this route only
pairs an option with an already-converted model, or records a document that
still has to be converted. The failure paths matter as much as the success one:
the request must name exactly one source, and neither source may come from
another tenant's project.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel
from app.modules.design_options.models import DesignOption
from app.modules.documents.models import Document
from tests.modules.design_options.conftest import (
    API_PREFIX,
    build_app,
    http_client,
    make_option,
    make_project,
    make_set,
    make_user,
)


async def _make_model(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    element_count: int = 42,
    model_format: str = "ifc",
) -> BIMModel:
    model = BIMModel(
        project_id=project_id,
        name=f"Model {uuid.uuid4().hex[:6]}",
        model_format=model_format,
        element_count=element_count,
        status="ready",
    )
    session.add(model)
    await session.flush()
    return model


async def _make_document(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    metadata: dict | None = None,
) -> Document:
    doc = Document(
        project_id=project_id,
        name=f"plan-{uuid.uuid4().hex[:6]}.dwg",
        file_path="/tmp/plan.dwg",
        file_size=1024,
        metadata_=metadata or {},
    )
    session.add(doc)
    await session.flush()
    return doc


async def _reload(session: AsyncSession, option_id: uuid.UUID) -> DesignOption:
    """Read the option back from the database, not from the identity map.

    ``update_option_fields`` is a bulk UPDATE whose ``synchronize_session``
    also patches the in-memory instance, and a plain ``select`` hands that same
    instance back. Without expunging first, the assertion cannot tell a row
    that was written from one that was merely synchronised.
    """
    session.expunge_all()
    return (await session.execute(select(DesignOption).where(DesignOption.id == option_id))).scalar_one()


# ── Success paths ────────────────────────────────────────────────────────────


async def test_attaching_a_model_moves_the_option_to_model_attached(session: AsyncSession) -> None:
    """A converted model is linked and its headline facts are snapshotted."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    model = await _make_model(session, project.id, element_count=310, model_format="rvt")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bim_model_id"] == str(model.id)
    assert body["status"] == "model_attached"
    assert body["error"] == ""
    stored = await _reload(session, option.id)
    assert stored.metadata_["attached_model_format"] == "rvt"
    assert stored.metadata_["attached_element_count"] == 310


async def test_attaching_a_model_clears_a_previously_recorded_document(session: AsyncSession) -> None:
    """Switching source from a document to a model drops the stale document."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    doc = await _make_document(session, project.id)
    option = await make_option(session, option_set, name="Steel", source_document_id=doc.id, status="converting")
    model = await _make_model(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )

    assert res.status_code == 200, res.text
    assert res.json()["source_document_id"] is None


async def test_attaching_an_unconverted_document_marks_the_option_converting(session: AsyncSession) -> None:
    """A document with no converted model leaves the option awaiting conversion."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    doc = await _make_document(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"source_document_id": str(doc.id)},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source_document_id"] == str(doc.id)
    assert body["status"] == "converting"
    assert body["bim_model_id"] is None


async def test_attaching_a_document_adopts_the_model_the_bim_hub_linked(session: AsyncSession) -> None:
    """A document the BIM hub already converted hands its model to the option."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    model = await _make_model(session, project.id)
    doc = await _make_document(
        session,
        project.id,
        metadata={"source_module": "bim_hub", "source_id": str(model.id)},
    )
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"source_document_id": str(doc.id)},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bim_model_id"] == str(model.id)
    assert body["source_document_id"] == str(doc.id)
    assert body["status"] == "model_attached"


async def test_attaching_an_unconverted_document_drops_the_stale_model(session: AsyncSession) -> None:
    """Re-sourcing an option from a document must not leave the old model on it.

    The model branch clears ``source_document_id`` explicitly, so the document
    branch has to be symmetric. Left in place, the stale model still satisfies
    ``generate``, which only checks that ``bim_model_id`` is set, so an option
    that claims to be converting would be priced from the previous design.
    """
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    model = await _make_model(session, project.id)
    option = await make_option(session, option_set, name="Steel", bim_model_id=model.id, status="model_attached")
    doc = await _make_document(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"source_document_id": str(doc.id)},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "converting"
    assert body["bim_model_id"] is None


# ── Bad input ────────────────────────────────────────────────────────────────


async def test_attaching_neither_source_returns_400(session: AsyncSession) -> None:
    """An empty request names no source at all."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(f"{API_PREFIX}/options/{option.id}/attach-model/", json={})

    assert res.status_code == 400, res.text
    assert "exactly one" in res.json()["detail"]


async def test_attaching_both_sources_returns_400(session: AsyncSession) -> None:
    """Two sources are as ambiguous as none, and are refused the same way."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    model = await _make_model(session, project.id)
    doc = await _make_document(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id), "source_document_id": str(doc.id)},
        )

    assert res.status_code == 400, res.text
    stored = await _reload(session, option.id)
    assert stored.bim_model_id is None
    assert stored.source_document_id is None


# ── Cross-project guards ─────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
async def test_attaching_a_model_from_another_project_returns_404(session: AsyncSession) -> None:
    """An option id must not become an oracle for foreign model ids."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    foreign_model = await _make_model(session, other_project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(foreign_model.id)},
        )

    assert res.status_code == 404, res.text
    assert (await _reload(session, option.id)).bim_model_id is None


@pytest.mark.tenant_isolation
async def test_attaching_a_document_from_another_project_returns_404(session: AsyncSession) -> None:
    """The same cross-project guard applies to documents."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    other_project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    foreign_doc = await _make_document(session, other_project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"source_document_id": str(foreign_doc.id)},
        )

    assert res.status_code == 404, res.text
    assert (await _reload(session, option.id)).source_document_id is None


async def test_attaching_a_missing_model_returns_404(session: AsyncSession) -> None:
    """An id that resolves to nothing is refused like a foreign one."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(uuid.uuid4())},
        )

    assert res.status_code == 404, res.text


async def test_attach_model_on_an_unknown_option_returns_404(session: AsyncSession) -> None:
    """The option is resolved before the request body is looked at."""
    user = await make_user(session)
    project = await make_project(session, user.id)
    model = await _make_model(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=user.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{uuid.uuid4()}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )

    assert res.status_code == 404, res.text


@pytest.mark.tenant_isolation
async def test_attach_model_on_another_users_option_returns_404(session: AsyncSession) -> None:
    """The route is gated on the option's project like every other route."""
    victim = await make_user(session)
    attacker = await make_user(session)
    project = await make_project(session, victim.id)
    option_set = await make_set(session, project.id)
    option = await make_option(session, option_set, name="Steel")
    model = await _make_model(session, project.id)
    await session.commit()

    app = build_app(session, caller_id=attacker.id)
    async with http_client(app) as client:
        res = await client.post(
            f"{API_PREFIX}/options/{option.id}/attach-model/",
            json={"bim_model_id": str(model.id)},
        )

    assert res.status_code == 404, res.text
    assert (await _reload(session, option.id)).bim_model_id is None
