# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill refuses a write in the language of the person who tried it.

Three refusals guard a locked bill: the full guard that hands the bill back,
the one-column guard used by the per-line writers, and the link refusal that
stops a new linked line from promoting an owner in a locked bill of the same
project. All three are the same message family, so they read from the same
bundle: English stays word for word what it was, and a German reader gets
German instead of an English sentence in the middle of a German screen.

The session is a stand-in, since what is under test is the wording and not the
query: each guard is fed the answer "locked" directly.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_locked_bill_refusals_speak_the_readers_language.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.i18n import load_translations, set_locale
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService

LOCKED_EN = "BOQ is locked and cannot be modified. Create a revision to make changes."


@pytest.fixture
def locale() -> Iterator[None]:
    # set_locale only accepts a language whose catalogue is loaded, and the
    # app loads the catalogues at startup, which a unit test never reaches.
    load_translations()
    yield
    set_locale("en")


def _service_with_locked_row() -> BOQService:
    session = MagicMock()
    result = MagicMock()
    result.first.return_value = (True,)
    session.execute = AsyncMock(return_value=result)
    return BOQService(session)


async def _refusal_of_the_full_guard() -> str:
    service = BOQService(MagicMock())
    service.get_boq = AsyncMock(return_value=SimpleNamespace(is_locked=True))  # type: ignore[method-assign]
    with pytest.raises(HTTPException) as exc:
        await service._ensure_not_locked(uuid.uuid4())
    assert exc.value.status_code == 409
    return exc.value.detail


async def _refusal_of_the_column_guard() -> str:
    with pytest.raises(HTTPException) as exc:
        await _service_with_locked_row()._ensure_boq_writable(uuid.uuid4())
    assert exc.value.status_code == 409
    return exc.value.detail


async def _refusal_of_the_link() -> str:
    locked_boq = uuid.uuid4()
    service = BOQService(MagicMock())
    service._locked_bills_among = AsyncMock(return_value={locked_boq: "Approved estimate"})  # type: ignore[method-assign]
    service.position_repo = SimpleNamespace(update_fields=AsyncMock())  # type: ignore[assignment]
    master = SimpleNamespace(id=uuid.uuid4(), ordinal="0040", link_group_id=None, link_role=None, boq_id=locked_boq)
    with pytest.raises(HTTPException) as exc:
        await service._create_reused_position(
            data=PositionCreate(boq_id=uuid.uuid4(), ordinal="0040", unit="m3", quantity=1, reference_code="0040"),
            master=master,  # type: ignore[arg-type]
            project_id=uuid.uuid4(),
            reference_code="0040",
            as_copy=False,
        )
    assert exc.value.status_code == 409
    service.position_repo.update_fields.assert_not_awaited()
    return exc.value.detail


@pytest.mark.asyncio
@pytest.mark.usefixtures("locale")
async def test_english_keeps_the_wording_every_client_already_reads() -> None:
    set_locale("en")

    assert await _refusal_of_the_full_guard() == LOCKED_EN
    assert await _refusal_of_the_column_guard() == LOCKED_EN
    assert await _refusal_of_the_link() == (
        "Code '0040' is defined by a line in the locked bill 'Approved estimate', and linking to it would "
        "change that bill. Unlock that bill first, or enter the line under a new code."
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("locale")
async def test_a_german_reader_is_refused_in_german() -> None:
    set_locale("de")

    full = await _refusal_of_the_full_guard()
    column = await _refusal_of_the_column_guard()
    link = await _refusal_of_the_link()

    assert full == column
    assert full.startswith("Das Leistungsverzeichnis ist gesperrt")
    assert link.startswith("Der Code '0040'")
    assert "'Approved estimate'" in link


@pytest.mark.asyncio
@pytest.mark.usefixtures("locale")
async def test_a_russian_reader_is_refused_in_russian() -> None:
    set_locale("ru")

    assert (await _refusal_of_the_column_guard()).startswith("Смета заблокирована")
    link = await _refusal_of_the_link()
    assert link.startswith("Код '0040'")
    assert "'Approved estimate'" in link
