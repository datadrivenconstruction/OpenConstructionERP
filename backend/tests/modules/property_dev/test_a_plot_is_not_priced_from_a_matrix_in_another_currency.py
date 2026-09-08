"""A price matrix in one currency does not write a price onto a plot in another.

``_svc_bulk_recompute_dev_prices`` wrote ``Plot.computed_price`` from the
active PriceMatrix without reading a currency on either side. A EUR matrix
over a plot recorded in USD produced a number that lands under the plot's
USD stamp, beside a ``price_base`` that really is USD, with nothing on the
row or the wire saying the two are different money.

The recompute now refuses the run before its first write when any plot's
currency (its own stamp, else the development's, else the project's)
disagrees with the matrix's, and the 422 names both currencies and the
plots. The refusal is the shape the module already uses for the escrow
transaction whose currency disagrees with its account, and for the same
reason: a write that would mis-stamp money is refused rather than labelled,
because the label column the plot has is shared with ``price_base`` and
cannot be re-stamped from the matrix without relabelling that too.

The first half drives the pure helper and the service function over stub
repositories, so the refusal and the "nothing was written" invariant are
proven without a database. The second half goes through the API on the
conftest PostgreSQL, so what is asserted is the shipping route and the
status code a client actually receives.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.property_dev.service import (
    PropertyDevService,
    plot_currency_mismatches,
)

from .conftest import _register_user

# ── Stubs ───────────────────────────────────────────────────────────────


class _Plot:
    def __init__(self, number: str, currency: str = "", area: str = "100", computed: Decimal | None = None) -> None:
        self.id = uuid.uuid4()
        self.plot_number = number
        self.currency = currency
        self.area_m2 = Decimal(area)
        self.price_base = Decimal("0")
        self.computed_price = computed
        self.level_in_block = 1
        self.view_type = None
        self.orientation = None
        self.block_id = None
        self.metadata_ = {}


class _Matrix:
    def __init__(self, currency: str, name: str = "Spring") -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.currency = currency
        self.base_price_per_m2 = Decimal("5000")
        self.rules: list[dict[str, Any]] = []


class _Development:
    def __init__(self, currency: str = "") -> None:
        self.id = uuid.uuid4()
        self.project_id = uuid.uuid4()
        self.currency = currency


class _OneRowRepo:
    def __init__(self, row: Any) -> None:
        self._row = row

    async def get_by_id(self, _id: uuid.UUID) -> Any:
        return self._row


class _MatrixRepo(_OneRowRepo):
    async def find_active_for_dev_on_date(self, _dev_id: uuid.UUID, _on: Any) -> Any:
        return self._row


class _PlotRepo:
    def __init__(self, rows: list[_Plot]) -> None:
        self.rows = {p.id: p for p in rows}
        self.writes: list[tuple[uuid.UUID, dict[str, Any]]] = []

    async def list_for_development(self, _dev_id: uuid.UUID, **_kw: Any) -> tuple[list[_Plot], int]:
        return list(self.rows.values()), len(self.rows)

    async def update_fields(self, plot_id: uuid.UUID, **fields: Any) -> None:
        self.writes.append((plot_id, fields))
        for key, value in fields.items():
            setattr(self.rows[plot_id], key, value)


class _NoProjectSession:
    """The FX metadata loader catches every failure and answers None."""


def _service(dev: _Development, matrix: _Matrix, plots: list[_Plot]) -> PropertyDevService:
    svc = PropertyDevService.__new__(PropertyDevService)
    svc.session = _NoProjectSession()  # type: ignore[assignment]
    svc.developments = _OneRowRepo(dev)  # type: ignore[assignment]
    svc.price_matrices = _MatrixRepo(matrix)  # type: ignore[assignment]
    svc.plots = _PlotRepo(plots)  # type: ignore[assignment]
    return svc


# ── Pure helper ─────────────────────────────────────────────────────────


def test_a_usd_plot_is_named_against_a_eur_matrix() -> None:
    plots = [_Plot("S-01", "USD"), _Plot("S-02", "EUR")]
    assert plot_currency_mismatches(plots, "EUR") == [("S-01", "USD")]


def test_a_matching_pair_has_nothing_to_report() -> None:
    plots = [_Plot("S-01", "EUR"), _Plot("S-02", "eur")]
    assert plot_currency_mismatches(plots, "EUR") == []


def test_a_blank_plot_is_read_in_the_developments_currency() -> None:
    # The plot carries no stamp; its money is the development's. A USD
    # development under a EUR matrix is the same mismatch as a USD stamp.
    plots = [_Plot("S-01", "")]
    assert plot_currency_mismatches(plots, "EUR", fallback_currency="USD") == [("S-01", "USD")]
    assert plot_currency_mismatches(plots, "EUR", fallback_currency="EUR") == []


def test_a_blank_on_either_side_is_not_a_mismatch() -> None:
    # Two stated codes are compared; a blank is not a currency to disagree with.
    assert plot_currency_mismatches([_Plot("S-01", "")], "EUR") == []
    assert plot_currency_mismatches([_Plot("S-01", "USD")], "") == []


# ── Service over stubs ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_recompute_is_refused_and_nothing_is_written() -> None:
    dev = _Development(currency="EUR")
    usd_plot = _Plot("S-01", "USD")
    eur_plot = _Plot("S-02", "EUR")
    svc = _service(dev, _Matrix("EUR", name="Spring Launch"), [usd_plot, eur_plot])

    with pytest.raises(HTTPException) as excinfo:
        await svc.bulk_recompute_dev_prices(dev.id)  # type: ignore[attr-defined]

    assert excinfo.value.status_code == 422
    detail = str(excinfo.value.detail)
    assert "EUR" in detail and "USD" in detail, detail
    assert "S-01" in detail and "S-02" not in detail, detail
    assert "Spring Launch" in detail, detail
    # The EUR plot could have been priced; it was not, because a run that
    # prices half a development behind a 422 is as misleading as one that
    # prices it all behind a 200.
    assert svc.plots.writes == []  # type: ignore[attr-defined]
    assert usd_plot.computed_price is None and eur_plot.computed_price is None


@pytest.mark.asyncio
async def test_a_matching_pair_is_priced() -> None:
    dev = _Development(currency="EUR")
    plots = [_Plot("S-01", "EUR", area="100"), _Plot("S-02", "", area="80")]
    svc = _service(dev, _Matrix("EUR"), plots)

    result = await svc.bulk_recompute_dev_prices(dev.id)  # type: ignore[attr-defined]

    assert result["plots_updated"] == 2 and result["plots_unchanged"] == 0
    assert plots[0].computed_price == Decimal("500000.00")
    assert plots[1].computed_price == Decimal("400000.00")


@pytest.mark.asyncio
async def test_a_development_in_another_currency_refuses_for_its_blank_plots() -> None:
    # No plot carries a stamp, so every plot's money is the development's USD.
    dev = _Development(currency="USD")
    svc = _service(dev, _Matrix("EUR"), [_Plot("S-01", ""), _Plot("S-02", "")])

    with pytest.raises(HTTPException) as excinfo:
        await svc.bulk_recompute_dev_prices(dev.id)  # type: ignore[attr-defined]

    assert excinfo.value.status_code == 422
    assert "2 of 2 plots" in str(excinfo.value.detail), excinfo.value.detail


# ── The shipping route ──────────────────────────────────────────────────


async def _development(client, headers, *, project_currency: str, plot_currencies: list[str]) -> dict[str, Any]:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"PlotCcy-{uuid.uuid4().hex[:6]}", "currency": project_currency},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": proj.json()["id"],
            "code": f"DEV-CCY-{uuid.uuid4().hex[:6]}",
            "name": "Two Currencies",
            "total_plots": len(plot_currencies),
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["id"]
    plots: list[dict[str, Any]] = []
    for index, currency in enumerate(plot_currencies):
        plot = await client.post(
            "/api/v1/property-dev/plots/",
            json={
                "development_id": dev_id,
                "plot_number": f"C-{index + 1:02d}",
                "area_m2": 100,
                "price_base": 350_000,
                "currency": currency,
                "level_in_block": 2,
            },
            headers=headers,
        )
        assert plot.status_code == 201, plot.text
        plots.append(plot.json())
    return {"development_id": dev_id, "plots": plots}


async def _active_matrix(client, headers, dev_id: str, currency: str) -> str:
    matrix = await client.post(
        "/api/v1/property-dev/price-matrices/",
        json={
            "development_id": dev_id,
            "name": f"Matrix {currency}",
            "base_price_per_m2": "5000",
            "currency": currency,
            "effective_from": "2026-01-01",
            "rules": [],
            "status": "active",
        },
        headers=headers,
    )
    assert matrix.status_code == 201, matrix.text
    return matrix.json()["id"]


@pytest.mark.asyncio
async def test_the_route_refuses_a_eur_matrix_over_a_usd_plot(client) -> None:
    _, _, headers = await _register_user(client, role="admin")
    made = await _development(client, headers, project_currency="EUR", plot_currencies=["USD", "EUR"])
    matrix_id = await _active_matrix(client, headers, made["development_id"], "EUR")

    res = await client.post(f"/api/v1/property-dev/price-matrices/{matrix_id}/bulk-recompute", headers=headers)

    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert "EUR" in detail and "USD" in detail and "C-01" in detail, detail
    # Neither plot was written, the EUR one included.
    for plot in made["plots"]:
        after = await client.get(f"/api/v1/property-dev/plots/{plot['id']}", headers=headers)
        assert after.status_code == 200, after.text
        assert after.json()["computed_price"] is None, after.json()


@pytest.mark.asyncio
async def test_the_route_prices_a_matching_pair(client) -> None:
    _, _, headers = await _register_user(client, role="admin")
    made = await _development(client, headers, project_currency="EUR", plot_currencies=["EUR", "EUR"])
    matrix_id = await _active_matrix(client, headers, made["development_id"], "EUR")

    res = await client.post(f"/api/v1/property-dev/price-matrices/{matrix_id}/bulk-recompute", headers=headers)

    assert res.status_code == 200, res.text
    assert res.json()["plots_updated"] == 2, res.json()
    after = await client.get(f"/api/v1/property-dev/plots/{made['plots'][0]['id']}", headers=headers)
    assert Decimal(after.json()["computed_price"]) == Decimal("500000.00"), after.json()


@pytest.mark.asyncio
async def test_the_route_reads_a_blank_plot_in_its_projects_currency(client) -> None:
    # Plots carry no stamp and the development carries none; the project is
    # USD, so the plots' money is USD and a EUR matrix is refused.
    _, _, headers = await _register_user(client, role="admin")
    made = await _development(client, headers, project_currency="USD", plot_currencies=["", ""])
    matrix_id = await _active_matrix(client, headers, made["development_id"], "EUR")

    res = await client.post(f"/api/v1/property-dev/price-matrices/{matrix_id}/bulk-recompute", headers=headers)

    assert res.status_code == 422, res.text
    assert "USD" in res.json()["detail"], res.text
