# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠HTTP tests for the FX router.

The router is mounted on a bare app with the test session injected, so these
exercise the real request/response contract - status codes, serialisation of
Decimals as strings, and the error translations - without standing up the whole
application. The ECB fetch is stubbed at the transport method, and ``/status/``
is the only endpoint that would otherwise probe the network.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fx.service import FxService
from tests.modules.fx.conftest import (
    API_PREFIX,
    ECB_XML,
    build_app,
    http_client,
    make_policy,
    make_project,
    make_rate_set,
    make_user,
)

MARCH_1 = date(2026, 3, 1)
MARCH_15 = date(2026, 3, 15)
CALLER = uuid.uuid4()


@pytest_asyncio.fixture
async def app(session: AsyncSession):  # noqa: ANN201 - FastAPI app, typed by the factory
    """The FX router mounted with the test session and an admin caller.

    The caller is persisted because the policy routes check project access,
    and that check reads the admin role from the user row, not the token.
    """
    await make_user(session, role="admin", user_id=CALLER)
    return build_app(session, caller_id=CALLER)


# ── Reads ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rates_endpoint_serialises_decimals_as_strings(session: AsyncSession, app) -> None:  # noqa: ANN001
    """Money and rates cross the wire as strings so no JS float ever rounds them."""
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})

    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/rates/")

    assert response.status_code == 200
    body = response.json()
    assert body["base"] == "EUR"
    assert body["rates"]["TRY"] == "38.700000"
    assert body["origin"] == "rate_set"
    assert body["as_of"] == "2026-03-01"


@pytest.mark.asyncio
async def test_rates_endpoint_answers_for_a_past_date(session: AsyncSession, app) -> None:  # noqa: ANN001
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3"})

    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/rates/", params={"on_date": "2026-03-10"})

    assert response.status_code == 200
    assert response.json()["rates"]["TRY"] == "38.700000"


@pytest.mark.asyncio
async def test_rates_endpoint_rejects_an_unquoted_base(session: AsyncSession, app) -> None:  # noqa: ANN001
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})

    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/rates/", params={"base": "ZWL"})

    assert response.status_code == 422
    assert "ZWL" in response.json()["detail"]


@pytest.mark.asyncio
async def test_status_endpoint_reports_the_register(
    session: AsyncSession, app, monkeypatch: pytest.MonkeyPatch
) -> None:  # noqa: ANN001
    async def _fake(_self: FxService) -> bytes:
        return ECB_XML.encode("utf-8")

    monkeypatch.setattr(FxService, "_fetch_ecb_xml", _fake)
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})

    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/status/")

    body = response.json()
    assert response.status_code == 200
    assert body["rate_sets"] == 1
    assert body["network_ok"] is True


# ── Conversion ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_convert_endpoint_returns_the_figure_and_its_provenance(
    session: AsyncSession,
    app,  # noqa: ANN001
) -> None:
    rate_set = await make_rate_set(
        session, rate_date=MARCH_1, rates={"TRY": "38.7"}, source="manual", source_ref="contract cl. 14.15"
    )

    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/convert/",
            json={"amount": "1000.00", "from_currency": "EUR", "to_currency": "TRY"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["converted"] == "38700.00"
    assert body["rate"] == "38.700000"
    assert body["source"] == "manual"
    assert body["source_ref"] == "contract cl. 14.15"
    assert body["rate_set_id"] == str(rate_set.id)


@pytest.mark.asyncio
async def test_convert_endpoint_404s_on_a_rate_set_that_is_not_there(
    session: AsyncSession,
    app,  # noqa: ANN001
) -> None:
    """A named set that cannot be resolved must never fall back to today's rates."""
    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/convert/",
            json={
                "amount": "1000",
                "from_currency": "EUR",
                "to_currency": "TRY",
                "rate_set_id": str(uuid.uuid4()),
            },
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revalue_endpoint_splits_the_movement(session: AsyncSession, app) -> None:  # noqa: ANN001
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"})
    await make_rate_set(session, rate_date=MARCH_15, rates={"TRY": "44.3", "USD": "1.09"})

    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/revalue/",
            json={
                "reporting_currency": "USD",
                "baseline_date": "2026-03-01",
                "current_date": "2026-03-15",
                "lines": [
                    {"ref": "SC-01", "currency": "TRY", "baseline_amount": "1000000", "current_amount": "1000000"},
                    {"ref": "SC-02", "currency": "USD", "baseline_amount": "500000", "current_amount": "600000"},
                ],
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["priced_lines"] == 2
    assert body["lines"][0]["scope_delta"] == "0.00"
    assert body["lines"][1]["scope_delta"] == "100000.00"
    total = Decimal(body["total_delta"])
    parts = Decimal(body["scope_delta"]) + Decimal(body["rate_delta"]) + Decimal(body["joint_delta"])
    assert parts == total


# ── Rate sets ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recording_a_manual_rate_set_round_trips(session: AsyncSession, app) -> None:  # noqa: ANN001
    """The rate a project is actually held to is often a contract's, not a feed's."""
    async with http_client(app) as client:
        created = await client.post(
            f"{API_PREFIX}/rate-sets/",
            json={
                "base_currency": "EUR",
                "rate_date": "2026-03-01",
                "rates": {"TRY": "38.7", "USD": "1.07"},
                "source": "manual",
                "source_ref": "contract cl. 14.15",
                "lock": True,
            },
        )
        assert created.status_code == 201
        set_id = created.json()["id"]

        fetched = await client.get(f"{API_PREFIX}/rate-sets/{set_id}/")
        listed = await client.get(f"{API_PREFIX}/rate-sets/", params={"source": "manual"})

    assert fetched.status_code == 200
    assert fetched.json()["is_locked"] is True
    assert fetched.json()["rates"]["TRY"] == "38.700000"
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["quote_count"] == 2


@pytest.mark.asyncio
async def test_rewriting_a_locked_set_is_a_conflict(session: AsyncSession, app) -> None:  # noqa: ANN001
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"}, source="manual", lock=True)

    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/rate-sets/",
            json={"rate_date": "2026-03-01", "rates": {"TRY": "99.0"}, "source": "manual"},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_non_positive_manual_rate_is_refused(session: AsyncSession, app) -> None:  # noqa: ANN001
    async with http_client(app) as client:
        response = await client.post(
            f"{API_PREFIX}/rate-sets/",
            json={"rate_date": "2026-03-01", "rates": {"TRY": "0"}},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_locking_then_deleting_a_set(session: AsyncSession, app) -> None:  # noqa: ANN001
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})

    async with http_client(app) as client:
        locked = await client.post(f"{API_PREFIX}/rate-sets/{rate_set.id}/lock/", json={"locked": True})
        blocked = await client.delete(f"{API_PREFIX}/rate-sets/{rate_set.id}/")
        await client.post(f"{API_PREFIX}/rate-sets/{rate_set.id}/lock/", json={"locked": False})
        removed = await client.delete(f"{API_PREFIX}/rate-sets/{rate_set.id}/")

    assert locked.json()["is_locked"] is True
    assert blocked.status_code == 409
    assert removed.status_code == 204


@pytest.mark.asyncio
async def test_an_unknown_rate_set_reads_as_404(session: AsyncSession, app) -> None:  # noqa: ANN001
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/rate-sets/{uuid.uuid4()}/")
    assert response.status_code == 404


# ── Policy ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_round_trip_and_validation(session: AsyncSession, app) -> None:  # noqa: ANN001
    rate_set = await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7", "USD": "1.07"}, lock=True)
    project_id = (await make_project(session)).id

    async with http_client(app) as client:
        saved = await client.put(
            f"{API_PREFIX}/policies/{project_id}/",
            json={
                "estimating_currency": "EUR",
                "procurement_currency": "TRY",
                "reporting_currency": "USD",
                "rate_mode": "pinned",
                "pinned_rate_set_id": str(rate_set.id),
            },
        )
        read = await client.get(f"{API_PREFIX}/policies/{project_id}/")
        report = await client.get(f"{API_PREFIX}/policies/{project_id}/validation/")

    assert saved.status_code == 200
    assert saved.json()["pinned_rate_set"]["is_locked"] is True
    assert read.json()["reporting_currency"] == "USD"
    assert report.status_code == 200
    assert report.json()["errors"] == []


@pytest.mark.asyncio
async def test_validation_endpoint_reports_a_currency_the_rates_cannot_price(
    session: AsyncSession,
    app,  # noqa: ANN001
) -> None:
    policy = await make_policy(session, reporting_currency="GBP")
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})

    async with http_client(app) as client:
        response = await client.get(
            f"{API_PREFIX}/policies/{policy.project_id}/validation/",
            params={"on_date": "2026-03-10"},
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "errors"
    assert [row["rule_id"] for row in body["errors"]] == ["fx.policy_currency_coverage"]


@pytest.mark.asyncio
async def test_a_project_without_a_policy_reads_as_404(session: AsyncSession, app) -> None:  # noqa: ANN001
    async with http_client(app) as client:
        response = await client.get(f"{API_PREFIX}/policies/{uuid.uuid4()}/")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_deleting_a_policy(session: AsyncSession, app) -> None:  # noqa: ANN001
    policy = await make_policy(session)

    async with http_client(app) as client:
        removed = await client.delete(f"{API_PREFIX}/policies/{policy.project_id}/")
        again = await client.delete(f"{API_PREFIX}/policies/{policy.project_id}/")

    assert removed.status_code == 204
    assert again.status_code == 404


# ── Permissions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_viewer_can_read_but_cannot_record_a_rate_set(session: AsyncSession) -> None:
    """Recording the rate a project is held to is a manager's act, not a reader's.

    The module's permissions are registered by the session fixture in conftest,
    the same way the application registers them from ``on_startup``.
    """
    viewer_app = build_app(session, caller_id=CALLER, role="viewer")
    await make_rate_set(session, rate_date=MARCH_1, rates={"TRY": "38.7"})

    async with http_client(viewer_app) as client:
        read = await client.get(f"{API_PREFIX}/rates/")
        write = await client.post(
            f"{API_PREFIX}/rate-sets/",
            json={"rate_date": "2026-03-01", "rates": {"TRY": "38.7"}},
        )
        refresh = await client.post(f"{API_PREFIX}/refresh/")

    assert read.status_code == 200
    assert write.status_code == 403
    assert refresh.status_code == 403
