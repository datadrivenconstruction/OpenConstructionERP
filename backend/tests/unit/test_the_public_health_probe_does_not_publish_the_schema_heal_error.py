"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An unauthenticated probe must not be handed the database's own words.

``/api/health`` reports whether the boot-time schema heal failed, and it briefly
also reported *why*, as ``f"{type(exc).__name__}: {exc}"``. What fails there is a
database exception, and SQLAlchemy DBAPI errors stringify with the statement
appended to them - ``[SQL: ALTER TABLE oe_... ADD COLUMN ...]``, very often
``[parameters: ...]`` as well.

Nothing authenticates that endpoint, on purpose. The desktop shell polls it with
no Authorization header to decide whether it may attach to a backend that is
already running rather than start a second one against the same data directory,
and container healthchecks ask on the same terms. So it answers anybody who can
reach the port, and on a deployment whose port is reachable the message would
hand an anonymous caller table names, column names and the text of the statement
that just failed on them.

The boolean beside it is the part an operator acts on, and the cause is written
in full to the boot log where the operator of that machine is. So the boolean is
published and the message is not. Both halves are held here: the text must not
appear anywhere in the response body, and the failure must still be reported,
because a fix that simply stopped saying anything would pass the first half and
lose the signal that made the field worth having.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI

# A real message of the shape this deployment produces, shortened. Each
# bracketed section is a separate reason the field cannot be public: the first
# names a table and a column of the deployment, the second is whatever was being
# bound when it failed.
DBAPI_MESSAGE = (
    "ProgrammingError: (psycopg2.errors.InsufficientPrivilege) permission denied "
    "for table oe_boq_position\n"
    "[SQL: ALTER TABLE oe_boq_position ADD COLUMN IF NOT EXISTS cost_line_id UUID]\n"
    "[parameters: ('tenant-7f3a',)]"
)

#: Fragments of it that must never leave the process over this endpoint. Each is
#: enough on its own to tell a stranger something about the deployment.
LEAKED_FRAGMENTS = (
    "ALTER TABLE",
    "oe_boq_position",
    "cost_line_id",
    "[SQL:",
    "[parameters:",
    "InsufficientPrivilege",
    "psycopg2",
)


@pytest.fixture
def app_with_a_failed_heal() -> FastAPI:
    """An application whose boot-time schema heal failed.

    The startup event is deliberately not run. It is what performs the real
    heal, and what is under test here is what the endpoint publishes about a
    verdict, not how the verdict is reached, so the verdict is written the way
    startup writes it and the endpoint is asked.
    """
    from app.main import create_app

    app = create_app()
    app.state.schema_heal_failed = True
    app.state.schema_heal_error = DBAPI_MESSAGE
    return app


def _health_response(app: FastAPI):
    """Ask ``/api/health`` the way an anonymous caller does: no credentials."""
    from fastapi.testclient import TestClient

    # Not entered as a context manager: that is what runs the lifespan, and the
    # lifespan would overwrite the verdict this test just set.
    return TestClient(app).get("/api/health")


def test_the_body_carries_no_fragment_of_the_exception(app_with_a_failed_heal: FastAPI) -> None:
    """The defect, stated as the consumer meets it: bytes on the wire.

    Asserted against the serialized body rather than against the absence of the
    ``schema_heal_error`` key, because absence of a key is not absence of the
    text. Re-adding the message under any other name, or folding it into
    ``status``, passes a key check and fails this one.
    """
    response = _health_response(app_with_a_failed_heal)

    assert response.status_code == 200
    body = response.text
    for fragment in LEAKED_FRAGMENTS:
        assert fragment not in body, f"the public health payload still publishes {fragment!r}"


def test_no_field_of_the_payload_is_the_message(app_with_a_failed_heal: FastAPI) -> None:
    """The same thing asked of the parsed values, so an encoding cannot hide it."""
    payload = _health_response(app_with_a_failed_heal).json()

    assert "schema_heal_error" not in payload
    for key, value in payload.items():
        assert not (isinstance(value, str) and "ALTER TABLE" in value), f"{key!r} carries the failed statement"


def test_the_failure_is_still_reported_to_whoever_asks(app_with_a_failed_heal: FastAPI) -> None:
    """The other polarity, and the reason the field exists at all.

    An operator on an external PostgreSQL whose role cannot issue DDL has this
    boolean and nothing else standing between them and an install that reports
    itself healthy while every read of a table with a newer column answers 500.
    Silencing the endpoint would be a worse bug than the leak.
    """
    payload = _health_response(app_with_a_failed_heal).json()

    assert payload["schema_heal_failed"] is True
    assert payload["status"] == "degraded"


def test_the_cause_is_kept_where_the_operator_can_read_it(app_with_a_failed_heal: FastAPI) -> None:
    """Not published is not discarded.

    The message is what the boot-time ``logger.error`` writes out in full, and
    it stays on the application so a process that has it can still be asked.
    Dropping it on the floor would make the leak untestable and the log line
    empty at the same time.
    """
    _health_response(app_with_a_failed_heal)

    assert app_with_a_failed_heal.state.schema_heal_error == DBAPI_MESSAGE


def test_a_deployment_that_healed_publishes_nothing_either() -> None:
    """No message on the success path, where there is none to leak."""
    from app.main import create_app

    app = create_app()
    app.state.schema_heal_failed = False
    app.state.schema_heal_error = None

    payload = _health_response(app).json()

    assert payload["schema_heal_failed"] is False
    assert "schema_heal_error" not in payload
