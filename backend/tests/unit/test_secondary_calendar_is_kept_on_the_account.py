# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The secondary calendar choice is a nullable account column with a closed value set."""

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


def test_column_is_nullable_without_default() -> None:
    col = User.__table__.c.secondary_calendar
    assert col.nullable is True
    assert col.default is None
    assert col.server_default is None


@pytest.mark.parametrize("value", ["none", "hijri"])
def test_allowed_values_pass(value: str) -> None:
    assert UserPreferencesUpdate(secondary_calendar=value).secondary_calendar == value


@pytest.mark.parametrize("value", ["gregorian", "HIJRI", "islamic-umalqura", ""])
def test_other_values_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        UserPreferencesUpdate(secondary_calendar=value)


@pytest.mark.asyncio
async def test_choice_is_written_as_a_column() -> None:
    service, repo = _service(SimpleNamespace(secondary_calendar=None))
    await service.update_preferences(uuid.uuid4(), UserPreferencesUpdate(secondary_calendar="hijri"))
    assert repo.writes == [{"secondary_calendar": "hijri"}]


@pytest.mark.asyncio
async def test_explicit_null_clears_the_choice() -> None:
    service, repo = _service(SimpleNamespace(secondary_calendar="hijri"))
    await service.update_preferences(uuid.uuid4(), UserPreferencesUpdate(secondary_calendar=None))
    assert repo.writes == [{"secondary_calendar": None}]


@pytest.mark.asyncio
async def test_omitted_field_is_not_touched() -> None:
    service, repo = _service(SimpleNamespace(secondary_calendar="hijri"))
    await service.update_preferences(uuid.uuid4(), UserPreferencesUpdate(date_format="auto"))
    assert repo.writes == [{"date_format": "auto"}]


def test_response_defaults_to_never_chose() -> None:
    resp = UserPreferencesResponse.model_validate(
        {
            "timezone": "UTC",
            "measurement_system": "metric",
            "paper_size": "A4",
            "number_format": "auto",
            "date_format": "auto",
            "currency_code": "",
        }
    )
    assert resp.secondary_calendar is None
