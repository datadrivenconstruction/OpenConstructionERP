# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``/api/health`` distinguishes "I did not find out" from "everything is fine".

Three questions on this payload were answered comfortably when they had not been
answered at all, and they are one defect wearing three hats: an absent answer
published as a reassuring one.

``schema_matches_models`` had two populations sharing its ``null``. The check
that fills it catches everything it can raise and deliberately leaves the field
untouched, so a diagnostic that crashed on this machine published exactly what a
deployment with no PostgreSQL publishes. A reader acts differently on each - the
first is nothing to do, the second is a broken check on the one machine whose
schema it exists to watch - and nothing in the body let them tell.

``true`` on that same field was narrower than its name. It is the verdict of a
nullability query and of nothing else, while the heal has two further ways to
leave the database short of the models. One of them is now measured beside it:
every CHECK and FOREIGN KEY the heal adds goes on ``NOT VALID``, and what the
boot's validation pass cannot get verified afterwards is a constraint whose rows
refuse it - which under a CHECK means rows nothing can write, since PostgreSQL
re-evaluates the constraint on every UPDATE of the row whatever column the
update names.

And the answer to "did this database arrive holding tables it never recorded"
was a local variable. It reached the stamp, which it refuses, and reached
nothing a reader could see - so the one cohort that cannot vouch for its own
schema published ``alembic_head_matches: null``, the same null a desktop bundle
shipping no migration tree publishes, and called itself healthy.

Two of the three leave the status alone and one degrades, and each answer has
its own reason rather than one policy.

A crashed diagnostic says nothing about the deployment. Degrading on it would
report our defect as the operator's and send them to look at a database that is
fine.

``schema_constraints_validated: false`` degrades, and that is only defensible
because the boot now validates. Before the validation pass in
``postgres_migrator.validate_pending_constraints`` this field was ``false`` on
every install the heal had ever added a constraint to and never cleared, so
degrading on it would have lit a permanent cause across that whole population,
which is how the stale alembic stamp stopped being a signal. After the pass,
``false`` means PostgreSQL was asked to verify a constraint and the rows refused
it, and a row that fails a CHECK is not merely unverified: the constraint is
re-evaluated on every UPDATE of that row whatever column the update names, so
nothing can write it and whichever screen edits it answers 500 until somebody
corrects the data. That is actionable, rare, and it clears itself on the next
start. The two changes cannot be separated: remove the pass and this degrade
becomes noise again.

Where the pass runs is part of the same argument. It runs after the boot's data
repairs rather than beside the heal that adds the constraints, because those
repairs rewrite exactly the rows such a constraint refuses: the shipped Canadian
tax configurations carry a sub-national combination and no subdivision code,
the seed having written the one three days before the other column existed, and
``tax_subdivision_backfill`` corrects them on the same boot. A pass placed ahead
of the repairs refuses that constraint, degrades, and clears on the next start,
on an install this boot has already fixed. Measured on a database holding those
rows: refused before the repairs, validated after.

The third is the one where the brief that reached this file overstated the case.
"A database that is known not to be at head" is not what the predicate
establishes. ``database_is_populated_but_unstamped`` evaluates exactly this: an
``oe_*`` table exists and no revision is recorded. That is true of the
pre-15.4.0 part-migrated cohort, and equally true of an install whose schema
``create_all`` built correctly and whose stamp write then failed - a failure
that is caught and logged one screen further down. The tables predate the boot
in both cases and the predicate cannot separate them. Worse, it cannot recover:
once it answers true the stamp is refused, so it answers true on every boot
afterwards. Degrading would hold a current schema at degraded for the life of
the database over one lost write. So the fact is published and the status is
left alone.

What none of this closes: the heal also pre-flights a unique constraint with a
duplicate probe and skips it outright when the table already holds duplicates.
That is the case where wrong data is already in and nothing will stop more of
it, and no runtime check in this process looks for it - ``schema_matches_models``
answers ``true`` straight through it. Closing it needs a declined-unique query
beside ``not_null_divergences`` in ``app.core.postgres_migrator``, which is not
part of this change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _pin_the_frontend_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave ``status`` a function of the schema fields, which is what this file is about.

    ``/api/health`` folds a frontend-build probe into the same ``status`` field
    these tests read, and it degrades whenever no ``index.html`` is on disk. The
    backend CI lane creates ``frontend/dist`` holding nothing but a
    ``.gitkeep``, so the probe answers False for the whole lane and every
    "healthy" case here would fail there on a verdict its subject took no part
    in.
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
    # and write the verdicts under test.
    return TestClient(app).get("/api/health").json()


# ── The check that could not run ─────────────────────────────────────────


def test_a_crashed_schema_check_is_not_published_as_a_deployment_nobody_checks() -> None:
    """The measured defect. Both states published ``schema_matches_models: null``.

    The verdict stays unknown, because it is unknown; what changes is that the
    payload now says which kind of unknown it is.
    """
    app = _fresh_app()
    app.state.schema_matches_models = None
    app.state.schema_match_check_failed = True

    payload = _health(app)

    assert payload["schema_matches_models"] is None, "a check that crashed must not report agreement"
    assert payload["schema_match_check_failed"] is True
    assert payload["status"] == "healthy", "our own diagnostic failing is not the deployment's fault"


def test_a_deployment_that_never_reached_the_check_reports_a_different_unknown() -> None:
    """The other population that answers ``null``, now separable from the one above."""
    payload = _health(_fresh_app())

    assert payload["schema_matches_models"] is None
    assert payload["schema_match_check_failed"] is None
    # Named so a red run says which other probe moved instead of pointing here.
    assert payload["frontend_dist_present"] is True
    assert payload["database"] == "ok"
    assert payload["status"] == "healthy"


def test_a_check_that_reached_a_verdict_reports_false() -> None:
    """``false`` is what stops ``null`` from ever being readable as "it ran"."""
    app = _fresh_app()
    app.state.schema_matches_models = True
    app.state.schema_match_check_failed = False

    payload = _health(app)

    assert payload["schema_match_check_failed"] is False
    assert payload["schema_matches_models"] is True
    assert payload["status"] == "healthy"


# ── The constraints nothing ever validated ───────────────────────────────


def test_an_unvalidated_constraint_is_visible_beside_a_true_nullability_verdict() -> None:
    """The two halves disagree, and until this key existed only the reassuring one showed.

    ``schema_matches_models`` answers the nullability question and answers it
    correctly here. The database still holds rows the boot asked PostgreSQL to
    verify against a CHECK or FOREIGN KEY the models declare and could not.
    """
    app = _fresh_app()
    app.state.schema_matches_models = True
    app.state.schema_match_check_failed = False
    app.state.schema_constraints_validated = False

    payload = _health(app)

    assert payload["schema_matches_models"] is True
    assert payload["schema_constraints_validated"] is False
    assert payload["status"] == "degraded", (
        "a constraint that survived the validation pass means rows no UPDATE can touch, which is not a healthy install"
    )


def test_a_fully_validated_schema_says_so() -> None:
    app = _fresh_app()
    app.state.schema_constraints_validated = True

    payload = _health(app)

    assert payload["schema_constraints_validated"] is True
    assert payload["status"] == "healthy"


def test_the_constraint_question_has_an_unknown_of_its_own() -> None:
    """``null`` covers a non-PostgreSQL deployment and a query that could not run.

    It must not degrade. ``false`` is a measured refusal and ``null`` is the
    absence of a measurement, and the whole point of this file is that the two
    are not the same claim.
    """
    payload = _health(_fresh_app())

    assert payload["schema_constraints_validated"] is None
    assert payload["status"] == "healthy"


# ── The database that arrived holding tables it never recorded ───────────


def test_a_database_that_arrived_populated_and_unstamped_says_so() -> None:
    """The defect: this reached the stamp and nothing else, so nothing published it.

    ``alembic_head_matches`` stays ``null`` and is right to - an absent revision
    is not a disagreement between revisions, and reporting it as one is the bug
    ``alembic_head_state`` exists to prevent. What was missing is the sentence
    beside it saying which ``null`` this is.
    """
    app = _fresh_app()
    app.state.arrived_populated_unstamped = True

    payload = _health(app)

    assert payload["arrived_populated_unstamped"] is True
    assert payload["status"] == "healthy", (
        "the predicate cannot separate a part-migrated database from one that lost a stamp write, "
        "and it never clears once true"
    )


def test_an_ordinary_install_reports_false() -> None:
    app = _fresh_app()
    app.state.arrived_populated_unstamped = False

    assert _health(app)["arrived_populated_unstamped"] is False


def test_a_question_that_could_not_be_put_is_not_answered_false() -> None:
    """``false`` here would claim the database was checked and found ordinary.

    It is the value the boot path's own local carries on failure, deliberately,
    because the stamp has to keep behaving as it did. The published field must
    not inherit it: a question that could not be put has no answer.
    """
    assert _health(_fresh_app())["arrived_populated_unstamped"] is None


# ── Shared contract ──────────────────────────────────────────────────────


def test_the_three_keys_are_always_present() -> None:
    """A reader has to tell "I cannot say" from "this backend has no such field".

    Both are falsy in Python and in most alerting DSLs, which is why every field
    on this payload is emitted unconditionally.
    """
    payload = _health(_fresh_app())

    for key in ("schema_match_check_failed", "schema_constraints_validated", "arrived_populated_unstamped"):
        assert key in payload


def test_none_of_the_three_can_be_read_with_a_bare_truth_test() -> None:
    """Polarity, held against the neighbours a monitor rule is written beside.

    ``schema_match_check_failed`` reads ``true`` for bad news, like the three
    ``_failed`` fields it sits with. The other two read ``true`` for good news,
    like ``schema_matches_models`` and ``alembic_head_matches``. A field whose
    name says "failed" and whose ``true`` meant good news is how a rule ends up
    written the wrong way round, so the naming carries the polarity and this
    asserts it does.
    """
    app = _fresh_app()
    app.state.schema_match_check_failed = True
    app.state.schema_constraints_validated = False
    app.state.arrived_populated_unstamped = True

    payload = _health(app)

    assert payload["schema_match_check_failed"] is True
    assert payload["schema_constraints_validated"] is False
    assert payload["arrived_populated_unstamped"] is True


def test_no_schema_detail_reaches_an_anonymous_caller() -> None:
    """The endpoint is unauthenticated, so it carries verdicts and not names.

    Same rule that keeps ``schema_heal_error`` and the divergent column names
    off this payload: a table name maps the deployment. All three new fields are
    booleans for that reason - the counts and the names are in the boot log,
    where the operator of the machine is.
    """
    app = _fresh_app()
    app.state.schema_match_check_failed = True
    app.state.schema_constraints_validated = False
    app.state.arrived_populated_unstamped = True
    app.state.schema_divergent_columns = ("oe_project.secret_column",)

    payload = _health(app)

    assert "oe_project" not in str(payload)
    assert "pg_constraint" not in str(payload)
