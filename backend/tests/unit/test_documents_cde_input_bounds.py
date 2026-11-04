"""Input bounds on the revision upload form and the CDE storage key."""

import pytest
from pydantic import ValidationError

from app.modules.cde.schemas import RevisionCreate


@pytest.mark.parametrize(
    "key",
    ["../secret.pdf", "a/../../b.pdf", "/etc/passwd", "C:/x.pdf", "a\\..\\b.pdf", "a\x00b"],
)
def test_revision_storage_key_rejects_escaping_keys(key):
    with pytest.raises(ValidationError):
        RevisionCreate(file_name="a.pdf", storage_key=key)


def test_revision_storage_key_accepts_relative_key():
    rev = RevisionCreate(file_name="a.pdf", storage_key="cde/abc.pdf")
    assert rev.storage_key == "cde/abc.pdf"


def test_document_revision_form_caps_revision_code_at_column_width():
    from app.modules.documents.router import router

    route = next(r for r in router.routes if getattr(r, "path", "").endswith("/{document_id}/revisions/"))
    field = next(f for f in route.dependant.body_params if f.name == "revision_code")
    limits = [getattr(m, "max_length", None) for m in field.field_info.metadata]
    assert 20 in limits


@pytest.mark.asyncio
async def test_revision_refuses_storage_key_owned_by_another_project():
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import HTTPException

    from app.modules.cde.service import CDEService

    session = MagicMock()
    session.execute = AsyncMock(return_value=SimpleNamespace(first=lambda: (uuid.uuid4(),)))
    svc = CDEService(session)
    container = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), cde_state="wip", container_code="C1")
    svc.get_container = AsyncMock(return_value=container)
    svc.revision_repo.next_revision_number = AsyncMock(side_effect=AssertionError("must stop earlier"))
    data = RevisionCreate(file_name="a.pdf", storage_key="uploads/other/x.pdf")
    with pytest.raises(HTTPException) as exc:
        await svc.create_revision(container.id, data, user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 400


def test_transmittal_response_rejects_blank_text():
    from app.modules.transmittals.schemas import RespondRequest

    with pytest.raises(ValidationError):
        RespondRequest(response="   ")
