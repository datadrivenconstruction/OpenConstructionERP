"""The markups list answers with the ``items`` envelope as well as ``markups``.

Most list routes answer ``{"items": [...], "total": n}``. The markups list only
ever answered ``{"markups": [...]}``, so a generic reader that looks for
``items`` concluded a bill had no markups. Both keys now carry the same rows.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.boq.schemas import MarkupListResponse, MarkupResponse


def _row(name: str) -> MarkupResponse:
    now = datetime.now(UTC)
    return MarkupResponse(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        name=name,
        markup_type="percentage",
        category="overhead",
        percentage=Decimal("10"),
        fixed_amount=Decimal("0"),
        apply_to="direct_cost",
        sort_order=0,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def test_the_rows_are_under_items_and_markups_with_a_total() -> None:
    rows = [_row("Overhead"), _row("Profit")]
    body = MarkupListResponse(markups=rows).model_dump(mode="json")
    assert [r["name"] for r in body["markups"]] == ["Overhead", "Profit"]
    assert [r["name"] for r in body["items"]] == ["Overhead", "Profit"]
    assert body["total"] == 2


def test_an_empty_list_says_zero() -> None:
    body = MarkupListResponse().model_dump(mode="json")
    assert body == {"markups": [], "items": [], "total": 0}
