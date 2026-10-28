# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The US pack's ``measurement_system`` has to decide a real validation outcome.

``BOQUnitSystemConsistencyRule`` has always been able to flag a bill whose
units belong to the other measurement system, and it has always read that
system from ``data["project_unit_system"]``. Nothing in the application ever
wrote that key, so on every real run the rule read ``None`` and returned an
empty result list - registered, enabled, and unreachable. On the other side of
the same gap, ``us_pack`` declared ``"measurement_system": "imperial"`` and no
code read it.

These tests join the two through the production path only. They call
``ValidationModuleService.run_validation`` against rows in the database, so a
regression that unhooks the resolver makes them fail; a test that built a
``ValidationContext`` by hand would have passed before the wiring existed.

The controls matter as much as the positive case. The same metric bill is
validated under a German project, where metric is correct and the rule passes,
and the imperial bill is validated there too, where the rule flags exactly the
units the US project accepted. That is what proves the pack's *value* selects
the outcome rather than its mere presence. A third project sits in a country no
pack claims, and there the rule stays silent - the pre-wiring behaviour, kept
for every market without a pack.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio

from app.database import async_session_factory
from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.users.models import User

_RULE_ID = "boq_quality.unit_system_consistency"

#: Metric units a US bill has no business carrying, and their imperial twins.
#: Both tuples are drawn from the rule's own vocabulary, so a unit the rule
#: does not recognise cannot mask a broken wire as a clean pass.
_METRIC_UNITS: tuple[str, ...] = ("m2", "m3")
_IMPERIAL_UNITS: tuple[str, ...] = ("ft2", "cy")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _app_started():
    """Run the real application lifespan once: schema, module loader, rules."""
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield


async def _committed_owner() -> uuid.UUID:
    """A user that really exists, so ``Project.owner_id`` never fails its FK."""
    async with async_session_factory() as session:
        user = User(
            email=f"unit-system-{uuid.uuid4().hex[:10]}@datadrivenconstruction.io",
            hashed_password="x" * 16,
            full_name="Unit System",
        )
        session.add(user)
        await session.commit()
        return user.id


async def _project_with_boq(
    *,
    owner_id: uuid.UUID,
    country_code: str,
    region: str,
    units: tuple[str, ...],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a committed project plus a BOQ whose positions carry ``units``.

    Args:
        owner_id: Existing user id for ``Project.owner_id``.
        country_code: ISO 3166-1 alpha-2 code stored on the project.
        region: Region marker stored on the project.
        units: One unit string per position, in ordinal order.

    Returns:
        ``(project_id, boq_id)``.
    """
    async with async_session_factory() as session:
        project = Project(
            id=uuid.uuid4(),
            name=f"Unit system {uuid.uuid4().hex[:6]}",
            owner_id=owner_id,
            currency="USD",
            region=region,
            country_code=country_code,
            classification_standard="masterformat",
            metadata_={},
            fx_rates=[],
        )
        session.add(project)
        await session.flush()

        boq = BOQ(project_id=project.id, name="Main")
        session.add(boq)
        await session.flush()

        for index, unit in enumerate(units, start=1):
            # Quantity and rate are non-zero so the other boq_quality rules
            # stay quiet and only the unit-system result is under test. Money
            # and quantity are String columns by design (see boq/models.py).
            session.add(
                Position(
                    boq_id=boq.id,
                    ordinal=f"1.{index}",
                    description=f"Position measured in {unit}",
                    unit=unit,
                    quantity="100",
                    unit_rate="50",
                ),
            )
        await session.commit()
        return project.id, boq.id


async def _unit_system_result(project_id: uuid.UUID, boq_id: uuid.UUID) -> dict[str, Any] | None:
    """Run the real validation service and return the unit-system result, if any.

    Args:
        project_id: Project owning the BOQ.
        boq_id: BOQ to validate.

    Returns:
        The stored result dict for :data:`_RULE_ID`, or ``None`` when the rule
        produced nothing - which is how it reports "not configured".
    """
    from app.core.validation.rules import register_builtin_rules
    from app.modules.validation.service import ValidationModuleService

    register_builtin_rules()
    async with async_session_factory() as session:
        response = await ValidationModuleService(session).run_validation(
            project_id=project_id,
            boq_id=boq_id,
            rule_sets=["boq_quality"],
        )
    return next((r for r in response["results"] if r["rule_id"] == _RULE_ID), None)


# ── Positive: the pack's value governs a US bill ────────────────────────────


async def test_a_us_project_rejects_metric_units_because_the_pack_says_imperial():
    """The pack declares imperial, so metric positions are flagged."""
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="US",
        region="US",
        units=_METRIC_UNITS,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None, "the rule did not run - project_unit_system never reached the engine"
    assert result["passed"] is False
    assert result["details"]["project_unit_system"] == "imperial"
    assert result["details"]["wrong_system"] == "metric"
    assert result["details"]["mismatch_count"] == len(_METRIC_UNITS)


async def test_a_us_project_accepts_the_imperial_units_the_pack_declares():
    """The same wiring has to let the pack's own units through untouched."""
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="US",
        region="US",
        units=_IMPERIAL_UNITS,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is True
    assert result["details"]["project_unit_system"] == "imperial"


# ── Negative controls: a different pack, and no pack at all ─────────────────


async def test_a_german_project_flags_the_units_the_us_project_accepted():
    """The strongest control: same bill, opposite verdict, because DACH is metric.

    If presence of *any* pack were doing the work rather than its declared
    value, this bill would pass here exactly as it did under the US project.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="DE",
        region="DACH",
        units=_IMPERIAL_UNITS,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is False
    assert result["details"]["project_unit_system"] == "metric"
    assert result["details"]["wrong_system"] == "imperial"
    assert result["details"]["mismatch_count"] == len(_IMPERIAL_UNITS)


async def test_a_german_project_accepts_metric_units():
    """The metric bill that failed under the US pack passes under the DACH one."""
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="DE",
        region="DACH",
        units=_METRIC_UNITS,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is True
    assert result["details"]["project_unit_system"] == "metric"


async def test_a_country_no_pack_claims_leaves_the_rule_silent():
    """Pack absent: the key is null and the rule skips, as it always did.

    Antarctica is claimed by no pack and is not any pack's ``region_code``, so
    nothing resolves. The mixed bill below would be flagged under either
    system; staying silent proves the non-resolution, not a lucky verdict.

    The key is written as null rather than left out. Absent now means the
    payload never went through the shared builder, and the rule reports that
    instead of skipping - so the two silences that used to look alike are told
    apart, and this one is still silence.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="AQ",
        region="Antarctica",
        units=_METRIC_UNITS + _IMPERIAL_UNITS,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is None, f"expected no unit-system result without a pack, got {result}"


# ── The resolver's own contract ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("country_code", "region", "expected"),
    [
        ("US", "", "imperial"),
        ("us", "", "imperial"),  # case is normalised
        ("DE", "", "metric"),
        ("GB", "", "metric"),
        ("", "US", "imperial"),  # region fallback when no country is stored
        ("", "DACH", "metric"),
        ("AQ", "", None),  # no pack claims it
        ("", "Antarctica", None),
        ("", "", None),
        (None, None, None),
    ],
)
def test_resolve_measurement_system_answers_only_when_a_pack_does(
    country_code: str | None,
    region: str | None,
    expected: str | None,
) -> None:
    """Unknown input resolves to ``None`` rather than to a default."""
    from app.core.regional_packs import resolve_measurement_system

    assert resolve_measurement_system(country_code=country_code, region=region) == expected


def test_the_value_really_comes_from_the_pack_file() -> None:
    """Guard against a copy: the resolver must return what ``us_pack`` declares.

    A resolver carrying its own ``"US": "imperial"`` table would satisfy every
    test above while leaving the pack as inert as it was. This one reads the
    pack, so editing ``us_pack/config.py`` moves the answer.
    """
    from app.core.regional_packs import resolve_measurement_system
    from app.modules.us_pack.config import PACK_CONFIG

    assert resolve_measurement_system(country_code="US") == PACK_CONFIG["measurement_system"]


def test_the_pack_module_list_still_covers_every_pack_on_disk() -> None:
    """A pack added later must be registered, not silently unconsulted."""
    from pathlib import Path

    from app.core.regional_packs import PACK_CONFIG_MODULES

    modules_dir = Path(__file__).resolve().parents[2] / "app" / "modules"
    on_disk = {
        f"app.modules.{pack_dir.name}.config"
        for pack_dir in modules_dir.glob("*_pack")
        if (pack_dir / "config.py").is_file()
    }
    assert on_disk, "pack discovery found nothing - the gate would be vacuous"
    assert set(PACK_CONFIG_MODULES) == on_disk
