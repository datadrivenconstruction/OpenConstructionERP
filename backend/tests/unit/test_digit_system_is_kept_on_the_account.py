# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The digit shapes a reader chose survive a sign-in on another device.

The choice is kept in the account's metadata JSON rather than a column, so it
needed no migration; these tests pin that it is written there without
disturbing the other keys the metadata already carries, and read back.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.users.models import User
from app.modules.users.schemas import UserPreferencesResponse, UserPreferencesUpdate
from app.modules.users.service import UserService


class _Repo:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.writes: list[dict[str, Any]] = []

    async def get_by_id(self, _user_id: uuid.UUID) -> Any:
        return self.user

    async def update_fields(self, _user_id: uuid.UUID, **fields: Any) -> None:
        self.writes.append(fields)
        for name, value in fields.items():
            setattr(self.user, name, value)


def _service(user: Any) -> tuple[UserService, _Repo]:
    service = UserService.__new__(UserService)
    repo = _Repo(user)
    service.user_repo = repo  # type: ignore[assignment]
    return service, repo


@pytest.mark.asyncio
async def test_the_choice_is_merged_into_the_metadata() -> None:
    user = SimpleNamespace(metadata_={"module_preferences": {"boq": True}})
    service, repo = _service(user)
    await service.update_preferences(uuid.uuid4(), UserPreferencesUpdate(digit_system="latn"))
    assert repo.writes == [{"metadata_": {"module_preferences": {"boq": True}, "digit_system": "latn"}}]


@pytest.mark.asyncio
async def test_other_preferences_do_not_touch_the_metadata() -> None:
    user = SimpleNamespace(metadata_={"x": 1})
    service, repo = _service(user)
    await service.update_preferences(uuid.uuid4(), UserPreferencesUpdate(number_format="ar-EG"))
    assert repo.writes == [{"number_format": "ar-EG"}]


def test_an_unknown_digit_system_is_refused() -> None:
    with pytest.raises(ValidationError):
        UserPreferencesUpdate(digit_system="roman")


def test_the_account_reads_it_back_and_defaults_to_auto() -> None:
    user = User(email="a@b.c", hashed_password="x", metadata_={"digit_system": "arab"})
    assert user.digit_system == "arab"
    assert User(email="a@b.c", hashed_password="x", metadata_={}).digit_system == "auto"
    fields = {
        "timezone": "Africa/Cairo",
        "measurement_system": "metric",
        "paper_size": "auto",
        "number_format": "auto",
        "date_format": "auto",
        "currency_code": "EGP",
        "digit_system": user.digit_system,
    }
    assert UserPreferencesResponse.model_validate(SimpleNamespace(**fields)).digit_system == "arab"
