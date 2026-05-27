"""‌⁠‍Deterministic seed data for the contracts module.

Generates 10 contracts spanning all primary types:
    * 3 lump-sum
    * 2 GMP
    * 1 cost-plus
    * 2 T&M
    * 1 unit-price
    * 1 design-build

Each contract gets 5-15 SoV lines, roughly 4 progress claims, and 2 of
them are closed with a FinalAccount. All decisions are seeded from a
fixed random.Random(seed=42) so output is reproducible.
"""

from __future__ import annotations

import logging
import random
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import (
    Contract,
    ContractLine,
    ContractTypeConfiguration,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    RetentionSchedule,
)

logger = logging.getLogger(__name__)


_TYPE_CONFIG_CATALOG: list[dict[str, object]] = [
    {
        "contract_type": "lump_sum",
        "display_name": "Lump-Sum",
        "allowed_fields": ["total_value", "retention_percent"],
        "default_fee_structure": {},
    },
    {
        "contract_type": "gmp",
        "display_name": "Guaranteed Maximum Price",
        "allowed_fields": ["gmp_cap", "target_cost", "gainshare_split_pct"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 4},
    },
    {
        "contract_type": "cost_plus",
        "display_name": "Cost-Plus",
        "allowed_fields": ["fee_percent", "max_fee"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 8},
    },
    {
        "contract_type": "tm",
        "display_name": "Time & Materials",
        "allowed_fields": ["tm_nte_cap", "labor_rates", "material_markup"],
        "default_fee_structure": {"fee_type": "percent_of_cost", "fee_percent": 5},
    },
    {
        "contract_type": "unit_price",
        "display_name": "Unit Price",
        "allowed_fields": ["measurement_method", "qty_variance_threshold"],
        "default_fee_structure": {},
    },
    {
        "contract_type": "design_build",
        "display_name": "Design-Build",
        "allowed_fields": ["design_phase_fee", "construction_phase_fee"],
        "default_fee_structure": {"fee_type": "fixed", "fee_fixed_amount": 0},
    },
    {
        "contract_type": "combination",
        "display_name": "Combination / Hybrid",
        "allowed_fields": ["component_breakdown"],
        "default_fee_structure": {},
    },
]


_TYPE_DISTRIBUTION: list[str] = [
    "lump_sum",
    "lump_sum",
    "lump_sum",
    "gmp",
    "gmp",
    "cost_plus",
    "tm",
    "tm",
    "unit_price",
    "design_build",
]


async def seed_type_configurations(session: AsyncSession) -> int:
    """‌⁠‍Insert ContractTypeConfiguration catalog rows if missing."""
    from sqlalchemy import select

    existing = (await session.execute(select(ContractTypeConfiguration.contract_type))).scalars().all()
    inserted = 0
    for cfg in _TYPE_CONFIG_CATALOG:
        if cfg["contract_type"] in existing:
            continue
        row = ContractTypeConfiguration(
            contract_type=cfg["contract_type"],  # type: ignore[arg-type]
            display_name=cfg["display_name"],  # type: ignore[arg-type]
            allowed_fields=cfg["allowed_fields"],
            default_fee_structure=cfg["default_fee_structure"],
            schema_version="1.0",
        )
        session.add(row)
        inserted += 1
    if inserted:
        await session.flush()
    return inserted


async def seed_contracts_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """‌⁠‍Generate 10 demo contracts across all primary types.

    Args:
        session: Open async DB session (the caller commits).
        project_ids: List of existing project UUIDs to distribute contracts to
            (round-robin). Empty list returns zero counts.

    Returns:
        Dict with counts: contracts, lines, claims, final_accounts,
        type_configs, fee_structures, gainshare_configs.
    """
    if not project_ids:
        logger.info("seed_contracts_demo: no project_ids → skipping")
        return {
            "contracts": 0,
            "lines": 0,
            "claims": 0,
            "final_accounts": 0,
            "type_configs": 0,
            "fee_structures": 0,
            "gainshare_configs": 0,
        }

    rng = random.Random(42)
    type_configs = await seed_type_configurations(session)

    contracts_count = 0
    lines_count = 0
    claims_count = 0
    final_account_count = 0
    fee_count = 0
    gainshare_count = 0

    for idx, c_type in enumerate(_TYPE_DISTRIBUTION):
        project_id = project_ids[idx % len(project_ids)]
        code = f"CT-{idx + 1:03d}-{c_type.upper()[:3]}"
        terms: dict[str, object] = {}
        if c_type == "gmp":
            terms = {
                "gmp_cap": str(Decimal("1000000") + idx * 100000),
                "target_cost": str(Decimal("900000") + idx * 100000),
                "gainshare_split_pct": "50",
            }
        elif c_type == "cost_plus":
            terms = {"fee_percent": "7.5"}
        elif c_type == "tm":
            terms = {"tm_nte_cap": str(Decimal("250000") + idx * 25000)}

        total_value = Decimal("100000") * (idx + 5)
        contract = Contract(
            code=code,
            title=f"Demo {c_type} contract #{idx + 1}",
            contract_type=c_type,
            counterparty_type="subcontractor" if idx % 2 else "client",
            counterparty_id=uuid.uuid4(),
            project_id=project_id,
            total_value=total_value,
            currency="EUR",
            retention_percent=Decimal("5"),
            retention_release_event="practical_completion",
            status="active",
            terms=terms,
        )
        session.add(contract)
        await session.flush()
        contracts_count += 1

        # SoV lines (5-15 per contract)
        line_count = rng.randint(5, 15)
        for li in range(line_count):
            qty = Decimal(str(rng.randint(1, 500)))
            rate = Decimal(str(rng.randint(50, 5000)))
            session.add(
                ContractLine(
                    contract_id=contract.id,
                    code=f"{idx + 1:02d}.{li + 1:03d}",
                    description=f"Demo line {li + 1} for {c_type}",
                    line_type=rng.choice(
                        ("work", "material", "labor", "fee", "contingency"),
                    ),
                    unit=rng.choice(("m", "m2", "m3", "kg", "pcs", "lsum")),
                    quantity=qty,
                    unit_rate=rate,
                    total_value=qty * rate,
                    order_index=li,
                )
            )
            lines_count += 1

        # FeeStructure for cost_plus / tm / design_build
        if c_type in ("cost_plus", "tm", "design_build"):
            session.add(
                FeeStructure(
                    contract_id=contract.id,
                    fee_type="percent_of_cost",
                    fee_percent=Decimal("7.5") if c_type == "cost_plus" else Decimal("5"),
                    fee_fixed_amount=None,
                    max_fee=None,
                    sliding_scale=[],
                )
            )
            fee_count += 1

        # GainshareConfiguration for GMP
        if c_type == "gmp":
            session.add(
                GainshareConfiguration(
                    contract_id=contract.id,
                    target_cost=Decimal(terms.get("target_cost") or 0),  # type: ignore[arg-type]
                    gmp_cap=Decimal(terms.get("gmp_cap") or 0),  # type: ignore[arg-type]
                    savings_split_owner_pct=Decimal("50"),
                    savings_split_contractor_pct=Decimal("50"),
                    overrun_responsibility="contractor",
                )
            )
            gainshare_count += 1

        # RetentionSchedule
        session.add(
            RetentionSchedule(
                contract_id=contract.id,
                accrual_rule={"per_claim_percent": 5},
                release_rule={"on_event": "practical_completion"},
                notes="Standard 5% retention",
            )
        )

        # LDClause
        session.add(
            LDClause(
                contract_id=contract.id,
                per_day_amount=Decimal("500"),
                currency="EUR",
                max_amount=Decimal("50000"),
                enforcement_status="active",
            )
        )

        # 4 progress claims
        statuses = ("paid", "approved", "submitted", "draft")
        for ci, st in enumerate(statuses):
            gross = total_value * Decimal(str(0.1 * (ci + 1)))
            retention = gross * Decimal("0.05")
            session.add(
                ProgressClaim(
                    contract_id=contract.id,
                    claim_number=f"PC-{ci + 1:04d}",
                    period_start=f"2026-0{ci + 1}-01",
                    period_end=f"2026-0{ci + 1}-28",
                    claim_date=f"2026-0{ci + 1}-28",
                    gross_amount=gross,
                    retention_amount=retention,
                    prior_claims_total=gross * Decimal(str(ci)),
                    net_due=gross - retention,
                    status=st,
                    currency="EUR",
                )
            )
            claims_count += 1

        # Close two of the contracts with a FinalAccount
        if idx in (0, 5):
            paid_amount = total_value * Decimal("0.95")
            session.add(
                FinalAccount(
                    contract_id=contract.id,
                    final_contract_value=total_value,
                    total_paid=paid_amount,
                    retention_held=total_value * Decimal("0.05"),
                    retention_released=Decimal("0"),
                    final_balance=total_value - paid_amount,
                    sign_off_date="2026-12-31",
                    status="closed",
                    notes="Closed via demo seed",
                )
            )
            final_account_count += 1

    await session.flush()
    logger.info(
        "seed_contracts_demo: %d contracts, %d lines, %d claims, %d final_accounts, %d type_configs",
        contracts_count,
        lines_count,
        claims_count,
        final_account_count,
        type_configs,
    )
    return {
        "contracts": contracts_count,
        "lines": lines_count,
        "claims": claims_count,
        "final_accounts": final_account_count,
        "type_configs": type_configs,
        "fee_structures": fee_count,
        "gainshare_configs": gainshare_count,
    }
