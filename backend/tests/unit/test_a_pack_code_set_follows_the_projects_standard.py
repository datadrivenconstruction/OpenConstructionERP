# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A "code required" set a pack adds to a project is filtered by the project's standard.

Eight country packs were given a set that demands one classification code on
every line: aus, nzs and south-africa name nrm, saudi-vision2030,
batimatech-ca, us-california and us-texas name masterformat, turkey-tr names
birimfiyat. Project creation copies
a pack's sets onto the project, and the BOQ router took the project's sets
verbatim, filtering by standard only the sets the country row adds. So a
project under the Texas pack that named UniFormat failed
masterformat.classification_required on every line of a correctly coded bill,
on import and on Validate, and changing the standard afterwards did not help.

The fix records which sets the pack added (project metadata
``pack_rule_sets``) and the router filters exactly those through the predicate
it applies to the country row. A set the creator asked for is never filtered,
because a dual-coded bill asks for a second code set on purpose: the Warsaw demo
is DIN 276 with a KNR reference on every line and carries ``poland``, the Delhi
demo is MasterFormat and carries ``cpwd``.

Every case below has its distinguishing twin: the same project without the
record, which is what the router saw before, fails the bill.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import uuid
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.partner_pack import discovery as pack_discovery
from app.core.partner_pack.apply import (
    PACK_RULE_SETS_METADATA_KEY,
    inherited_rule_sets,
    split_inherited_rule_sets,
)
from app.core.partner_pack.manifest import PartnerPackManifest
from app.core.validation.engine import validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.router import (
    _CLASSIFICATION_CODE_SETS,
    _STANDARD_RULE_SETS,
    _build_rule_sets,
    _pack_added_rule_sets,
)
from app.modules.projects import service as project_service_module
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.service import ProjectService
from tests._pg import transactional_session

PACKS_DIR = Path(__file__).resolve().parents[3] / "packs"

#: The packs whose new declaration this repair is about, each with a standard
#: a real project under it may name instead: elemental UniFormat in North
#: America, NRM among Gulf consultants, Uniclass and DIN 276 elsewhere.
REPAIRED: dict[str, str] = {
    "aus": "uniclass",
    "nzs": "masterformat",
    "saudi-vision2030": "nrm",
    "batimatech-ca": "uniformat",
    "us-california": "uniformat",
    "us-texas": "uniformat",
    "turkey-tr": "din276",
    # The Johannesburg demo the pack installs is coded in MasterFormat.
    "south-africa": "masterformat",
}


@lru_cache(maxsize=1)
def _manifests() -> dict[str, PartnerPackManifest]:
    out: dict[str, PartnerPackManifest] = {}
    for path in sorted(PACKS_DIR.glob("*/src/*/manifest.py")):
        name = f"_code_set_manifest_{path.parts[-2]}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader, f"{path} cannot be loaded as a module"
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        out[module.MANIFEST.slug] = module.MANIFEST
    return out


def _code_sets(manifest: PartnerPackManifest) -> list[str]:
    return [name for name in manifest.validation_rule_sets if name in _CLASSIFICATION_CODE_SETS]


def _code_set_packs() -> list[str]:
    return sorted(slug for slug, m in _manifests().items() if _code_sets(m))


def _another_standard(manifest: PartnerPackManifest) -> str:
    """A registered standard whose rule set is none of the pack's code sets."""
    for standard in ("din276", "nrm", "masterformat"):
        if _STANDARD_RULE_SETS[standard] not in manifest.validation_rule_sets:
            return standard
    raise AssertionError(f"{manifest.slug} names every candidate standard's set")


def _bill(code_key: str, code: str) -> dict[str, Any]:
    """Three priced leaf lines, each coded in one standard only."""
    return {
        "positions": [
            {
                "id": f"p-{i}",
                "parent_id": None,
                "ordinal": f"01.{i:02d}",
                "description": f"Coded line {i}",
                "unit": "m2",
                "quantity": 10.0,
                "unit_rate": 50.0,
                "total": 500.0,
                "classification": {code_key: code} if code_key else {},
                "type": "position",
            }
            for i in range(1, 4)
        ]
    }


def _errors_from(rule_sets: list[str], payload: dict[str, Any], code_sets: list[str]) -> dict[str, int]:
    """Error results of the pack's code sets when ``payload`` is validated with ``rule_sets``."""
    register_builtin_rules()
    runnable = [name for name in rule_sets if validation_engine.registry.has_rules(name)]
    report = asyncio.run(
        validation_engine.validate(data=payload, rule_sets=runnable, target_type="boq", metadata={"locale": "en"})
    )
    errors: dict[str, int] = {}
    for result in report.results:
        if result.passed or result.severity.value != "error":
            continue
        if any(result.rule_id.startswith(f"{name}.") for name in code_sets):
            errors[result.rule_id] = errors.get(result.rule_id, 0) + 1
    return errors


def _project_sets(manifest: PartnerPackManifest, asked: list[str] | None = None) -> tuple[list[str], list[str]]:
    register_builtin_rules()
    return split_inherited_rule_sets(asked if asked is not None else ["boq_quality"], manifest)


# ── Controls ─────────────────────────────────────────────────────────────────


def test_the_population_holds_the_repaired_packs() -> None:
    packs = set(_code_set_packs())
    for slug in REPAIRED:
        assert slug in packs, f"{slug} names no code set any more; this file lost its subject"
    assert len(packs) >= 20, f"only {len(packs)} packs name a code set; the walk lost a population"


def test_the_split_records_only_what_the_pack_added() -> None:
    texas = _manifests()["us-texas"]
    all_sets, added = _project_sets(texas)
    assert all_sets == ["boq_quality", "masterformat"]
    assert added == ["masterformat"]
    # Asked for by the caller: kept, and not the pack's to filter.
    all_sets, added = _project_sets(texas, ["boq_quality", "masterformat"])
    assert all_sets == ["boq_quality", "masterformat"]
    assert added == []
    # The baseline seeded for an empty request is not the pack's either.
    _all, added = _project_sets(texas, [])
    assert "boq_quality" not in added
    # The single-list reader still answers exactly as before.
    assert inherited_rule_sets(["boq_quality"], texas) == ["boq_quality", "masterformat"]


@pytest.mark.parametrize(
    "metadata",
    [None, {}, {"partner_pack": "us-texas"}, {PACK_RULE_SETS_METADATA_KEY: "masterformat"}, "not a dict"],
)
def test_a_project_without_a_readable_record_counts_every_set_as_asked_for(metadata: Any) -> None:
    assert _pack_added_rule_sets(SimpleNamespace(metadata_=metadata)) == []


def test_the_record_is_read_back_as_written() -> None:
    project = SimpleNamespace(metadata_={PACK_RULE_SETS_METADATA_KEY: ["masterformat", 7, "nrm"]})
    assert _pack_added_rule_sets(project) == ["masterformat", "nrm"]


# ── The defect, per repaired pack ────────────────────────────────────────────


@pytest.mark.parametrize(("slug", "standard"), sorted(REPAIRED.items()))
def test_a_project_under_the_pack_coded_in_another_standard_gets_no_code_errors(slug: str, standard: str) -> None:
    manifest = _manifests()[slug]
    code_sets = _code_sets(manifest)
    project_sets, added = _project_sets(manifest)
    bill = _bill(standard, "B2010.10")

    fixed = _build_rule_sets(project_sets, standard, "", manifest.market_country_code, pack_rule_sets=added)
    for name in code_sets:
        assert name not in fixed, f"{slug}: a {standard} project still runs {name}: {fixed}"
    assert _errors_from(fixed, bill, code_sets) == {}

    # The twin: without the record the router took the sets verbatim, and the
    # correctly coded bill failed on every line.
    before = _build_rule_sets(project_sets, standard, "", manifest.market_country_code)
    errors = _errors_from(before, bill, code_sets)
    assert sum(errors.values()) >= 3, f"{slug}: the unfiltered sets {before} raised only {errors}"


@pytest.mark.parametrize("slug", _code_set_packs())
def test_no_pack_code_set_reaches_a_project_that_names_another_standard(slug: str) -> None:
    """Every pack with a code set, against a standard with no rule set and one with another."""
    manifest = _manifests()[slug]
    project_sets, added = _project_sets(manifest)
    for standard in ("uniformat", _another_standard(manifest)):
        sets = _build_rule_sets(project_sets, standard, "", manifest.market_country_code, pack_rule_sets=added)
        leaked = [name for name in _code_sets(manifest) if name in sets and name != _STANDARD_RULE_SETS.get(standard)]
        assert leaked == [], f"{slug}: a {standard} project still runs {leaked}"


# ── What the pack must keep doing ────────────────────────────────────────────


@pytest.mark.parametrize("slug", sorted(REPAIRED))
def test_a_project_that_names_no_standard_keeps_the_pack_set(slug: str) -> None:
    """The pack still widens: nothing says which code the lines carry."""
    manifest = _manifests()[slug]
    project_sets, added = _project_sets(manifest)
    sets = _build_rule_sets(project_sets, "", "", None, pack_rule_sets=added)
    for name in _code_sets(manifest):
        assert name in sets, f"{slug}: a project naming no standard lost {name}: {sets}"


@pytest.mark.parametrize("slug", sorted(REPAIRED))
def test_a_project_in_the_packs_own_standard_keeps_the_set_and_it_fires(slug: str) -> None:
    manifest = _manifests()[slug]
    code_sets = _code_sets(manifest)
    own = next(std for std, rs in _STANDARD_RULE_SETS.items() if rs == code_sets[0] and std == rs)
    project_sets, added = _project_sets(manifest)
    sets = _build_rule_sets(project_sets, own, "", manifest.market_country_code, pack_rule_sets=added)
    assert code_sets[0] in sets
    errors = _errors_from(sets, _bill("", ""), code_sets)
    assert sum(errors.values()) >= 3, f"{slug}: an uncoded {own} bill raised only {errors}"


@pytest.mark.parametrize(
    ("slug", "demo_id", "code_set"),
    [("poland-pl", "residential-warsaw", "poland"), ("india-cpwd", "govt-building-delhi", "cpwd")],
)
def test_a_set_the_demo_asks_for_survives_beside_another_standard(slug: str, demo_id: str, code_set: str) -> None:
    """The dual-coded demos: a blanket filter by standard would strip their national check."""
    from app.core.demo_projects import DEMO_TEMPLATES

    template = DEMO_TEMPLATES[demo_id]
    assert _STANDARD_RULE_SETS.get(template.classification_standard) != code_set, "the demo is not dual-coded now"
    project_sets, added = _project_sets(_manifests()[slug], list(template.validation_rule_sets))
    assert code_set not in added, f"{code_set} was asked for by the demo, not added by {slug}"
    sets = _build_rule_sets(project_sets, template.classification_standard, template.region, None, pack_rule_sets=added)
    assert code_set in sets, f"{demo_id} lost {code_set}: {sets}"


# ── Through project creation, on PostgreSQL ──────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _clear_reservation_set() -> Any:
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


@pytest_asyncio.fixture
async def owner_id(session: AsyncSession) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(email=f"owner-{uuid.uuid4().hex}@test.local", hashed_password="x", full_name="Owner")
    session.add(user)
    await session.flush()
    return user.id


def _service(session: AsyncSession) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


def _sets_of(project: Any) -> list[str]:
    return _build_rule_sets(
        project.validation_rule_sets or ["boq_quality"],
        project.classification_standard or "",
        project.region or "",
        project.country_code,
        pack_rule_sets=_pack_added_rule_sets(project),
    )


@pytest.mark.asyncio
async def test_a_texas_project_whose_standard_changes_to_uniformat_drops_masterformat(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_builtin_rules()
    monkeypatch.setattr(pack_discovery, "get_active_pack", lambda: _manifests()["us-texas"])
    service = _service(session)

    project = await service.create_project(ProjectCreate(name=f"Texas {uuid.uuid4().hex[:6]}", region=""), owner_id)
    await session.flush()
    assert "masterformat" in project.validation_rule_sets
    assert project.metadata_.get(PACK_RULE_SETS_METADATA_KEY) == ["masterformat"]
    assert "masterformat" in _sets_of(project), "a project naming no standard keeps the pack's set"

    project = await service.update_project(project.id, ProjectUpdate(classification_standard="uniformat"))
    await session.flush()
    assert "masterformat" in project.validation_rule_sets, "the stored list is left as it was"
    assert "masterformat" not in _sets_of(project), "the changed standard did not reach the router"

    # A settings save that carries metadata merges it, so the record survives.
    project = await service.update_project(project.id, ProjectUpdate(metadata={"note": "kick-off"}))
    await session.flush()
    assert project.metadata_.get(PACK_RULE_SETS_METADATA_KEY) == ["masterformat"]
    assert project.metadata_.get("note") == "kick-off"
    assert "masterformat" not in _sets_of(project)

    # A copy keeps the record, so it is not promoted to a set someone asked for.
    copy = await service.duplicate_project(project.id, owner_id)
    await session.flush()
    assert copy.metadata_.get(PACK_RULE_SETS_METADATA_KEY) == ["masterformat"]
    assert "masterformat" not in _sets_of(copy)


@pytest.mark.asyncio
async def test_a_set_the_creator_asks_for_is_not_recorded_as_the_packs(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    register_builtin_rules()
    monkeypatch.setattr(pack_discovery, "get_active_pack", lambda: _manifests()["us-texas"])
    project = await _service(session).create_project(
        ProjectCreate(
            name=f"Dual {uuid.uuid4().hex[:6]}",
            region="",
            classification_standard="uniformat",
            validation_rule_sets=["boq_quality", "masterformat"],
        ),
        owner_id,
    )
    await session.flush()
    assert PACK_RULE_SETS_METADATA_KEY not in (project.metadata_ or {})
    assert "masterformat" in _sets_of(project)


@pytest.mark.asyncio
async def test_a_project_created_with_no_pack_carries_no_record(
    session: AsyncSession, owner_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pack_discovery, "get_active_pack", lambda: None)
    project = await _service(session).create_project(
        ProjectCreate(name=f"Plain {uuid.uuid4().hex[:6]}", region=""), owner_id
    )
    await session.flush()
    assert PACK_RULE_SETS_METADATA_KEY not in (project.metadata_ or {})
