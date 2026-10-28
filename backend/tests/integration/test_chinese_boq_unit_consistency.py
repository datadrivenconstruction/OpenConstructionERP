# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit-system consistency has to reach a Chinese bill of quantities.

``BOQUnitSystemConsistencyRule`` reads ``data["project_unit_system"]``, and that
value comes from whichever regional pack claims the project's country. A market
no pack claims resolves to ``None``, and on ``None`` the rule returns an empty
list: no result, no finding, no exit code. That silence is indistinguishable
from a bill with no unit problems, which is the whole reason these tests exist.

China was such a market. The rule's unit vocabulary already carried the words a
GB 50500 bill writes - 平方米, 立方米, 米 - so the vocabulary looked done, but no
pack declared ``"CN"``, so the rule never ran on a Chinese project at all and
the vocabulary was unreachable. Reading the vocabulary alone could not tell the
two apart, so these tests go through ``ValidationModuleService.run_validation``
against committed rows: a regression that unhooks the pack makes them fail,
while a test that assembled a ``ValidationContext`` by hand would pass either
way.

The check is directional, which decides what each case here proves. The rule
compares a bill's units against the set for the system the project is *not* in.
So on a Chinese project - metric - it is the imperial vocabulary that gets
read, and a Chinese bill is protected by the imperial words, not by the metric
ones. The metric words matter in the other direction, on an imperial project
carrying a Chinese row. Both directions are covered below, because a suite that
only tested one of them would report a vocabulary as protecting a market it
never touches.
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

#: A bill as a GB 50500 estimator writes it: metric words plus a lump-sum count
#: item. Every one of these units appears in the two Chinese demo projects this
#: repository ships, so the bill is the shape of real data rather than a
#: convenient fixture.
_CHINESE_METRIC_BILL: tuple[str, ...] = ("平方米", "立方米", "米", "项")

#: The same bill with one row measured in an imperial unit written in Latin.
#: This is the inconsistency the rule exists to catch.
_CHINESE_BILL_WITH_LATIN_IMPERIAL: tuple[str, ...] = (*_CHINESE_METRIC_BILL, "ft2")

#: The same inconsistency written the way a Chinese document writes it. Our own
#: zh locale renders a square foot as 平方英尺 and a cubic yard as 立方码, so
#: these are the platform's own spellings, not invented ones.
_CHINESE_BILL_WITH_CHINESE_IMPERIAL: tuple[str, ...] = (*_CHINESE_METRIC_BILL, "平方英尺", "立方码")

#: Chinese metric rows on a US project - the other direction of the same check.
_CHINESE_METRIC_UNITS_ONLY: tuple[str, ...] = ("平方米", "立方米")

#: Labour and plant time. A 工日 is a man-day and a 台班 a machine-shift; neither
#: has a dimension that can be metric or imperial, so neither may be flagged.
_CHINESE_LABOUR_AND_PLANT_UNITS: tuple[str, ...] = ("工日", "台班")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _app_started():
    """Run the real application lifespan once: schema, module loader, rules."""
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield


async def _committed_owner() -> uuid.UUID:
    """Return the id of a committed user, so ``Project.owner_id`` satisfies its FK."""
    async with async_session_factory() as session:
        user = User(
            email=f"cn-units-{uuid.uuid4().hex[:10]}@datadrivenconstruction.io",
            hashed_password="x" * 16,
            full_name="China Units",
        )
        session.add(user)
        await session.commit()
        return user.id


async def _project_with_boq(
    *,
    owner_id: uuid.UUID,
    country_code: str,
    region: str,
    currency: str,
    classification_standard: str,
    units: tuple[str, ...],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a committed project plus a BOQ whose positions carry ``units``.

    Args:
        owner_id: Existing user id for ``Project.owner_id``.
        country_code: ISO 3166-1 alpha-2 code stored on the project.
        region: Region marker stored on the project.
        currency: Project currency code.
        classification_standard: Standard the project's items are coded to.
        units: One unit string per position, in ordinal order.

    Returns:
        ``(project_id, boq_id)``.
    """
    async with async_session_factory() as session:
        project = Project(
            id=uuid.uuid4(),
            name=f"Chinese unit consistency {uuid.uuid4().hex[:6]}",
            owner_id=owner_id,
            currency=currency,
            region=region,
            country_code=country_code,
            classification_standard=classification_standard,
            metadata_={},
            fx_rates=[],
        )
        session.add(project)
        await session.flush()

        boq = BOQ(project_id=project.id, name="Main")
        session.add(boq)
        await session.flush()

        for index, unit in enumerate(units, start=1):
            # Quantity and rate are non-zero so the other boq_quality rules stay
            # quiet and only the unit-system result is under test. Money and
            # quantity are String columns by design (see boq/models.py).
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


async def _chinese_project_with_boq(owner_id: uuid.UUID, units: tuple[str, ...]) -> tuple[uuid.UUID, uuid.UUID]:
    """Create a Chinese project carrying ``units``, coded the way the demo packs are."""
    return await _project_with_boq(
        owner_id=owner_id,
        country_code="CN",
        region="CN",
        currency="CNY",
        classification_standard="gbt50500",
        units=units,
    )


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


# ── The rule has to speak at all on a Chinese project ───────────────────────


async def test_a_chinese_project_is_judged_rather_than_skipped():
    """The headline: a Chinese bill gets a verdict instead of silence.

    Before a pack claimed ``"CN"`` this returned ``None`` - the rule produced no
    result and the bill read as clean. The assertion is deliberately on the
    presence of a result rather than on its verdict, because presence is the
    thing that was missing and a passing verdict is still a verdict.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _chinese_project_with_boq(owner_id, _CHINESE_METRIC_BILL)

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None, "the rule stayed silent on a Chinese project - no pack resolved 'CN'"
    assert result["details"]["project_unit_system"] == "metric"


async def test_a_consistent_chinese_bill_passes():
    """A metric bill on a metric project is clean, and says so.

    The control for every failing case below: the rule is not simply flagging
    Chinese units, it is comparing them against the project's system.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _chinese_project_with_boq(owner_id, _CHINESE_METRIC_BILL)

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is True, f"a metric Chinese bill was flagged: {result['message']}"


# ── The negative controls: a genuine inconsistency must fail ────────────────


async def test_a_chinese_bill_with_a_latin_imperial_row_is_flagged():
    """One ft2 row in an otherwise metric Chinese bill has to fail the rule."""
    owner_id = await _committed_owner()
    project_id, boq_id = await _chinese_project_with_boq(owner_id, _CHINESE_BILL_WITH_LATIN_IMPERIAL)

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None, "the rule stayed silent on a bill that is genuinely inconsistent"
    assert result["passed"] is False
    assert result["details"]["project_unit_system"] == "metric"
    assert result["details"]["wrong_system"] == "imperial"
    assert result["details"]["mismatch_count"] == 1
    assert result["details"]["mismatches"][0]["unit"] == "ft2"


async def test_a_chinese_bill_with_imperial_units_written_in_chinese_is_flagged():
    """The inconsistency a Chinese document actually contains has to fail too.

    A Chinese bill does not write its imperial rows in Latin. It writes 平方英尺
    and 立方码, and until those words were in the imperial vocabulary the rule
    read them as unrecognised and skipped them - so the market whose bills the
    Chinese vocabulary was added for was the one still not protected. This is
    the direction that matters on a Chinese project, because the rule only ever
    reads the set for the system the project is *not* in.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _chinese_project_with_boq(owner_id, _CHINESE_BILL_WITH_CHINESE_IMPERIAL)

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is False, "imperial units written in Chinese were not recognised as imperial"
    assert result["details"]["mismatch_count"] == 2
    flagged = {row["unit"] for row in result["details"]["mismatches"]}
    assert flagged == {"平方英尺", "立方码"}


async def test_an_imperial_project_flags_chinese_metric_rows():
    """The other direction, and the case the Chinese metric vocabulary serves.

    A US project is imperial, so the rule reads the metric set - which is where
    the Chinese metric words live. Without them this bill passed: the units were
    unrecognised, and an unrecognised unit is skipped rather than flagged.
    """
    owner_id = await _committed_owner()
    project_id, boq_id = await _project_with_boq(
        owner_id=owner_id,
        country_code="US",
        region="US",
        currency="USD",
        classification_standard="masterformat",
        units=_CHINESE_METRIC_UNITS_ONLY,
    )

    result = await _unit_system_result(project_id, boq_id)

    assert result is not None
    assert result["passed"] is False
    assert result["details"]["project_unit_system"] == "imperial"
    assert result["details"]["wrong_system"] == "metric"
    assert result["details"]["mismatch_count"] == len(_CHINESE_METRIC_UNITS_ONLY)


# ── Units that must never be flagged ────────────────────────────────────────


async def test_labour_and_plant_time_units_are_never_a_system_mismatch():
    """A man-day is neither metric nor imperial, on either kind of project.

    Both system sets are only ever read as the wrong set, so a dimensionless
    unit listed in either one would misfire on every project of the other
    system. Running the same labour bill under both a Chinese and a US project
    is what proves the units are absent from *both* sets rather than merely
    from the one that happened to be read.
    """
    owner_id = await _committed_owner()

    chinese_project, chinese_boq = await _chinese_project_with_boq(owner_id, _CHINESE_LABOUR_AND_PLANT_UNITS)
    us_project, us_boq = await _project_with_boq(
        owner_id=owner_id,
        country_code="US",
        region="US",
        currency="USD",
        classification_standard="masterformat",
        units=_CHINESE_LABOUR_AND_PLANT_UNITS,
    )

    chinese_result = await _unit_system_result(chinese_project, chinese_boq)
    us_result = await _unit_system_result(us_project, us_boq)

    assert chinese_result is not None
    assert chinese_result["passed"] is True, f"labour units flagged on a metric project: {chinese_result['message']}"
    assert us_result is not None
    assert us_result["passed"] is True, f"labour units flagged on an imperial project: {us_result['message']}"


# ── The resolver's own contract for China ───────────────────────────────────


def test_china_resolves_to_the_system_its_own_pack_declares() -> None:
    """Guard against a hand-written country table standing in for the pack.

    A resolver carrying its own ``"CN": "metric"`` entry would satisfy every
    test above while leaving the pack inert. This one reads the pack file, so
    editing ``china_pack/config.py`` moves the answer.
    """
    from app.core.regional_packs import resolve_measurement_system
    from app.modules.china_pack.config import PACK_CONFIG

    assert resolve_measurement_system(country_code="CN") == PACK_CONFIG["measurement_system"]


@pytest.mark.parametrize(("country_code", "region"), [("CN", ""), ("cn", ""), ("", "CN")])
def test_china_resolves_by_country_and_by_region(country_code: str, region: str) -> None:
    """Both the ISO column and the free-text region marker have to reach the pack.

    The two Chinese demo projects this repository ships set ``region="CN"``, so
    the region fallback is not hypothetical - it is the path the seeded data
    takes.
    """
    from app.core.regional_packs import resolve_measurement_system

    assert resolve_measurement_system(country_code=country_code, region=region) == "metric"


def test_the_china_pack_declares_its_default_units_in_chinese() -> None:
    """The pack's own defaults have to be units the rule can read.

    ``russia_pack`` declaring its defaults in Cyrillic is precisely what made
    the rule blind on Russian bills, because the words it prescribed were words
    the rule did not know. A pack that prescribes units its own platform cannot
    check reintroduces that gap one market over, so the two are pinned together
    here rather than trusted to stay in step.
    """
    from app.core.validation.rules import _METRIC_BOQ_UNITS
    from app.modules.china_pack.config import PACK_CONFIG

    declared = PACK_CONFIG["default_units"]
    for dimension in ("length", "area", "volume", "weight"):
        unit = declared[dimension]
        assert unit in _METRIC_BOQ_UNITS, f"the pack prescribes {unit!r} for {dimension}, which the rule cannot read"
