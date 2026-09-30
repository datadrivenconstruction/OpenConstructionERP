# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Importing a bending schedule end to end (PostgreSQL).

Exercises the persistence layer against a real database: importing the whole
fixture corpus, reading the shapes back, recognising a re-sent file, summarising
steel by bar diameter, and re-exporting bytes the bending shop can compare
against what it received.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.rebar_schedule.service import RebarScheduleError, RebarScheduleService
from app.modules.rebar_schedule.validators import register_rules
from app.modules.users.models import User
from tests._pg import transactional_session
from tests.modules.rebar_schedule import abs_fixtures


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _rules() -> None:
    """The rule set is registered by the module's startup hook in production."""
    register_rules()


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"rebar-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Rebar",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Rebar {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def test_importing_the_whole_corpus_stores_every_shape(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)

    result = await service.import_file(project_id, "schedule.abs", abs_fixtures.fixture_file())

    stored = result["import_record"]
    assert result["duplicate"] is False
    assert stored.record_count == len(abs_fixtures.RECORDS)
    assert stored.encoding == "ascii"

    shapes, total = await service.list_shapes(stored.id, limit=1000)
    assert total == len(abs_fixtures.RECORDS)
    assert [shape.line_no for shape in shapes] == list(range(1, total + 1))
    assert all(shape.checksum_ok for shape in shapes)
    assert {shape.super_group for shape in shapes} == {"BF2D", "BF3D", "BFWE", "BFMA", "BFGT", "BFAU"}


async def test_header_fields_land_in_the_columns_they_belong_to(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    record = abs_fixtures.RECORDS["bar-with-one-bend"]
    result = await service.import_file(project_id, "one.abs", (record + "\r\n").encode())

    shapes, _ = await service.list_shapes(result["import_record"].id)
    shape = shapes[0]
    assert shape.project_ref == "OCE-DEMO"
    assert shape.drawing_ref == "312"
    assert shape.drawing_index == "b"
    assert shape.position == "1"
    assert shape.length_mm == Decimal("1000.00")
    assert shape.quantity == 10
    assert shape.weight_kg == Decimal("0.8880")
    assert shape.diameter_mm == Decimal("12.00")
    assert shape.steel_grade == "B500B"
    assert shape.bending_roller_mm == Decimal("48.00")
    assert shape.block_layout == "HGC"
    assert shape.geometry["kind"] == "segments"
    assert [seg["length_mm"] for seg in shape.geometry["segments"]] == ["300", "700"]


async def test_a_mesh_records_which_axis_was_bent(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    record = abs_fixtures.RECORDS["bent-drawn-mesh"]
    result = await service.import_file(project_id, "mesh.abs", (record + "\r\n").encode())

    shapes, _ = await service.list_shapes(result["import_record"].id)
    assert shapes[0].geometry["bent_axis"] == "y"
    assert shapes[0].block_layout == "HGyYYXXC"


async def test_a_spatial_bar_stores_its_vertices(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    result = await service.import_file(
        project_id,
        "spatial.abs",
        (abs_fixtures.RECORDS["spatial-bar"] + "\r\n").encode(),
    )

    shapes, _ = await service.list_shapes(result["import_record"].id)
    assert shapes[0].geometry["kind"] == "coordinates"
    assert len(shapes[0].geometry["vertices"]) == 5


async def test_the_total_weight_multiplies_each_shape_by_its_count(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    # Ten bars weighing 0.888 kg each.
    record = abs_fixtures.RECORDS["bar-with-one-bend"]
    result = await service.import_file(project_id, "one.abs", (record + "\r\n").encode())
    assert result["import_record"].total_weight_kg == Decimal("8.880")


async def test_re_sending_the_same_file_is_recognised_rather_than_duplicated(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    data = abs_fixtures.fixture_file()

    first = await service.import_file(project_id, "schedule.abs", data)
    second = await service.import_file(project_id, "schedule-resent.abs", data)

    assert second["duplicate"] is True
    assert second["import_record"].id == first["import_record"].id
    assert second["import_record"].filename == "schedule.abs"
    imports, total = await service.list_imports(project_id)
    assert total == 1
    assert len(imports) == 1


async def test_the_same_file_may_be_imported_into_a_second_project(session: AsyncSession) -> None:
    """The duplicate check is per project, not global."""
    service = RebarScheduleService(session)
    data = abs_fixtures.fixture_file()
    first_project = await _project(session)
    second_project = await _project(session)

    await service.import_file(first_project, "schedule.abs", data)
    second = await service.import_file(second_project, "schedule.abs", data)

    assert second["duplicate"] is False


async def test_exporting_returns_the_bytes_that_came_in(session: AsyncSession) -> None:
    """A checksum covers exact characters, so a re-render is not the same file."""
    project_id = await _project(session)
    service = RebarScheduleService(session)
    data = abs_fixtures.fixture_file()
    result = await service.import_file(project_id, "schedule.abs", data)

    assert await service.export(result["import_record"].id) == data


async def test_exporting_one_super_group_writes_only_those_shapes(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    result = await service.import_file(project_id, "schedule.abs", abs_fixtures.fixture_file())

    meshes = await service.export(result["import_record"].id, super_group="BFMA")
    lines = meshes.decode("ascii").splitlines()
    assert lines
    assert all(line.startswith("BFMA@") for line in lines)


async def test_the_cutting_summary_groups_bars_and_weight_by_diameter(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    result = await service.import_file(project_id, "schedule.abs", abs_fixtures.fixture_file())

    summary = await service.cutting_summary(result["import_record"].id)
    by_diameter = {row["diameter_mm"]: row for row in summary}
    # Most of the corpus is 12 mm. The meshes, the accessories and the lattice
    # girder carry no diameter in the header and are excluded rather than
    # counted as zero.
    assert "12.00" in by_diameter
    assert by_diameter["12.00"]["bars"] > 0
    assert by_diameter["12.00"]["weight_kg"] > 0
    assert all(row["diameter_mm"] is not None for row in summary)


async def test_a_file_that_fails_validation_is_still_stored_and_marked(session: AsyncSession) -> None:
    """Refusing it would leave the operator with a report and nothing to point at."""
    project_id = await _project(session)
    service = RebarScheduleService(session)
    damaged = abs_fixtures.RECORDS["bar-with-one-bend"].replace("@l1000@", "@l1001@")

    result = await service.import_file(project_id, "damaged.abs", (damaged + "\r\n").encode())

    stored = result["import_record"]
    assert stored.validation_status == "errors"
    assert stored.error_count >= 1
    assert result["validation"]["findings"]
    shapes, total = await service.list_shapes(stored.id)
    assert total == 1
    assert shapes[0].checksum_ok is False


async def test_a_clean_file_reports_no_findings(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    record = abs_fixtures.RECORDS["bar-with-one-bend"]
    result = await service.import_file(project_id, "one.abs", (record + "\r\n").encode())

    assert result["import_record"].validation_status == "passed"
    assert result["validation"]["findings"] == []


async def test_unreadable_content_is_refused_with_the_line_that_broke(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)

    with pytest.raises(RebarScheduleError, match="line 2"):
        await service.import_file(project_id, "bad.abs", b"BF2D@Hj@r@i@p@l@n@e@d@g@s@v@C69@\r\nnot-a-record\r\n")


async def test_deleting_an_import_takes_its_shapes_with_it(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)
    result = await service.import_file(project_id, "schedule.abs", abs_fixtures.fixture_file())
    import_id = result["import_record"].id

    await service.delete_import(import_id)

    _, remaining = await service.list_imports(project_id)
    assert remaining == 0
    shapes, total = await service.list_shapes(import_id)
    assert (shapes, total) == ([], 0)


async def test_a_dry_run_stores_nothing(session: AsyncSession) -> None:
    project_id = await _project(session)
    service = RebarScheduleService(session)

    preview = await service.preview(abs_fixtures.fixture_file().decode("ascii"))

    assert preview["record_count"] == len(abs_fixtures.RECORDS)
    assert preview["shapes"][0]["super_group"] == "BF2D"
    assert preview["validation"]["status"] == "errors"
    _, stored = await service.list_imports(project_id)
    assert stored == 0


async def test_the_dry_run_reports_the_one_finding_the_corpus_carries(session: AsyncSession) -> None:
    """The corpus keeps one record whose header is short by two fields.

    It is there so this path has something to go red on, and so a reader who
    sees the import report an error can find out why without re-deriving it.
    """
    service = RebarScheduleService(session)
    preview = await service.preview(abs_fixtures.fixture_file().decode("ascii"))

    findings = preview["validation"]["findings"]
    assert [item["rule_id"] for item in findings] == ["bvbs_abs.header_field_order"]
    assert "e, v" in findings[0]["message"]


def _cp1252_record() -> bytes:
    """One record whose drawing field holds a cp1252 umlaut, with the checksum right for it."""
    from app.modules.rebar_schedule.abs_format import compute_checksum

    base = abs_fixtures.RECORDS["bar-with-one-bend"]
    record = base.replace("@r312@", "@rBügel@")
    prefix = record[: record.rindex("@C") + 2]
    return (prefix + str(compute_checksum(prefix)) + "@\r\n").encode("cp1252")


async def test_a_dry_run_on_bytes_reads_the_file_as_the_import_does(session: AsyncSession) -> None:
    """Preview and import must decode one file the same way, or the preview lies about checksums.

    A browser decoding these bytes as UTF-8 turns the umlaut into U+FFFD, whose
    code point shifts the checksum sum, so the text preview flagged a record
    the import stores as sound.
    """
    project_id = await _project(session)
    service = RebarScheduleService(session)
    data = _cp1252_record()

    preview = await service.preview(data)
    imported = await service.import_file(project_id, "buegel.abs", data)
    shapes, _ = await service.list_shapes(imported["import_record"].id)

    assert preview["encoding"] == imported["import_record"].encoding == "cp1252"
    assert preview["shapes"][0]["checksum_ok"] is True
    assert shapes[0].checksum_ok is True
    assert preview["shapes"][0]["drawing_ref"] == shapes[0].drawing_ref == "Bügel"

    # What the old browser-decoded path sent, kept here as the reason for the above.
    garbled = await service.preview(data.decode("utf-8", errors="replace"))
    assert garbled["shapes"][0]["checksum_ok"] is False
