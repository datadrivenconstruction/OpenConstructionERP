# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``/api/health`` says whether the boot-time data repairs ran, in three states.

The field beside this one, ``schema_heal_failed``, answers for the SCHEMA half
of an upgrade. Until ``data_repairs_failed`` existed there was no answer for the
other half at all, and the field that looks like one lies about it:
``alembic_head_matches`` reports ``true`` on a database whose data rewrites
never executed, because the boot path stamps head from ``create_all`` and a
revision's ``upgrade()`` body is never run. A monitor reading that payload had
no way to tell a database whose row-level corrections landed from one where they
did not.

Three states, and they are three, for the same reason the two fields above it
have three. ``true`` at least one repair raised, ``false`` every repair
completed, ``null`` the pass never ran. ``null`` is where a deployment whose
database is not PostgreSQL stays for its whole life, because the repair pass
sits inside the same ``if "postgresql" in settings.database_url`` branch the
heal does. Reporting that as ``false`` would say "all repairs completed" about
a pass that never happened, which is exactly the substitution these fields exist
to stop making.

The polarity matches ``schema_heal_failed`` and is the inverse of
``alembic_head_matches``: here ``true`` is the bad news, which is why the
endpoint reads it with ``is True`` rather than as a truth value. ``null`` is not
a fault and must not degrade the status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def _fresh_app() -> FastAPI:
    """An application as it exists before any startup has run."""
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Deliberately not the context-manager form, which would run the lifespan
    # and replace the verdict under test.
    return TestClient(app).get("/api/health").json()


def test_a_failed_repair_reports_true_and_degrades() -> None:
    app = _fresh_app()
    app.state.data_repairs_failed = True
    app.state.data_repairs_failed_ids = ("formwork_debrand",)

    payload = _health(app)

    assert payload["data_repairs_failed"] is True
    assert payload["status"] == "degraded"


def test_a_pass_where_every_repair_completed_reports_false() -> None:
    app = _fresh_app()
    app.state.data_repairs_failed = False
    app.state.data_repairs_failed_ids = ()

    payload = _health(app)

    assert payload["data_repairs_failed"] is False


def test_a_deployment_that_never_ran_the_repairs_reports_unknown() -> None:
    """The state that would otherwise be indistinguishable from success."""
    payload = _health(_fresh_app())

    assert payload["data_repairs_failed"] is None


def test_the_field_is_always_present_so_an_old_build_is_distinguishable() -> None:
    """A monitor has to tell "I cannot say" from "this backend has no such field".

    Both are falsy in Python and in most alerting DSLs, so the key is emitted
    unconditionally, exactly as ``schema_heal_failed`` is.
    """
    assert "data_repairs_failed" in _health(_fresh_app())


def test_which_repairs_failed_is_not_published_to_an_anonymous_caller() -> None:
    """The endpoint is unauthenticated, so it carries the verdict and not the detail.

    Repair ids name internal tables and releases. The same argument keeps
    ``schema_heal_error`` off this payload, and the ids stay on ``app.state``
    and in the boot log where the operator of the machine is.
    """
    app = _fresh_app()
    app.state.data_repairs_failed = True
    app.state.data_repairs_failed_ids = ("formwork_debrand",)

    payload = _health(app)

    assert "formwork_debrand" not in str(payload)
