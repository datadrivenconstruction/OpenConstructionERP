# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo ships one customised invoice template in German and English."""

from __future__ import annotations

import pytest

from app.modules.doc_templates.seed import seed_doc_templates_demo
from tests.modules.doc_templates.test_doc_templates_api import _app, _http, _user, db_session  # noqa: F401


@pytest.mark.asyncio
async def test_demo_invoice_template_is_published_in_german_and_english_once(db_session) -> None:
    assert await seed_doc_templates_demo(db_session) == 2
    await db_session.commit()
    assert await seed_doc_templates_demo(db_session) == 0
    user = await _user(db_session)
    async with _http(_app(db_session, str(user.id))) as c:
        de = (await c.get("/dt/finance.invoice", params={"locale": "de"})).json()
        en = (await c.get("/dt/finance.invoice", params={"locale": "en"})).json()
    assert "2 % Skonto" in de["published_text"]["terms"]
    assert "2 % cash discount" in en["published_text"]["terms"]
    assert de["options"]["font"] == "serif"
    assert [v["number"] for v in de["versions"]] == [1]
    assert de["has_draft"] is False
