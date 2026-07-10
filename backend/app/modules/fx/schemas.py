"""Currency / FX Pydantic schemas for request/response validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

# Money and rates are exchanged as strings on the wire so JSON's float bridge
# never silently rounds a precision-critical value (same convention as
# ``app.modules.costs.schemas.DecimalMoney``). Inputs accept any JSON number or
# numeric string; Pydantic v2 promotes them to ``Decimal``. Outputs serialise to
# strings so a 199.99 amount does not become 199.98999999 in a JS client.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]


# ── Convert ────────────────────────────────────────────────────────────────


class ConvertRequest(BaseModel):
    """Request body for ``POST /api/v1/fx/convert/``."""

    amount: Decimal = Field(..., description="Amount to convert. Accepts a JSON number or a numeric string.")
    from_currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 source currency (e.g. EUR).")
    to_currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 target currency (e.g. TRY).")
    mode: Literal["market", "ppp"] = Field(
        default="market",
        description="market = ECB reference rate; ppp = World Bank purchasing-power-parity.",
    )


class ConvertResponse(BaseModel):
    """Result of a currency conversion.

    On success ``converted`` and ``rate`` are populated and ``available`` is
    true. When the requested mode has no data (typically a missing PPP factor)
    the endpoint still returns 200 with ``available=false``, null ``converted`` /
    ``rate`` and a plain-language ``note`` - an unavailable mode is an honest
    state, not an error.
    """

    amount: DecimalMoney
    converted: DecimalMoney | None = Field(
        default=None,
        description="Converted amount; null when the requested mode is unavailable.",
    )
    rate: DecimalMoney | None = Field(
        default=None,
        description="Effective source-to-target rate applied; null when unavailable.",
    )
    from_currency: str
    to_currency: str
    mode: Literal["market", "ppp"]
    as_of: date | None = Field(
        default=None,
        description="Effective date of the market rate; null for PPP or bundled-seed rates.",
    )
    source: str = Field(default="", description="Origin of the figure: ecb | cache | seed | worldbank.")
    available: bool = Field(
        default=True,
        description="False when the requested mode has no data (e.g. a missing PPP factor).",
    )
    note: str = Field(default="", description="Human-readable explanation, especially when unavailable.")


# ── Rates ──────────────────────────────────────────────────────────────────


class FxRatesResponse(BaseModel):
    """Latest rate map for a base currency (units of each currency per 1 base)."""

    base: str = Field(..., description="Base currency the rates are quoted against.")
    as_of: date | None = Field(default=None, description="Effective date of the rates.")
    source: str = Field(default="", description="Origin of the rates: ecb | cache | seed.")
    count: int = Field(..., ge=0, description="Number of quoted currencies.")
    rates: dict[str, DecimalMoney] = Field(
        default_factory=dict,
        description="Map of ISO 4217 currency code to units of that currency per 1 base.",
    )


# ── Status ─────────────────────────────────────────────────────────────────


class FxStatusResponse(BaseModel):
    """Health and freshness of the FX subsystem."""

    source: str = Field(..., description="Where the active rates come from: ecb | cache | seed.")
    rates_as_of: date | None = Field(default=None, description="Effective date of the active rates.")
    cached_currencies: int = Field(..., ge=0, description="Currencies currently held in the database cache.")
    currencies: list[str] = Field(
        default_factory=list,
        description="Currency codes available for conversion right now.",
    )
    ppp_countries: int = Field(default=0, ge=0, description="Countries with a cached PPP factor.")
    network_ok: bool = Field(..., description="Whether the ECB feed was reachable on the last probe.")


# ── Refresh ────────────────────────────────────────────────────────────────


class RefreshResponse(BaseModel):
    """Result of a manual refresh from the live ECB feed."""

    updated: int = Field(..., ge=0, description="Number of currency rows written to the cache.")
    source: str = Field(..., description="ecb when the live feed was used, seed on network fallback.")
    as_of: date | None = Field(default=None, description="Effective date of the rates written.")
    network_ok: bool = Field(..., description="Whether the ECB feed was reachable.")
    note: str = Field(default="", description="Human-readable summary of what happened.")
