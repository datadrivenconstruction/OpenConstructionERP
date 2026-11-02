# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule format profile: a declarative description of an owner's bid schedule file.

A profile says where the pay items sit in the owner's file (sheet, first row,
which column holds which role), how item numbers look, how the owner rounds,
how lump sums and alternates are marked and which cells must be filled back.
Profiles come from three places, in this order of precedence on equal score:
the platform (generic spreadsheet and CSV), packs (agency formats shipped as
JSON, see :func:`pack_profiles`) and users (saved from the mapping wizard).

XML schedules are GAEB and stay on the existing GAEB exchange path; the
profile for them only routes the user there.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

Role = Literal["item_no", "description", "unit", "quantity", "unit_price", "amount", "alternate_flag"]
ROLES: tuple[str, ...] = ("item_no", "description", "unit", "quantity", "unit_price", "amount", "alternate_flag")
FILL_ROLES: tuple[str, ...] = ("unit_price", "amount")

_COL_RE = re.compile(r"^[A-Z]{1,3}$")


class RoundingRules(BaseModel):
    """How the owner rounds a priced line."""

    model_config = ConfigDict(extra="forbid")

    unit_price_decimals: int = Field(default=2, ge=0, le=6)
    amount_decimals: int = Field(default=2, ge=0, le=6)
    # round_qty_x_price: amount = round(qty * rounded price); given: amount is typed, not derived.
    amount_mode: Literal["round_qty_x_price", "given"] = "round_qty_x_price"


class LumpSumRules(BaseModel):
    """How a lump sum item is recognised and priced."""

    model_config = ConfigDict(extra="forbid")

    unit_tokens: list[str] = Field(default_factory=lambda: ["ls", "lump sum", "lump", "psum", "lsum"])
    # amount_only: the price goes into the amount cell, the unit price cell stays as the owner left it.
    mode: Literal["amount_only", "price_and_amount"] = "amount_only"


class ScheduleProfile(BaseModel):
    """One owner format."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    name: str = Field(min_length=1, max_length=200)
    source: Literal["platform", "pack", "user"] = "user"
    file_type: Literal["xlsx", "csv", "xml"]
    sheet: str | None = Field(default=None, max_length=120)
    header_row: int | None = Field(default=None, ge=1)
    first_data_row: int | None = Field(default=None, ge=1)
    # Fixed columns (letters) win over header aliases.
    columns: dict[Role, str] = Field(default_factory=dict)
    header_aliases: dict[Role, list[str]] = Field(default_factory=dict)
    numbering_pattern: str | None = Field(default=None, max_length=200)
    alternate_tokens: list[str] = Field(default_factory=lambda: ["alt", "alternate", "option", "a"])
    alternates_required: bool = False
    total_markers: list[str] = Field(default_factory=lambda: ["total", "grand total", "sum"])
    rounding: RoundingRules = Field(default_factory=RoundingRules)
    lump_sum: LumpSumRules = Field(default_factory=LumpSumRules)
    fill_back: list[Literal["unit_price", "amount"]] = Field(default_factory=lambda: ["unit_price", "amount"])
    write_total: bool = True
    csv_delimiter: str = Field(default=",", min_length=1, max_length=1)
    csv_encoding: str = Field(default="utf-8-sig", max_length=20)
    handled_by: Literal["profile", "gaeb"] = "profile"

    @field_validator("columns")
    @classmethod
    def _letters(cls, value: dict[str, str]) -> dict[str, str]:
        out = {}
        for role, col in value.items():
            col = col.strip().upper()
            if not _COL_RE.match(col):
                raise ValueError(f"column for {role} must be a letter reference like 'C', got {col!r}")
            out[role] = col
        return out

    @field_validator("numbering_pattern")
    @classmethod
    def _regex(cls, value: str | None) -> str | None:
        if value:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"numbering_pattern is not a valid regular expression: {exc}") from exc
        return value

    @model_validator(mode="after")
    def _roles(self) -> ScheduleProfile:
        if self.handled_by == "gaeb":
            return self
        known = set(self.columns) | {r for r, a in self.header_aliases.items() if a}
        missing = [r for r in ("item_no", "description", "quantity") if r not in known]
        if missing:
            raise ValueError(f"profile must locate the columns: {', '.join(missing)}")
        if not set(self.fill_back) & known:
            raise ValueError("profile must locate at least one column it fills back (unit_price or amount)")
        if self.columns and self.first_data_row is None and self.header_row is None:
            raise ValueError("fixed columns need first_data_row or header_row")
        return self

    def data_start(self, header_row: int | None) -> int:
        if self.first_data_row:
            return self.first_data_row
        return (header_row or self.header_row or 0) + 1


def profile_json_schema() -> dict[str, Any]:
    """The JSON schema a pack or the wizard writes profiles against."""
    return ScheduleProfile.model_json_schema()


_BUILTIN_DIR = Path(__file__).parent / "profiles"


def platform_profiles() -> list[ScheduleProfile]:
    """The neutral profiles shipped with the platform."""
    out = []
    for path in sorted(_BUILTIN_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append(ScheduleProfile.model_validate({**data, "source": "platform"}))
    return out


#: Manifest metadata key a pack uses to list its profile files (paths inside the pack package).
PACK_METADATA_KEY = "owner_schedule_profiles"


def pack_profiles() -> list[ScheduleProfile]:
    """Profiles shipped by installed packs.

    A pack lists JSON files in ``metadata["owner_schedule_profiles"]``; each is
    validated and a broken one is skipped with a warning, never fatal.
    """
    try:
        from app.core.partner_pack.discovery import discover_packs, read_pack_file
    except Exception:  # noqa: BLE001 - packs are optional
        return []
    out: list[ScheduleProfile] = []
    for pack in discover_packs():
        for rel in (pack.metadata or {}).get(PACK_METADATA_KEY) or []:
            raw = read_pack_file(pack.slug, str(rel))
            if raw is None:
                logger.warning("pack %s lists missing owner schedule profile %s", pack.slug, rel)
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
                data["key"] = f"{pack.slug}.{data.get('key', '')}"
                out.append(ScheduleProfile.model_validate({**data, "source": "pack"}))
            except Exception:  # noqa: BLE001 - a broken pack file must not break imports
                logger.warning("pack %s owner schedule profile %s is invalid", pack.slug, rel, exc_info=True)
    return out
