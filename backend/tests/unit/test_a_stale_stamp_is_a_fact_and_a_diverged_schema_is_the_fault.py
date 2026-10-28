"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Which of the two schema facts ``/api/health`` is entitled to degrade on.

The product never runs ``alembic upgrade``. The schema moves through
``create_all`` and the boot heal, so the recorded revision falls behind on a
normal, correct upgrade the moment a release adds any revision at all. While
``alembic_head_matches`` degraded the status, every upgraded install reported
``degraded`` for the rest of its life over a stamp, and an aggregate with a
permanently active cause is not a signal any more. That is not a prediction: it
was observed hiding a total frontend outage, because ``status`` was already
pinned to degraded and could not move when ``frontend_dist_present`` went false.

So the stamp is published as a fact and degrades nothing, and the question that
does degrade is asked directly instead: do the models and the database still
agree. The heal can finish without raising and still leave them disagreeing,
because it enforces a NOT NULL only when a default exists to backfill the rows
already in the table.

The stamp half is written differentially - the same application answered twice,
once with the head check saying true and once false - because the status of a
test application depends on things this test does not control, such as whether
a frontend build is on disk. Asserting ``status != "degraded"`` outright would
pass or fail for reasons that have nothing to do with the change. Asserting
that flipping the field does not move the status is the actual claim.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def _fresh_app() -> FastAPI:
    from app.main import create_app

    return create_app()


def _health(app: FastAPI) -> dict:
    from fastapi.testclient import TestClient

    # Not the context-manager form: that would run the lifespan and overwrite
    # the state the test just set.
    return TestClient(app).get("/api/health").json()


def _health_with_head_state(app: FastAPI, verdict: bool | None, monkeypatch) -> dict:
    """The payload as it reads when the head comparison returns ``verdict``.

    Patched at :func:`app.main.alembic_head_state` rather than by moving a real
    stamp, because the claim under test is about what the endpoint does with
    the answer, not about how the answer is reached.
    """
    import app.main as main_module

    monkeypatch.setattr(main_module, "alembic_head_state", lambda expected, actual: verdict)
    return _health(app)


def test_a_stamp_that_is_behind_is_published_and_does_not_degrade(monkeypatch) -> None:
    """The whole point: the value still says false, the status does not move.

    Both halves matter. Publishing it is what keeps the release lane and any
    external monitor able to see the stamp; not degrading on it is what gives
    ``status`` its meaning back.
    """
    app = _fresh_app()

    behind = _health_with_head_state(app, False, monkeypatch)
    at_head = _health_with_head_state(app, True, monkeypatch)

    assert behind["alembic_head_matches"] is False, "the fact has to survive; only its authority is removed"
    assert at_head["alembic_head_matches"] is True
    assert behind["status"] == at_head["status"], (
        "a stamp that is behind moved the status, which is the permanently-lit signal this removes"
    )


def test_a_schema_that_diverged_from_the_models_degrades() -> None:
    app = _fresh_app()
    app.state.schema_matches_models = False
    app.state.schema_divergent_columns = ("oe_costs_item.currency_code",)

    payload = _health(app)

    assert payload["schema_matches_models"] is False
    assert payload["status"] == "degraded"


def test_a_schema_that_agrees_reports_true() -> None:
    app = _fresh_app()
    app.state.schema_matches_models = True

    payload = _health(app)

    assert payload["schema_matches_models"] is True


def test_a_check_that_never_ran_reports_null_and_does_not_degrade() -> None:
    """The third state, and the reason it is three and not two.

    A deployment whose database is not PostgreSQL never reaches the check. Its
    honest answer is "nobody asked", and answering ``true`` there would be the
    same class of lie the two fields beside it were rewritten to stop telling.
    Written differentially for the same reason as the stamp test above.
    """
    app = _fresh_app()
    app.state.schema_matches_models = None

    unknown = _health(app)

    app.state.schema_matches_models = True
    agreed = _health(app)

    assert unknown["schema_matches_models"] is None
    assert unknown["status"] == agreed["status"], "null is not bad news and must not degrade"


def test_the_divergent_column_names_are_not_published() -> None:
    """``/api/health`` is unauthenticated, so the names stay in the log.

    Same rule the heal's failing statement and the failed repair ids already
    follow. What the endpoint owes an anonymous caller is that something is
    wrong, not a map of the schema.
    """
    app = _fresh_app()
    app.state.schema_matches_models = False
    app.state.schema_divergent_columns = ("oe_secret_table.secret_column",)

    payload = _health(app)

    assert "oe_secret_table" not in str(payload)
    assert "schema_divergent_columns" not in payload


def _main_tree() -> ast.Module:
    main = Path(__file__).resolve().parents[2] / "app" / "main.py"
    return ast.parse(main.read_text(encoding="utf-8"), filename=str(main))


def _postgresql_branch_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Line spans of every ``if ... "postgresql" ... database_url`` block."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.unparse(node.test)
        if "postgresql" in test_src and "database_url" in test_src:
            spans.append((node.lineno, node.end_lineno or node.lineno))
    return spans


def test_the_boot_path_actually_asks_the_question() -> None:
    """The endpoint reports state; something has to put the state there.

    Every test above sets ``app.state`` by hand, so all of them would stay green
    if the boot wiring were deleted tomorrow and the field answered ``null`` on
    every install forever. That is the shape of a health field nobody checks.
    Read statically off ``app/main.py``, which is the same way the data-repair
    runner's wiring is pinned, and for the same reason: whether the call sits on
    the boot path is a property of the source.
    """
    tree = _main_tree()
    spans = _postgresql_branch_ranges(tree)
    assert spans, "no PostgreSQL branch found in main.py at all; this test is measuring nothing"

    called = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "not_null_divergences"
    ]
    assert called, "nothing on the boot path asks whether the schema matches the models"
    assert any(lo <= line <= hi for line in called for lo, hi in spans), (
        "the divergence check is called outside the PostgreSQL branch, where it cannot run"
    )

    assigned = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "schema_matches_models"
    ]
    assert any(lo <= line <= hi for line in assigned for lo, hi in spans), (
        "the verdict is never written inside the branch that computes it, so it stays null"
    )
