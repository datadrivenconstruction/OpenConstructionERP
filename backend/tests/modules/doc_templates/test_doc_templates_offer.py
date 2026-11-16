# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The offer keeps its generator; the firm's published wording becomes its company text."""

from __future__ import annotations

import pytest

from app.modules.offers import pack as pack_mod
from app.modules.offers.models import OfferTextBlock
from app.modules.offers.service import OfferService
from app.modules.projects.models import Project
from tests.modules.doc_templates.test_doc_templates_api import _app, _http, _publish, _user, db_session  # noqa: F401

OFFER = "offers.offer"


async def _project(session, owner_id) -> Project:
    project = Project(name="Haus B", owner_id=owner_id, locale="de")
    session.add(project)
    await session.commit()
    return project


@pytest.mark.asyncio
async def test_published_offer_wording_becomes_the_company_text(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    async with _http(_app(db_session, str(user.id))) as c:
        state = await _publish(
            c, OFFER, "de", {"intro": "Gern bieten wir Ihnen für {{offer.project_name}} an.", "terms": ""}
        )
    texts = await OfferService(db_session)._pick_texts(project.id, pack_mod.pack_for("DE"), "de")
    assert texts["intro"]["body"] == "Gern bieten wir Ihnen für {project_name} an."
    assert texts["intro"]["source"] == "company"
    assert texts["intro"]["template_version_id"] == state["versions"][0]["id"]
    assert texts["payment_terms"]["body"] == pack_mod.default_text(pack_mod.pack_for("DE"), "payment_terms", "de")
    assert "template_version_id" not in texts["payment_terms"]


@pytest.mark.asyncio
async def test_a_project_text_still_wins_over_the_template(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    db_session.add(
        OfferTextBlock(scope="project", project_id=project.id, kind="intro", language="de", body="Projekttext")
    )
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        await _publish(c, OFFER, "de", {"intro": "Vorlagentext"})
    texts = await OfferService(db_session)._pick_texts(project.id, pack_mod.pack_for("DE"), "de")
    assert texts["intro"]["body"] == "Projekttext" and texts["intro"]["source"] == "project"


@pytest.mark.asyncio
async def test_without_a_template_the_offer_is_unchanged(db_session) -> None:
    user = await _user(db_session)
    project = await _project(db_session, user.id)
    texts = await OfferService(db_session)._pick_texts(project.id, pack_mod.pack_for("DE"), "de")
    assert texts["intro"]["body"] == pack_mod.default_text(pack_mod.pack_for("DE"), "intro", "de")
    assert all("template_version_id" not in t for t in texts.values())
