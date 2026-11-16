"""The demo stories land where the worked examples say they stand."""

from __future__ import annotations

from decimal import Decimal as D

from app.modules.framework_agreements import seed
from app.modules.framework_agreements.models import FrameworkRateItem


def _items(story: seed._Story) -> dict[str, FrameworkRateItem]:
    return {
        i.code: FrameworkRateItem(
            code=i.code, description=i.description, unit=i.unit, base_rate=i.rate, surcharge_flags=list(i.flags)
        )
        for i in story.items
    }


def _issued_total(story: seed._Story, items: dict[str, FrameworkRateItem]) -> D:
    return sum(
        (
            seed._price(story, o, items).net + (o.extra[1] if o.extra else D("0"))
            for o in story.orders
            if o.status != "draft"
        ),
        D("0"),
    )


def test_berlin_order_0147_prices_as_example_1_and_takes_the_agreement_to_96_20() -> None:
    story = seed._STORIES["residential-berlin"]
    items = _items(story)
    a0147 = next(o for o in story.orders if o.code == "A-2026-0147")
    assert seed._price(story, a0147, items).net == D("5889.56")
    before = _issued_total(story, items) - D("5889.56")
    filler = seed._filler(story, items, story.target_committed - before)
    assert filler is not None
    total = _issued_total(story, items) + seed._price(story, filler, items).net
    assert total == D("3848039.56")
    assert (total / story.cap * 100).quantize(D("0.01")) == D("96.20")


def test_us_draft_to_0007_is_over_the_cap() -> None:
    story = seed._STORIES["medical-us"]
    items = _items(story)
    before = _issued_total(story, items)
    filler = seed._filler(story, items, story.target_committed - before)
    assert filler is not None
    committed = before + seed._price(story, filler, items).net
    assert committed == story.target_committed
    draft = next(o for o in story.orders if o.code == "TO-0007")
    assert committed + seed._price(story, draft, items).net > story.cap


def test_london_story_has_an_extra_on_to_0231() -> None:
    story = seed._STORIES["office-london"]
    to = next(o for o in story.orders if o.code == "TO-0231")
    assert to.extra is not None and to.extra[1] == D("696.64")
    assert len(story.orders) == 12
