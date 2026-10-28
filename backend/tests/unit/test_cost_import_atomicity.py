"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A cost-file import that dies half-way must leave nothing behind, and say so.

The endpoint stages its rows through ``bulk_import``, which adds and flushes but
never commits; the request-scoped session commits once when the endpoint returns
and rolls back when it raises. So the rows were already all-or-nothing. What was
missing was any way for the caller to know which of the two had happened: a
failure after several slices had flushed surfaced as an opaque 500 with no
statement about the rows, and the response of a run that finished said nothing
about durability either, so "did any of it land?" could only be answered by
going and looking.

Two things were genuinely wrong rather than merely unstated.

``create_catalog`` commits, and it commits on the SAME session the import then
writes through - both service dependencies resolve one ``SessionDep`` per
request. A catalog created inline for an upload therefore outlived the rollback
that discarded its rows, and because the name-availability gate refuses a
duplicate name with a 409, the obvious next move - upload the same file again -
was refused. An import that promises all-or-nothing has to take that catalog
with it, and only that one: a catalog the caller addressed by ``catalog_id``
existed before the upload and is not the import's to delete.

The failure path is what these tests are for. A suite that only covers the
successful import says nothing at all about durability, because on the happy
path atomic and resumable are indistinguishable.

No database is involved: the service is replaced by a recorder that fails on a
chosen hand-over, and the session by one that counts its rollbacks.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.costs import router

HANDOVER = 7
ITEMS = 25
FAIL_ON_BATCH = 2
CATALOG_NAME = "Imported base"


def _csv(count: int) -> bytes:
    """A minimal cost catalogue: one priced line per row."""
    lines = ["code,description,unit,rate,currency"]
    lines += [f"C{index:04d},Work item {index},m3,{100 + index},EUR" for index in range(count)]
    return ("\n".join(lines) + "\n").encode("utf-8")


class _Upload:
    """The two members of ``UploadFile`` this endpoint touches."""

    def __init__(self, content: bytes) -> None:
        self.filename = "catalogue.csv"
        self._content = content

    async def read(self) -> bytes:
        return self._content


class _Session:
    """Counts the rollbacks the endpoint performs on its own behalf.

    ``fail`` makes the rollback itself raise, which is the case where the
    cleanup is in no position to finish and the caller still has to be told
    what happened.
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.rollbacks = 0
        self._fail = fail

    async def rollback(self) -> None:
        self.rollbacks += 1
        if self._fail:
            raise RuntimeError("the connection was already gone")


class _Catalog:
    """The three members of a catalog the import reads."""

    def __init__(self, name: str, currency: str) -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.currency = currency


class _CatalogService:
    """Stands in for ``CostCatalogService`` on the two paths the import takes."""

    def __init__(self, existing: _Catalog | None = None, *, fail_delete: bool = False) -> None:
        self.created: list[_Catalog] = []
        self.deleted: list[uuid.UUID] = []
        self._existing = existing
        self._fail_delete = fail_delete

    async def create_catalog(self, data: Any, *, created_by: Any = None, source: str = "manual") -> _Catalog:
        catalog = _Catalog(data.name, data.currency)
        self.created.append(catalog)
        return catalog

    async def get_owned_catalog(self, catalog_id: uuid.UUID, *, owner_id: Any = None, is_admin: bool = False) -> Any:
        return self._existing

    async def delete_catalog(self, catalog_id: uuid.UUID, *, mode: str = "keep_items") -> int:
        self.deleted.append(catalog_id)
        if self._fail_delete:
            raise RuntimeError("the catalog row was already gone")
        return 0


class _FailingService:
    """Stands in for ``CostItemService``, failing on a chosen hand-over.

    ``fail_on`` counts hand-overs, not rows: the point is a failure that lands
    AFTER at least one slice has already been flushed, which is the only shape
    in which "how much of it survived?" is a real question.
    """

    def __init__(self, *, fail_on: int | None = None, fail_rollback: bool = False) -> None:
        self.session = _Session(fail=fail_rollback)
        self.batch_sizes: list[int] = []
        self.created_codes: list[str] = []
        self._fail_on = fail_on
        self._seen: set[str] = set()

    async def bulk_import(self, items: list[Any]) -> list[Any]:
        self.batch_sizes.append(len(items))
        if self._fail_on is not None and len(self.batch_sizes) == self._fail_on:
            raise RuntimeError("deadlock detected while flushing cost items")
        created = []
        for item in items:
            if item.code in self._seen:
                continue
            self._seen.add(item.code)
            self.created_codes.append(item.code)
            created.append(item)
        return created


async def _import(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_on: int | None = None,
    catalog_name: str | None = None,
    catalog_id: str | None = None,
    existing: _Catalog | None = None,
    rows: int = ITEMS,
    fail_delete: bool = False,
    fail_rollback: bool = False,
) -> tuple[_FailingService, _CatalogService, Any]:
    """Run an import and return the recorders plus the response or the raised error."""
    monkeypatch.setattr(router, "_IMPORT_HANDOVER_ROWS", HANDOVER)
    service = _FailingService(fail_on=fail_on, fail_rollback=fail_rollback)
    catalog_service = _CatalogService(existing=existing, fail_delete=fail_delete)
    try:
        response: Any = await router.import_cost_file(
            user={"sub": None, "role": "user"},
            file=_Upload(_csv(rows)),  # type: ignore[arg-type]
            column_map=None,
            catalog_id=catalog_id,
            catalog_name=catalog_name,
            catalog_currency="EUR" if catalog_name else None,
            service=service,  # type: ignore[arg-type]
            catalog_service=catalog_service,  # type: ignore[arg-type]
        )
    except HTTPException as exc:
        response = exc
    return service, catalog_service, response


async def test_a_finished_import_states_the_durability_it_had(monkeypatch: pytest.MonkeyPatch) -> None:
    # The happy path cannot distinguish atomic from resumable by itself, which
    # is exactly why it has to name which one it is.
    service, _, response = await _import(monkeypatch)

    assert not isinstance(response, HTTPException)
    assert response["durability"] == "atomic"
    assert response["imported"] == ITEMS
    assert service.session.rollbacks == 0


async def test_a_failure_halfway_is_reported_as_a_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test the success path cannot give. Before this the RuntimeError went
    # up as an unshaped 500 and the caller was left to work out for itself
    # whether the first slices had survived.
    service, _, error = await _import(monkeypatch, fail_on=FAIL_ON_BATCH)

    assert isinstance(error, HTTPException), "a failing hand-over did not produce a stated outcome"
    assert error.status_code == 500
    detail = error.detail
    assert isinstance(detail, dict), f"the failure carried no structured outcome, only {detail!r}"
    assert detail["durability"] == "atomic"
    assert detail["imported"] == 0
    assert detail["rows_discarded"] == HANDOVER * FAIL_ON_BATCH
    assert detail["total_rows"] == ITEMS
    assert service.session.rollbacks == 1


async def test_the_failure_lands_after_a_slice_has_already_been_staged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The assertion above is only about durability if rows really had been
    # written before the failure. A run that died on its first hand-over would
    # satisfy it while testing nothing.
    service, _, _ = await _import(monkeypatch, fail_on=FAIL_ON_BATCH)

    assert len(service.batch_sizes) == FAIL_ON_BATCH
    assert service.created_codes, "nothing was staged before the failure, so nothing was at risk"


async def test_the_catalog_a_failed_import_created_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    # ``create_catalog`` commits on the shared session, so this row survives the
    # rollback that removes its items. Left behind, it takes the name with it
    # and the 409 from the name gate refuses the retry.
    _, catalog_service, error = await _import(monkeypatch, fail_on=FAIL_ON_BATCH, catalog_name=CATALOG_NAME)

    assert isinstance(error, HTTPException)
    assert len(catalog_service.created) == 1
    assert catalog_service.deleted == [catalog_service.created[0].id]


async def test_a_catalog_the_caller_already_owned_survives_a_failed_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of the same rule, and the one a blunt cleanup gets wrong.
    # A catalog addressed by id existed before this upload and holds rows this
    # upload never touched; removing it would turn a failed import into data
    # loss.
    existing = _Catalog("Someone else's base", "EUR")
    _, catalog_service, error = await _import(
        monkeypatch,
        fail_on=FAIL_ON_BATCH,
        catalog_id=str(existing.id),
        existing=existing,
    )

    assert isinstance(error, HTTPException)
    assert catalog_service.created == []
    assert catalog_service.deleted == []


async def test_a_finished_import_removes_no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _, catalog_service, response = await _import(monkeypatch, catalog_name=CATALOG_NAME)

    assert not isinstance(response, HTTPException)
    assert len(catalog_service.created) == 1
    assert catalog_service.deleted == []
    assert response["catalog"] == CATALOG_NAME


async def test_a_cleanup_that_fails_does_not_replace_the_error_it_was_cleaning_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The cleanup runs inside the handler that builds the 500. An exception
    # escaping it would propagate instead of that 500, and the caller would get
    # something opaque about a catalog rather than the statement that the import
    # rolled back - the endpoint would be least informative in exactly the case
    # the caller most needs to read. The removal is attempted and its failure
    # swallowed, so the outcome below is unchanged from the ordinary failure.
    _, catalog_service, error = await _import(
        monkeypatch,
        fail_on=FAIL_ON_BATCH,
        catalog_name=CATALOG_NAME,
        fail_delete=True,
    )

    assert isinstance(error, HTTPException), "a failing cleanup replaced the outcome it was cleaning up after"
    assert error.status_code == 500
    assert isinstance(error.detail, dict)
    assert error.detail["durability"] == "atomic"
    assert error.detail["imported"] == 0
    assert catalog_service.deleted == [catalog_service.created[0].id], "the removal was never attempted"


async def test_a_rollback_that_fails_still_reports_the_import_as_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same rule one step earlier. A session too broken to roll back is
    # still a session whose transaction never commits - the request-scoped
    # dependency discards it either way - so the durability the caller is told
    # about is unchanged, and the raise must not escape the handler.
    service, catalog_service, error = await _import(
        monkeypatch,
        fail_on=FAIL_ON_BATCH,
        catalog_name=CATALOG_NAME,
        fail_rollback=True,
    )

    assert isinstance(error, HTTPException), "a failing rollback replaced the outcome it was reporting"
    assert error.status_code == 500
    assert isinstance(error.detail, dict)
    assert error.detail["durability"] == "atomic"
    assert service.session.rollbacks == 1
    # The rollback failed, so the catalog cleanup after it cannot be trusted to
    # act on a usable session and is not attempted.
    assert catalog_service.deleted == []


async def test_a_rejected_file_is_not_reported_as_a_rollback(monkeypatch: pytest.MonkeyPatch) -> None:
    # The gates that fire before any row is staged keep their own answers. A
    # file with no data rows is a 400 about the file, not a 500 about
    # durability, and there is nothing to discard.
    service, catalog_service, error = await _import(monkeypatch, rows=0)

    assert isinstance(error, HTTPException)
    assert error.status_code == 400
    assert isinstance(error.detail, str)
    assert service.session.rollbacks == 0
    assert catalog_service.deleted == []
