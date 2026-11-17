# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Access, deletion, pricing and retention guarantees of sealed estimates, against a fake session."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.validation.engine import validation_engine
from app.modules.estimate_archive import engine, fixtures, models, seed
from app.modules.estimate_archive import service as svc_mod
from app.modules.estimate_archive.models import EstimateSeal, SealDerivation, SealImmutableError
from app.modules.estimate_archive.permissions import register_estimate_archive_permissions
from app.modules.estimate_archive.service import EstimateArchiveService
from app.modules.estimate_archive.validators import (
    PRICING_RULE_SET,
    SEAL_RULE_SET,
    register_estimate_archive_rules,
)

VIEWER = {"role": "viewer", "permissions": []}
EDITOR = {"role": "editor", "permissions": []}

_DE_CHANGE: dict[str, Any] = {
    "quantity": "310",
    "changes": [{"code": "L-TRENCH", "consumption": "0.62", "note": "Deeper trench, more hand digging"}],
    "additions": [
        {
            "kind": "plant",
            "code": "SHORING",
            "description": "Trench shoring hire",
            "unit": "m3",
            "consumption": "1",
            "unit_cost": "3.40",
            "quote_ref": "Q-118",
            "price_date": "2026-11-03",
        }
    ],
    "current_unit_costs": {"L-TRENCH": "55.10"},
}


@pytest.fixture(autouse=True)
def _registered() -> None:
    register_estimate_archive_permissions()
    register_estimate_archive_rules()


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any:
        return self.scalar()

    def __iter__(self) -> Any:
        return iter(self._rows)


class _Session:
    def __init__(self, objects: dict[tuple[str, Any], Any] | None = None) -> None:
        self.objects = objects or {}
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.results: list[list[Any]] = []

    async def get(self, model: Any, key: Any) -> Any:
        return self.objects.get((model.__name__, key))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self.results.pop(0) if self.results else [])


def _seal(payload: dict[str, Any] | None = None, project_id: uuid.UUID | None = None) -> EstimateSeal:
    payload = payload or fixtures.example_de_trench()
    return EstimateSeal(
        id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        label="Water main - sealed",
        schema_version=engine.SCHEMA,
        payload=payload,
        content_hash=engine.seal_digest(payload),
        sealed_at=datetime(2026, 3, 31, tzinfo=UTC),
        award_total=Decimal("0"),
        currency="EUR",
        basis_kind="award",
        status="sealed",
        deposit_mode="platform",
        supersede_reason="",
        profile="de",
        metadata_={},
    )


def _service(session: _Session | None = None, openings: list[Any] | None = None) -> tuple[EstimateArchiveService, list]:
    svc = EstimateArchiveService(session or _Session())  # type: ignore[arg-type]
    events: list[tuple[str, dict]] = []

    async def log(seal: Any, event_type: str, actor_id: Any, **kw: Any) -> None:
        events.append((event_type, kw))

    async def list_openings(**_kw: Any) -> list[Any]:
        return list(openings or [])

    svc.log = log  # type: ignore[method-assign]
    svc.repo.openings = list_openings  # type: ignore[method-assign]
    return svc, events


def _open_session(attendee: uuid.UUID, scope: str = "full", ordinals: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status="open",
        scope=scope,
        scope_ordinals=ordinals or [],
        positions_viewed=[],
        attendees=[{"user_id": str(attendee), "name": "Petra Lang", "side": "counterparty", "present": True}],
    )


# ── 1. A seal outlives the project ────────────────────────────────────────────


def test_orm_refuses_to_delete_a_seal() -> None:
    with pytest.raises(SealImmutableError):
        models._refuse_delete(None, None, _seal())


async def test_project_sweep_leaves_sealed_estimates_alone() -> None:
    from app.modules.projects.service import purge_project_children_without_cascade

    session = _Session()
    await purge_project_children_without_cascade(session, [uuid.uuid4()])  # type: ignore[arg-type]
    swept = {getattr(getattr(s, "table", None), "name", "") for s in session.statements}
    assert "oe_tasks_task" in swept or len(swept) > 5
    assert not {t for t in swept if t.startswith("oe_estimate_archive_")}


async def test_permanent_project_delete_is_refused_while_a_seal_is_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.projects.service import ProjectService

    pid = uuid.uuid4()
    svc = ProjectService.__new__(ProjectService)
    svc.session = _Session()  # type: ignore[assignment]

    async def get_project(_pid: Any, include_archived: bool = False) -> Any:
        return SimpleNamespace(id=pid, status="archived", name="Water main", metadata_={})

    async def retained(_session: Any, _ids: Any) -> int:
        return 1

    monkeypatch.setattr(svc, "get_project", get_project)
    monkeypatch.setattr(svc_mod, "seals_under_retention", retained)
    with pytest.raises(HTTPException) as exc:
        await svc.purge_project(pid, confirm_name="Water main")
    assert exc.value.status_code == 409


async def test_seals_under_retention_counts_open_retention_only() -> None:
    session = _Session()
    session.results = [[2]]
    assert await svc_mod.seals_under_retention(session, [uuid.uuid4()], today=date(2026, 11, 16)) == 2  # type: ignore[arg-type]
    sql = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "retention_until" in sql
    assert "2026-11-16" in sql


# ── 2. The PostgreSQL guard on installs that never ran the migration ─────────


class _Conn:
    def __init__(self, dialect: str) -> None:
        self.dialect = SimpleNamespace(name=dialect)
        self.sql: list[str] = []

    def exec_driver_sql(self, sql: str) -> None:
        self.sql.append(sql)


def test_guard_is_installed_on_postgres_and_skipped_elsewhere() -> None:
    pg, lite = _Conn("postgresql"), _Conn("sqlite")
    models.install_seal_guard(pg)
    models.install_seal_guard(lite)
    joined = "\n".join(pg.sql)
    assert "CREATE OR REPLACE FUNCTION oe_estimate_archive_seal_guard" in joined
    assert "BEFORE UPDATE OR DELETE ON" in joined
    assert '"content_hash"' in joined
    assert lite.sql == []


def test_guard_follows_create_all() -> None:
    from sqlalchemy import event

    assert event.contains(EstimateSeal.__table__, "after_create", models._guard_after_create)


# ── 3. An open session shows contents to its attendees only ──────────────────


async def test_open_session_shows_contents_to_attendees_and_sealed_readers_only() -> None:
    attendee, stranger = uuid.uuid4(), uuid.uuid4()
    svc, events = _service(openings=[_open_session(attendee)])
    seal = _seal()
    with pytest.raises(HTTPException) as exc:
        await svc.contents(seal, str(stranger), VIEWER)
    assert exc.value.status_code == 403
    out = await svc.contents(seal, str(attendee), VIEWER)
    assert out.payload["positions"]
    assert (await svc.contents(seal, str(stranger), EDITOR)).payload["positions"]
    assert [e[0] for e in events] == ["read", "read"]


async def test_derive_inside_an_opening_is_for_attendees_only() -> None:
    attendee, stranger = uuid.uuid4(), uuid.uuid4()
    svc, _events = _service(openings=[_open_session(attendee)])
    req = svc_mod.DeriveRequest(position_ordinal="02.03.0040")
    with pytest.raises(HTTPException) as exc:
        await svc.derive(_seal(), req, str(stranger), VIEWER)
    assert exc.value.status_code == 403


# ── 4. Choosing a method reprices the variation line ─────────────────────────


async def test_choosing_a_method_reprices_the_variation_line(monkeypatch: pytest.MonkeyPatch) -> None:
    seal = _seal()
    result = engine.derive_rate(seal.payload, "02.03.0040", **_DE_CHANGE)
    pos_id = uuid.uuid4()
    position = SimpleNamespace(id=pos_id, quantity="310", unit_rate="51.65", total="16011.50")
    svc, events = _service(_Session({("Position", pos_id): position}))

    async def get_seal(_sid: Any, _uid: Any) -> EstimateSeal:
        return seal

    monkeypatch.setattr(svc, "get_seal_for_user", get_seal)
    derivation = SealDerivation(
        id=uuid.uuid4(),
        seal_id=seal.id,
        position_ordinal="02.03.0040",
        quantity=Decimal("310"),
        result=result,
        basis_method="original_basis",
        chosen_rate=Decimal("51.65"),
        variation_position_id=pos_id,
    )
    await svc.choose_method(derivation, "cost_plus_markup", str(uuid.uuid4()))
    assert derivation.chosen_rate == Decimal("53.43")
    assert position.unit_rate == "53.43"
    assert position.total == "16563.30"
    assert events[-1][0] == "method_chosen"


# ── 5 and 6. Net rates in, the sealed (marked-up) rate out ────────────────────


@pytest.mark.parametrize(
    ("build", "ordinal", "net"),
    [
        (fixtures.example_de_trench, "02.03.0040", "28.88"),
        (fixtures.example_de_trench, "02.03.0050", "33.24"),
        (fixtures.example_uk_trench, "D20.1", "37.88"),
        (fixtures.example_fidic_pipe_surround, "4.07", "165.80"),
    ],
)
def test_fixture_rates_are_net_so_markups_apply_once(build: Any, ordinal: str, net: str) -> None:
    payload = build()
    position = engine.find_position(payload, ordinal)
    assert position is not None
    assert Decimal(str(position["unit_rate"])) == Decimal(net)
    assert engine.derive_rate(payload, ordinal)["sealed_net"] == net


def test_fidic_sealed_rate_and_total() -> None:
    payload = fixtures.example_fidic_pipe_surround()
    assert engine.derive_rate(payload, "4.07")["sealed_rate"] == "188.02"


async def test_change_order_original_rate_is_the_sealed_rate() -> None:
    seal = _seal()
    item_id, order_id = uuid.uuid4(), uuid.uuid4()
    item = SimpleNamespace(id=item_id, change_order_id=order_id, original_rate=None, metadata_={})
    order = SimpleNamespace(id=order_id, project_id=seal.project_id)
    svc, _events = _service(_Session({("ChangeOrderItem", item_id): item, ("ChangeOrder", order_id): order}))
    _item, rate = await svc.fill_change_order_rate(seal, item_id, "02.03.0040", str(uuid.uuid4()))
    assert rate == Decimal("36.16")
    assert item.original_rate == Decimal("36.16")


def test_demo_change_is_built_from_the_sealed_bill_itself() -> None:
    payload = fixtures.example_uk_trench()
    ordinal, change = seed.demo_change(payload)
    assert ordinal == "D20.1"
    result = engine.derive_rate(payload, ordinal, **change)
    assert Decimal(result["original_basis_rate"]) > Decimal(result["sealed_rate"])
    bare = engine.build_payload(
        estimate={"name": "x", "currency": "EUR"},
        positions=[{"ordinal": "1", "description": "Wall", "unit": "m2", "quantity": "40", "unit_rate": "55"}],
        markups=[],
    )
    assert seed.demo_change(bare)[0] == "1"
    assert seed.demo_change({"positions": []}) is None


# ── 7. The variation bill must be this project's draft ───────────────────────


def test_variation_bill_lookup_is_scoped_to_the_project_and_drafts() -> None:
    seal = _seal()
    stmt = svc_mod.variation_bill_stmt(seal.project_id, uuid.uuid4())
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert sql.count(seal.project_id.hex) + sql.count(str(seal.project_id)) >= 2
    assert "'draft'" in sql


# ── 8. Pricing from the seal is a read ────────────────────────────────────────


async def test_derive_logs_a_read() -> None:
    svc, events = _service()
    await svc.derive(_seal(), svc_mod.DeriveRequest(position_ordinal="02.03.0040"), str(uuid.uuid4()), EDITOR)
    assert ("read" in [e[0] for e in events]) and events[0][1]["detail"]["ordinal"] == "02.03.0040"


# ── 9 and 12. Sealing needs the market and, to supersede, the same project ───


def _preview(project_id: uuid.UUID, enabled: bool = True, contract_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project_id,
        contract_id=contract_id or uuid.uuid4(),
        can_seal=True,
        checks=[],
        policy=SimpleNamespace(enabled=enabled),
    )


async def test_sealing_is_refused_where_the_market_does_not_use_it(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, _events = _service()

    async def preview(_data: Any, _uid: Any) -> Any:
        return _preview(uuid.uuid4(), enabled=False)

    monkeypatch.setattr(svc, "preview", preview)
    with pytest.raises(HTTPException) as exc:
        await svc.create_seal(svc_mod.SealCreate(source_boq_id=uuid.uuid4()), str(uuid.uuid4()))
    assert exc.value.status_code == 403


async def test_sealing_needs_a_client_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, _events = _service()

    async def preview(_data: Any, _uid: Any) -> Any:
        prev = _preview(uuid.uuid4())
        prev.contract_id = None
        return prev

    monkeypatch.setattr(svc, "preview", preview)
    with pytest.raises(HTTPException) as exc:
        await svc.create_seal(svc_mod.SealCreate(source_boq_id=uuid.uuid4()), str(uuid.uuid4()))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "CONTRACT_REQUIRED"


async def test_superseding_needs_the_same_project(monkeypatch: pytest.MonkeyPatch) -> None:
    svc, _events = _service()

    async def preview(_data: Any, _uid: Any) -> Any:
        return _preview(uuid.uuid4())

    monkeypatch.setattr(svc, "preview", preview)
    with pytest.raises(HTTPException) as exc:
        await svc.create_seal(
            svc_mod.SealCreate(source_boq_id=uuid.uuid4()), str(uuid.uuid4()), supersedes=_seal(), reason="typo"
        )
    assert exc.value.status_code == 422


# ── 11. The pricing rules see real data ───────────────────────────────────────


async def _codes(rule_set: str, data: dict) -> set[str]:
    report = await validation_engine.validate(
        data=data, rule_sets=[rule_set], target_type="t", target_id="", metadata={"locale": "en"}
    )
    return {r.details.get("code") for r in report.results if not r.passed and not r.is_engine_error} - {None}


async def test_markups_of_the_variation_bill_are_checked_against_the_seal() -> None:
    seal = _seal()
    result = engine.derive_rate(seal.payload, "02.03.0040", **_DE_CHANGE)
    data = svc_mod.pricing_data(seal, result, "original_basis", claimed_markups=["BGK", "AGK", "WuG", "Wagnis"])
    report = await validation_engine.validate(
        data=data, rule_sets=[PRICING_RULE_SET], target_type="t", target_id="", metadata={"locale": "en"}
    )
    failed = [r for r in report.results if not r.passed]
    assert any("Wagnis" in r.message for r in failed)


async def test_a_carried_cost_far_from_the_benchmark_is_flagged() -> None:
    payload = fixtures.example_fidic_pipe_surround()
    result = engine.derive_rate(
        payload, "4.07", quantity="64", changes=[{"code": "CONC", "unit_cost": "113.50", "note": "Higher grade"}]
    )
    data = svc_mod.pricing_data(None, result, "cost_plus_markup", benchmarks={"CONC": "80.00", "LAB": "46.00"})
    assert [r["code"] for r in data["carried"]] == ["CONC", "LAB"]
    report = await validation_engine.validate(
        data=data, rule_sets=[PRICING_RULE_SET], target_type="t", target_id="", metadata={"locale": "en"}
    )
    abnormal = [r for r in report.results if not r.passed and r.rule_id.endswith("abnormal_carried_rate")]
    assert len(abnormal) == 1


def test_an_original_basis_line_without_a_live_seal_is_reported() -> None:
    live = uuid.uuid4()
    traces = [
        SimpleNamespace(id=uuid.uuid4(), basis_method="original_basis", sealed_seal_id=None, note="L1"),
        SimpleNamespace(id=uuid.uuid4(), basis_method="original_basis", sealed_seal_id=live, note="L2"),
        SimpleNamespace(id=uuid.uuid4(), basis_method="agreed", sealed_seal_id=None, note="L3"),
    ]
    rows = svc_mod.trace_checks(traces, {live})
    assert [(r["code"], r["has_seal"]) for r in rows] == [("L1", False), ("L2", True)]


# ── 13. Within a cent is a match ──────────────────────────────────────────────


async def test_a_one_cent_difference_is_within_tolerance() -> None:
    data = {"seal_total": "1000.01", "award_value": "1000.00", "currency": "EUR"}
    assert "ARC_TOTAL_MISMATCH" not in await _codes(SEAL_RULE_SET, data)
    data["seal_total"] = "1000.02"
    assert "ARC_TOTAL_MISMATCH" in await _codes(SEAL_RULE_SET, data)


# ── 15. Retention runs from acceptance, to the day ────────────────────────────


def test_retention_keeps_the_day_and_starts_at_acceptance() -> None:
    assert svc_mod.add_years(date(2026, 3, 31), 10) == date(2036, 3, 31)
    assert svc_mod.add_years(date(2024, 2, 29), 5) == date(2029, 2, 28)
    sealed = datetime(2026, 3, 31, tzinfo=UTC)
    accepted = SimpleNamespace(metadata_={"acceptance_date": "2027-06-15"})
    assert svc_mod.retention_start(accepted, sealed) == date(2027, 6, 15)
    assert svc_mod.retention_start(None, sealed) == date(2026, 3, 31)
    assert svc_mod.retention_start(SimpleNamespace(metadata_={}), sealed) == date(2026, 3, 31)


def test_uk_retention_names_its_source() -> None:
    from app.modules.estimate_archive import policy

    assert "Limitation Act 1980" in str(policy.policy_for("uk").get("retention_note"))


# ── 9. Only markets whose profile uses seals see the module ───────────────────


def test_module_is_tagged_with_the_markets_that_seal() -> None:
    from app.modules.estimate_archive import policy
    from app.modules.estimate_archive.manifest import manifest

    assert {"DE", "GB", "US", "AE"} <= set(manifest.markets)
    assert "FR" not in manifest.markets
    assert all(policy.policy_for(policy.resolve_profile_id(c))["enabled"] for c in manifest.markets)
