# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-free import smoke test for the deadlines module (item #18).

The pure-logic test cannot catch an import typo, a bad symbol, or a circular
import in the impure files (service / router / sweeper), and a broken router
import does NOT crash the app - the module loader swallows it and silently
fails to mount. This asserts every impure file imports and the router object
exists with both endpoints.

Engine creation is lazy and sibling-model imports are deferred inside the
collectors, so importing these modules touches no database.

Run:
    cd backend
    python -m pytest tests/unit/test_deadlines_imports.py -q
"""

from __future__ import annotations


def test_router_module_exposes_router() -> None:
    from fastapi import APIRouter

    from app.modules.deadlines import router as router_mod

    assert isinstance(router_mod.router, APIRouter)
    paths = {getattr(r, "path", None) for r in router_mod.router.routes}
    assert "/" in paths
    assert "/sweep" in paths


def test_service_symbols_present() -> None:
    from app.modules.deadlines import service

    assert callable(service.compute_deadlines)
    assert callable(service.collect_overdue_for_sweep)
    # Collector registry is well-formed (module_key, collector, owns_sweep).
    assert [m for m, _c, _o in service._COLLECTORS] == [
        "correspondence",
        "qms_ncr_action",
        "punchlist",
        "rfi",
        "submittals",
        "variations",
        "temporary_works",
        "temporary_works_permit",
        "defects_liability",
        "inspections",
        "compliance_docs",
        "bid_management",
        "signing",
        "contracts_payment_plan_claim",
        "contracts_payment_plan",
    ]
    # Module keys are unique (they key the notification event type and the
    # ``?module=`` filter) and every collector is callable.
    keys = [m for m, _c, _o in service._COLLECTORS]
    assert len(keys) == len(set(keys))
    assert all(callable(c) for _m, c, _o in service._COLLECTORS)
    # No source self-sweeps today. The registry comment carries the evidence per
    # source; the one that could change under us is gated by
    # test_compliance_docs_expiry_alert_has_no_subscriber below.
    assert not any(o for _m, _c, o in service._COLLECTORS)


def test_sweeper_symbols_present() -> None:
    from app.modules.deadlines import sweeper

    assert callable(sweeper.sweep_overdue)
    assert callable(sweeper.start_deadline_sweeper)
    assert sweeper.OVERDUE_TYPE == "deadline_overdue"
    assert sweeper.ESCALATED_TYPE == "deadline_escalated"


def test_manifest_and_permissions_import() -> None:
    from app.modules.deadlines.manifest import manifest
    from app.modules.deadlines.permissions import register_deadlines_permissions

    assert manifest.name == "oe_deadlines"
    assert callable(register_deadlines_permissions)


def test_notification_templates_registered() -> None:
    # The sweeper's title/body keys must have server-side English fallbacks.
    from app.modules.notifications.templates import icon_category_for, render

    assert render("notifications.deadline.overdue.title", {"title": "Door 12"}) == "Overdue: Door 12"
    body = render(
        "notifications.deadline.overdue.body",
        {"module": "punchlist", "title": "Door 12", "days_overdue": 3},
    )
    assert "3 day(s) past due" in body
    assert icon_category_for("deadline_overdue") == "warning"
    assert icon_category_for("deadline_escalated") == "error"


def test_compliance_docs_expiry_alert_has_no_subscriber() -> None:
    """The one source that could double-notify, pinned instead of commented.

    ``compliance_docs`` publishes ``compliance_docs.expiry.alert`` when a
    document crosses into ``expiring_soon`` or ``expired``. It carries
    ``owns_overdue_sweep=False`` in the deadlines registry, so the sweeper also
    notifies on that document - correct today only because nothing subscribes
    to the event, so the publish produces no notification.

    Wiring a subscriber is a two-line change of exactly the kind the wave
    modules already got, and it would make both paths fire on the transition
    day. Read the source rather than the live bus: registering subscribers here
    to inspect them would leave them attached for every later test in the
    process.
    """
    from pathlib import Path

    import app.modules.notifications as notifications_pkg

    event = "compliance_docs.expiry.alert"
    wired = sorted(
        p.name for p in Path(notifications_pkg.__file__).parent.glob("*.py") if event in p.read_text(encoding="utf-8")
    )
    assert wired == [], (
        f"{wired} now handles {event}, so compliance_docs notifies on its own. "
        "Set owns_overdue_sweep=True for it in deadlines/service.py::_COLLECTORS, "
        "or the sweeper will send a second notification on the transition day."
    )


def test_event_types_registered() -> None:
    """Every collector's overdue event must be in the preference catalogue.

    ``enqueue_or_dispatch`` does not gate on the catalogue, so a missing entry
    still notifies - but it never reaches the preferences UI, which means the
    user has no way to move that source onto a digest or switch it off.
    """
    from app.modules.deadlines.service import _COLLECTORS
    from app.modules.notifications.service import KNOWN_EVENT_TYPES

    etypes = {e["event_type"] for e in KNOWN_EVENT_TYPES}
    missing = [m for m, _c, _o in _COLLECTORS if f"deadlines.{m}.overdue" not in etypes]
    assert missing == [], f"deadline sources missing from KNOWN_EVENT_TYPES: {missing}"
