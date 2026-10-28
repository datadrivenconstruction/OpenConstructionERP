# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``/api/health`` says whether the record of the boot-time repairs survived.

``run_data_repairs`` returns ``ledger_written`` separately from the repair
outcomes, and the report's own docstring argues at length for why: a repair can
succeed against a database whose role may write rows but not create tables, in
which case the data is correct and the *record* of it is missing, and
collapsing the two would let the smaller failure hide the larger.

The boot path published the outcomes side and threw the other one away. With
``oe_data_repair_ledger`` dropped, both registered repairs landed,
``ledger_written`` came back ``False``, and ``/api/health`` answered ``healthy``
with ``data_repairs_failed: false``. Nothing on that install could then answer
"did this repair run here", which is the only question the ledger exists for,
and nothing said so. Reporting them separately is worth nothing unless both are
then published; this file holds the second half.

The key is ``data_repair_ledger_failed`` and not ``ledger_written`` because of
its neighbours. ``schema_heal_failed`` and ``data_repairs_failed`` both read
``true`` for bad news and are both tested with ``is True``; a field on the same
payload whose ``true`` meant good news would make every monitor rule carry one
opposite predicate for one field, which is how a rule ends up written the wrong
way round.

Three states, for the same reason the fields beside it have three. ``true`` at
least one ledger write failed, ``false`` every one was written, ``null`` the
pass never ran - where a deployment whose database is not PostgreSQL stays for
its whole life, because the repair pass sits inside the same ``if "postgresql"
in settings.database_url`` branch the heal does. That third state is what stops
``false`` from ever being readable as "nothing was attempted": a pass that did
not run never leaves ``null``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _pin_the_frontend_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave ``status`` a function of the ledger, which is what this file is about.

    ``/api/health`` folds a frontend-build probe into the same ``status``
    field every test here reads, and that probe degrades whenever no
    ``index.html`` is on disk. The backend CI lane creates ``frontend/dist``
    holding nothing but a ``.gitkeep``, so the probe answers False for the
    whole lane, and it broke this file in both directions at once: the
    "healthy" case could not pass there whatever the ledger said, and each
    "degraded" case passed there whatever the ledger said, on a verdict the
    field under test took no part in. A test whose subject cannot change its
    result is the same defect either way round.

    Pinning the probe is not a claim that a build exists. It says only that
    whether one does is somebody else's question, asked in its own test.
    """
    from app import cli_static

    monkeypatch.setattr(cli_static, "mounted_frontend_intact", lambda: True)


def _fresh_app() -> FastAPI:
    """An application as it exists before any startup has run."""
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Deliberately not the context-manager form, which would run the lifespan
    # and replace the verdict under test.
    return TestClient(app).get("/api/health").json()


def test_a_lost_ledger_is_visible_and_degrades_the_status() -> None:
    """The measured defect, stated so it fails.

    Repairs fine, record gone. Before the key existed this exact state
    answered ``healthy``.
    """
    app = _fresh_app()
    app.state.data_repairs_failed = False
    app.state.data_repairs_failed_ids = ()
    app.state.data_repair_ledger_failed = True

    payload = _health(app)

    assert payload["data_repair_ledger_failed"] is True
    assert payload["data_repairs_failed"] is False, "a lost ledger must not be reported as a failed repair"
    assert payload["status"] == "degraded"


def test_a_written_ledger_reports_false() -> None:
    app = _fresh_app()
    app.state.data_repair_ledger_failed = False

    payload = _health(app)

    assert payload["data_repair_ledger_failed"] is False


def test_a_deployment_that_never_ran_the_repairs_reports_unknown() -> None:
    """``null``, not ``false``.

    This is the whole reason ``false`` can be trusted to mean "the record was
    written" rather than "nobody tried". If a pass that never happened reported
    ``false``, the two would be the same value and the field would be worth
    nothing.
    """
    payload = _health(_fresh_app())

    assert payload["data_repair_ledger_failed"] is None
    # The two other probes a freshly built application can degrade on, named
    # so that a red run says which one moved instead of pointing at the
    # ledger. The first is the one the fixture pins; the second is the test
    # database, without which nothing in this suite means anything anyway.
    assert payload["frontend_dist_present"] is True
    assert payload["database"] == "ok"
    assert payload["status"] == "healthy", "never having run is not a fault"


def test_the_field_is_always_present_so_an_old_build_is_distinguishable() -> None:
    """A monitor has to tell "I cannot say" from "this backend has no such field".

    Both are falsy in Python and in most alerting DSLs, so the key is emitted
    unconditionally, exactly as the two fields beside it are.
    """
    assert "data_repair_ledger_failed" in _health(_fresh_app())


def test_the_verdict_writer_publishes_both_halves_of_a_report() -> None:
    """The wiring, held against the function the boot path actually calls.

    The endpoint tests above pass against an ``app.state`` set by hand, so they
    would go on passing if the boot path never wrote the field - which is
    precisely the shape of the defect. This one enters through
    ``publish_data_repair_verdict``, the only writer of either field, with a
    report whose repairs succeeded and whose ledger write did not.
    """
    from app.core.data_repairs import DataRepairOutcome, DataRepairReport
    from app.main import publish_data_repair_verdict

    app = _fresh_app()
    publish_data_repair_verdict(
        app,
        DataRepairReport(
            outcomes=(DataRepairOutcome(repair_id="example", status="applied", rows_changed=3),),
            ledger_written=False,
        ),
    )

    payload = _health(app)

    assert payload["data_repairs_failed"] is False
    assert payload["data_repair_ledger_failed"] is True
    assert payload["status"] == "degraded"


def test_a_pass_that_could_not_run_at_all_fails_both_fields() -> None:
    """``None`` for the report, which is not the ``None`` the fields start at.

    A pass that raised before producing a report left rows unrepaired AND
    unrecorded. Reporting the ledger as ``null`` there would say "never
    attempted" about a boot that attempted and could not, and would sit
    incoherently beside ``data_repairs_failed: true``.
    """
    from app.main import publish_data_repair_verdict

    app = _fresh_app()
    publish_data_repair_verdict(app, None)

    payload = _health(app)

    assert payload["data_repairs_failed"] is True
    assert payload["data_repair_ledger_failed"] is True
    assert payload["status"] == "degraded"


def test_which_write_failed_is_not_published_to_an_anonymous_caller() -> None:
    """The endpoint is unauthenticated, so it carries the verdict and not the detail.

    Same argument that keeps ``schema_heal_error`` and the failed repair ids off
    this payload: the cause names internal tables and statements and belongs in
    the boot log, where the operator of the machine is.
    """
    app = _fresh_app()
    app.state.data_repair_ledger_failed = True

    payload = _health(app)

    assert "oe_data_repair_ledger" not in str(payload)
