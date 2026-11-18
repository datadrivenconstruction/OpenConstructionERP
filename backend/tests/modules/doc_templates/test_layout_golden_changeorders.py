# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The change order prints exactly what it printed before the block engine.

The digests in ``golden_changeorder_forms.json`` were taken from the hand-written
form before it moved onto a document layout. Regenerate only on an intended change
of the printed form: ``python -m tests.modules.doc_templates.test_layout_golden_changeorders``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.modules.doc_templates._golden import digest, regenerate
from tests.unit import _record_pdf_samples as samples

GOLDEN = Path(__file__).with_name("golden_changeorder_forms.json")
_GENERATED = "2026-11-18 09:30 UTC"
_SUBMITTER = str(samples.USER_ID)
_APPROVER = samples.VENDOR_ID
_LOCALES = ("en", "de", "ru", "ar", "fr", "tr", "zh", "es")


def _item(**over: Any) -> SimpleNamespace:
    item = SimpleNamespace(
        sort_order=1,
        description="Steel pipe DN100",
        change_type="added",
        unit="m",
        original_quantity=Decimal("10"),
        new_quantity=Decimal("12.5"),
        original_rate=Decimal("100"),
        new_rate=Decimal("98.765"),
        cost_delta=Decimal("234.56"),
    )
    for key, value in over.items():
        setattr(item, key, value)
    return item


def change_order(**over: Any) -> SimpleNamespace:
    order = SimpleNamespace(
        id="dddddddd-0000-0000-0000-000000000004",
        project_id=None,
        code="CO-007",
        title="Extra drainage at the north wall",
        description="Ground water found during excavation.",
        reason_category="unforeseen_conditions",
        variation_type="instruction",
        status="submitted",
        submitted_at="2026-10-10T08:00:00+00:00",
        approved_at="2026-10-14T08:00:00+00:00",
        submitted_by=_SUBMITTER,
        approved_by=_APPROVER,
        contractor_amount=Decimal("1234.56"),
        engineer_amount=Decimal("1000"),
        approved_amount=Decimal("1100"),
        cost_impact=Decimal("1100"),
        currency="EUR",
        time_impact_days=3,
        schedule_impact_days=5,
        approved_time_days=2,
        items=[_item(), _item(sort_order=0, description="", change_type="removed", cost_delta=Decimal("-34.56"))],
    )
    for key, value in over.items():
        setattr(order, key, value)
    return order


def _cases() -> Iterator[tuple[str, Callable[[], Any]]]:
    from app.modules.changeorders.pdf_export import change_order_record

    def co(locale: str = "en", **over: Any) -> Any:
        return lambda: change_order_record(
            change_order(**over), project=samples.PROJECT, people=samples.PEOPLE, locale=locale, generated=_GENERATED
        )

    for locale in _LOCALES:
        yield f"co-{locale}", co(locale)
    yield "co-no-items", co(items=[])
    yield "co-no-description", co(description="")
    yield "co-draft", co(status=None, submitted_at=None, approved_at=None, submitted_by=None, approved_by=None)
    yield "co-no-currency", co(currency=None)
    yield "co-schedule-impact", co(time_impact_days=None, approved_time_days=None)
    yield "co-no-amounts", co(contractor_amount=None, engineer_amount=None, approved_amount=None, cost_impact=None)
    yield "co-delta-missing", co(items=[_item(cost_delta=None, unit=None, change_type=None)])


def test_every_golden_case_is_still_generated() -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(stored) == {name for name, _ in _cases()}


@pytest.mark.parametrize(("name", "build"), list(_cases()), ids=[name for name, _ in _cases()])
def test_the_standard_template_prints_the_form_it_printed_before(name: str, build: Callable[[], Any]) -> None:
    stored = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert digest(build()) == stored[name], f"{name}: the printed form changed"


if __name__ == "__main__":  # pragma: no cover - regeneration helper
    regenerate(GOLDEN, _cases())
