"""Unit tests for ``BIMHubService.get_model_schema`` (RFC 24).

The endpoint feeds the quantity-rule editor combobox options from the
selected BIM model. Every scenario below targets a promise made in the RFC:
empty collections on empty models, dedup, null-value exclusion, 404 on
unknown models, and the 1000-distinct-value per-property cap.

Repositories are stubbed — no database needed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.bim_hub.service import BIMHubService

# ── Stubs ─────────────────────────────────────────────────────────────────


class _StubModelRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def get(self, model_id: uuid.UUID) -> Any:
        return self.rows.get(model_id)


class _StubElementRepo:
    def __init__(self) -> None:
        self.rows_by_model: dict[uuid.UUID, list[Any]] = {}

    async def list_for_model(
        self,
        model_id: uuid.UUID,
        *,
        element_type: str | None = None,  # noqa: ARG002
        storey: str | None = None,  # noqa: ARG002
        discipline: str | None = None,  # noqa: ARG002
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[Any], int]:
        rows = self.rows_by_model.get(model_id, [])
        return rows[offset : offset + limit], len(rows)


def _make_service() -> tuple[BIMHubService, _StubModelRepo, _StubElementRepo]:
    """Build a service wired up with stub repos only.

    Uses ``__new__`` so the real ``__init__`` (which expects an
    ``AsyncSession``) never runs.
    """
    service = BIMHubService.__new__(BIMHubService)
    model_repo = _StubModelRepo()
    element_repo = _StubElementRepo()
    service.session = None  # type: ignore[attr-defined]
    service.model_repo = model_repo  # type: ignore[attr-defined]
    service.element_repo = element_repo  # type: ignore[attr-defined]
    return service, model_repo, element_repo


def _register_model(
    model_repo: _StubModelRepo,
    element_repo: _StubElementRepo,
    elements: list[dict[str, Any]],
) -> uuid.UUID:
    model_id = uuid.uuid4()
    model_repo.rows[model_id] = SimpleNamespace(
        id=model_id,
        element_count=len(elements),
    )
    element_repo.rows_by_model[model_id] = [SimpleNamespace(**e) for e in elements]
    return model_id


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_model_returns_empty_collections() -> None:
    service, model_repo, element_repo = _make_service()
    model_id = _register_model(model_repo, element_repo, [])

    schema = await service.get_model_schema(model_id)

    assert schema.distinct_types == []
    assert schema.property_keys == {}
    assert schema.property_keys_truncated == {}
    assert schema.element_count == 0
    # Quantity presets always present regardless of the element set.
    assert schema.available_quantities == [
        "area_m2",
        "volume_m3",
        "length_m",
        "weight_kg",
        "count",
    ]


@pytest.mark.asyncio
async def test_duplicate_types_and_values_are_deduped() -> None:
    service, model_repo, element_repo = _make_service()
    model_id = _register_model(
        model_repo,
        element_repo,
        [
            {"element_type": "Wall", "properties": {"material": "concrete"}},
            {"element_type": "Wall", "properties": {"material": "concrete"}},
            {"element_type": "Floor", "properties": {"material": "steel"}},
            {"element_type": "Wall", "properties": {"material": "steel"}},
        ],
    )

    schema = await service.get_model_schema(model_id)

    assert schema.distinct_types == ["Floor", "Wall"]
    assert schema.property_keys == {"material": ["concrete", "steel"]}
    assert schema.property_keys_truncated == {"material": False}
    assert schema.element_count == 4


@pytest.mark.asyncio
async def test_null_property_values_are_excluded() -> None:
    service, model_repo, element_repo = _make_service()
    model_id = _register_model(
        model_repo,
        element_repo,
        [
            {
                "element_type": "Wall",
                "properties": {"material": "concrete", "fire_rating": None},
            },
            {
                "element_type": "Wall",
                "properties": {"material": None, "fire_rating": "F90"},
            },
        ],
    )

    schema = await service.get_model_schema(model_id)

    assert schema.property_keys == {
        "material": ["concrete"],
        "fire_rating": ["F90"],
    }
    # Keys are still reported (a consumer can still offer the key in the
    # combobox) but with only the non-null observed values.
    assert "material" in schema.property_keys_truncated
    assert "fire_rating" in schema.property_keys_truncated


@pytest.mark.asyncio
async def test_missing_model_raises_404() -> None:
    service, _model_repo, _element_repo = _make_service()

    with pytest.raises(HTTPException) as exc_info:
        await service.get_model_schema(uuid.uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_elements_without_element_type_are_skipped() -> None:
    service, model_repo, element_repo = _make_service()
    model_id = _register_model(
        model_repo,
        element_repo,
        [
            {"element_type": None, "properties": {"material": "concrete"}},
            {"element_type": "Wall", "properties": {"material": "steel"}},
            {"element_type": "", "properties": {}},
        ],
    )

    schema = await service.get_model_schema(model_id)

    # Only the one real element_type contributes.
    assert schema.distinct_types == ["Wall"]
    # Properties are still aggregated across every element with a dict.
    assert schema.property_keys == {"material": ["concrete", "steel"]}


@pytest.mark.asyncio
async def test_truncation_cap_applied_when_over_1000_values() -> None:
    service, model_repo, element_repo = _make_service()
    # 1500 distinct values for ``serial_no`` → should cap at 1000.
    elements = [
        {
            "element_type": "Fixture",
            "properties": {"serial_no": f"SN-{i:05d}", "vendor": "Acme"},
        }
        for i in range(1500)
    ]
    model_id = _register_model(model_repo, element_repo, elements)

    schema = await service.get_model_schema(model_id)

    assert len(schema.property_keys["serial_no"]) == 1000
    assert schema.property_keys_truncated["serial_no"] is True
    # Sorted alphabetically — ``SN-00000`` is first after the ASCII sort.
    assert schema.property_keys["serial_no"][0] == "SN-00000"
    assert schema.property_keys["serial_no"][-1] == "SN-00999"
    # ``vendor`` only has one value → not truncated.
    assert schema.property_keys["vendor"] == ["Acme"]
    assert schema.property_keys_truncated["vendor"] is False
