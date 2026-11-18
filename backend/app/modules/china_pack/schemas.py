# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas of the China pack's fee programme endpoints."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PCT_MAX = Decimal(100)


def _rates(value: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for code, raw in (value or {}).items():
        if raw is None or str(raw).strip() == "":
            continue
        try:
            rate = Decimal(str(raw).strip())
        except InvalidOperation as exc:
            raise ValueError(f"rate of {code} is not a number") from exc
        if not rate.is_finite() or rate < 0 or rate > _PCT_MAX:
            raise ValueError(f"rate of {code} must be between 0 and 100")
        out[str(code)[:40]] = str(rate)
    return out


class FeeSettings(BaseModel):
    """What a person states inside a provincial fee programme."""

    model_config = ConfigDict(extra="forbid")

    schedule_key: str | None = Field(default=None, max_length=60)
    rates: dict[str, str] = Field(default_factory=dict, description="Rate in percent per line code")
    options: dict[str, str] = Field(default_factory=dict, description="Zone, grade or class per option key")
    bases: dict[str, dict[str, str]] = Field(default_factory=dict, description="Own base per line code")
    labour_includes_social_insurance: bool = False
    apply_labour_factor: bool | None = None

    @field_validator("rates", mode="before")
    @classmethod
    def _check_rates(cls, value: Any) -> dict[str, str]:
        return _rates(value if isinstance(value, dict) else {})


class FeeCalcRequest(BaseModel):
    """A fee programme run without the database."""

    subdivision: str | None = Field(default=None, max_length=10)
    city: str | None = Field(default=None, max_length=100)
    tender_date: date | None = None
    contract_date: date | None = None
    tax_method: Literal["general", "simplified", "exempt"] = "general"
    components: dict[str, str] = Field(default_factory=dict)
    settings: FeeSettings = Field(default_factory=FeeSettings)
    markup_names: list[str] = Field(default_factory=list, max_length=200)
