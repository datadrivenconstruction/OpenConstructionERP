"""Site logistics plan: the wiring the review of 2026-10-12 found missing or wrong, pinned without a database."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.routing import APIRoute

from app.modules.site_logistics import hosting, links, plan_schemas, plan_service, router, validators
from app.modules.site_logistics.messages import translate

MODULE = Path(router.__file__).parent
SITE = ZoneInfo("Asia/Kolkata")  # UTC+05:30, no daylight saving: far enough from UTC to tell the clocks apart


def _run(coro):
    return asyncio.run(coro)


# ── finding 6: the plan rules actually execute ─────────────────────────────


def _payload(findings: list[dict]) -> dict:
    return {"findings": findings, "deliveries": [], "gates": {}, "concept_hours": None, "site_timezone": None}


def _validate(monkeypatch: pytest.MonkeyPatch, payload: dict) -> dict:
    validators.register_site_logistics_validation_rules()

    async def fake_payload(self, project_id, today=None):
        return payload

    monkeypatch.setattr(plan_service.LogisticsPlanService, "validation_payload", fake_payload)
    return _run(plan_service.LogisticsPlanService(None).validate(uuid.uuid4(), locale="en"))


def test_validate_runs_every_plan_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _validate(monkeypatch, _payload([]))
    expected = {f"site_logistics.{r.key}" for r in validators.PLAN_RULES}
    assert len(expected) == 23
    # Fails when the payload does not reach the rules: a plan rule without ``findings`` returns nothing.
    assert expected <= set(report["rules_run"])
    assert report["counts"]["errors"] == 0
    assert report["counts"]["passed"] >= len(expected)


def test_validate_reports_a_finding_through_its_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    finding = {
        "rule": "site_timezone_set",
        "code": "site_timezone_missing",
        "severity": "error",
        "ref": None,
        "params": {},
    }
    report = _validate(monkeypatch, _payload([finding]))
    failed = [r for r in report["results"] if not r["passed"]]
    assert [r["rule_id"] for r in failed] == ["site_logistics.site_timezone_set"]
    assert failed[0]["message"] == translate("site_logistics.findings.site_timezone_missing.fail", locale="en")
    assert report["status"] != "passed"


def test_an_empty_payload_would_run_no_plan_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect itself: the rule set used to be handed a payload without ``findings``."""
    report = _validate(monkeypatch, {})
    assert not {f"site_logistics.{r.key}" for r in validators.PLAN_RULES} & set(report["rules_run"])


def test_validation_payload_carries_what_the_rules_read() -> None:
    import inspect

    source = inspect.getsource(plan_service.LogisticsPlanService.validation_payload)
    for key in ("findings", "site_timezone", "concept_hours", "gates", "deliveries"):
        assert f'"{key}"' in source, key


def test_validate_route_exists_and_reads_only() -> None:
    routes = {(sorted(r.methods)[0], r.path): r for r in router.router.routes if isinstance(r, APIRoute)}
    route = routes[("POST", "/projects/{project_id}/validate")]
    perms = {p for d in route.dependant.dependencies if (p := getattr(d.call, "permission", None))}
    assert perms == {"site_logistics.read"}


# ── finding 1: one site clock ──────────────────────────────────────────────


def _at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, 12, h, m, tzinfo=UTC)


def test_gate_hours_are_read_on_the_site_clock() -> None:
    # 02:00 UTC is 07:30 on site: inside 07:00 to 18:00, though the UTC clock reads 02:00.
    assert validators.delivery_within_gate_hours("07:00", "18:00", _at(2), _at(3), SITE) == (True, None)
    # 08:00 UTC is 13:30 on site; 13:00 UTC is 18:30: after closing, though the UTC clock reads 13:00.
    ok, reason = validators.delivery_within_gate_hours("07:00", "18:00", _at(8), _at(13), SITE)
    assert ok is False and "closes" in str(reason)
    # 00:00 UTC is 05:30 on site: before opening.
    ok, reason = validators.delivery_within_gate_hours("07:00", "18:00", _at(0), _at(3), SITE)
    assert ok is False and "opens" in str(reason)
    # 18:00 to 19:00 UTC is one UTC day and crosses the site's midnight.
    ok, reason = validators.delivery_within_gate_hours("00:00", "23:59", _at(18), _at(19), SITE)
    assert ok is False and "same day" in str(reason)


def test_gate_hours_without_a_zone_are_not_checked_and_say_so() -> None:
    # 22:00 to 23:00 is outside 07:00 to 18:00 on the UTC clock and on most others. Without a
    # zone nothing is compared: the window passes, and the reason says the hours were not checked.
    for start, end in ((_at(8), _at(9)), (_at(22), _at(23))):
        ok, reason = validators.delivery_within_gate_hours("07:00", "18:00", start, end)
        assert ok is True
        assert str(reason).startswith("gate_hours_unchecked")
    # A window that ends before it starts is wrong on every clock.
    ok, reason = validators.delivery_within_gate_hours("07:00", "18:00", _at(9), _at(8))
    assert ok is False and not str(reason).startswith("gate_hours_unchecked")


def test_a_gate_without_hours_needs_no_zone() -> None:
    assert validators.delivery_within_gate_hours(None, None, _at(8), _at(9)) == (True, None)


def _gate_context(tz: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        data={
            "site_timezone": tz,
            "concept_hours": None,
            "gates": {"g": {"name": "North", "open_time": "07:00", "close_time": "18:00"}},
            "deliveries": [
                {"id": "a", "gate_id": "g", "window_start": _at(2).isoformat(), "window_end": _at(3).isoformat()},
                {"id": "b", "gate_id": "g", "window_start": _at(13).isoformat(), "window_end": _at(14).isoformat()},
            ],
        },
        metadata={},
    )


def test_gate_hours_rule_uses_the_zone_of_the_payload() -> None:
    results = _run(validators.SiteLogisticsGateHoursRule().validate(_gate_context("Asia/Kolkata")))
    assert {r.element_ref: r.passed for r in results} == {"a": True, "b": False}


def test_gate_hours_rule_reports_the_missing_zone_once() -> None:
    results = _run(validators.SiteLogisticsGateHoursRule().validate(_gate_context(None)))
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].message.startswith("gate_hours_unchecked")
    # A warning: unchecked hours do not turn the report into an error.
    assert results[0].severity == validators.Severity.WARNING


# ── FIX_BRIEF: no client date on a write route ─────────────────────────────


def test_sweep_takes_no_date_from_the_client() -> None:
    assert plan_schemas.SweepIn.model_fields == {}
    with pytest.raises(ValueError, match="today"):
        plan_schemas.SweepIn.model_validate({"today": "2020-01-01"})


def test_no_plan_request_schema_carries_today() -> None:
    for name in dir(plan_schemas):
        model = getattr(plan_schemas, name)
        if isinstance(model, type) and issubclass(model, plan_schemas._In):
            assert "today" not in model.model_fields, name


def test_state_changes_take_no_date_argument() -> None:
    import inspect

    svc = plan_service.LogisticsPlanService
    for name in (
        "transition_transport",
        "transition_permit",
        "transition_customs",
        "transition_complaint",
        "transition_media",
        "transition_stage",
        "sweep_permit",
        "sweep_permits",
        "sweep_complaint",
        "sweep_complaints",
        "sync_arrivals",
    ):
        assert "today" not in inspect.signature(getattr(svc, name)).parameters, name


# ── neutrality: no governance code in the module ───────────────────────────


def test_module_names_no_governance_area_gate_or_document() -> None:
    from app.modules.project_governance.catalogue import list_catalogues

    codes: set[str] = set()
    for cat in list_catalogues():
        codes |= {a.code for a in cat.areas if "logistics" in a.code}
        codes |= {d.code for d in cat.document_types if "logistics" in d.code}
        codes |= {g.code for g in cat.gates}
    codes = {c for c in codes if len(c) > 3}
    assert codes, "the governance catalogues ship areas and gates"
    for path in MODULE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        used = {c for c in codes if re.search(rf"\b{re.escape(c)}\b", text)}
        assert not used, (path.name, used)


# What the tags of the shipped phase models resolve to. The codes live here, in a
# test, and nowhere in the module.
SHIPPED_HOSTS = {
    "neutral": ("resources", "resource_plan"),
    "elf_module_framework": ("m06_logistics", "m06_logistics_frame"),
    "aho_heft9": ("d", "rahmenterminplan"),
}


def test_hosting_resolves_logistics_through_the_port_in_every_shipped_model() -> None:
    from app.modules.project_governance.catalogue import list_catalogues

    seen = {}
    for cat in list_catalogues():
        target = hosting.target_in(cat)
        assert target.reason is None, (cat.id, target)
        assert target.area_code in {a.code for a in cat.areas}
        assert target.frame_doc_type in {d.code for d in cat.document_types}
        enabling = {p.code for p in cat.phases_enabling(hosting.CAPABILITY)}
        assert target.gate_codes == tuple(g.code for g in cat.gates if g.to_phase in enabling)
        assert target.gate_codes
        seen[cat.id] = (target.area_code, target.frame_doc_type)
    for cid, expected in SHIPPED_HOSTS.items():
        assert seen[cid] == expected, cid


def test_the_subject_and_capability_are_in_the_governance_vocabulary() -> None:
    from app.modules.project_governance.catalogue_kinds import host_subjects, phase_capabilities

    assert hosting.SUBJECT in host_subjects()
    assert hosting.CAPABILITY in phase_capabilities()


class _Untagged:
    """A phase model that hosts nothing and enables nothing."""

    gates = (SimpleNamespace(code="g", to_phase="p"),)

    def host_of(self, subject: str):
        return None

    def phases_enabling(self, capability: str):
        return ()


def test_a_model_without_the_tags_resolves_to_a_named_reason() -> None:
    target = hosting.target_in(_Untagged())
    assert (target.area_code, target.frame_doc_type, target.gate_codes) == (None, None, ())
    assert target.reason == "no_area_hosts_logistics"
    assert hosting.GovernanceTarget(has_model=False).reason == "no_governance_model"
    assert hosting.GovernanceTarget(has_model=True, area_code="x").reason == "no_gate_for_logistics"


def test_a_plan_the_model_does_not_place_is_reported_unknown_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Data exists and nothing matches: one ``unknown`` item with the reason, on one area, never met."""
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.site_logistics import evidence

    svc = plan_service.LogisticsPlanService
    target = hosting.GovernanceTarget(has_model=True)

    async def fake_target(self, project_id):
        return target

    async def started(self, project_id):
        return True

    async def anchor(session, project_id):
        return "first"

    monkeypatch.setattr(svc, "governance_target", fake_target)
    monkeypatch.setattr(svc, "plan_started", started)
    monkeypatch.setattr(hosting, "first_applicable_area", anchor)
    attempt = GateAttempt(gate_id=uuid.uuid4(), gate_code="any", attempt_no=1)
    pid = uuid.uuid4()
    on_first = _run(evidence.logistics_readiness(None, pid, attempt, SimpleNamespace(code="first")))
    assert [(i.code, i.state, i.detail) for i in on_first] == [
        ("site_logistics:unresolved", "unknown", "no_area_hosts_logistics")
    ]
    assert _run(evidence.logistics_readiness(None, pid, attempt, SimpleNamespace(code="second"))) == []

    async def not_started(self, project_id):
        return False

    monkeypatch.setattr(svc, "plan_started", not_started)
    assert _run(evidence.logistics_readiness(None, pid, attempt, SimpleNamespace(code="first"))) == []


def test_the_module_reads_governance_only_through_its_port() -> None:
    for path in MODULE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "project_governance.models" not in text, path.name
        assert "project_governance.repository" not in text, path.name
        assert "GovernanceService" not in text, path.name
    source = (MODULE / "plan_service.py").read_text(encoding="utf-8")
    calls = re.findall(r"resolve_catalogue\(([^)]*)\)", source, flags=re.S)
    assert calls, "the plan resolves its pinned catalogue"
    for call in calls:
        assert "from_pin=True" in call or "tenant_id=" in call, call


def test_evidence_provider_is_registered_for_every_area_and_blocking() -> None:
    from app.modules.project_governance.evidence import ANY_AREA, evidence_providers
    from app.modules.site_logistics.evidence import PROVIDER, register_gate_evidence

    register_gate_evidence()
    [reg] = [p for p in evidence_providers() if p.name == PROVIDER]
    assert reg.key == ANY_AREA
    assert reg.blocking is True


# ── the link port for modules that are not merged yet ──────────────────────


def test_link_resolver_registry() -> None:
    async def owner(session, row_id):
        return None

    assert links.resolver("plant_item") is None or callable(links.resolver("plant_item"))
    links.register_link_resolver("plant_item", owner)
    try:
        assert links.resolver("plant_item") is owner
    finally:
        links.unregister_link_resolver("plant_item")
    assert links.resolver("plant_item") is None
    with pytest.raises(ValueError, match="unknown link kind"):
        links.register_link_resolver("purchase_order", owner)


class _NoSession:
    """A session that fails the test if the port touches the database."""

    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected session use: {name}")


def test_port_refuses_a_link_nobody_can_check() -> None:
    from app.modules.site_logistics.errors import LogisticsError

    svc = plan_service.LogisticsPlanService(_NoSession())
    project = uuid.uuid4()
    links.unregister_link_resolver("plant_item")
    with pytest.raises(LogisticsError) as exc:
        _run(svc._port("plant_item", uuid.uuid4(), project))
    assert (exc.value.code, exc.value.status_code) == ("link_target_unavailable", 422)
    # Nothing to check: no value, or the value already stored.
    _run(svc._port("plant_item", None, project))
    same = uuid.uuid4()
    _run(svc._port("plant_item", str(same), project, same))


def test_port_accepts_only_a_row_of_the_same_project() -> None:
    from app.modules.site_logistics.errors import LogisticsError

    project, other, row = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owners = {row: project}

    async def owner(session, row_id):
        return owners.get(row_id)

    svc = plan_service.LogisticsPlanService(_NoSession())
    links.register_link_resolver("plant_position", owner)
    try:
        _run(svc._port("plant_position", row, project))
        for foreign_project, foreign_row in ((other, row), (project, uuid.uuid4())):
            with pytest.raises(LogisticsError) as exc:
                _run(svc._port("plant_position", foreign_row, foreign_project))
            assert (exc.value.code, exc.value.status_code) == ("plant_position_not_found", 404)
    finally:
        links.unregister_link_resolver("plant_position")


# ── the periodic sweep ─────────────────────────────────────────────────────


def test_sweep_is_a_registered_platform_process() -> None:
    from app.core.processes import process_registry
    from app.modules.site_logistics.sweep import PROCESS_ID, register_sweep_process

    register_sweep_process()
    assert PROCESS_ID in process_registry.ids()


# ── permission, not a raw role ─────────────────────────────────────────────


def test_customs_values_follow_the_permission_of_the_token() -> None:
    from app.modules.site_logistics.permissions import register_site_logistics_permissions

    register_site_logistics_permissions()
    assert router._sees_values({"role": "viewer", "permissions": ["site_logistics.customs"]}) is True
    assert router._sees_values({"role": "viewer", "permissions": []}) is False
    assert router._sees_values({"role": "manager"}) is True
    assert router._sees_values({}) is False


# ── values, never clamped ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "new", "same"),
    [
        (None, None, True),
        (None, "x", False),
        ("x", None, False),
        (uuid.UUID(int=7), str(uuid.UUID(int=7)), True),
        (uuid.UUID(int=7), str(uuid.UUID(int=8)), False),
        (datetime(2026, 10, 12, 8, tzinfo=UTC), datetime(2026, 10, 12, 13, 30, tzinfo=SITE), True),
        (datetime(2026, 10, 12, 8, tzinfo=UTC), datetime(2026, 10, 12, 8, tzinfo=SITE), False),
        (plan_service.Decimal("62.00"), "62", True),
        (plan_service.Decimal("62.00"), "62.5", False),
        ("oversize_permit", "oversize_permit", True),
    ],
)
def test_same_compares_what_a_request_sends_with_what_is_stored(current, new, same: bool) -> None:
    assert plan_service._same(current, new) is same


# ── routes and connection points drawn on the site plan ────────────────────


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "LineString", "coordinates": [[0, 0], [10, 5]]},
        {"type": "LineString", "coordinates": [[0, 0], [10, 5], [10.25, 30.5]]},
        {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[5, 5], [6, 5]]]},
    ],
)
def test_a_route_is_a_line(geometry: dict) -> None:
    from app.modules.site_logistics.geometry import validate_route

    validate_route(geometry)


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "LineString", "coordinates": []},
        {"type": "LineString", "coordinates": [[0, 0]]},
        {"type": "LineString", "coordinates": [[3, 3], [3, 3]]},
        {"type": "LineString", "coordinates": [[0, 0], [float("nan"), 1]]},
        {"type": "LineString", "coordinates": [[0, 0], [2e7, 1]]},
        {"type": "LineString", "coordinates": [[0, 0], ["1", 1]]},
        {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[5, 5]]]},
        {"type": "LineString", "coordinates": [[i, 0] for i in range(5001)]},
    ],
)
def test_a_route_that_is_not_a_line_is_refused(geometry) -> None:
    from app.modules.site_logistics.geometry import GeometryError, validate_route

    with pytest.raises(GeometryError):
        validate_route(geometry)


def test_a_connection_point_is_a_point() -> None:
    from app.modules.site_logistics.geometry import GeometryError, validate_point

    validate_point({"type": "Point", "coordinates": [12.5, -3]})
    for bad in (
        None,
        {"type": "Point"},
        {"type": "Point", "coordinates": [1]},
        {"type": "Point", "coordinates": [1, float("inf")]},
        {"type": "Point", "coordinates": [1, 2e7]},
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
    ):
        with pytest.raises(GeometryError):
            validate_point(bad)


def test_stage_schema_carries_the_site_plan_backdrop() -> None:
    stage = plan_schemas.StageIn.model_validate(
        {"plan_document_id": str(uuid.uuid4()), "plan_metres_per_pixel": "0.052500", "plan_origin_px": [120, 840.5]}
    )
    assert stage.plan_origin_px == (120.0, 840.5)
    for bad in (
        {"plan_metres_per_pixel": "0"},
        {"plan_metres_per_pixel": "-1"},
        {"plan_metres_per_pixel": "0.1234567"},
        {"plan_origin_px": [1]},
        {"plan_origin_px": [1, 2, 3]},
        {"plan_origin_px": ["a", 2]},
    ):
        with pytest.raises(ValueError):
            plan_schemas.StageIn.model_validate(bad)


# ── round 2 ──────────────────────────────────────────────────────────────────


def test_a_flow_keeps_what_a_save_does_not_send() -> None:
    takt = str(uuid.uuid4())
    stored = {"flow_code": "facade", "mode": "just_in_time", "takt_schedule_id": takt, "buffer_days": 0}
    # The form shows no takt column: the field is not in the request and stays.
    kept = plan_service.merge_flow(stored, {"flow_code": "facade", "description": "Facade elements"})
    assert (kept["takt_schedule_id"], kept["mode"], kept["description"]) == (takt, "just_in_time", "Facade elements")
    # Sent as null it is cleared, like any nullable field.
    assert (
        plan_service.merge_flow(stored, {"flow_code": "facade", "takt_schedule_id": None})["takt_schedule_id"] is None
    )
    assert plan_service.merge_flow(None, {"flow_code": "new"}) == {"flow_code": "new"}


def test_the_concept_route_sends_only_what_the_form_sent() -> None:
    import inspect

    assert "model_dump(exclude_unset=True) for f in body.strategy" in inspect.getsource(router.plan_put_concept)
    assert "merge_flow(" in inspect.getsource(plan_service.LogisticsPlanService.put_concept)


def test_the_board_of_a_site_that_has_not_started_lies_in_its_first_week() -> None:
    from app.modules.site_logistics import demo

    rows = demo.planned_deliveries()
    assert len(rows) == len(demo._DELIVERIES)
    first = demo.DEMO_CONSTRUCTION_START_DAY + 1
    assert first == 191
    assert [r[0] for r in rows] == list(range(first, first + len(rows)))
    assert {r[4] for r in rows} == {"approved", "requested"}
    # Hours, gates and quantities are those of the running board: the gate hours still hold.
    assert [(r[1], r[2], r[3], r[5]) for r in rows] == [(r[1], r[2], r[3], r[5]) for r in demo._DELIVERIES]


@pytest.mark.parametrize(
    ("phases", "gates", "expected"),
    [
        ((), [("build", "in_preparation")], False),
        (("build",), [], False),
        (("build",), [("design", "in_preparation")], False),
        (("build",), [("design", "decided"), ("build", "in_preparation")], True),
        (("build",), [("build", "not_started")], True),
        (("build",), [("build", "decided")], False),
    ],
)
def test_before_construction_is_read_from_the_gate_into_it(monkeypatch, phases, gates, expected: bool) -> None:
    from app.modules.project_governance import public

    async def enabling(session, project_id, capability):
        assert capability == hosting.CAPABILITY
        return phases

    async def listed(session, project_id):
        return tuple(SimpleNamespace(to_phase=p, status=s) for p, s in gates)

    monkeypatch.setattr(public, "phases_enabling", enabling)
    monkeypatch.setattr(public, "project_gates", listed)
    assert _run(hosting.before_construction(None, uuid.uuid4())) is expected


def test_the_plan_seed_does_not_swallow_a_refusal() -> None:
    source = (MODULE / "demo_plan.py").read_text(encoding="utf-8")
    assert "except Exception" not in source
    assert "before_construction(" in source and "before_construction(" in (MODULE / "demo.py").read_text(
        encoding="utf-8"
    )


# German words that were written without their umlaut or eszett. Each has a correct form,
# so none of these spellings may come back in what a German user reads.
TRANSLITERATED = [
    "Ablageflaeche",
    "Baustelleneinrichtungsflaeche",
    "Behoerde",
    "Behoerdliche",
    "Bestaetigen",
    "Bestaetigt",
    "Dafuer",
    "Eintraege",
    "Faellig",
    "Flaeche",
    "Flaechen",
    "Flaechenart",
    "Flaechenbilanz",
    "Flaechenumriss",
    "Fuer",
    "Geprueft",
    "Geraet",
    "Geraeteposition",
    "Gesamtflaeche",
    "Gueltige",
    "Gueltigkeit",
    "Gueltigkeitsdaten",
    "Immissionsschutzbehoerde",
    "Kaeufer",
    "Kuerzel",
    "Laendercode",
    "Laermgrenzwert",
    "Laermgrenzwerte",
    "Lagerflaeche",
    "Massgrenzen",
    "Massnahme",
    "Massstab",
    "Mindestlaenge",
    "Naeher",
    "Restflaeche",
    "Sozialraeume",
    "Strassenbaulastraeger",
    "Strassenverkehrsbehoerde",
    "Verkaeufer",
    "Verkehrstraeger",
    "Verknuepfung",
    "Waehrung",
    "Waehrungscode",
    "Zollvorgaenge",
    "abschliessen",
    "aendern",
    "aufloesbar",
    "ausser",
    "ausserhalb",
    "behaelt",
    "benoetigt",
    "bestaetigter",
    "erhoehen",
    "frueher",
    "frueheren",
    "fuer",
    "geaendert",
    "geloescht",
    "geprueft",
    "groesser",
    "gueltige",
    "gueltiger",
    "gueltiges",
    "hoechstens",
    "koennen",
    "laeuft",
    "pruefbar",
    "pruefen",
    "ueberlappen",
    "ueberschreitet",
    "ungueltig",
    "verknuepfen",
    "verlaengern",
    "vollstaendig",
    "waehlen",
    "waehrend",
    "zulaessig",
    "zulaessige",
]


def test_german_texts_are_written_with_umlauts_and_eszett() -> None:
    assert len(TRANSLITERATED) > 70
    for path in (MODULE / "messages" / "de.json", MODULE / "catalogues" / "site_logistics" / "de.json"):
        text = path.read_text(encoding="utf-8")
        found = sorted(set(re.findall(r"[A-Za-z]+", text)) & set(TRANSLITERATED))
        assert not found, (path.name, found)
        assert re.search("[äöüß]", text), path.name


# ── decisions of 2026-10-13 ─────────────────────────────────────────────────


def _board(tz: ZoneInfo | None, gate: SimpleNamespace | None, concept_hours=None):
    from app.modules.site_logistics import service as board

    svc = board.SiteLogisticsService.__new__(board.SiteLogisticsService)

    async def site_tz(project_id):
        return tz

    async def get_by_id(gate_id):
        return gate

    async def hours(project_id):
        return concept_hours

    svc._plan = lambda: SimpleNamespace(site_tz=site_tz)
    svc.gate_repo = SimpleNamespace(get_by_id=get_by_id)
    svc._concept_hours = hours
    return svc


def _booked(gate_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(project_id=uuid.uuid4(), gate_id=gate_id, window_start=_at(22), window_end=_at(23))


def test_a_delivery_on_a_site_without_a_zone_carries_the_warning() -> None:
    gate = SimpleNamespace(open_time="07:00", close_time="18:00")
    warning = {"code": "gate_hours_unchecked", "severity": "warning", "field": "site_timezone"}
    assert _run(_board(None, gate).delivery_warnings(_booked(uuid.uuid4()))) == [warning]
    # Hours of the concept count like hours of the gate.
    open_gate = SimpleNamespace(open_time=None, close_time=None)
    assert _run(_board(None, open_gate, ("07:00", "18:00")).delivery_warnings(_booked(uuid.uuid4()))) == [warning]


def test_no_warning_where_nothing_was_skipped() -> None:
    gate = SimpleNamespace(open_time="07:00", close_time="18:00")
    open_gate = SimpleNamespace(open_time=None, close_time=None)
    # The site has a zone: the hours were compared.
    assert _run(_board(SITE, gate).delivery_warnings(_booked(uuid.uuid4()))) == []
    # No hours to compare with, and no gate at all.
    assert _run(_board(None, open_gate).delivery_warnings(_booked(uuid.uuid4()))) == []
    assert _run(_board(None, gate).delivery_warnings(_booked(None))) == []


def test_the_gate_hours_check_never_refuses_for_a_missing_zone() -> None:
    from fastapi import HTTPException

    from app.modules.site_logistics import service as board

    gate = SimpleNamespace(open_time="07:00", close_time="18:00")
    check = board.SiteLogisticsService._assert_within_gate_hours
    assert check(gate, _at(22), _at(23), None, None) is None
    with pytest.raises(HTTPException) as exc:
        # 22:00 UTC is 03:30 on site: with a zone the same window is refused.
        check(gate, _at(22), _at(23), None, SITE)
    assert exc.value.code == "outside_gate_hours"


def test_unchecked_hours_have_their_texts() -> None:
    for locale in ("en", "de"):
        for key in ("errors.gate_hours_unchecked", "findings.gate_hours_unchecked.fail"):
            text = translate(f"site_logistics.{key}", locale=locale)
            assert text and "gate_hours_unchecked" not in text, (locale, key)


def test_only_a_granted_permit_makes_a_heavy_transport_ready() -> None:
    from app.modules.site_logistics import planning as pl

    kinds = {"oversize_permit"}

    def permit(state: str, kind: str = "oversize_permit") -> dict:
        return {"permit_kind": kind, "state": state}

    assert pl.heavy_permit_standing([], kinds) == "missing"
    assert pl.heavy_permit_standing([permit("draft")], kinds) == "missing"
    # The defect: an application used to count as enough.
    assert pl.heavy_permit_standing([permit("applied")], kinds) == "applied"
    assert pl.heavy_permit_standing([permit("applied"), permit("granted")], kinds) == "granted"
    # A granted permit of another kind does not carry a heavy load.
    assert pl.heavy_permit_standing([permit("granted", "night_work")], kinds) == "missing"


def test_a_pack_catalogue_is_a_source_the_pin_accepts() -> None:
    from app.modules.project_governance.catalogue_packs import PACK_SOURCE

    assert plan_schemas.CataloguePinIn(source=PACK_SOURCE, catalogue_id="site").source == "pack"
    with pytest.raises(ValueError, match="source"):
        plan_schemas.CataloguePinIn(source="elsewhere", catalogue_id="site")


def test_a_pinned_catalogue_that_no_longer_loads_is_named_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.project_governance import catalogue_store
    from app.modules.project_governance.catalogue import InvalidCatalogueError
    from app.modules.site_logistics.errors import LogisticsError

    async def broken(*args, **kwargs):
        raise InvalidCatalogueError("/srv/packs/site.json", ["area kind 'x' is declared twice"])

    async def concept(self, project_id):
        return SimpleNamespace(catalogue_source="pack", catalogue_id="site", catalogue_version=1)

    monkeypatch.setattr(catalogue_store, "resolve_catalogue", broken)
    monkeypatch.setattr(plan_service.LogisticsPlanService, "concept", concept)
    with pytest.raises(LogisticsError) as exc:
        _run(plan_service.LogisticsPlanService(None).catalogue(uuid.uuid4()))
    assert (exc.value.code, exc.value.status_code) == ("catalogue_invalid", 422)
    assert exc.value.detail == "area kind 'x' is declared twice"


def test_evidence_items_open_the_plan_of_their_project() -> None:
    from app.modules.project_governance import evidence as gov
    from app.modules.site_logistics import evidence

    pid = uuid.uuid4()
    gov.unregister_evidence_link(evidence.LINK_KIND)
    assert gov.evidence_link_href(evidence.LINK_KIND, str(pid), pid) is None
    evidence.register_gate_evidence()
    assert gov.evidence_link_href(evidence.LINK_KIND, str(pid), pid) == f"/projects/{pid}/site-logistics"


# ── integration verdict of 2026-10-13 ───────────────────────────────────────


def test_links_from_the_previous_release_to_a_new_table_are_keys_the_heal_defers() -> None:
    """The upgrade lane: the boot heal alters existing tables before the new ones exist.

    A foreign key from the gate, laydown zone or delivery table (all three shipped
    in the previous release) to a table v78 added is one the heal cannot issue
    before ``create_all``; it defers it (``heal_deferred_foreign_keys``). Exactly
    two such keys exist, both SET NULL, and v98 is the revision that adds them on
    a database whose chain is walked by hand. Any other one needs the same care.
    """
    from app.modules.site_logistics import models as m

    shipped_before = {m.Gate.__tablename__, m.LaydownZone.__tablename__, m.DeliveryBooking.__tablename__}
    line_table = m.DeliveryLine.__tablename__
    into_new = set()
    for model in (m.Gate, m.LaydownZone, m.DeliveryBooking):
        for fk in model.__table__.foreign_key_constraints:
            target = fk.elements[0].column.table.name
            if target.startswith("oe_site_logistics_") and target not in shipped_before | {line_table}:
                into_new.add((model.__tablename__, fk.name, target, fk.ondelete))
    assert into_new == {
        (m.LaydownZone.__tablename__, "fk_oe_site_zone_area", m.SiteArea.__tablename__, "SET NULL"),
        (m.DeliveryBooking.__tablename__, "fk_oe_site_delivery_transport", m.Transport.__tablename__, "SET NULL"),
    }
    v78 = (MODULE.parents[2] / "alembic" / "versions" / "v78_site_logistics_ext.py").read_text(encoding="utf-8")
    assert "fk_oe_site_zone_area" not in v78 and "fk_oe_site_delivery_transport" not in v78
    v98 = (MODULE.parents[2] / "alembic" / "versions" / "v98_site_logistics_link_keys.py").read_text(encoding="utf-8")
    assert "fk_oe_site_zone_area" in v98 and "fk_oe_site_delivery_transport" in v98


def test_deleting_an_area_or_a_transport_unlinks_what_pointed_at_it() -> None:
    import inspect

    area = inspect.getsource(plan_service.LogisticsPlanService.delete_area)
    transport = inspect.getsource(plan_service.LogisticsPlanService.delete_transport)
    assert "update(LaydownZone)" in area and "site_area_id=None" in area
    assert "update(DeliveryBooking)" in transport and "transport_id=None" in transport


def test_the_plan_drawing_is_a_constrained_document_reference() -> None:
    from app.modules.site_logistics import models as m

    (fk,) = m.ExpansionStage.__table__.c.plan_document_id.foreign_keys
    assert fk.target_fullname == "oe_documents_document.id"
    assert fk.ondelete == "SET NULL"


@pytest.mark.parametrize("bad", ["1", "1.5", None, True, [1], {"x": 1}])
def test_a_coordinate_is_a_number_and_nothing_else(bad) -> None:
    from app.modules.site_logistics.geometry import GeometryError, polygon_area_m2, validate_point, validate_route

    with pytest.raises(GeometryError):
        validate_point({"type": "Point", "coordinates": [bad, 1]})
    with pytest.raises(GeometryError):
        validate_route({"type": "LineString", "coordinates": [[0, 0], [1, bad]]})
    with pytest.raises(GeometryError):
        polygon_area_m2({"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, bad], [0, 0]]]})


def _ring(x0: float, y0: float, w: float, h: float) -> list[list[float]]:
    return [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h], [x0, y0]]


def test_a_hole_lies_inside_its_polygon() -> None:
    from decimal import Decimal

    from app.modules.site_logistics.geometry import GeometryError, polygon_area_m2

    outer = _ring(0, 0, 10, 10)

    def area(*holes: list[list[float]]) -> Decimal:
        return polygon_area_m2({"type": "Polygon", "coordinates": [outer, *holes]})

    assert area(_ring(2, 2, 4, 4)) == Decimal("84.00")
    # A hole that shares an edge with the outline is still inside it.
    assert area(_ring(0, 0, 4, 4)) == Decimal("84.00")
    for hole in (_ring(20, 20, 4, 4), _ring(8, 8, 4, 4), _ring(-1, -1, 12, 12)):
        # Away from the polygon, half out of it, and around it.
        with pytest.raises(GeometryError, match="geometry_bad_hole"):
            area(hole)
    # Every corner on the outline and one edge outside it: a notch the corners do not show.
    notched = [[0, 0], [10, 0], [10, 10], [5, 5], [0, 10], [0, 0]]
    with pytest.raises(GeometryError, match="geometry_bad_hole"):
        polygon_area_m2({"type": "Polygon", "coordinates": [notched, [[0, 10], [10, 10], [5, 5], [0, 10]]]})


def test_the_export_declares_the_language_it_was_written_in() -> None:
    from app.modules.site_logistics import export

    assert export.written_locale("de") == "de"
    assert export.written_locale("en") == "en"
    # A language the module has no texts for is written in English, and says so.
    assert export.written_locale("fr") == "en"
    assert export.written_locale(None) == "en"
