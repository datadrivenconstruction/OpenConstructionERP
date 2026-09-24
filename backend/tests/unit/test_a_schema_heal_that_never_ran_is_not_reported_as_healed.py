"""A verdict about work that never happened is not "it went fine".

``/api/health`` reports ``schema_heal_failed``, and it computed it as a plain
two-valued boolean: false unless a failure was recorded. The heal that would
record one runs inside ``if "postgresql" in settings.database_url`` in the
startup sequence, so a deployment whose database is not PostgreSQL never reaches
it and answered ``false`` for its whole life - "healed fine" about a heal that
never happened, which is not what that deployment knows.

Three states are needed and there are three: healed, failed, never ran. This is
the same argument the field one line above it already makes -
``alembic_head_matches`` answers ``null`` where the comparison cannot be made,
because a permanent wrong answer is worse than no answer, and consumers act on
it. See ``test_an_undeterminable_migration_head_reads_as_unknown.py``.

The polarity is inverted between the two fields, which is why the endpoint reads
this one with ``is True``: for the head check ``false`` is the bad news, here
``true`` is. ``null`` is not bad news in either and must not degrade the status.

The verdict also belongs to the application it describes rather than to the
process. It used to live in a module global, so a second ``create_app()`` in one
interpreter - which the test suite does routinely, and a desktop process that
restarts its backend in place could - inherited the first application's verdict
about a database it never opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def _fresh_app() -> FastAPI:
    """An application as it exists before any startup has run.

    The startup event is never entered here. That is the point: this is the
    state a deployment which is not on PostgreSQL keeps for its whole life,
    because the heal sits behind a conditional it does not satisfy. Reaching it
    this way rather than by pointing a real startup at a non-PostgreSQL database
    is what makes the test cheap; that the two arrive at the same state is what
    ``test_the_verdict_is_written_only_where_the_heal_actually_runs`` is for.
    """
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Deliberately not the context-manager form, which would run the lifespan
    # and replace the verdict under test.
    return TestClient(app).get("/api/health").json()


def test_a_heal_that_failed_reports_true_and_degrades() -> None:
    app = _fresh_app()
    app.state.schema_heal_failed = True
    app.state.schema_heal_error = "ProgrammingError: permission denied for table oe_boq_position"

    payload = _health(app)

    assert payload["schema_heal_failed"] is True
    assert payload["status"] == "degraded"


def test_a_heal_that_finished_reports_false() -> None:
    app = _fresh_app()
    app.state.schema_heal_failed = False
    app.state.schema_heal_error = None

    payload = _health(app)

    assert payload["schema_heal_failed"] is False


def test_a_deployment_that_never_ran_the_heal_reports_unknown() -> None:
    """The state that used to be indistinguishable from success.

    Every install whose database is not PostgreSQL is here permanently.
    ``null``, and no degrade: not having run a heal is not a fault, and treating
    it as one would degrade a healthy deployment forever, which is the mirror
    image of the bug.
    """
    healed = _fresh_app()
    healed.state.schema_heal_failed = False

    payload = _health(_fresh_app())

    assert payload["schema_heal_failed"] is None
    # Asserted as a difference rather than against a literal status, because
    # other checks in the same payload have their own opinions here and this
    # test is only about the contribution of this one field.
    assert payload["status"] == _health(healed)["status"], (
        "an unknown heal degrades a deployment that a healed one does not"
    )


def test_the_key_is_present_even_when_the_answer_is_unknown() -> None:
    """Null rather than absent, so a monitor can tell the two apart.

    An omitted key says "this backend predates the field". A null says "this
    backend has the field and cannot answer it". They call for different
    handling and must not look the same on the wire.
    """
    payload = _health(_fresh_app())

    assert "schema_heal_failed" in payload
    assert payload["schema_heal_failed"] is None


def test_unknown_and_healed_are_not_interchangeable_to_a_consumer() -> None:
    """Written the way it is read, not the way it is computed.

    ``None`` and ``False`` are both falsy, so a reader spelled ``if not
    failed:`` cannot tell "the heal succeeded" from "no heal ever ran" and
    reinstates the whole defect while the endpoint keeps returning the right
    values. ``is`` is the reading that survives that.
    """
    healed = _fresh_app()
    healed.state.schema_heal_failed = False

    never_ran = _health(_fresh_app())["schema_heal_failed"]
    healed_answer = _health(healed)["schema_heal_failed"]

    assert never_ran is None
    assert healed_answer is False
    assert never_ran is not healed_answer
    # Both are falsy, which is exactly why the distinction has to be made with
    # ``is`` at every reader.
    assert not never_ran and not healed_answer


def test_a_second_application_does_not_inherit_the_first_ones_verdict() -> None:
    """The verdict describes an application, not the interpreter it runs in."""
    failed = _fresh_app()
    failed.state.schema_heal_failed = True
    failed.state.schema_heal_error = "ProgrammingError: permission denied"

    second = _fresh_app()

    assert _health(failed)["schema_heal_failed"] is True
    assert _health(second)["schema_heal_failed"] is None
    assert getattr(second.state, "schema_heal_error", None) is None


def test_the_verdict_is_written_only_where_the_heal_actually_runs() -> None:
    """Ties the unknown state to the deployment that lives in it.

    The tests above set the state by hand, which proves what the endpoint does
    with each answer but not that a non-PostgreSQL deployment produces the
    unknown one. That comes from where the writes sit: the verdicts are written
    by ``run_schema_heal`` and nowhere else, and the startup calls it inside the
    ``postgresql`` branch and nowhere else, so a run that does not enter that
    branch keeps the ``None`` the application was built with. Read from the
    source because running a real startup to learn it would need the very
    database whose absence is the case under test.
    """
    import inspect

    from app.main import create_app, run_schema_heal

    lines = inspect.getsource(create_app).splitlines()

    guards = [i for i, line in enumerate(lines) if 'if "postgresql" in settings.database_url:' in line]
    assert len(guards) == 1, "the heal's guard moved or is no longer the only one"
    guard_line = guards[0]
    guard_indent = len(lines[guard_line]) - len(lines[guard_line].lstrip())

    writes = [line for line in lines if "app.state.schema_heal_failed =" in line]
    assert len(writes) == 1, "the startup itself must only establish the unknown state"
    assert writes[0].strip().endswith("= None"), "the unknown state must be established when the app is built"

    calls = [(i, line) for i, line in enumerate(lines) if "await run_schema_heal(" in line]
    assert len(calls) == 1, "the heal must be run, and its verdict recorded, from exactly one place"
    index, line = calls[0]
    assert index > guard_line, f"the heal runs before its guard: {line.strip()!r}"
    assert len(line) - len(line.lstrip()) > guard_indent, f"the heal runs outside its guard: {line.strip()!r}"

    heal_source = inspect.getsource(run_schema_heal)
    assert "app.state.schema_heal_failed = False" in heal_source, "nothing records a verdict any more"
