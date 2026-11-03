# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Catalogue rules R1-R6 as a table, the parameter parser and the rule set. No database."""

from __future__ import annotations

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.bi_feed import validators as v
from app.modules.bi_feed.feeds import FEEDS, ColumnSpec, FeedSpec, build_catalogue, resolve


def _spec(feed_id: str = "demo", *columns: ColumnSpec) -> FeedSpec:
    cols = columns or (ColumnSpec("id", "id", "uuid"), ColumnSpec("name", "name", "text"))
    return FeedSpec(
        id=feed_id,
        title_key="bi_feed.feed.demo",
        model="app.modules.projects.models:Project",
        columns=cols,
        project_col="id",
    )


def test_shipped_catalogue_passes_every_rule() -> None:
    """R1, R2, R3, R5 over the real allow-list; R4 is the cap constant; R6 needs a live database."""
    assert v.unresolvable_columns(FEEDS) == []  # R1
    assert v.sensitive_columns(FEEDS) == []  # R2
    assert v.money_without_currency(FEEDS) == []  # R3
    assert v.bad_feed_ids(FEEDS) == []  # R5
    assert set(build_catalogue()) == set(FEEDS)


@pytest.mark.parametrize(
    ("columns", "check", "expected"),
    [
        # R1
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("x", "no_such_attr", "text")), v.unresolvable_columns, 1),
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("x", "name", "blob")), v.unresolvable_columns, 1),
        ((ColumnSpec("x", "name", "text"),), v.unresolvable_columns, 1),  # no id column
        # R2
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("owner_email", "name", "text")), v.sensitive_columns, 1),
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("x", "hashed_password", "text")), v.sensitive_columns, 1),
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("Api_Key", "name", "text")), v.sensitive_columns, 1),
        # R3
        ((ColumnSpec("id", "id", "uuid"), ColumnSpec("total", "name", "money")), v.money_without_currency, 1),
        (
            (
                ColumnSpec("id", "id", "uuid"),
                ColumnSpec("total", "name", "money"),
                ColumnSpec("currency", "currency", "text"),
            ),
            v.money_without_currency,
            0,
        ),
    ],
)
def test_catalogue_rules_flag_bad_definitions(columns, check, expected) -> None:
    spec = _spec("demo", *columns)
    assert len(check({"demo": spec})) == expected


@pytest.mark.parametrize(
    ("feed_id", "ok"), [("boq_positions", True), ("Boq", False), ("boq-positions", False), ("_x", False)]
)
def test_feed_ids_must_be_snake_case(feed_id: str, ok: bool) -> None:
    assert (v.bad_feed_ids({feed_id: _spec(feed_id)}) == []) is ok


def test_feed_id_must_match_its_key() -> None:
    assert v.bad_feed_ids({"a": _spec("b")}) == ["a"]


def test_resolve_rejects_unknown_attribute() -> None:
    with pytest.raises(Exception, match="no column attribute"):
        resolve(_spec("demo", ColumnSpec("id", "id", "uuid"), ColumnSpec("x", "nope", "text")))


def test_view_parity_compares_names_and_order() -> None:
    names = {fid: [c.name for c in spec.columns] for fid, spec in FEEDS.items()}
    assert v.view_mismatches(FEEDS, names) == []
    names["invoices"] = names["invoices"][::-1]
    assert v.view_mismatches(FEEDS, names) == ["invoices"]
    del names["invoices"]
    assert v.view_mismatches(FEEDS, names) == []  # a feed without a view is simply not enabled


def test_money_columns_all_have_a_currency_sibling() -> None:
    for spec in FEEDS.values():
        if any(c.kind == "money" for c in spec.columns):
            assert {c.name for c in spec.columns} & {"currency", "currency_code"}, spec.id


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"limit": "50001"}, "BI_FEED_LIMIT"),
        ({"limit": "0"}, "BI_FEED_BAD_PARAM"),
        ({"limit": "ten"}, "BI_FEED_BAD_PARAM"),
        ({"offset": "-1"}, "BI_FEED_BAD_PARAM"),
        ({"project_id": "nope"}, "BI_FEED_BAD_PARAM"),
        ({"updated_since": "yesterday"}, "BI_FEED_BAD_PARAM"),
        ({"$filter": "x eq 1"}, "BI_FEED_BAD_PARAM"),
        ({"order_by": "id; drop table x"}, "BI_FEED_BAD_PARAM"),
    ],
)
def test_parse_params_refuses_with_a_stable_code(raw: dict[str, str], code: str) -> None:
    with pytest.raises(v.BiFeedError) as info:
        v.parse_params(raw)
    assert info.value.status_code == 400
    assert info.value.code == code


def test_parse_params_accepts_the_documented_set() -> None:
    p = v.parse_params(
        {
            "project_id": "11111111-1111-1111-1111-111111111111",
            "updated_since": "2026-01-02T03:04:05Z",
            "limit": "50000",
            "offset": "10",
            "after": "22222222-2222-2222-2222-222222222222",
        }
    )
    assert p.limit == 50000 and p.offset == 10
    assert p.updated_since.utcoffset().total_seconds() == 0
    assert v.parse_params({}) == v.FeedParams()


@pytest.mark.asyncio
async def test_rule_set_registers_and_passes_on_the_shipped_catalogue() -> None:
    v.register_bi_feed_rules()
    v.register_bi_feed_rules()  # idempotent
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([v.BI_FEED_RULE_SET])}
    assert ids == {cls.rule_id for cls in v.BI_FEED_RULES}
    for cls in v.BI_FEED_RULES:
        results = await cls().validate(ValidationContext(data={"specs": FEEDS}))
        assert all(r.passed for r in results), (cls.rule_id, [r.message for r in results])


@pytest.mark.asyncio
async def test_rules_fail_on_a_bad_catalogue() -> None:
    bad = {"demo": _spec("demo", ColumnSpec("id", "id", "uuid"), ColumnSpec("token", "name", "text"))}
    results = await v.NoSensitiveNamesRule().validate(ValidationContext(data={"specs": bad}))
    assert not results[0].passed
    results = await v.LimitCapRule().validate(ValidationContext(data={"max_limit": 50001}))
    assert not results[0].passed


def test_every_feed_names_the_read_permission_of_its_module() -> None:
    from app.modules.bi_feed.feeds import FEEDS

    assert all(s.permission.endswith(".read") for s in FEEDS.values())


async def test_a_role_without_the_module_permission_gets_403_before_any_query(monkeypatch) -> None:
    import pytest

    from app.core.permissions import permission_registry
    from app.modules.bi_feed.feeds import build_catalogue
    from app.modules.bi_feed.service import BiFeedService
    from app.modules.bi_feed.validators import BiFeedError, FeedParams

    denied = {"finance.read"}
    monkeypatch.setattr(permission_registry, "role_has_permission", lambda role, perm: perm not in denied)
    service = BiFeedService(None, catalogue=build_catalogue())  # type: ignore[arg-type]
    with pytest.raises(BiFeedError) as raised:
        await service.export("invoices", "csv", "u", "viewer", FeedParams())
    assert (raised.value.status_code, raised.value.code) == (403, "BI_FEED_FORBIDDEN")
