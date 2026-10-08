# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bill's tax date is its own field, and it follows the base date until set.

The defect
----------
``BOQ.base_date`` carried two meanings. It is the price level reference, the
day the unit rates are current at, and it was also the day the bill's VAT was
resolved on. Those are different days often enough to matter: an estimate
priced off a 2025 rate book for works carried out in 2026 is common, and in
Russia the standard rate moved from 20 to 22 on 2026-01-01. Such a bill was
seeded at 20 because its price base said 2025, while the works it prices are
taxed at 22.

The fix
-------
``BOQ.tax_date`` is a separate, nullable field. The tax lookup reads
``tax_date`` when it is stated and ``base_date`` otherwise, through
:func:`app.modules.boq.base_date.tax_point`, so a bill that never states a tax
date (every bill that existed before the column) is taxed exactly as before.
Price-level readers keep reading ``base_date`` and are not touched.

These tests drive ``BOQService.apply_default_markups``, the path the product
uses, with the stored rows stubbed and the shipped Russian seed windows on the
tax table. The PG lane holds the same case against stored rows in
``tests/pg/test_a_bill_is_priced_at_its_own_countrys_vat.py``.
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.validation.engine import ValidationContext
from app.core.validation.messages import is_key_present
from app.core.validation.rules import BOQBaseDateReadable
from app.modules.boq import service as boq_service_module
from app.modules.boq.base_date import tax_point
from app.modules.boq.models import BOQ
from app.modules.boq.repository import BOQ_HEADER_COLUMNS
from app.modules.boq.schemas import BOQCreate, BOQResponse, BOQUpdate
from app.modules.boq.service import BOQService
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import row_from_mapping

_BACKEND = Path(__file__).resolve().parents[2]


# ── The service path, stubbed at the storage edge ───────────────────────────


class _SeedTaxRepo:
    """Stands in for ``TaxConfigRepository``: the shipped seed rows for one country."""

    def __init__(self, _session: Any) -> None:
        pass

    async def list(self, *, country_code: str) -> list[Any]:
        # ``row_from_orm`` reads attributes, and a flattened seed row carries
        # every one it reads under the same name.
        return [row_from_mapping(row) for row in load_tax_seed_rows() if row["country_code"] == country_code]


class _MarkupSink:
    """Captures what ``apply_default_markups`` would have written."""

    def __init__(self) -> None:
        self.created: list[Any] = []

    async def list_for_boq(self, _boq_id: uuid.UUID) -> list[Any]:
        return list(self.created)

    async def delete_all_for_boq(self, _boq_id: uuid.UUID, keep: list[Any] | None = None) -> None:
        return None

    async def bulk_create(self, markups: list[Any]) -> list[Any]:
        self.created = list(markups)
        return self.created


async def _seeded_tax_line(monkeypatch: pytest.MonkeyPatch, *, base_date: str | None, tax_date: str | None) -> Any:
    """Seed default markups on a Russian bill and return its single tax line."""
    boq = SimpleNamespace(id=uuid.uuid4(), base_date=base_date, tax_date=tax_date)
    project = SimpleNamespace(default_vat_rate=None, country_code="RU")

    svc = BOQService.__new__(BOQService)
    svc.session = object()
    svc.markup_repo = _MarkupSink()

    async def _ensure_not_locked(_boq_id: uuid.UUID) -> Any:
        return boq

    async def _project_for_boq(_boq_id: uuid.UUID) -> Any:
        return project

    async def _no_publish(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(svc, "_ensure_not_locked", _ensure_not_locked)
    monkeypatch.setattr(svc, "project_for_boq", _project_for_boq)
    monkeypatch.setattr(boq_service_module, "TaxConfigRepository", _SeedTaxRepo)
    monkeypatch.setattr(boq_service_module, "_safe_publish", _no_publish)

    await svc.apply_default_markups(boq.id)
    lines = [m for m in svc.markup_repo.created if m.category == "tax"]
    assert len(lines) == 1, f"a Russian bill carries one tax line, got {len(lines)}"
    return lines[0]


async def test_a_bill_priced_to_2025_for_works_in_2026_is_charged_2026s_rate(monkeypatch) -> None:
    """The case that motivated the field: 2025 rates, 2026 works, 22 percent."""
    line = await _seeded_tax_line(monkeypatch, base_date="2025-06", tax_date="2026-01-01")
    assert Decimal(line.percentage) == Decimal("22"), (
        f"a bill whose tax date is 2026-01-01 was charged {line.percentage}; the price base "
        f"(2025-06) still decided its tax rate"
    )
    assert line.metadata_["vat_rate_source"] == "country_seed"


async def test_a_bill_that_states_no_tax_date_is_taxed_on_its_base_date_as_before(monkeypatch) -> None:
    """Every bill that existed before the column: nothing about it moves."""
    line = await _seeded_tax_line(monkeypatch, base_date="2025-06", tax_date=None)
    assert Decimal(line.percentage) == Decimal("20")


@pytest.mark.parametrize("blank", ["", "   "])
async def test_a_blank_tax_date_follows_the_base_date(monkeypatch, blank: str) -> None:
    """A cleared field means "same as the price base", not "today"."""
    line = await _seeded_tax_line(monkeypatch, base_date="2025-06", tax_date=blank)
    assert Decimal(line.percentage) == Decimal("20")


async def test_a_tax_date_earlier_than_the_price_base_wins_too(monkeypatch) -> None:
    """The other direction, so the fix is not "the later of the two dates"."""
    line = await _seeded_tax_line(monkeypatch, base_date="2026-Q1", tax_date="2025-Q4")
    assert Decimal(line.percentage) == Decimal("20")


# ── The one rule for which field decides ────────────────────────────────────


@pytest.mark.parametrize(
    ("tax_date", "base_date", "expected"),
    [
        ("2026-01-01", "2025-06", ("tax_date", "2026-01-01")),
        ("  2026-Q1 ", "2025", ("tax_date", "2026-Q1")),
        (None, "2025-06", ("base_date", "2025-06")),
        ("", "2025-06", ("base_date", "2025-06")),
        ("   ", None, ("base_date", None)),
        (None, None, ("base_date", None)),
    ],
)
def test_tax_point_names_the_field_it_read(
    tax_date: str | None, base_date: str | None, expected: tuple[str, str | None]
) -> None:
    assert tax_point(tax_date, base_date) == expected


# ── The field travels through the model, the read path and the API ──────────


def test_the_column_is_nullable_free_text_like_base_date() -> None:
    column = BOQ.__table__.c.tax_date
    assert column.nullable, "NULL is how a bill says its tax date follows its base date"
    assert column.type.length == BOQ.__table__.c.base_date.type.length


def test_the_full_bill_read_selects_the_tax_date() -> None:
    assert "tax_date" in {c.key for c in BOQ_HEADER_COLUMNS}


@pytest.mark.parametrize("stated", ["2026-03-15", "2026-03", "2026-Q1", "2026"])
def test_the_api_accepts_every_shape_the_tax_lookup_reads(stated: str) -> None:
    pid = uuid.uuid4()
    assert BOQCreate(project_id=pid, name="B", tax_date=stated).tax_date == stated
    assert BOQUpdate(tax_date=stated).tax_date == stated


@pytest.mark.parametrize("stated", ["01.02.2026", "2026-Q5", "mid 2026"])
def test_the_api_refuses_a_tax_date_it_could_not_tax_on(stated: str) -> None:
    """A new field has no legacy values to keep, so an unreadable one is refused at the door.

    ``base_date`` stores free text and reports it, because rows predating the
    parser hold such values. ``tax_date`` has none, and storing a value the
    tax lookup cannot read would tax the bill at today's rate.
    """
    with pytest.raises(ValidationError):
        BOQCreate(project_id=uuid.uuid4(), name="B", tax_date=stated)
    with pytest.raises(ValidationError):
        BOQUpdate(tax_date=stated)


def test_clearing_the_tax_date_is_an_update() -> None:
    """``null`` is sent on purpose to make the bill follow its base date again."""
    dumped = BOQUpdate(tax_date=None).model_dump(exclude_unset=True)
    assert dumped == {"tax_date": None}


def test_the_response_carries_the_tax_date() -> None:
    assert "tax_date" in BOQResponse.model_fields


# ── The validation rule reads the field the bill is taxed on ────────────────


def _bill(**fields: Any) -> ValidationContext:
    return ValidationContext(data={"positions": [], "boq": fields, "markups": []}, metadata={"locale": "en"})


async def test_an_unreadable_tax_date_is_reported_under_its_own_name() -> None:
    results = await BOQBaseDateReadable().validate(_bill(base_date="2025-06", tax_date="01.02.2026"))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].details == {"tax_date": "01.02.2026"}
    assert "01.02.2026" in results[0].message
    assert "tax date" in results[0].message.lower()


async def test_a_readable_tax_date_passes_whatever_the_price_base_says() -> None:
    """The rule exists because an unreadable date taxes the bill today. Once the
    tax date is stated and readable, the base date no longer decides the tax."""
    results = await BOQBaseDateReadable().validate(_bill(base_date="mid 2025", tax_date="2026-01-01"))
    assert len(results) == 1
    assert results[0].passed
    assert results[0].details == {"tax_date": "2026-01-01"}


async def test_without_a_tax_date_the_rule_reads_the_base_date_as_before() -> None:
    results = await BOQBaseDateReadable().validate(_bill(base_date="01.02.2026", tax_date=None))
    assert len(results) == 1
    assert not results[0].passed
    assert results[0].details == {"base_date": "01.02.2026"}


@pytest.mark.parametrize("locale", ["en", "de", "es", "ru"])
@pytest.mark.parametrize("key", ["boq_quality.tax_date_readable.fail"])
def test_the_tax_date_message_is_translated_in_every_shipped_locale(locale: str, key: str) -> None:
    assert is_key_present(key, locale=locale)


async def test_the_validation_payload_carries_the_tax_date() -> None:
    """The rule can only read what the payload builder hands it."""
    source = (_BACKEND / "app" / "modules" / "validation" / "service.py").read_text(encoding="utf-8")
    assert '"tax_date": boq.tax_date' in source


# ── The migration ───────────────────────────────────────────────────────────


def test_the_migration_adds_the_column_and_nothing_else() -> None:
    path = _BACKEND / "alembic" / "versions" / "v55_boq_tax_date.py"
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assigned = {
        node.targets[0].id if isinstance(node, ast.Assign) else node.target.id: node.value
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.targets[0] if isinstance(node, ast.Assign) else node.target, ast.Name)
    }
    assert ast.literal_eval(assigned["revision"]) == "v55_boq_tax_date"
    assert ast.literal_eval(assigned["_TABLE"]) == "oe_boq_boq"
    assert ast.literal_eval(assigned["_COLUMN"]) == "tax_date"
