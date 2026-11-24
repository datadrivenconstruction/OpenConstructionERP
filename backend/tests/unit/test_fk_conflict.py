"""A foreign-key violation becomes a 409 body naming the blocking records."""

from sqlalchemy.exc import IntegrityError

from app.core.fk_conflict import foreign_key_conflict


def _integrity(message: str) -> IntegrityError:
    return IntegrityError("DELETE FROM oe_boq_boq", {}, Exception(message))


def test_postgres_violation_names_the_referencing_table() -> None:
    exc = _integrity(
        'update or delete on table "oe_boq_boq" violates foreign key constraint '
        '"fk_tender_boq" on table "oe_tendering_package"'
    )
    body = foreign_key_conflict(exc)
    assert body is not None
    assert body["code"] == "fk_conflict"
    assert body["blocked_by"] == "tendering package"
    assert "tendering package" in body["detail"]


def test_sqlite_violation_is_a_conflict_without_table() -> None:
    body = foreign_key_conflict(_integrity("FOREIGN KEY constraint failed"))
    assert body == {
        "detail": "This record is still referenced by other records; remove or relink them first.",
        "code": "fk_conflict",
        "blocked_by": None,
    }


def test_wrapped_violation_is_found_through_the_cause_chain() -> None:
    try:
        try:
            raise _integrity("FOREIGN KEY constraint failed")
        except IntegrityError as inner:
            raise RuntimeError("service failed") from inner
    except RuntimeError as outer:
        assert foreign_key_conflict(outer) is not None


def test_other_integrity_errors_stay_unhandled() -> None:
    assert foreign_key_conflict(_integrity('duplicate key value violates unique constraint "uq_x"')) is None
    assert foreign_key_conflict(ValueError("x")) is None
