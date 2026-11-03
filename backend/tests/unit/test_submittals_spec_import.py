"""Spec import: confirm is idempotent, dedups against the register, and the permission exists."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.permissions import Role, permission_registry
from app.modules.submittals import spec_checks, spec_service
from app.modules.submittals.models import SpecImport, SpecProposal
from app.modules.submittals.permissions import register_submittals_permissions
from app.modules.submittals.spec_service import SpecImportService


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> list[Any]:
        return self._rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, imp: SpecImport, props: list[SpecProposal]) -> None:
        self.imp, self.props = imp, props

    async def get(self, _model: Any, _key: Any) -> SpecImport:
        return self.imp

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self.props)

    async def flush(self) -> None:
        return None


def _prop(imp: SpecImport, title: str, conf: float = 0.9) -> SpecProposal:
    return SpecProposal(
        id=uuid.uuid4(),
        import_id=imp.id,
        project_id=imp.project_id,
        spec_section="03 30 00",
        section_title="Concrete",
        kind="product_data",
        submittal_type="product_data",
        title=title,
        source_page=4,
        source_excerpt="",
        confidence=conf,
        decision="pending",
    )


@pytest.fixture
def setup(monkeypatch: pytest.MonkeyPatch) -> tuple[SpecImportService, SpecImport, list[SpecProposal], list[Any]]:
    imp = SpecImport(id=uuid.uuid4(), project_id=uuid.uuid4(), document_id=uuid.uuid4(), status="parsed")
    props = [_prop(imp, "Product data - Concrete"), _prop(imp, "Samples - Concrete")]
    created: list[Any] = []

    async def create_submittal(self: Any, data: Any, user_id: str | None = None) -> Any:
        created.append(data)
        return SimpleNamespace(id=uuid.uuid4(), submittal_number=f"SUB-{len(created):03d}")

    monkeypatch.setattr(spec_service.SubmittalService, "create_submittal", create_submittal)
    svc = SpecImportService(_Session(imp, props))  # type: ignore[arg-type]
    existing: set[tuple[str, str, str]] = set()

    async def keys(_project: uuid.UUID) -> set[tuple[str, str, str]]:
        return existing

    monkeypatch.setattr(svc, "_existing_keys", keys)
    return svc, imp, props, created


@pytest.mark.asyncio
async def test_confirm_creates_drafts_once(setup: Any) -> None:
    svc, imp, props, created = setup
    first = await svc.confirm(imp.id, [props[0].id], {}, [], "u1")
    again = await svc.confirm(imp.id, [props[0].id], {}, [], "u1")  # replay

    assert len(first["created"]) == 1 and len(created) == 1
    assert created[0].status == "draft" and created[0].metadata == {
        "spec_import_id": str(imp.id),
        "source_page": 4,
    }
    assert again["created"] == [] and again["already_created"] == [str(props[0].id)]
    assert props[0].decision == "accepted" and props[0].submittal_id is not None


@pytest.mark.asyncio
async def test_confirm_skips_what_the_register_already_holds(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    svc, imp, props, created = setup

    async def keys(_project: uuid.UUID) -> set[tuple[str, str, str]]:
        return {("03 30 00", "product_data", "product data concrete")}

    monkeypatch.setattr(svc, "_existing_keys", keys)
    result = await svc.confirm(imp.id, [props[0].id, props[1].id], {}, [], "u1")
    assert result["skipped_duplicates"] == [str(props[0].id)]
    assert len(created) == 1 and created[0].title == "Samples - Concrete"


@pytest.mark.asyncio
async def test_edits_are_applied_and_marked(setup: Any) -> None:
    svc, imp, props, created = setup
    await svc.confirm(imp.id, [props[1].id], {str(props[1].id): {"title": "Samples - slab finish"}}, [], "u1")
    assert created[0].title == "Samples - slab finish" and props[1].decision == "edited"


@pytest.mark.asyncio
async def test_unknown_proposal_and_type_are_refused(setup: Any) -> None:
    svc, imp, props, _ = setup
    with pytest.raises(HTTPException) as exc:
        await svc.confirm(imp.id, [uuid.uuid4()], {}, [], "u1")
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await svc.confirm(imp.id, [props[0].id], {str(props[0].id): {"submittal_type": "nonsense"}}, [], "u1")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_import_is_confirmed_when_nothing_is_pending(setup: Any) -> None:
    svc, imp, props, _ = setup
    await svc.confirm(imp.id, [props[0].id], {}, [props[1].id], "u1")
    assert imp.status == "confirmed" and props[1].decision == "rejected"


def test_import_permission_is_registered_for_editors() -> None:
    register_submittals_permissions()
    assert permission_registry.get_min_role("submittals.import") == Role.EDITOR


def test_checks() -> None:
    assert spec_checks.check_spec_section_format({"spec_section": "03 30 00"}) == []
    assert spec_checks.check_spec_section_format({"spec_section": "LB 013"}) == []
    assert spec_checks.check_spec_section_format({"spec_section": "concrete"})
    assert spec_checks.check_duplicate_in_register({"title": "x", "duplicate": True})
    assert spec_checks.check_no_sections_found({"section_count": 0, "pages_done": 12})
    assert not spec_checks.check_no_sections_found({"section_count": 2, "pages_done": 12})
    assert spec_checks.check_required_type_missing({"spec_section": "03 30 00", "kinds": ["sample"]})
    assert not spec_checks.check_required_type_missing({"spec_section": "03 30 00", "kinds": ["mix_design"]})
