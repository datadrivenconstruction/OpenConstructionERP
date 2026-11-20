# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data traces: named end-to-end scenarios across modules, played step by step.

Every step names the evidence that carries the data to it: a ``Model.field``
link (resolved against the ORM) or a function the receiving code calls
(found as a literal in the module's source). ``trace_problems`` checks both,
so a trace cannot describe a hand-over the code does not make.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.dataflow.graph import Graph, ModelInfo, _module_source, module_dir, resolve_ref


@dataclass(frozen=True)
class TraceStep:
    """One stop on a trace.

    Args:
        module: The module the data is in at this step.
        label: i18n key of what the data is here (``Volume between two surfaces``).
        via: Evidence for the hand-over from the previous step: ``Model.field`` or a
            function name prefixed with ``code:`` (``code:record_progress``). Empty on step one.
    """

    module: str
    label: str
    via: str = ""


@dataclass(frozen=True)
class Trace:
    """A named scenario; ``label`` and ``summary`` are i18n keys."""

    id: str
    label: str
    summary: str
    steps: tuple[TraceStep, ...]

    def modules(self) -> tuple[str, ...]:
        return tuple(s.module for s in self.steps)


TRACES: tuple[Trace, ...] = (
    Trace(
        "survey_to_payment",
        "data_paths.trace.survey_to_payment",
        "data_paths.trace.survey_to_payment_summary",
        (
            TraceStep("oe_survey_core", "data_paths.trace.step.survey_points"),
            TraceStep("oe_surfaces_volumes", "data_paths.trace.step.surface", "SurveySurface.point_set_id"),
            TraceStep("oe_surfaces_volumes", "data_paths.trace.step.volume", "SurveyVolume.base_surface_id"),
            TraceStep("oe_boq", "data_paths.trace.step.boq_position", "SurveyVolume.boq_position_id"),
            TraceStep("oe_progress", "data_paths.trace.step.progress_entry", "ProgressEntry.boq_position_id"),
            TraceStep("oe_contracts", "data_paths.trace.step.progress_claim", "code:populate_claim_from_progress"),
        ),
    ),
    Trace(
        "takeoff_to_contract",
        "data_paths.trace.takeoff_to_contract",
        "data_paths.trace.takeoff_to_contract_summary",
        (
            TraceStep("oe_takeoff", "data_paths.trace.step.takeoff_measurement"),
            TraceStep("oe_boq", "data_paths.trace.step.boq_position", "TakeoffMeasurement.linked_boq_position_id"),
            TraceStep("oe_tendering", "data_paths.trace.step.tender_package", "TenderPackage.boq_id"),
            TraceStep("oe_tendering", "data_paths.trace.step.awarded_bid", "TenderBid.package_id"),
            TraceStep("oe_contracts", "data_paths.trace.step.contract", "Contract.metadata_.tender_package_id"),
        ),
    ),
    Trace(
        "setting_out_to_ncr",
        "data_paths.trace.setting_out_to_ncr",
        "data_paths.trace.setting_out_to_ncr_summary",
        (
            TraceStep("oe_survey_core", "data_paths.trace.step.control_points"),
            TraceStep("oe_setting_out", "data_paths.trace.step.setting_out_request", "SettingOutRequest.control_ref"),
            TraceStep("oe_setting_out", "data_paths.trace.step.as_staked", "SettingOutRecord.request_id"),
            TraceStep("oe_ncr", "data_paths.trace.step.ncr", "SettingOutRecord.ncr_id"),
        ),
    ),
    Trace(
        "scan_to_ncr",
        "data_paths.trace.scan_to_ncr",
        "data_paths.trace.scan_to_ncr_summary",
        (
            TraceStep("oe_pointcloud", "data_paths.trace.step.scan"),
            TraceStep("oe_construction_control", "data_paths.trace.step.as_built", "code:pointcloud_registration"),
            TraceStep("oe_ncr", "data_paths.trace.step.ncr", "AsBuiltRecord.raised_ncr_id"),
        ),
    ),
    Trace(
        "parcels_to_work_zone",
        "data_paths.trace.parcels_to_work_zone",
        "data_paths.trace.parcels_to_work_zone_summary",
        (
            TraceStep("oe_land_parcels", "data_paths.trace.step.parcel"),
            TraceStep("oe_land_parcels", "data_paths.trace.step.land_right", "LandRight.parcel_id"),
            TraceStep("oe_land_parcels", "data_paths.trace.step.land_take", "code:work_zones"),
            TraceStep("oe_setting_out", "data_paths.trace.step.corner_stakes", "code:stake_corners"),
        ),
    ),
    Trace(
        "stockpile_to_inventory",
        "data_paths.trace.stockpile_to_inventory",
        "data_paths.trace.stockpile_to_inventory_summary",
        (
            TraceStep("oe_surfaces_volumes", "data_paths.trace.step.surface"),
            TraceStep("oe_stockpiles", "data_paths.trace.step.stockpile_survey", "StockpileSurvey.pile_surface_id"),
            TraceStep("oe_site_inventory", "data_paths.trace.step.stock_movement", "code:_inventory_item"),
        ),
    ),
    Trace(
        "haul_to_payment",
        "data_paths.trace.haul_to_payment",
        "data_paths.trace.haul_to_payment_summary",
        (
            TraceStep("oe_haul_tickets", "data_paths.trace.step.haul_ticket"),
            TraceStep("oe_haul_tickets", "data_paths.trace.step.haul_invoice", "HaulTicket.invoice_id"),
            TraceStep("oe_procurement", "data_paths.trace.step.purchase_order", "HaulTicket.po_id"),
        ),
    ),
    Trace(
        "schedule_to_earned_value",
        "data_paths.trace.schedule_to_earned_value",
        "data_paths.trace.schedule_to_earned_value_summary",
        (
            TraceStep("oe_schedule", "data_paths.trace.step.activity"),
            TraceStep("oe_costmodel", "data_paths.trace.step.budget_line", "BudgetLine.activity_id"),
            TraceStep("oe_full_evm", "data_paths.trace.step.earned_value", "BudgetLine.actual_amount"),
        ),
    ),
    Trace(
        "mine_period_to_claim",
        "data_paths.trace.mine_period_to_claim",
        "data_paths.trace.mine_period_to_claim_summary",
        (
            TraceStep("oe_surfaces_volumes", "data_paths.trace.step.volume"),
            TraceStep("oe_mine_survey", "data_paths.trace.step.mine_period", "MinePeriodEntry.actual_volume_id"),
            TraceStep("oe_progress", "data_paths.trace.step.progress_entry", "code:record_progress"),
        ),
    ),
)


def _code_known(symbol: str, modules: tuple[str, ...]) -> bool:
    pattern = re.compile(rf"\b{re.escape(symbol)}\b")
    return any(pattern.search(_module_source(module_dir(m))) for m in modules)


def trace_problems(traces: tuple[Trace, ...], models: dict[str, list[ModelInfo]], known: set[str]) -> list[str]:
    """Every step whose module is unknown or whose hand-over evidence does not exist; empty = sound."""
    problems: list[str] = []
    ids: set[str] = set()
    for trace in traces:
        if trace.id in ids:
            problems.append(f"{trace.id}: duplicate trace id")
        ids.add(trace.id)
        if len(trace.steps) < 3:
            problems.append(f"{trace.id}: a trace needs at least three steps")
        for idx, step in enumerate(trace.steps):
            where = f"{trace.id} step {idx + 1}"
            if step.module not in known:
                problems.append(f"{where}: unknown module {step.module}")
                continue
            if idx == 0:
                continue
            prev = trace.steps[idx - 1].module
            if not step.via:
                problems.append(f"{where}: no evidence for the hand-over from {prev}")
            elif step.via.startswith("code:"):
                if not _code_known(step.via[5:], (step.module, prev)):
                    problems.append(f"{where}: {step.via[5:]!r} not found in {prev} or {step.module}")
            else:
                got = resolve_ref(step.via, (step.module, prev), models)
                if isinstance(got, str):
                    problems.append(f"{where}: {got}")
    return problems


def traces_through(module: str, visible: set[str] | None = None) -> list[tuple[Trace, list[int]]]:
    """Traces that pass through ``module`` with the step indexes where they do; hidden modules drop the trace."""
    out: list[tuple[Trace, list[int]]] = []
    for trace in TRACES:
        if visible is not None and any(m not in visible for m in trace.modules()):
            continue
        hits = [i for i, s in enumerate(trace.steps) if s.module == module]
        if hits:
            out.append((trace, hits))
    return out


def all_visible(graph: Graph, visible: set[str]) -> list[Trace]:
    """Every trace whose modules the caller can see."""
    return [t for t in TRACES if all(m in visible and m in graph.manifests for m in t.modules())]


__all__ = ["TRACES", "Trace", "TraceStep", "all_visible", "trace_problems", "traces_through"]
