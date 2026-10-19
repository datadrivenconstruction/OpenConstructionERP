"""Retention billed on a claim is announced as released when that claim is paid."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event
from app.modules.contracts import service as contracts_service
from app.modules.contracts.service import ContractsService
from app.modules.notifications import _wave5_cross_module_subscribers as wave5


class _Releases:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    async def billed_on_claims(self, claim_ids: list[uuid.UUID]) -> list[Any]:
        return self.rows


def _service(rows: list[Any]) -> ContractsService:
    svc = ContractsService.__new__(ContractsService)
    svc.session = object()  # type: ignore[assignment]
    svc.release_repo = _Releases(rows)  # type: ignore[assignment]

    async def _get_contract(_id: uuid.UUID) -> Any:
        return SimpleNamespace(id=_id)

    async def _ledger(_contract: Any) -> tuple[Decimal, Decimal]:
        return Decimal("1000"), Decimal("400")

    svc.get_contract = _get_contract  # type: ignore[method-assign]
    svc._retention_ledger = _ledger  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_paying_a_claim_announces_each_release_billed_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        contracts_service, "publish_after_commit", lambda _s, name, data, **_kw: seen.append((name, data))
    )
    contract_id, claim_id = uuid.uuid4(), uuid.uuid4()
    release = SimpleNamespace(id=uuid.uuid4(), event="practical_completion", amount=Decimal("250.00"))
    claim = SimpleNamespace(id=claim_id, contract_id=contract_id)

    await _service([release])._announce_retention_released(claim, "u1")  # type: ignore[arg-type]

    assert [n for n, _ in seen] == ["contracts.retention.released"]
    data = seen[0][1]
    assert data["contract_id"] == str(contract_id)
    assert data["amount_released"] == "250.00"
    assert data["remaining"] == "600"
    assert data["event"] == "practical_completion"


@pytest.mark.asyncio
async def test_a_claim_with_no_release_announces_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(contracts_service, "publish_after_commit", lambda _s, name, *_a, **_kw: seen.append(name))

    await _service([])._announce_retention_released(SimpleNamespace(id=uuid.uuid4(), contract_id=uuid.uuid4()), None)  # type: ignore[arg-type]

    assert seen == []


@pytest.mark.asyncio
async def test_the_release_reaches_the_project_owner_as_a_notification(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid.uuid4()
    contract = SimpleNamespace(id=uuid.uuid4(), code="C-7", created_by=owner)
    created: list[dict[str, Any]] = []

    class _Repo:
        def __init__(self, _session: Any) -> None: ...

        async def get_by_id(self, _id: uuid.UUID) -> Any:
            return contract

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    class _Notifications:
        def __init__(self, _session: Any) -> None: ...

        async def create(self, **kw: Any) -> None:
            created.append(kw)

    async def _ok() -> bool:
        return True

    monkeypatch.setattr(wave5, "_can_open_isolated_session", _ok)
    monkeypatch.setattr(wave5, "async_session_factory", lambda: _Session())
    monkeypatch.setattr(wave5, "NotificationService", _Notifications)
    monkeypatch.setattr("app.modules.contracts.repository.ContractRepository", _Repo)

    await wave5._on_retention_released(
        Event(
            name="contracts.retention.released",
            data={"contract_id": str(contract.id), "amount_released": "250.00", "remaining": "600"},
        )
    )

    assert len(created) == 1
    assert created[0]["user_id"] == str(owner)
    assert created[0]["body_context"]["amount_released"] == "250.00"
    assert created[0]["title_key"] == "notifications.contracts.retention_released.title"
