"""Seed 4D Schedule, 5D Budget, and Tendering data for demo projects.

Creates for Wohnanlage Berlin-Mitte and One Canary Square:
  - Schedule with activities per BOQ section (4D)
  - Budget lines per section (5D)
  - Cash flow periods (5D)
  - EVM snapshot (5D)
  - Tender package with 3 bids

Usage:
    cd backend && python -m app.scripts.seed_demo_4d5d
"""

import asyncio
import uuid
from datetime import datetime, timedelta, UTC

from sqlalchemy import select

from app.database import Base, engine, async_session_factory
from app.modules.projects.models import Project
from app.modules.boq.models import BOQ, Position
from app.modules.schedule.models import Schedule, Activity
from app.modules.costmodel.models import BudgetLine, CashFlow, CostSnapshot
from app.modules.tendering.models import TenderPackage, TenderBid


def _id() -> uuid.UUID:
    return uuid.uuid4()


async def main() -> None:
    print("=" * 70)
    print("  OpenConstructionERP  —  4D / 5D / Tendering Demo Seeder")
    print("=" * 70)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        result = await session.execute(
            select(Project).where(
                Project.name.in_(["Wohnanlage Berlin-Mitte", "One Canary Square"])
            )
        )
        projects = list(result.scalars().all())

        if not projects:
            print("ERROR: No demo projects. Run seed_demo_estimates.py first.")
            return

        for project in projects:
            print(f"\n{'—' * 70}")
            print(f"  {project.name} ({project.currency})")
            print(f"{'—' * 70}")

            # Get BOQ
            boq_r = await session.execute(select(BOQ).where(BOQ.project_id == project.id))
            boq = boq_r.scalars().first()
            if not boq:
                print("  SKIP: No BOQ")
                continue

            # Check existing
            sch_r = await session.execute(select(Schedule).where(Schedule.project_id == project.id))
            if sch_r.scalars().first():
                print("  SKIP: Already has schedule data")
                continue

            # Get positions
            pos_r = await session.execute(
                select(Position).where(Position.boq_id == boq.id).order_by(Position.sort_order)
            )
            all_pos = list(pos_r.scalars().all())
            sections = [p for p in all_pos if not p.unit or p.unit.strip() == ""]
            items = [p for p in all_pos if p.unit and p.unit.strip()]
            grand_total = sum(float(p.total or 0) for p in items)

            is_berlin = "Berlin" in project.name
            total_months = 18 if is_berlin else 24
            start = datetime(2026, 4, 1)

            # ── 4D SCHEDULE ────────────────────────────────────────────
            print(f"\n  4D Schedule — {len(sections)} activities, {total_months} months")

            schedule = Schedule(
                id=_id(),
                project_id=project.id,
                name="Bauablaufplan" if is_berlin else "Construction Programme",
                description="Terminplan" if is_berlin else "NRM programme",
                start_date=start.strftime("%Y-%m-%d"),
                end_date=(start + timedelta(days=total_months * 30)).strftime("%Y-%m-%d"),
                status="active",
                metadata_={},
            )
            session.add(schedule)
            await session.flush()

            current_start = start
            prev_id = None
            activities_created = []

            for i, sec in enumerate(sections):
                sec_items = [p for p in items if str(p.parent_id) == str(sec.id)]
                sec_total = sum(float(p.total or 0) for p in sec_items)
                pct = sec_total / grand_total if grand_total else 1 / max(len(sections), 1)
                dur = max(14, int(total_months * 30 * pct))

                if i > 0:
                    current_start = current_start - timedelta(days=int(dur * 0.35))

                end_date = current_start + timedelta(days=dur)
                prog = min(90, int((i / len(sections)) * 75 + 10)) if is_berlin else 0

                act = Activity(
                    id=_id(),
                    schedule_id=schedule.id,
                    name=sec.description or f"Phase {i+1}",
                    description=f"{len(sec_items)} pos, {sec_total:,.0f} {project.currency}",
                    wbs_code=sec.ordinal or str(i+1),
                    start_date=current_start.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    duration_days=dur,
                    progress_pct=prog,
                    status="in_progress" if prog > 0 else "planned",
                    color="#ef4444" if i % 3 == 0 else "#0071e3",
                    dependencies=[str(prev_id)] if prev_id else [],
                    boq_position_ids=[str(p.id) for p in sec_items],
                    metadata_={"section_total": round(sec_total, 2), "is_critical": i % 3 == 0},
                )
                session.add(act)
                activities_created.append(act)
                prev_id = act.id
                current_start = end_date

                p_str = f" ({prog}%)" if prog else ""
                print(f"    {(sec.description or '')[:42]:<42s} {dur:>3d}d  {sec_total:>12,.0f}{p_str}")

            # ── 5D BUDGET LINES ────────────────────────────────────────
            print(f"\n  5D Budget — {len(sections)} lines")

            for i, sec in enumerate(sections):
                sec_items = [p for p in items if str(p.parent_id) == str(sec.id)]
                planned = sum(float(p.total or 0) for p in sec_items)
                if is_berlin:
                    spend = max(0, min(1, (len(sections) - i) / len(sections) * 0.8))
                    actual = round(planned * spend * (0.95 + 0.1 * (i % 3)), 2)
                    committed = round(planned * min(1, spend + 0.15), 2)
                else:
                    actual = 0.0
                    committed = round(planned * 0.1, 2) if i < 3 else 0.0
                forecast = round(planned * (1.02 + 0.01 * (i % 4)), 2)

                bl = BudgetLine(
                    id=_id(),
                    project_id=project.id,
                    category=sec.description or f"Category {i+1}",
                    description=f"From BOQ section {sec.ordinal}",
                    planned_amount=str(round(planned, 2)),
                    committed_amount=str(round(committed, 2)),
                    actual_amount=str(round(actual, 2)),
                    forecast_amount=str(round(forecast, 2)),
                    currency=project.currency,
                    metadata_={},
                )
                session.add(bl)
                print(f"    {(sec.description or '')[:30]:<30s} P:{planned:>11,.0f}  A:{actual:>11,.0f}  F:{forecast:>11,.0f}")

            # ── 5D CASH FLOW ───────────────────────────────────────────
            print(f"\n  5D Cash Flow — {total_months} periods")
            cum_p, cum_a = 0.0, 0.0
            for m in range(total_months):
                mid = total_months / 2
                w = 1 - abs(m - mid) / mid
                monthly = grand_total * w / (total_months * 0.55)
                cum_p += monthly
                act_m = monthly * 0.92 if is_berlin and m < 10 else 0
                cum_a += act_m
                period = f"{2026 + (3 + m) // 12:04d}-{((3 + m) % 12) + 1:02d}"

                cf = CashFlow(
                    id=_id(),
                    project_id=project.id,
                    period=period,
                    category="total",
                    planned_outflow=str(round(monthly, 2)),
                    actual_outflow=str(round(act_m, 2)),
                    planned_inflow="0",
                    actual_inflow="0",
                    cumulative_planned=str(round(cum_p, 2)),
                    cumulative_actual=str(round(cum_a, 2)),
                    metadata_={},
                )
                session.add(cf)

            # ── 5D EVM SNAPSHOT ────────────────────────────────────────
            ev = grand_total * 0.52 if is_berlin else 0
            pv = grand_total * 0.58 if is_berlin else 0
            ac = grand_total * 0.54 if is_berlin else 0
            spi = round(ev / pv, 2) if pv else 1.0
            cpi = round(ev / ac, 2) if ac else 1.0
            eac = round(grand_total / cpi, 2) if cpi else grand_total
            period_now = f"2026-{datetime.now().month:02d}"

            snap = CostSnapshot(
                id=_id(),
                project_id=project.id,
                period=period_now,
                planned_cost=str(round(pv, 2)),
                earned_value=str(round(ev, 2)),
                actual_cost=str(round(ac, 2)),
                forecast_eac=str(round(eac, 2)),
                spi=str(spi),
                cpi=str(cpi),
                notes="Baseline" if not is_berlin else "Month 10 review",
                metadata_={},
            )
            session.add(snap)
            print(f"\n  5D Snapshot: BAC={grand_total:,.0f} | SPI={spi} | CPI={cpi} | EAC={eac:,.0f}")

            # ── TENDERING ──────────────────────────────────────────────
            print(f"\n  Tendering")
            pkg = TenderPackage(
                id=_id(),
                project_id=project.id,
                boq_id=boq.id,
                name="Rohbauarbeiten" if is_berlin else "Shell & Core Package",
                description="Ausschreibung" if is_berlin else "Main structural works",
                status="evaluating",
                deadline=(start - timedelta(days=30)).strftime("%Y-%m-%d"),
                metadata_={},
            )
            session.add(pkg)
            await session.flush()

            companies = [
                ("Hochtief AG", "tender@hochtief.de", 0.98),
                ("Strabag SE", "bids@strabag.com", 1.05),
                ("Zublin GmbH", "vergabe@zueblin.de", 1.02),
            ] if is_berlin else [
                ("Laing O'Rourke", "tenders@lor.com", 0.96),
                ("Balfour Beatty", "bids@bb.com", 1.08),
                ("Mace Group", "proc@mace.com", 1.01),
            ]

            for co, email, factor in companies:
                total = round(grand_total * factor, 2)
                bid = TenderBid(
                    id=_id(),
                    package_id=pkg.id,
                    company_name=co,
                    contact_email=email,
                    total_amount=str(total),
                    currency=project.currency,
                    submitted_at=datetime.now(UTC).isoformat(),
                    status="submitted",
                    notes=f"Tender — {co}",
                    line_items=[],
                    metadata_={},
                )
                session.add(bid)
                dev = (factor - 1) * 100
                print(f"    {co:<25s} {total:>14,.0f} {project.currency}  ({dev:+.1f}%)")

        await session.commit()

    print(f"\n{'=' * 70}")
    print(f"  DONE — 4D Schedule + 5D Budget + Tendering seeded")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
