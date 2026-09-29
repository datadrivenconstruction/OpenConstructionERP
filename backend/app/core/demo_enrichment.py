# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# OpenConstructionERP - DataDrivenConstruction (DDC)
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License
"""Reusable per-module demo enrichment.

The rich per-module demo seeders (photos, takeoff, BIM grouping, clash,
carbon, QMS, advanced scheduling, cost model, MoC, supplier catalogs,
variations, accommodation, markups, catalog, plus CRM / service / bid /
HSE / portal / tendering) used to run only inline at first boot in
``app/main.py``. The in-app partner-pack apply paths installed the demo
project's BOQ / budget / schedule / tender / BIM model / PDFs but never ran
these enrichment seeders, so a pack applied from the Modules page after boot
opened with empty photos / takeoff / clash / carbon / qms / variations /
costmodel / moc / markups / catalog.

This module extracts that seeder list into one reusable, fail-soft coroutine
so both boot AND the pack-apply paths run the exact same enrichment. Each
seeder runs in its own DB session inside its own ``try/except`` so a single
seeder (or a single project) failing never aborts the rest, never aborts the
pack apply and never aborts boot.

No new DB tables: this only orchestrates seeders that already exist.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)

# The flagship reference project. Kept first in the enrichment order so the
# seeders that cap at a few projects (advanced scheduling, QMS, supplier
# catalog) always cover the project users land on.
_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# The curated showcase, by ``metadata.demo_id``. Six kinds of work across four
# classification standards and four currencies, which is what makes a tour of
# the demo show breadth rather than the same building six times.
#
# This is the set the seeders that cover only a few projects are pointed at, so
# a reader who opens any of the six finds the same modules filled in each. The
# order is the order those seeders consume, and the flagship is not in the list
# because it is prepended separately: it is the reference project rather than
# one of the six.
#
# Append rather than insert when this set grows. The change-control seeder
# derives its marker codes from a project's position in this tuple, so putting
# a new id anywhere but the end renumbers projects that are already seeded on a
# running install.
#
# Changing the demo's shape means changing this tuple, which is the point of it
# being a tuple in one file rather than an accident of which project seeded
# first. Ids that do not resolve are skipped, so trimming the showcase never
# breaks the enrichment.
_FOCUS_DEMO_IDS: tuple[str, ...] = (
    "residential-berlin",
    "office-frankfurt",
    "school-paris",
    "medical-us",
    "warehouse-dubai",
    "condo-toronto",
)


async def enrich_projects(project_ids: list[uuid.UUID]) -> None:
    """Run every per-module demo seeder across the given projects.

    Mirrors the first-boot enrichment block that used to live inline in
    ``app/main.py`` (the unconditional ``OE_TEST_FAST_STARTUP``-gated block).
    Each seeder runs in its own session and its own ``try/except`` so one
    failing seeder (or one failing project) can never abort the rest. Safe to
    call repeatedly: every seeder is either internally idempotent or gated on a
    marker table so a re-run never duplicates rows.

    Only the demo projects among ``project_ids`` are enriched: a project
    without the ``demo_id`` marker, or one the user deleted, is never handed to
    any seeder (see ``app.core.demo_marker``).

    Args:
        project_ids: The projects to consider. Typically every project at boot,
            or the single project a partner-pack apply just installed.
    """
    if not project_ids:
        return

    try:
        from sqlalchemy import func as _func
        from sqlalchemy import select as _msel

        from app.database import async_session_factory
        from app.modules.accommodation.seed import seed_accommodation
        from app.modules.allowances.seed import seed_allowances_demo
        from app.modules.bcf.seed import seed_bcf_demo
        from app.modules.bid_management.seed import seed_bid_management_demo
        from app.modules.bim_hub.seed import seed_bim_hub
        from app.modules.carbon.models import CarbonInventory
        from app.modules.carbon.seed import seed_carbon_demo
        from app.modules.catalog.seed import seed_catalog
        from app.modules.clash.seed import seed_clash
        from app.modules.closeout.seed import seed_closeout_demo
        from app.modules.commissioning.seed import seed_commissioning_demo
        from app.modules.construction_control.seed import seed_construction_control_demo
        from app.modules.contracts.seed import seed_contracts_demo
        from app.modules.costmodel.seed import seed_costmodel
        from app.modules.crm.seed import seed_crm_demo
        from app.modules.cvr.seed import seed_cvr_demo
        from app.modules.daily_diary.seed import seed_daily_diary_demo, seed_daily_diary_showcase_de
        from app.modules.documents.documents_seed import seed_documents_demo
        from app.modules.documents.photos_seed import seed_photos
        from app.modules.dwg_takeoff.seed import seed_dwg_takeoff_demo
        from app.modules.einvoice_clearance.seed import seed_einvoice_clearance_demo
        from app.modules.estimate_basis.seed import seed_estimate_basis_demo
        from app.modules.field_time.seed import seed_field_time_demo
        from app.modules.finance.einvoice_settings_seed import seed_einvoice_settings_demo
        from app.modules.forms.submissions_seed import seed_forms_submissions_demo
        from app.modules.full_evm.seed import seed_full_evm_demo
        from app.modules.hse_advanced.seed import seed_hse_advanced_demo
        from app.modules.interface_management.seed import seed_interface_management_demo
        from app.modules.markups.seed import seed_markups
        from app.modules.moc.seed import seed_moc
        from app.modules.pointcloud.seed import seed_pointcloud_demo
        from app.modules.portal.seed import seed_portal_demo
        from app.modules.portfolio.seed import seed_portfolio_demo
        from app.modules.qms.models import ITPPlan
        from app.modules.qms.seed import seed_qms
        from app.modules.reconciliation.seed import seed_reconciliation_demo
        from app.modules.schedule_advanced.seed import seed_schedule_advanced_demo
        from app.modules.service.seed import seed_service_demo, seed_service_recurring_schedules
        from app.modules.site_inventory.seed import seed_site_inventory_demo
        from app.modules.site_logistics.demo import seed_site_logistics_demo
        from app.modules.site_prep.seed import seed_site_prep_demo
        from app.modules.supplier_catalogs.seed import seed_supplier_catalogs
        from app.modules.takeoff.seed import seed_takeoff_demo
        from app.modules.temporary_works.seed import seed_temporary_works_demo
        from app.modules.validation.seed import seed_validation_demo
        from app.modules.value.seed import seed_value_demo
        from app.modules.variations.models import Notice
        from app.modules.variations.seed import seed_variations_demo, seed_variations_showcase_de

        # Keep the flagship reference project first so seeders that cap at a
        # few projects (advanced scheduling, QMS, supplier catalog) always
        # cover the project users land on.
        _all_pids = list(project_ids)
        _all_pids.sort(key=lambda _p: 0 if _p == _FLAGSHIP_ID else 1)

        # The demo projects, and the only projects any seeder below is handed.
        #
        # ``enrich_all`` offers this function every project in the database, and
        # the backfill re-runs at least once per app version, so on a working
        # installation a live project reaches this list on every upgrade. A
        # seeder gated on "my own table is empty for this project" cannot refuse
        # it: a real project that has recorded no diary, no inspection plan and
        # no photos yet is empty by that test, and the first run is what does
        # the damage. That is how a self-hosted install found a quality plan,
        # three inspections, two NCRs, eight punch items and an audit, ninety
        # days of site diary, bid packages and a team roster in every project
        # created after the demo, and why nothing afterwards can tell those
        # rows from real ones.
        #
        # So the filter is applied here, once, for every seeder, rather than in
        # each seeder: a rule written once per caller is a rule the next caller
        # forgets. A demo project is one carrying the ``demo_id`` marker every
        # installer writes, and one the user deleted (archived) is not one any
        # more. See ``app.core.demo_marker``.
        _demo_pids: list[uuid.UUID] = []
        _by_demo_id: dict[str, uuid.UUID] = {}
        try:
            from app.core.demo_marker import live_demo_projects

            async with async_session_factory() as _dm:
                _live = await live_demo_projects(_dm, _all_pids)
            _live_ids = {_pid for _pid, _did in _live}
            _demo_pids = [_p for _p in _all_pids if _p in _live_ids]
            _by_demo_id = {_did: _pid for _pid, _did in _live}
        except Exception:
            # Fail closed. An empty list means every seeder below does nothing,
            # which leaves a screen unfilled; the other branch writes invented
            # records into projects we could not prove are ours.
            logger.warning("Demo project discovery failed - demo seeds skipped", exc_info=True)
            _demo_pids = []
        if not _demo_pids:
            return
        _first_pid = _demo_pids[0]

        # Which projects the seeders that fill a few projects rather than all of
        # them should land on. Each of them used to take a prefix of the list it
        # was handed, and the list arrives in creation order, so the modules
        # landed on the flagship plus whichever two projects happened to install
        # first. Measured on a clean thirteen-project install that was
        # residential-berlin and warehouse-dubai, which left accommodation,
        # markups, change control, the deep cost model and the Last Planner
        # schedule empty on three of the five projects the demo is curated
        # around, for no reason anyone chose.
        #
        # Named here rather than reordered inside each seeder for the same
        # reason _demo_pids is built here: a rule written once per caller is a
        # rule the next caller forgets, and there are five callers of this one.
        #
        # Where none of the curated ids resolve, the answer is the flagship
        # alone, and nothing at all when even that is absent. This used to fall
        # back to the first three projects in creation order, which guessed. On
        # a workspace holding only packs from outside the curated set that
        # filled three arbitrary projects, and on an install with demo seeding
        # still enabled and no demo projects in it those three were somebody's
        # real projects, which is how invented cost models, change-control
        # records and Last Planner boards could land in live work.
        #
        # Seeding nothing is the right answer when we cannot prove what is a
        # demo project. An instrument that returns a plausible result where it
        # should return none is the defect; the empty list is not.
        _curated_pids = [_by_demo_id[_did] for _did in _FOCUS_DEMO_IDS if _did in _by_demo_id]
        _focus_pids: list[uuid.UUID] = [_p for _p in _demo_pids if _p == _FLAGSHIP_ID] + _curated_pids

        # (name, marker model gating a restart-safe skip, coroutine builder).
        # A None marker means the seeder self-guards against duplicates.
        _module_seeders = [
            ("crm", None, lambda s: seed_crm_demo(s)),
            ("service", None, lambda s: seed_service_demo(s, _demo_pids)),
            ("bid_management", None, lambda s: seed_bid_management_demo(s, _demo_pids)),
            ("hse_advanced", None, lambda s: seed_hse_advanced_demo(s, _demo_pids)),
            ("portal", None, lambda s: seed_portal_demo(s, _demo_pids)),
            ("supplier_catalogs", None, lambda s: seed_supplier_catalogs(s, _first_pid)),
            ("carbon", CarbonInventory, lambda s: seed_carbon_demo(s, _demo_pids)),
            # A None marker rather than MasterSchedule: a table-wide marker
            # skipped the whole seeder as soon as any one project had a board,
            # so a project joining the curated set later was never filled. The
            # seeder guards per project itself now.
            ("schedule_advanced", None, lambda s: seed_schedule_advanced_demo(s, _focus_pids)),
            ("variations", Notice, lambda s: seed_variations_demo(s, _demo_pids)),
            # Field time runs after variations so a daywork booking can name an
            # open variation order, and after the equipment seed (which runs at
            # boot before this list) so plant hours price off a real rental.
            # Self-guards per project on an existing timesheet.
            ("field_time", None, lambda s: seed_field_time_demo(s, _demo_pids)),
            # ── Modules that shipped without any startup seeder at all ──
            # Each new seeder below is internally idempotent (it returns an
            # empty dict once its own marker rows already exist), so they are
            # wired with a None marker and re-checked cheaply on every restart.
            # A None marker is required here rather than a global row-count gate
            # because several of these (takeoff, markups) legitimately share
            # their table with rows seeded elsewhere or by users, so a
            # table-wide count would skip the projects that are still empty.
            ("costmodel", None, lambda s: seed_costmodel(s, _focus_pids)),
            ("moc", None, lambda s: seed_moc(s, _focus_pids)),
            ("takeoff", None, lambda s: seed_takeoff_demo(s, _demo_pids)),
            ("accommodation", None, lambda s: seed_accommodation(s, _focus_pids)),
            ("markups", None, lambda s: seed_markups(s, _focus_pids)),
            ("catalog", None, lambda s: seed_catalog(s, _demo_pids)),
            # Runs after the service seeder above, which is what writes the
            # contracts these rules stamp their tickets against. Demo
            # projects only, which is what lets it ask the question per
            # project instead of bailing on the first one.
            ("service_recurring", None, lambda s: seed_service_recurring_schedules(s, _demo_pids)),
            # The diary seeder was written complete and never wired, so the
            # module shipped with an empty register on every install. Ninety
            # days per project, so it self-guards per project rather than on a
            # table-wide count: a user writing one diary entry must not stop
            # the seed reaching the projects that are still empty.
            ("daily_diary", None, lambda s: seed_daily_diary_demo(s, _demo_pids)),
            # Site photos drop real JPEGs into the gallery so the Photos module
            # and the dashboard "latest photos" widget are never empty on a
            # fresh install. Self-guards per project on an existing seeded photo.
            ("photos", None, lambda s: seed_photos(s, _demo_pids)),
            # ── Earned records ──
            # Every seeder in this list receives ``_demo_pids`` now; the ones
            # below were the first to, because they write records a real
            # project would have earned -
            # signed permits, accepted inspections, released hold gates, a
            # basis of estimate - and writing those into a customer's live
            # project is a data-integrity problem, not a cosmetic one. See the
            # discovery block above for why an "am I empty?" guard cannot
            # substitute for this.
            #
            # Order inside the block is load-bearing where a seeder reads what
            # another one wrote; the dependency is named on each line that has
            # one. Everything else is grouped by the part of the job it belongs
            # to so the log reads in the order a project is actually run.
            ("documents", None, lambda s: seed_documents_demo(s, _demo_pids)),
            ("validation", None, lambda s: seed_validation_demo(s, _demo_pids)),
            ("allowances", None, lambda s: seed_allowances_demo(s, _demo_pids)),
            # The basis of estimate quotes the allowances register line by line,
            # so it cannot run before the register exists.
            ("estimate_basis", None, lambda s: seed_estimate_basis_demo(s, _demo_pids)),
            # Progress-claim backfill for the authored demo contracts (the
            # installer writes contracts but no payment history), plus the
            # generic contract catalog for any demo project that has no
            # contracts at all. A claim run is money a real project has earned,
            # so it stays on the demo estate. Self-guards per contract on an
            # existing claim. Also gives each contract the schedule of values
            # it was agreed against and breaks every claim down against it,
            # without which the continuation sheet has nothing to continue.
            # The projects whose contracts are worded in German get a German
            # schedule, of DIN 276 cost groups or Leistungsverzeichnis
            # positions, picked by the trade each contract's title names.
            ("contracts", None, lambda s: seed_contracts_demo(s, _demo_pids)),
            # The cost-value reconciliation register: closed months, the month
            # running, the cashflow curve and the interim applications raised
            # against them. Scales itself from the project's priced bill, so it
            # runs after the installer has written one; a project without a
            # priced bill is skipped rather than given an invented contract
            # value. Demo estate only, for the same reason as the contracts
            # above - a reconciliation states what a job earned and what it
            # cost, and inventing one inside a live project is a data incident.
            # Self-guards per project on an existing report.
            ("cvr", None, lambda s: seed_cvr_demo(s, _demo_pids)),
            # The frozen budget the same job is measured against, and the
            # monthly measurements taken since. Reads the same commercial
            # profile as the reconciliation above, so the margin one screen
            # reports and the outturn the other forecasts describe one job
            # rather than two. Self-guards per project on an existing baseline.
            ("full_evm", None, lambda s: seed_full_evm_demo(s, _demo_pids)),
            # Seller identity and bank account for the E-Rechnung screen, copied
            # out of the showcase invoice that already carries them, so the
            # settings form is not empty on an install whose invoice exports
            # green. Instance-wide configuration, hence the demo estate only,
            # and it fills empty fields only - a value a user typed wins.
            ("einvoice_settings", None, lambda s: seed_einvoice_settings_demo(s, _demo_pids)),
            # The country registration and one submitted document behind it, so
            # the clearance screen opens on a real trail rather than on an empty
            # state. Runs after the settings above, so the XRechnung it renders
            # and stores carries the seller a visitor then finds on /settings.
            ("einvoice_clearance", None, lambda s: seed_einvoice_clearance_demo(s, _demo_pids)),
            # German showcase Nachtrag chains: notices, requests and orders in
            # German with contract-clause anchors, custody hand-offs and dated
            # trails, so the claims-evidence panel can grade at least one chain
            # per German project as provable. Runs after the generic variations
            # sprinkle above (which skips these projects) and before the
            # reconciliation correlator at the end of this list. Self-guards
            # per project on its own seeded notice codes.
            ("variations_showcase_de", None, lambda s: seed_variations_showcase_de(s, _demo_pids)),
            # German Bautagebuch for the same four projects: thirty consecutive
            # German working days ending today, entries and site photos, and a
            # signed and archived chain closed by the named site supervisor.
            # Must run after "photos" above, which commits the image files this
            # register points at. Self-guards per project on its own diaries.
            ("daily_diary_showcase_de", None, lambda s: seed_daily_diary_showcase_de(s, _demo_pids)),
            ("temporary_works", None, lambda s: seed_temporary_works_demo(s, _demo_pids)),
            # Mobilisation plan and readiness register. Demo-only: it records
            # signed consents, issued certificates and closed commencement gates,
            # which is exactly the kind of earned record that must never appear
            # in a customer's live project. Stages each project by its position
            # in this list, so the flagship shows a live mobilisation rather than
            # one already closed out. Self-guards per project on an existing plan
            # or item.
            ("site_prep", None, lambda s: seed_site_prep_demo(s, _demo_pids)),
            # Gates, laydown zones and a working week of deliveries, each one
            # booked against a real position of the project's own bill - which is
            # what gives the delivery board its estimate coverage table something
            # to cover. Runs after the installer has priced a bill; a project
            # without a deliverable position is skipped rather than given
            # deliveries of nothing. Self-guards per project on an existing gate
            # or delivery, so a board in use is never added to.
            ("site_logistics", None, lambda s: seed_site_logistics_demo(s, _demo_pids)),
            # The yard and the material ledger: deliveries into stock, material
            # installed against the position that priced it, off-cuts and a
            # relocation. Demo estate only - a consumption booked against a bill
            # states what a job really used, which is an earned record. Reads the
            # priced bill and the progress readings the installer wrote, so it
            # runs after both; a project with no priced material line is skipped
            # rather than given stock of nothing. Self-guards per project on an
            # existing item or movement. Post-calculation reads this ledger for
            # its material actuals, so an unseeded yard leaves that report
            # honestly saying it does not know what the material cost.
            ("site_inventory", None, lambda s: seed_site_inventory_demo(s, _demo_pids)),
            ("forms", None, lambda s: seed_forms_submissions_demo(s, _demo_pids)),
            ("construction_control", None, lambda s: seed_construction_control_demo(s, _demo_pids)),
            ("commissioning", None, lambda s: seed_commissioning_demo(s, _demo_pids)),
            ("interface_management", None, lambda s: seed_interface_management_demo(s, _demo_pids)),
            ("pointcloud", None, lambda s: seed_pointcloud_demo(s, _demo_pids)),
            # Measures the demo DXF the flagship installer authored, so it runs
            # after that installer (which is a boot step ahead of this list).
            ("dwg_takeoff", None, lambda s: seed_dwg_takeoff_demo(s, _demo_pids)),
            # Binds handover evidence to documents that really exist in the
            # project's CDE, so it runs after the documents seed above.
            ("closeout", None, lambda s: seed_closeout_demo(s, _demo_pids)),
            # A structure over the projects rather than a register inside one:
            # it files the whole estate into one tree, so it runs once the
            # estate is complete.
            ("portfolio", None, lambda s: seed_portfolio_demo(s, _demo_pids)),
            # Books the assisted work the other seeders never logged, so the
            # value dashboard has activity to read. Late, so the module mix it
            # books reflects the modules that were actually filled.
            ("value", None, lambda s: seed_value_demo(s, _demo_pids)),
            # bim_hub groups the BIM models that already exist for a project, so
            # it runs near the end (after every other seeder). clash runs right
            # after it so its clash results reference the freshly grouped
            # models; clash also feeds the coordination_hub dashboard's clash
            # rollup.
            ("bim_hub", None, lambda s: seed_bim_hub(s, _demo_pids)),
            ("clash", None, lambda s: seed_clash(s, _demo_pids)),
            # Coordination topics derived from the clash run above carry that
            # run's real element names and centroids, so bcf follows clash. The
            # topics that are not clash-derived do not need it, but splitting
            # the seeder in two to gain a few seconds would cost the ordering
            # rule its one obvious home.
            ("bcf", None, lambda s: seed_bcf_demo(s, _demo_pids)),
            # Last on purpose. It correlates rows that other modules wrote -
            # correspondence, change orders, variations, management of change -
            # and scores every pair with the module's own engine, so anything
            # seeded after it would simply not be in the register.
            ("reconciliation", None, lambda s: seed_reconciliation_demo(s, _demo_pids)),
        ]
        for _name, _marker, _build in _module_seeders:
            try:
                if _marker is not None:
                    async with async_session_factory() as _chk:
                        _n = (await _chk.execute(_msel(_func.count()).select_from(_marker))).scalar_one()
                    if _n:
                        continue
                async with async_session_factory() as _ms:
                    _counts = await _build(_ms)
                    await _ms.commit()
                    if isinstance(_counts, dict) and any(_counts.values()):
                        logger.info("%s demo seed: %s", _name, _counts)
            except Exception:
                logger.warning("%s demo seed skipped (non-fatal)", _name, exc_info=True)

        # The project roster seeds one project at a time and guards itself on
        # the project already having roster lines, so a re-run is a no-op.
        for _pid in _demo_pids:
            try:
                from app.modules.teams.seed import seed_teams_roster

                async with async_session_factory() as _rs:
                    _written = await seed_teams_roster(_rs, project_id=_pid)
                    await _rs.commit()
                    if _written:
                        logger.info("teams roster demo seed: %s", _written)
            except Exception:
                logger.warning("teams roster demo seed skipped for %s (non-fatal)", _pid, exc_info=True)

        # QMS seeds one project at a time and is not internally idempotent; loop
        # the projects, skipping any that already carry an ITP plan so a re-run
        # never duplicates.
        for _pid in _demo_pids:
            try:
                async with async_session_factory() as _qs:
                    _has = (
                        await _qs.execute(_msel(ITPPlan.id).where(ITPPlan.project_id == _pid).limit(1))
                    ).scalar_one_or_none()
                    if _has is None:
                        await seed_qms(_qs, project_id=_pid)
                        await _qs.commit()
            except Exception:
                logger.warning("qms demo seed skipped for %s (non-fatal)", _pid, exc_info=True)
    except Exception:
        logger.warning("Feature-module demo seeds skipped (non-fatal)", exc_info=True)


async def enrich_all() -> None:
    """Enrich every project that currently exists in the database.

    Convenience wrapper used at boot: discovers all project ids and runs
    :func:`enrich_projects` over them. Fail-soft; a discovery error logs and
    returns without raising.
    """
    try:
        from sqlalchemy import select as _msel

        from app.database import async_session_factory
        from app.modules.projects.models import Project as _Proj

        # Ordered on purpose. Several seeders take a prefix of this list, and an
        # unordered select hands back heap order, which changes after a vacuum
        # or a reseed. That made "the first three projects" a different three on
        # different days, so a screen could be full one week and empty the next
        # with nothing in the tree having changed.
        async with async_session_factory() as _pid_s:
            _all_pids = list(
                (await _pid_s.execute(_msel(_Proj.id).order_by(_Proj.created_at, _Proj.id))).scalars().all()
            )
    except Exception:
        logger.warning("Feature-module demo seeds skipped (project discovery failed)", exc_info=True)
        return

    await enrich_projects(_all_pids)
