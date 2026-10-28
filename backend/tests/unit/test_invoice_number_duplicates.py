# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# invoice_number had no protection of any kind. There is no unique constraint on
# the column, and a caller-supplied number was written straight through, so
# posting the same number twice produced two invoices carrying it. That number
# is what reconciliation, payment matching and every accounting export key on,
# so the result is not a display quirk, it is two documents nobody can tell
# apart.
#
# The generator's docstring also claimed that using MAX rather than COUNT avoids
# race conditions. It does not. MAX is what makes numbering survive a deletion;
# it does nothing about concurrency, because nothing between the read and the
# insert holds a lock. That claim is corrected rather than relied upon.

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.finance.service import FinanceService


class _StubInvoiceRepo:
    def __init__(self, taken: bool) -> None:
        self._taken = taken
        self.generated = False
        self.checked: list[str] = []

    async def invoice_number_taken(
        self,
        _project_id: uuid.UUID,
        _direction: str,
        invoice_number: str,
    ) -> bool:
        self.checked.append(invoice_number)
        return self._taken

    async def next_invoice_number(self, _project_id: uuid.UUID, _direction: str) -> str:
        self.generated = True
        return "INV-R-007"


class _Payload:
    """Only the fields create_invoice touches before the duplicate check."""

    def __init__(self, invoice_number: str | None) -> None:
        self.project_id = uuid.uuid4()
        self.invoice_direction = "receivable"
        self.invoice_number = invoice_number
        self.status = "draft"


def _service(taken: bool) -> tuple[FinanceService, _StubInvoiceRepo]:
    service = FinanceService.__new__(FinanceService)
    repo = _StubInvoiceRepo(taken)
    service.invoices = repo
    return service, repo


async def _run(service: FinanceService, payload: Any) -> None:
    """Drive create_invoice far enough to pass or fail the duplicate check.

    Everything after that point needs a live session, so the call is expected to
    blow up on its own once the check has been cleared. The test only cares
    whether an HTTPException with 409 was raised before that.
    """
    await service.create_invoice(payload)


@pytest.mark.asyncio
async def test_a_reused_invoice_number_is_refused() -> None:
    service, repo = _service(taken=True)
    payload = _Payload("INV-R-001")

    with pytest.raises(HTTPException) as raised:
        await _run(service, payload)

    assert raised.value.status_code == 409
    assert "INV-R-001" in str(raised.value.detail), "the message should name the number"
    assert repo.checked == ["INV-R-001"]
    assert not repo.generated, "a supplied number must not be silently replaced"


@pytest.mark.asyncio
async def test_a_free_invoice_number_passes_the_check() -> None:
    """The guard must not reject numbers that are actually available."""
    service, repo = _service(taken=False)

    with pytest.raises(Exception) as raised:  # noqa: B017 - fails later, past the check
        await _run(service, _Payload("INV-R-002"))

    assert not isinstance(raised.value, HTTPException) or raised.value.status_code != 409
    assert repo.checked == ["INV-R-002"]


@pytest.mark.asyncio
async def test_an_omitted_number_is_generated_and_not_checked() -> None:
    """Generation is the normal path and must not pay for the duplicate lookup."""
    service, repo = _service(taken=False)

    with pytest.raises(Exception):  # noqa: B017 - fails later, past the check
        await _run(service, _Payload(None))

    assert repo.generated, "an omitted number must be generated"
    assert repo.checked == [], "nothing to check when we produced the number ourselves"
