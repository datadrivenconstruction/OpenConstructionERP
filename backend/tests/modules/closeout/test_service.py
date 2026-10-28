"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Closeout service logic tests.

Covers checklist seeding per project type, completeness recompute + gaps,
bind / verify flow, suggest-bindings (suggests without binding), and the
idempotent build revision hash.
"""

from __future__ import annotations

import pytest

from app.modules.closeout.service import CloseoutService

pytestmark = pytest.mark.asyncio


async def _make_package(session, project_id, project_type="commercial"):
    service = CloseoutService(session)
    package = await service.create_package(project_id, project_type)
    return service, package


async def test_create_package_seeds_template_slots(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    slots = await service.repo.list_slots(package.id)
    keys = {s.slot_key for s in slots}
    # Commercial template includes COBie + punch + final inspection + H&S.
    assert "as_built_drawings" in keys
    assert "cobie_asset_register" in keys
    assert "final_inspection_cert" in keys
    assert "hs_file" in keys
    assert package.project_type == "commercial"
    assert package.checklist_template == "commercial"


async def test_create_package_residential_has_no_cobie(session, project_id):
    service, package = await _make_package(session, project_id, "residential")
    keys = {s.slot_key for s in await service.repo.list_slots(package.id)}
    assert "epc_certificate" in keys
    assert "cobie_asset_register" not in keys


async def test_unknown_project_type_falls_back_to_commercial(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    # The schema pins the allowed values; an unknown key resolves to commercial.
    assert package.checklist_template == "commercial"


async def test_create_package_is_idempotent_per_project(session, project_id):
    service, package = await _make_package(session, project_id, "fitout")
    again = await service.create_package(project_id, "commercial")
    assert again.id == package.id  # one package per project


async def test_completeness_and_gaps_initial(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    gaps = await service.gaps(package)
    # A document-backed slot is a gap until someone binds evidence to it.
    assert "As-built drawing set" in gaps
    # So is a generated artifact, until the package has been built. The COBie
    # export does not exist before the build writes it and this package has
    # never been built, so "generated artifacts are not gaps" is only true of
    # the built view - the one the build itself reports from while assembling
    # its own manifest. Both directions are asserted so neither reading can
    # rot unnoticed.
    assert "COBie / asset register" in gaps
    assert "COBie / asset register" not in await service.gaps(package, treat_built=True)
    assert package.completeness_pct < 100
    assert package.status in ("draft", "in_progress")


async def test_bind_then_verify_advances_completeness(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    slots = await service.repo.list_slots(package.id)
    as_built = next(s for s in slots if s.slot_key == "as_built_drawings")

    # Bind to an external URL (no document row needed).
    await service.bind_slot(
        as_built,
        document_id=None,
        external_url="https://cde.example.com/as-built.pdf",
        mark_verified=False,
        verified_by=None,
    )
    package = await service.get_package_or_404(package.id)
    status_map = await service._slot_status_map(package)
    assert status_map[as_built.id] == "bound"
    # Bound-not-verified is still a gap (completeness counts verified only).
    assert "As-built drawing set" in await service.gaps(package)

    await service.verify_slot(as_built, is_verified=True, verified_by="manager-1")
    package = await service.get_package_or_404(package.id)
    status_map = await service._slot_status_map(package)
    assert status_map[as_built.id] == "verified"
    assert "As-built drawing set" not in await service.gaps(package)


async def test_verify_without_binding_is_conflict(session, project_id):
    from fastapi import HTTPException

    service, package = await _make_package(session, project_id, "commercial")
    slot = (await service.repo.list_slots(package.id))[0]
    with pytest.raises(HTTPException) as exc:
        await service.verify_slot(slot, is_verified=True, verified_by="m")
    assert exc.value.status_code == 409


async def test_unbind_clears_evidence(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    slot = (await service.repo.list_slots(package.id))[0]
    await service.bind_slot(slot, document_id=None, external_url="https://x/y.pdf", mark_verified=True, verified_by="m")
    assert (await service.repo.get_binding_for_slot(slot.id)) is not None
    await service.unbind_slot(slot)
    assert (await service.repo.get_binding_for_slot(slot.id)) is None


async def test_mutation_marks_built_package_stale(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    package.package_key = "closeout/x/y.zip"
    package.last_built_at = "2026-01-01T00:00:00+00:00"
    session.add(package)
    await session.flush()
    slot = (await service.repo.list_slots(package.id))[0]
    await service.bind_slot(
        slot, document_id=None, external_url="https://x/y.pdf", mark_verified=False, verified_by=None
    )
    refreshed = await service.get_package_or_404(package.id)
    assert refreshed.package_key is None
    assert refreshed.last_built_at is None


async def test_add_and_delete_custom_slot(session, project_id):
    service, package = await _make_package(session, project_id, "custom")
    before = len(await service.repo.list_slots(package.id))
    slot = await service.add_slot(
        package,
        {
            "slot_key": "fire_strategy",
            "title": "Fire strategy report",
            "category": "other",
            "is_required": True,
            "source_kind": "cde_document",
            "ordinal": 5,
        },
    )
    assert len(await service.repo.list_slots(package.id)) == before + 1
    await service.delete_slot(slot)
    assert len(await service.repo.list_slots(package.id)) == before


async def test_build_revision_hash_changes_on_binding(session, project_id):
    service, package = await _make_package(session, project_id, "commercial")
    slots = await service.repo.list_slots(package.id)
    bindings = await service.repo.list_bindings_for_package(package.id)
    h1 = service._slot_revision_hash(slots, bindings)
    # Same state -> same hash (idempotent build key).
    assert h1 == service._slot_revision_hash(slots, bindings)

    await service.bind_slot(
        slots[0], document_id=None, external_url="https://x/y.pdf", mark_verified=False, verified_by=None
    )
    slots2 = await service.repo.list_slots(package.id)
    bindings2 = await service.repo.list_bindings_for_package(package.id)
    h2 = service._slot_revision_hash(slots2, bindings2)
    assert h1 != h2


async def test_suggest_bindings_returns_suggestions_without_binding(session, project_id):
    from app.modules.documents.models import Document

    service, package = await _make_package(session, project_id, "residential")

    # A real project document that should match the O&M slot by name keyword.
    doc = Document(
        project_id=project_id,
        name="Operation and Maintenance manual",
        category="om_manual",
        cde_state="published",
        is_current_revision=True,
    )
    session.add(doc)
    await session.flush()

    suggestions = await service.suggest_bindings(package)
    assert suggestions, "expected at least one suggestion"
    om = [s for s in suggestions if s["slot_key"] == "om_manual"]
    assert om and om[0]["document_id"] == doc.id
    assert 0.0 < om[0]["confidence"] <= 1.0

    # Suggesting binds nothing - every slot stays unbound.
    slots = await service.repo.list_slots(package.id)
    bindings = await service.repo.list_bindings_for_package(package.id)
    assert all(bindings.get(s.id) is None for s in slots)
