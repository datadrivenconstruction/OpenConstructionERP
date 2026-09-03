# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""One request, several types.

A panel can need FDS *and* PLC programming *and* SCADA at once, so a
request carries a LIST. ``request_type`` stays as the first of it, which
is what every row raised before this and every caller that still sends
the singular relies on.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.work_requests import service
from tests._pg import transactional_session
from tests.modules.work_requests._helpers import make_project, make_user, raise_request, seeded


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.mark.asyncio
async def test_three_types_store_in_order_and_derive_the_singular(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        department="automation",
        request_type="",
        request_types=["fds", "plc_programming", "scada"],
        title="MCC-02 automation package",
    )
    assert req.request_types == ["fds", "plc_programming", "scada"], "the order chosen is the order kept"
    assert req.request_type == "fds", "the singular column is the FIRST of the list"

    out = await service.payload(session, req)
    assert out["request_types"] == ["fds", "plc_programming", "scada"]
    assert out["request_type"] == "fds"
    assert out["request_type_labels"] == ["FDS creation", "PLC programming", "SCADA"]
    # Every automation type carries the same two questions, so the union
    # of three of them is still those two - asked once, not three times.
    assert [f["key"] for f in out["field_specs"]] == ["planner_uploaded", "info_link"]


@pytest.mark.asyncio
async def test_the_field_union_dedupes_by_key_first_definition_winning(session: AsyncSession) -> None:
    depts = await seeded(session)
    await service.update_department(
        session,
        depts["engineering"],
        {
            "request_types": [
                {
                    "key": "alpha",
                    "label": "Alpha",
                    "disciplines": ["engineering"],
                    "fields": [
                        {"key": "shared", "label": "Asked by Alpha", "type": "text"},
                        {"key": "only_alpha", "label": "Only Alpha", "type": "number"},
                    ],
                },
                {
                    "key": "beta",
                    "label": "Beta",
                    "disciplines": ["drafting"],
                    "fields": [
                        {"key": "shared", "label": "Asked by Beta", "type": "date"},
                        {"key": "only_beta", "label": "Only Beta", "type": "text"},
                    ],
                },
            ]
        },
    )
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        department="engineering",
        request_type="",
        request_types=["alpha", "beta"],
        title="Feeder sizing",
        fields={"shared": "a plain string", "only_alpha": 3, "only_beta": "yes"},
        cost_centres={"drafting": "CC-200"},
    )
    out = await service.payload(session, req)
    assert [f["key"] for f in out["field_specs"]] == ["shared", "only_alpha", "only_beta"]
    assert out["field_specs"][0]["label"] == "Asked by Alpha", "first definition wins"
    assert out["fields"]["shared"] == "a plain string", "so 'shared' is validated as Alpha's text, not Beta's date"
    assert out["fields"]["only_alpha"] == 3.0 and out["fields"]["only_beta"] == "yes"
    assert out["cost_centres"] == {"drafting": "CC-200"}, "the disciplines are the union too"


@pytest.mark.asyncio
async def test_required_fields_of_every_chosen_type_are_enforced(session: AsyncSession) -> None:
    depts = await seeded(session)
    await service.update_department(
        session,
        depts["engineering"],
        {
            "request_types": [
                {"key": "alpha", "label": "Alpha", "fields": [{"key": "a_ref", "label": "A ref", "type": "text"}]},
                {
                    "key": "beta",
                    "label": "Beta",
                    "fields": [{"key": "b_ref", "label": "B ref", "type": "text", "required": True}],
                },
            ]
        },
    )
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    with pytest.raises(service.WorkRequestError, match="B ref"):
        await raise_request(
            session,
            project=proj,
            user=pm,
            department="engineering",
            request_type="",
            request_types=["alpha", "beta"],
            title="Needs B",
            fields={"a_ref": "only A"},
        )
    ok = await raise_request(
        session,
        project=proj,
        user=pm,
        department="engineering",
        request_type="",
        request_types=["alpha"],
        title="Alpha alone",
        fields={"a_ref": "only A"},
    )
    assert ok.request_types == ["alpha"], "Beta's required field is not Alpha's problem"


@pytest.mark.asyncio
async def test_the_legacy_singular_still_raises_and_reads_as_a_one_element_list(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)  # request_type="switchboard"
    assert req.request_type == "switchboard"
    assert req.request_types == ["switchboard"]
    out = await service.payload(session, req)
    assert out["request_types"] == ["switchboard"]
    assert out["request_type_labels"] == ["Switchboard"]


@pytest.mark.asyncio
async def test_a_row_written_before_the_column_existed_backfills_on_read(session: AsyncSession) -> None:
    """The boot column-heal adds ``request_types`` empty. Every such row
    must read back as ``[request_type]`` without a data migration."""
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(session, project=proj, user=pm)
    req.request_types = []  # exactly what the healed column holds
    await session.flush()

    assert service.type_keys_of(req) == ["switchboard"]
    out = await service.payload(session, req)
    assert out["request_types"] == ["switchboard"]
    assert out["request_type_labels"] == ["Switchboard"]
    assert [f["key"] for f in out["field_specs"]][:1] == ["factory_cost_centre"]
    found = await service.list_requests(session, project_ids=None, request_type="switchboard")
    assert [r.id for r in found] == [req.id], "the filter finds it by the singular alone"


@pytest.mark.asyncio
async def test_a_type_from_another_department_or_a_retired_one_is_refused(session: AsyncSession) -> None:
    depts = await seeded(session)
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)

    with pytest.raises(service.WorkRequestError, match="drafting_only"):
        await raise_request(
            session,
            project=proj,
            user=pm,
            department="automation",
            request_type="",
            request_types=["scada", "drafting_only"],
            title="Wrong department",
        )
    with pytest.raises(service.WorkRequestError, match="A request type is needed"):
        await raise_request(
            session, project=proj, user=pm, department="automation", request_type="", request_types=[], title="None"
        )
    with pytest.raises(service.WorkRequestError, match="At most 8"):
        await raise_request(
            session,
            project=proj,
            user=pm,
            department="automation",
            request_type="",
            request_types=[t["key"] for t in depts["automation"].request_types] + ["scada2"],
            title="Too many",
        )

    await service.update_request_type(session, depts["automation"], "scada", {"active": False})
    with pytest.raises(service.WorkRequestError, match="retired"):
        await raise_request(
            session,
            project=proj,
            user=pm,
            department="automation",
            request_type="",
            request_types=["fds", "scada"],
            title="Retired type",
        )


@pytest.mark.asyncio
async def test_patch_swaps_the_list_and_re_derives_the_singular(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        department="automation",
        request_type="",
        request_types=["fds", "scada"],
        title="MCC-02 automation package",
    )
    await service.update_request(
        session,
        req,
        {"request_types": ["plc_programming", "commissioning", "fds"]},
        user_id=str(pm.id),
        can_manage=True,
    )
    assert req.request_types == ["plc_programming", "commissioning", "fds"]
    assert req.request_type == "plc_programming", "the singular follows the new first"

    # The legacy singular on a PATCH collapses to a one-element list.
    await service.update_request(session, req, {"request_type": "scada"}, user_id=str(pm.id), can_manage=True)
    assert req.request_types == ["scada"] and req.request_type == "scada"

    with pytest.raises(service.WorkRequestError, match="switchboard"):
        await service.update_request(
            session, req, {"request_types": ["switchboard"]}, user_id=str(pm.id), can_manage=True
        )

    activity = await service.activity(session, req)
    assert any(a["what"] == "Edited" and "request types" in a["detail"] for a in activity)


@pytest.mark.asyncio
async def test_duplicates_collapse_and_order_is_preserved(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    req = await raise_request(
        session,
        project=proj,
        user=pm,
        department="automation",
        request_type="",
        request_types=["scada", "fds", "SCADA", "scada"],
        title="Duplicated",
    )
    assert req.request_types == ["scada", "fds"]


@pytest.mark.asyncio
async def test_the_filter_matches_any_member_of_the_list(session: AsyncSession) -> None:
    pm = await make_user(session, name="PM Example")
    proj = await make_project(session, owner=pm)
    multi = await raise_request(
        session,
        project=proj,
        user=pm,
        department="automation",
        request_type="",
        request_types=["fds", "plc_programming", "scada"],
        title="Whole package",
    )
    single = await raise_request(
        session, project=proj, user=pm, department="automation", request_type="scada", title="SCADA only"
    )
    other = await raise_request(
        session, project=proj, user=pm, department="automation", request_type="commissioning", title="Commissioning"
    )

    async def keys(**kw) -> set:
        return {r.id for r in await service.list_requests(session, project_ids=None, **kw)}

    assert await keys(request_type="scada") == {multi.id, single.id}, "membership, not equality"
    assert await keys(request_type="plc_programming") == {multi.id}
    assert await keys(request_types="scada,commissioning") == {multi.id, single.id, other.id}
    assert await keys(request_types="scada, fds") == {multi.id, single.id}
    assert await keys(request_type="drafting_only") == set()
    assert await keys(request_type="sc_da") == set(), "an underscore is a character, not a LIKE wildcard"
