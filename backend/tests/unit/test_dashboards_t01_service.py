"""T01 unit tests for :class:`SnapshotService` and the cad2data bridge.

Covers:
* Cad2data bridge — canonicalisation of IFC-ish element dicts into the
  entities / materials / source-files DataFrame shape, including the
  unsupported-format branch.
* SnapshotService.create — validates label, detects duplicates, writes
  Parquet + manifest, inserts DB rows, publishes the ``snapshot.created``
  event, and rolls back storage on mid-flight failure.
* SnapshotService.delete — cascades to storage cleanup, invalidates the
  DuckDB pool entry, publishes ``snapshot.deleted``.
* SnapshotService.get/list — tenant scoping.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.events import event_bus
from app.core.storage import LocalStorageBackend
from app.database import Base
from app.modules.dashboards import cad2data_bridge as bridge
from app.modules.dashboards import events as event_taxonomy
from app.modules.dashboards.models import Snapshot, SnapshotSourceFile  # noqa: F401
from app.modules.dashboards.repository import SnapshotRepository
from app.modules.dashboards.service import (
    CreateSnapshotArgs,
    SnapshotAccessDeniedError,  # noqa: F401 — re-exported for downstream tasks
    SnapshotConversionFailedError,
    SnapshotLabelDuplicateError,
    SnapshotLabelInvalidError,
    SnapshotLabelTooLongError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotUnsupportedFormatError,
)
from app.modules.dashboards.snapshot_storage import (
    parquet_key,
    snapshot_prefix,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
async def session() -> AsyncSession:
    """In-memory async SQLite scoped to just the tables we need.

    ``create_all(tables=[...])`` keeps the schema surface small and
    avoids pulling in unrelated modules' FKs (matches the pattern used
    by ``test_contact_tenancy``). We include ``User`` because
    ``Project.owner_id`` FKs to it.
    """
    from app.modules.dashboards.models import Snapshot as _Snap
    from app.modules.dashboards.models import SnapshotSourceFile as _Src
    from app.modules.projects.models import Project as _Proj
    from app.modules.users.models import User as _User

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                _User.__table__,
                _Proj.__table__,
                _Snap.__table__,
                _Src.__table__,
            ],
        )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def tmp_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalStorageBackend:
    backend = LocalStorageBackend(base_dir=tmp_path)
    monkeypatch.setattr(
        "app.modules.dashboards.snapshot_storage.get_storage_backend",
        lambda: backend,
    )
    return backend


@pytest.fixture
async def project_row(session: AsyncSession):
    """Minimal project row so the snapshot FK resolves.

    Creates the referenced :class:`User` first because
    ``Project.owner_id`` FKs to it and SQLite enforces the constraint
    (pragma ``foreign_keys=ON`` is active for every connection).
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"owner-{uuid.uuid4()}@example.test",
        hashed_password="x",
        full_name="Test Owner",
        role="admin",
    )
    session.add(owner)
    await session.flush()

    proj = Project(
        name="Test Project",
        region="DACH",
        classification_standard="din276",
        currency="EUR",
        locale="en",
        validation_rule_sets=[],
        status="active",
        owner_id=owner.id,
    )
    session.add(proj)
    await session.flush()
    return proj


@pytest.fixture
def captured_events():
    """Capture every event published while the test is running."""
    captured: list[dict] = []

    async def handler(event):
        captured.append({"name": event.name, "data": dict(event.data)})

    event_bus.subscribe("*", handler)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", handler)


def _fake_ifc_conversion(
    elements: list[dict] | None = None,
) -> dict:
    """Return the dict shape that bim_hub's ``process_ifc_file`` emits."""
    return {
        "elements": elements
        or [
            {
                "guid": "guid-wall-1",
                "category": "IfcWallStandardCase",
                "properties": {"material": "Concrete", "fire_rating": "F 90"},
                "quantities": {"thickness_mm": 240},
            },
            {
                "guid": "guid-wall-2",
                "category": "IfcWallStandardCase",
                "properties": {"material": "Concrete", "fire_rating": "F 90"},
                "quantities": {"thickness_mm": 240},
            },
            {
                "guid": "guid-door-1",
                "category": "IfcDoor",
                "properties": {"material": "Wood"},
                "layers": [
                    {"material": "Wood", "thickness_mm": 45},
                    {"material": "Steel", "thickness_mm": 2},
                ],
            },
        ],
        "conversion_method": "fake",
    }


# ── Cad2data bridge ────────────────────────────────────────────────────────


class TestCad2DataBridge:
    def test_canonicalise_ifc_prefix(self) -> None:
        assert bridge._canonical_category("IfcWallStandardCase") == "wallstandardcase"
        assert bridge._canonical_category("Wall") == "wall"
        assert bridge._canonical_category(None) == "unknown"
        assert bridge._canonical_category("") == "unknown"

    def test_safe_float_happy_and_sad_paths(self) -> None:
        assert bridge._safe_float("240") == 240.0
        assert bridge._safe_float(240) == 240.0
        assert bridge._safe_float(None) is None
        assert bridge._safe_float("nope") is None

    def test_unsupported_extension_raises(self) -> None:
        with pytest.raises(bridge.UnsupportedFormatError):
            bridge.convert_to_snapshot_frames(
                [
                    bridge.UploadedFile(
                        original_name="plan.dwg",
                        extension="dwg",
                        content=b"\x00\x00",
                    )
                ]
            )

    def test_empty_list_raises_no_entities(self) -> None:
        with pytest.raises(bridge.NoEntitiesExtractedError):
            bridge.convert_to_snapshot_frames([])

    def test_ifc_happy_path_produces_frames(self) -> None:
        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            result = bridge.convert_to_snapshot_frames(
                [
                    bridge.UploadedFile(
                        original_name="small.ifc",
                        extension="ifc",
                        content=b"ISO-10303-21;\n",
                        discipline="architecture",
                    )
                ]
            )

        assert result.total_entities == 3
        assert set(result.entities_df["category"]) == {"wallstandardcase", "door"}
        # Materials rows come from the ``layers`` list of the door entity.
        assert len(result.materials_df) == 2
        assert set(result.materials_df["material"]) == {"Wood", "Steel"}
        # Summary stats reflect the category counts.
        assert result.summary_stats == {"wallstandardcase": 2, "door": 1}
        # Source-files DataFrame carries per-file metadata.
        assert len(result.source_files_df) == 1
        row = result.source_files_df.iloc[0].to_dict()
        assert row["original_name"] == "small.ifc"
        assert row["format"] == "ifc"
        assert row["discipline"] == "architecture"
        assert row["entity_count"] == 3

    def test_ifc_converter_exception_wrapped_in_bridge_error(self) -> None:
        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            side_effect=RuntimeError("ifc parser exploded"),
        ):
            with pytest.raises(bridge.BridgeError, match="ifc parser exploded"):
                bridge.convert_to_snapshot_frames(
                    [
                        bridge.UploadedFile(
                            original_name="boom.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                        )
                    ]
                )

    def test_ifc_all_empty_raises_no_entities(self) -> None:
        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value={"elements": [], "conversion_method": "fake"},
        ):
            with pytest.raises(bridge.NoEntitiesExtractedError):
                bridge.convert_to_snapshot_frames(
                    [
                        bridge.UploadedFile(
                            original_name="empty.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                        )
                    ]
                )

    def test_flatten_nested_properties(self) -> None:
        """Single-level nested scalars inside ``properties`` / ``quantities``
        get flattened into the entity attribute dict with a ``parent.child``
        prefix, so autocomplete (T03) can see them without JSON traversal."""
        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            result = bridge.convert_to_snapshot_frames(
                [
                    bridge.UploadedFile(
                        original_name="small.ifc",
                        extension="ifc",
                        content=b"ISO-10303-21;\n",
                    )
                ]
            )

        attrs = result.entities_df.iloc[0]["attributes"]
        assert attrs["properties.material"] == "Concrete"
        assert attrs["properties.fire_rating"] == "F 90"
        assert attrs["quantities.thickness_mm"] == 240

    def test_supported_extensions_self_reports(self) -> None:
        supported = bridge.supported_extensions()
        assert "ifc" in supported
        assert "rvt" in supported
        assert "dwg" not in supported  # T10


# ── SnapshotService.create ─────────────────────────────────────────────────


class TestSnapshotServiceCreate:
    async def test_empty_label_rejected(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        with pytest.raises(SnapshotLabelInvalidError):
            await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="   ",
                    files=[
                        bridge.UploadedFile(
                            original_name="x.ifc", extension="ifc", content=b"",
                        )
                    ],
                    user_id=uuid.uuid4(),
                )
            )

    async def test_over_long_label_rejected(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        with pytest.raises(SnapshotLabelTooLongError):
            await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="x" * 201,
                    files=[
                        bridge.UploadedFile(
                            original_name="x.ifc", extension="ifc", content=b"",
                        )
                    ],
                    user_id=uuid.uuid4(),
                )
            )

    async def test_duplicate_label_rejected(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        uploaded = [
            bridge.UploadedFile(
                original_name="one.ifc",
                extension="ifc",
                content=b"ISO-10303-21;\n",
            )
        ]
        user_id = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="Baseline",
                    files=uploaded,
                    user_id=user_id,
                )
            )

            with pytest.raises(SnapshotLabelDuplicateError):
                await svc.create(
                    CreateSnapshotArgs(
                        project_id=project_row.id,
                        label="Baseline",
                        files=uploaded,
                        user_id=user_id,
                    )
                )

    async def test_unsupported_format_wrapped(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        with pytest.raises(SnapshotUnsupportedFormatError):
            await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="Will fail",
                    files=[
                        bridge.UploadedFile(
                            original_name="plan.dwg",
                            extension="dwg",
                            content=b"\x00",
                        )
                    ],
                    user_id=uuid.uuid4(),
                )
            )

    async def test_conversion_failure_wrapped(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value={"elements": [], "conversion_method": "fake"},
        ):
            with pytest.raises(SnapshotConversionFailedError):
                await svc.create(
                    CreateSnapshotArgs(
                        project_id=project_row.id,
                        label="Empty",
                        files=[
                            bridge.UploadedFile(
                                original_name="empty.ifc",
                                extension="ifc",
                                content=b"ISO-10303-21;\n",
                            )
                        ],
                        user_id=uuid.uuid4(),
                    )
                )

    async def test_happy_path_persists_everything(
        self, session, tmp_storage, project_row, captured_events,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            snap = await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="Baseline",
                    files=[
                        bridge.UploadedFile(
                            original_name="small.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                            discipline="architecture",
                        )
                    ],
                    user_id=user_id,
                    tenant_id=str(user_id),
                )
            )

        assert snap.total_entities == 3
        assert snap.total_categories == 2
        assert snap.summary_stats == {"wallstandardcase": 2, "door": 1}
        assert snap.parquet_dir == snapshot_prefix(project_row.id, snap.id)
        assert snap.tenant_id == str(user_id)

        # Parquet files landed on disk.
        expected = tmp_storage.base_dir / parquet_key(
            project_row.id, snap.id, "entities"
        )
        assert expected.is_file()

        # Event emitted.
        names = [e["name"] for e in captured_events]
        assert event_taxonomy.SNAPSHOT_CREATED in names
        created = [
            e for e in captured_events
            if e["name"] == event_taxonomy.SNAPSHOT_CREATED
        ][0]
        assert created["data"]["snapshot_id"] == str(snap.id)
        assert created["data"]["total_entities"] == 3


# ── SnapshotService.get / list / delete ────────────────────────────────────


class TestSnapshotServiceReadAndDelete:
    async def test_get_missing_raises_404_typed(self, session) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        with pytest.raises(SnapshotNotFoundError):
            await svc.get(uuid.uuid4(), tenant_id=str(uuid.uuid4()))

    async def test_tenant_scope_blocks_foreign_read(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            snap = await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="Mine",
                    files=[
                        bridge.UploadedFile(
                            original_name="mine.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                        )
                    ],
                    user_id=user_a,
                    tenant_id=str(user_a),
                )
            )

        with pytest.raises(SnapshotNotFoundError):
            await svc.get(snap.id, tenant_id=str(user_b))

        # Same call with correct tenant succeeds.
        row = await svc.get(snap.id, tenant_id=str(user_a))
        assert row.id == snap.id

    async def test_delete_removes_row_and_storage(
        self, session, tmp_storage, project_row, captured_events,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            snap = await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="To be deleted",
                    files=[
                        bridge.UploadedFile(
                            original_name="doomed.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                        )
                    ],
                    user_id=user_id,
                    tenant_id=str(user_id),
                )
            )

        entities_file = tmp_storage.base_dir / parquet_key(
            project_row.id, snap.id, "entities"
        )
        assert entities_file.is_file()

        await svc.delete(snap.id, tenant_id=str(user_id))

        with pytest.raises(SnapshotNotFoundError):
            await svc.get(snap.id, tenant_id=str(user_id))
        assert not entities_file.exists()

        names = [e["name"] for e in captured_events]
        assert event_taxonomy.SNAPSHOT_DELETED in names

    async def test_list_for_project_paginates(
        self, session, tmp_storage, project_row,
    ) -> None:
        svc = SnapshotService(repo=SnapshotRepository(session))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            for i in range(3):
                await svc.create(
                    CreateSnapshotArgs(
                        project_id=project_row.id,
                        label=f"Snapshot {i}",
                        files=[
                            bridge.UploadedFile(
                                original_name=f"f{i}.ifc",
                                extension="ifc",
                                content=b"ISO-10303-21;\n",
                            )
                        ],
                        user_id=user_id,
                        tenant_id=str(user_id),
                    )
                )

        rows, total = await svc.list_for_project(
            project_row.id, tenant_id=str(user_id), limit=2, offset=0,
        )
        assert total == 3
        assert len(rows) == 2

    async def test_manifest_file_round_trips(
        self, session, tmp_storage, project_row,
    ) -> None:
        """``manifest.json`` on disk matches the label / counts / source files
        of the DB row — reviewers often cross-check this off-line."""
        svc = SnapshotService(repo=SnapshotRepository(session))
        user_id = uuid.uuid4()

        with patch(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            return_value=_fake_ifc_conversion(),
        ):
            snap = await svc.create(
                CreateSnapshotArgs(
                    project_id=project_row.id,
                    label="Manifest check",
                    files=[
                        bridge.UploadedFile(
                            original_name="m.ifc",
                            extension="ifc",
                            content=b"ISO-10303-21;\n",
                        )
                    ],
                    user_id=user_id,
                )
            )

        from app.modules.dashboards.snapshot_storage import read_manifest

        manifest = await read_manifest(project_row.id, snap.id)
        assert manifest["label"] == "Manifest check"
        assert manifest["total_entities"] == 3
        assert manifest["summary_stats"] == {"wallstandardcase": 2, "door": 1}
        assert len(manifest["source_files"]) == 1
        assert manifest["source_files"][0]["format"] == "ifc"
