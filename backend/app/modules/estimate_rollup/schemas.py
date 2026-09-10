# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate-rollup response schemas.

Every money amount is emitted as a Decimal-as-string, matching the platform-wide
money convention (the BOQ totals, the allowances register and the preliminaries
roll-up all serialise money the same way); nothing here routes a total through a
float. The schemas render the pure
:class:`app.modules.estimate_rollup.composition.EstimateRollup` dataclass onto
the wire.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.estimate_rollup.composition import EstimateRollup


def _s(amount: Decimal) -> str:
    """Render a 2 dp Decimal money amount as a plain string (never scientific)."""
    return str(amount)


class RollupLineOut(BaseModel):
    """One component line of the composition, ready for a UI to render the sum."""

    key: str = Field(..., description="Stable machine key / i18n anchor for the label.")
    label: str = Field(..., description="Human-facing English default label.")
    amount: str = Field(..., description="The line's contribution (Decimal string).")


class PreliminariesOut(BaseModel):
    """The preliminaries contribution, split into fixed and time-related."""

    total: str = Field(..., description="Preliminaries grand total (Decimal string).")
    fixed_total: str = Field(..., description="One-off / fixed portion (Decimal string).")
    time_related_total: str = Field(..., description="Duration-priced portion (Decimal string).")
    item_count: int = Field(..., description="Number of preliminaries lines rolled up.")


class AllowancesOut(BaseModel):
    """The allowances contribution (remaining), with contingency called out."""

    total: str = Field(..., description="Remaining across every allowance type (Decimal string).")
    provisional_sum_total: str = Field(..., description="Remaining provisional sums (Decimal string).")
    pc_sum_total: str = Field(..., description="Remaining prime-cost sums (Decimal string).")
    contingency_total: str = Field(..., description="Remaining contingency (Decimal string).")
    allowance_count: int = Field(..., description="Total allowances across every currency and type.")
    unconverted_currencies: list[str] = Field(
        default_factory=list,
        description="Foreign currencies with no FX rate to the base (summed in own units; advisory).",
    )


class EstimateRollupResponse(BaseModel):
    """A project's composed estimate total and its line-item breakdown.

    ``estimate_total == boq_base + preliminaries.total + allowances.total`` and
    the ``lines`` sum exactly to ``estimate_total``, so a UI can render
    "BOQ base + Preliminaries + Contingency = Estimate total" directly.
    """

    project_id: str
    base_currency: str = Field(..., description="Currency every amount is expressed in ('' when unset).")
    boq_base: str = Field(..., description="Measured works: BOQ direct cost + markups (Decimal string).")
    preliminaries: PreliminariesOut
    allowances: AllowancesOut
    estimate_total: str = Field(..., description="The composed headline total (Decimal string).")
    lines: list[RollupLineOut] = Field(default_factory=list)

    @classmethod
    def from_rollup(cls, rollup: EstimateRollup, *, project_id: uuid.UUID) -> EstimateRollupResponse:
        """Render the pure :class:`EstimateRollup` onto the wire schema."""
        return cls(
            project_id=str(project_id),
            base_currency=rollup.base_currency,
            boq_base=_s(rollup.boq_base),
            preliminaries=PreliminariesOut(
                total=_s(rollup.preliminaries.total),
                fixed_total=_s(rollup.preliminaries.fixed_total),
                time_related_total=_s(rollup.preliminaries.time_related_total),
                item_count=rollup.preliminaries.item_count,
            ),
            allowances=AllowancesOut(
                total=_s(rollup.allowances.total),
                provisional_sum_total=_s(rollup.allowances.provisional_sum_total),
                pc_sum_total=_s(rollup.allowances.pc_sum_total),
                contingency_total=_s(rollup.allowances.contingency_total),
                allowance_count=rollup.allowances.allowance_count,
                unconverted_currencies=list(rollup.allowances.unconverted_currencies),
            ),
            estimate_total=_s(rollup.estimate_total),
            lines=[RollupLineOut(key=line.key, label=line.label, amount=_s(line.amount)) for line in rollup.lines],
        )
