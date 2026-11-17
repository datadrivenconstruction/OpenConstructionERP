# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Use cases of the payroll hours export: profiles, preview and immutable runs."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.active_markets import pack_active
from app.modules.field_time.payroll_export import (
    ExportProfile,
    HourLine,
    Row,
    check_run,
    plan_rows,
    render,
)
from app.modules.field_time.payroll_models import PayrollExportProfile, PayrollExportRun, PayrollExportRunLine
from app.modules.field_time.payroll_repository import PayrollRepository
from app.modules.field_time.payroll_schemas import (
    ExampleOut,
    IssueOut,
    PreviewResponse,
    PreviewRow,
    ProfileConfig,
    ProfileCreate,
)

logger = logging.getLogger(__name__)

MAX_PERIOD_DAYS = 400


@dataclass
class Plan:
    profile: ExportProfile
    rows: list[Row]
    issues: list[dict[str, Any]]
    overlapping: list[str]

    @property
    def blocked(self) -> bool:
        return any(i["severity"] == "error" for i in self.issues)


def run_label(number: int) -> str:
    return f"R{number}"


class PayrollService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PayrollRepository(session)

    # ── profiles ──────────────────────────────────────────────────────────

    async def list_profiles(self) -> list[PayrollExportProfile]:
        return await self.repo.list_profiles()

    async def get_profile(self, profile_id: uuid.UUID) -> PayrollExportProfile:
        row = await self.repo.get_profile(profile_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export profile not found")
        return row

    async def save_profile(self, data: ProfileCreate, profile_id: uuid.UUID | None = None) -> PayrollExportProfile:
        config = data.config.model_dump(mode="json")
        clash = await self.repo.get_profile_by_name(data.name)
        if clash is not None and clash.id != profile_id:
            raise HTTPException(status.HTTP_409_CONFLICT, f"A profile named '{data.name}' already exists")
        if profile_id is None:
            return await self.repo.add_profile(
                PayrollExportProfile(
                    name=data.name, legal_entity_id=data.legal_entity_id, is_sample=data.is_sample, config=config
                )
            )
        row = await self.get_profile(profile_id)
        row.name, row.legal_entity_id, row.is_sample, row.config = data.name, data.legal_entity_id, False, config
        await self.session.flush()
        return row

    async def delete_profile(self, profile_id: uuid.UUID) -> None:
        await self.repo.delete_profile(await self.get_profile(profile_id))

    @staticmethod
    def examples(markets: list[str]) -> list[ExampleOut]:
        """Example layouts from the active packs (column layouts only; pay codes stay the customer's)."""
        from app.core.regional_packs import pack_configs

        out: list[ExampleOut] = []
        for config in pack_configs():
            example = config.get("payroll_profile")
            if isinstance(example, dict) and pack_active(markets, config.get("countries") or ()):
                body = {k: v for k, v in example.items() if k not in ("label_key", "name")}
                out.append(
                    ExampleOut(
                        key=str(config.get("region_code", "pack")).lower(),
                        label_key=str(example["label_key"]),
                        name=str(example.get("name") or ""),
                        config=ProfileConfig.model_validate(body),
                    )
                )
        if not out:
            out.append(
                ExampleOut(
                    key="neutral",
                    label_key="field_time.payroll_export.example_neutral",
                    name="",
                    config=ProfileConfig(
                        columns=[
                            {"header": "Worker", "source": "worker_ref"},
                            {"header": "Date", "source": "date"},
                            {"header": "Project", "source": "project_code"},
                            {"header": "Cost code", "source": "cost_code"},
                            {"header": "Pay code", "source": "pay_code"},
                            {"header": "Hours", "source": "hours"},
                        ],
                        delimiter=",",
                        decimal=".",
                        date_format="YYYY-MM-DD",
                    ),
                )
            )
        return out

    # ── plan and runs ─────────────────────────────────────────────────────

    async def plan(
        self,
        profile_id: uuid.UUID,
        period_from: date,
        period_to: date,
        project_ids: set[uuid.UUID] | None,
    ) -> Plan:
        if period_to < period_from:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The period ends before it starts")
        if (period_to - period_from).days > MAX_PERIOD_DAYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The period is longer than 400 days")
        profile_row = await self.get_profile(profile_id)
        profile = ExportProfile.from_dict({**profile_row.config, "name": profile_row.name})
        baseline = await self.repo.exported_baseline()
        if project_ids is not None:
            allowed = {str(p) for p in project_ids}
            baseline = {k: v for k, v in baseline.items() if k[2] in allowed}
        earliest = min([period_from, *(k[1] for k in baseline)])
        lines, pending = await self.repo.labour_lines(earliest, period_to, project_ids)
        rows = plan_rows(lines, baseline, period_from, period_to, profile)
        in_period = [ln for ln in lines if period_from <= ln.work_date <= period_to]
        overlapping = [run_label(r.number) for r in await self.repo.overlapping(period_from, period_to)]
        issues = check_run(in_period, profile, unapproved_refs=pending, overlapping_runs=overlapping)
        return Plan(profile=profile, rows=rows, issues=issues, overlapping=overlapping)

    def preview(self, plan: Plan, sample_size: int = 20) -> PreviewResponse:
        profile = plan.profile
        file_lines = render(plan.rows[:3], profile).decode(profile.encoding, errors="replace").splitlines()
        return PreviewResponse(
            workers=len({r.key[0] for r in plan.rows}),
            rows=len(plan.rows),
            hours=sum((r.hours for r in plan.rows), Decimal("0")),
            corrections=sum(1 for r in plan.rows if r.correction),
            issues=[IssueOut(**i) for i in plan.issues],
            blocked=plan.blocked,
            overlapping_runs=plan.overlapping,
            sample=[
                PreviewRow(
                    worker_ref=r.worker_ref,
                    worker_name=r.worker_name,
                    date=r.key[1],
                    project_code=r.project_code,
                    cost_code=r.key[3],
                    hour_type=r.key[4],
                    pay_code=profile.pay_codes.get(r.key[4], ""),
                    hours=r.hours,
                    correction=r.correction,
                )
                for r in plan.rows[:sample_size]
            ],
            preview_lines=file_lines,
        )

    async def create_run(
        self,
        profile_id: uuid.UUID,
        period_from: date,
        period_to: date,
        project_ids: set[uuid.UUID] | None,
        user_id: uuid.UUID | None,
    ) -> PayrollExportRun:
        plan = await self.plan(profile_id, period_from, period_to, project_ids)
        if plan.blocked:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Fix the issues first",
                    "issues": [i for i in plan.issues if i["severity"] == "error"],
                },
            )
        if not plan.rows:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No approved hours to export in this period")
        profile_row = await self.get_profile(profile_id)
        content = render(plan.rows, plan.profile)
        number = await self.repo.next_number()
        run = PayrollExportRun(
            number=number,
            profile_id=profile_row.id,
            profile_name=profile_row.name,
            profile_snapshot=dict(profile_row.config),
            period_from=period_from,
            period_to=period_to,
            project_ids=sorted(str(p) for p in project_ids) if project_ids else [],
            row_count=len(plan.rows),
            correction_count=sum(1 for r in plan.rows if r.correction),
            worker_count=len({r.key[0] for r in plan.rows}),
            total_hours=sum((r.hours for r in plan.rows), Decimal("0")),
            filename=f"hours-{run_label(number)}-{period_from.isoformat()}-{period_to.isoformat()}.csv",
            sha256=hashlib.sha256(content).hexdigest(),
            content=content.decode(plan.profile.encoding, errors="replace"),
            created_by=user_id,
        )
        run_lines = [
            PayrollExportRunLine(
                run_id=run.id,
                resource_id=uuid.UUID(r.key[0]),
                work_date=r.key[1],
                project_id=uuid.UUID(r.key[2]),
                cost_code=r.key[3],
                hour_type=r.key[4],
                hours=r.hours,
                is_correction=r.correction,
            )
            for r in plan.rows
        ]
        return await self.repo.add_run(run, run_lines)

    async def page_runs(
        self, allowed: set[uuid.UUID] | None, offset: int, limit: int
    ) -> tuple[list[PayrollExportRun], int]:
        return await self.repo.page_runs(allowed, offset, limit)

    async def get_run(self, run_id: uuid.UUID) -> PayrollExportRun:
        run = await self.repo.get_run(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export run not found")
        return run

    async def run_project_ids(self, run_id: uuid.UUID) -> set[uuid.UUID]:
        return await self.repo.run_project_ids(run_id)

    async def run_file(self, run_id: uuid.UUID) -> tuple[PayrollExportRun, bytes]:
        run = await self.repo.get_run(run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export run not found")
        encoding = str((run.profile_snapshot or {}).get("encoding") or "utf-8")
        return run, run.content.encode(encoding, errors="replace")


__all__ = ["HourLine", "PayrollService", "Plan", "run_label"]
