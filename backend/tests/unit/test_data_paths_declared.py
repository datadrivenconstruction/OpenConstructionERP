# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Gate: data path declarations exist for the first wave and name only real fields.

* every first-wave module declares ``data_paths``;
* the number of undeclared modules may only shrink (ratchet);
* every ``via``, measured field, filter, parameter, drive and stale reference
  resolves against the ORM, and every JSON key appears in module code;
* every label key exists in ``en.ts``;
* ``DataPaths.gaps()`` is empty;
* every data trace steps through real modules on real links;
* every module is declared or has links derived from the code (ratchet on "none").
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from app.core.data_paths import DataPath, DataPaths, Entity, Param, Stale, Where
from app.core.module_loader import ModuleLoader
from app.modules.dataflow.graph import declaration_problems, index_models, module_dir

SURVEY_WAVE = (
    "oe_survey_core",
    "oe_setting_out",
    "oe_monitoring",
    "oe_land_parcels",
    "oe_surfaces_volumes",
    "oe_stockpiles",
    "oe_mine_survey",
    "oe_pointcloud",
    "oe_daily_diary",
)

FIRST_WAVE = (
    "oe_boq",
    "oe_takeoff",
    "oe_costs",
    "oe_validation",
    "oe_tendering",
    "oe_procurement",
    "oe_contracts",
    "oe_changeorders",
    "oe_finance",
    "oe_payment_clock",
    "oe_schedule",
    "oe_full_evm",
    "oe_costmodel",
    "oe_construction_control",
    "oe_ncr",
)

# Ratchet: modules still without a declaration. Lower it when you declare one; never raise it.
UNDECLARED_CEILING = 225

# Ratchet: modules with neither a declaration nor a derived link (country packs and
# platform services such as backup, search, scim). Never raise it.
UNLINKED_CEILING = 50

EN_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "locales" / "en.ts"


@pytest.fixture(scope="module")
def manifests() -> dict:
    loader = ModuleLoader()
    found = {m.name: m for m in loader.discover()}
    for name in found:
        try:
            importlib.import_module(f"app.modules.{module_dir(name)}.models")
        except ImportError:
            continue
    return found


@pytest.fixture(scope="module")
def models(manifests: dict) -> dict:
    return index_models(manifests)


def _labels(decl: DataPaths) -> list[str]:
    keys = [decl.why]
    keys += [e.label for e in decl.entities]
    for _d, p in decl.paths():
        keys += [p.label, p.breaks] + ([p.missing] if p.missing else [])
    keys += [p.label for p in decl.parameters]
    keys += [s.label for s in decl.stale]
    keys += [d.label for d in decl.duties]
    keys += [e.label for e in decl.external]
    keys += [c.label for c in decl.chips]
    return [k for k in keys if k]


def test_first_wave_is_declared(manifests: dict) -> None:
    missing = [m for m in FIRST_WAVE if m in manifests and manifests[m].data_paths is None]
    assert missing == [], f"first-wave modules without data_paths: {missing}"
    absent = [m for m in FIRST_WAVE if m not in manifests]
    assert absent == [], f"first-wave modules not discovered: {absent}"


def test_survey_wave_is_declared(manifests: dict) -> None:
    missing = [m for m in SURVEY_WAVE if m in manifests and manifests[m].data_paths is None]
    assert missing == [], f"survey and site modules without data_paths: {missing}"


def test_undeclared_modules_only_shrink(manifests: dict) -> None:
    undeclared = sorted(n for n, m in manifests.items() if m.data_paths is None)
    assert len(undeclared) <= UNDECLARED_CEILING, (
        f"{len(undeclared)} modules without data_paths, ceiling {UNDECLARED_CEILING}: declare the new module"
    )


def test_every_declared_reference_resolves(manifests: dict, models: dict) -> None:
    known = set(manifests)
    problems: list[str] = []
    for name, manifest in sorted(manifests.items()):
        if manifest.data_paths is not None:
            problems += declaration_problems(name, manifest.data_paths, models, known)
    assert problems == [], "\n".join(problems)


def test_every_label_key_exists_in_en(manifests: dict) -> None:
    text = EN_TS.read_text(encoding="utf-8")
    keys = set(re.findall(r'^\s*"([^"]+)":', text, flags=re.MULTILINE))
    missing = sorted(
        {
            f"{name}: {key}"
            for name, manifest in manifests.items()
            if manifest.data_paths is not None
            for key in _labels(manifest.data_paths)
            if key not in keys
        }
    )
    assert missing == [], "label keys missing in en.ts:\n" + "\n".join(missing)


# ── The gate itself catches what it claims to catch ────────────────────────


def test_gate_flags_an_invented_field(models: dict, manifests: dict) -> None:
    decl = DataPaths(
        why="x",
        entities=(Entity("Contract"),),
        outputs=(DataPath("oe_finance", "Invoice", via="Invoice.contract_id"),),
    )
    problems = declaration_problems("oe_contracts", decl, models, set(manifests))
    assert any("Invoice has no field contract_id" in p for p in problems), problems


def test_gate_flags_an_invented_json_key(models: dict, manifests: dict) -> None:
    decl = DataPaths(
        why="x",
        stale=(Stale(source="Contract.updated_at", copy="Contract.metadata_.never_written_key_xyz"),),
    )
    problems = declaration_problems("oe_contracts", decl, models, set(manifests))
    assert any("never_written_key_xyz" in p for p in problems), problems


def test_gate_flags_unknown_module_model_and_filter(models: dict, manifests: dict) -> None:
    decl = DataPaths(
        why="x",
        inputs=(
            DataPath("oe_nowhere", "X", via="X.id"),
            DataPath("oe_boq", "Nothing", via="Nothing.id"),
            DataPath("oe_boq", "Position", via="Position.boq_id", where=(Where("nope", "eq", "a"),)),
        ),
        parameters=(Param("Contract.retention_percent", drives=("oe_nowhere:x",)),),
    )
    problems = "\n".join(declaration_problems("oe_contracts", decl, models, set(manifests)))
    assert "unknown module oe_nowhere" in problems
    assert "no model Nothing" in problems
    assert "Position has no field nope" in problems
    assert "names unknown module oe_nowhere" in problems


def test_gaps_require_reason_why_and_breaks() -> None:
    assert DataPaths().gaps()
    assert DataPaths(reason="nothing flows").gaps() == []
    critical = DataPaths(why="w", inputs=(DataPath("oe_boq", "BOQ", via="BOQ.id", importance="critical"),))
    assert any("breaks" in g for g in critical.gaps())
    no_why = DataPaths(entities=(Entity("BOQ"),), inputs=(DataPath("oe_boq", "BOQ", via="BOQ.id"),))
    assert any("why" in g for g in no_why.gaps())


# ── Traces and coverage ────────────────────────────────────────────────────


def test_every_trace_walks_real_links(manifests: dict, models: dict) -> None:
    from app.modules.dataflow.traces import TRACES, trace_problems

    assert len(TRACES) >= 6
    problems = trace_problems(TRACES, models, set(manifests))
    assert problems == [], chr(10).join(problems)


def test_trace_labels_exist_in_en() -> None:
    from app.modules.dataflow.traces import TRACES

    text = EN_TS.read_text(encoding="utf-8")
    keys = set(re.findall(r'^\s*"([^"]+)":', text, flags=re.MULTILINE))
    wanted = {k for t in TRACES for k in (t.label, t.summary, *(s.label for s in t.steps))}
    assert sorted(wanted - keys) == []


def test_trace_gate_flags_an_invented_step(models: dict, manifests: dict) -> None:
    from app.modules.dataflow.traces import Trace, TraceStep, trace_problems

    fake = Trace(
        "fake",
        "x",
        "x",
        (
            TraceStep("oe_boq", "x"),
            TraceStep("oe_contracts", "x", "Contract.no_such_field"),
            TraceStep("oe_finance", "x", "code:no_such_function_anywhere"),
            TraceStep("oe_nowhere", "x", "Invoice.id"),
        ),
    )
    problems = trace_problems((fake,), models, set(manifests))
    assert any("no_such_field" in p for p in problems)
    assert any("no_such_function_anywhere" in p for p in problems)
    assert any("oe_nowhere" in p for p in problems)


def test_every_module_is_declared_or_derived(manifests: dict) -> None:
    from app.modules.dataflow.focus import coverage
    from app.modules.dataflow.graph import build_graph

    graph = build_graph(manifests, frozenset(manifests))
    cov = coverage(graph)
    unlinked = sorted(n for n, kind in cov.items() if kind == "none")
    assert len(unlinked) <= UNLINKED_CEILING, f"{len(unlinked)} modules with no known data path: {unlinked}"
    assert all(cov[m] == "declared" for m in SURVEY_WAVE if m in cov)
