# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Where a payment certificate gets its taxes from, without importing who computes them.

The tax lines of a certificate (VAT, VAT withholding, income withholding,
stamp duty) are computed and stored by another module. Contracts must not
import it: modules are plugins, and an install without the tax module is a
normal install. So, as in :mod:`app.modules.contracts.claim_context`, the
dependency points the other way. The module that owns the taxes registers one
provider here and the certificate asks this registry.

Three outcomes, kept apart on purpose:

* nothing registered, or the provider answers ``None``: there are no taxes to
  show. The caller gets ``None`` and every tax line of the certificate is held
  with the reason ``module_absent``;
* the provider answers: its result is passed through untouched;
* the provider raises: that is neither of the above, and it must not look like
  the first. The caller gets a result whose five figures are all held with the
  reason ``provider_failed``, and the failure is logged with its traceback.

This last case is where the registry deliberately differs from
``claim_context``, which lets a failing provider's exception through. A rule
context is built while a claim is being submitted, where stopping is right. A
certificate is opened to be read, and a page that refuses to open tells the
quantity surveyor less than a draft that says which lines could not be
computed and why.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Figure, PaymentTaxResult

logger = logging.getLogger(__name__)

#: ``provider(session, source_kind, source_id)`` returns the taxes of one
#: certificate source (``progress_claim`` or ``sub_payment_application``), or
#: ``None`` when it has none for that source. It may be sync or async.
CertificateTaxProvider = Callable[
    [AsyncSession, str, Any],
    PaymentTaxResult | None | Awaitable[PaymentTaxResult | None],
]

_FIGURE_KINDS: tuple[str, ...] = ("vat_computed", "vat_withheld", "vat_payable", "income_withheld", "stamp_duty")

_provider: CertificateTaxProvider | None = None


def register_certificate_tax_provider(provider: CertificateTaxProvider) -> None:
    """Make ``provider`` the source of every certificate's taxes.

    There is one provider, because there is one tax calculation. Registering
    again replaces it, so a module that registers on every load stays
    registered once.

    Args:
        provider: Called as ``provider(session, source_kind, source_id)``; its
            return value is awaited when it is awaitable.
    """
    global _provider  # noqa: PLW0603 - the registry is this module's one piece of state
    _provider = provider


def unregister_certificate_tax_provider() -> None:
    """Remove the provider; with none registered this does nothing."""
    global _provider  # noqa: PLW0603 - see register_certificate_tax_provider
    _provider = None


def held_result(reason_key: str, **reason_params: str) -> PaymentTaxResult:
    """A tax result whose five figures are all held for one reason."""

    def figure(kind: str) -> Figure:
        return Figure(
            kind=kind,
            status="held",
            amount=None,
            base=None,
            rate_pct=None,
            numerator=None,
            denominator=None,
            code="",
            legal_reference="",
            effective_from=None,
            review_status="",
            overridden=False,
            reason_key=reason_key,
            reason_params=MappingProxyType(dict(reason_params)),
        )

    return PaymentTaxResult(*(figure(kind) for kind in _FIGURE_KINDS))


async def collect_certificate_taxes(session: AsyncSession, source_kind: str, source_id: Any) -> PaymentTaxResult | None:
    """The taxes of one certificate source, from whoever registered to compute them.

    Returns:
        ``None`` when no provider is registered or the provider has nothing
        for this source; the provider's result otherwise; and when the
        provider raises, or answers with something that is not a tax result,
        a result with every figure held for ``provider_failed``. It never
        raises on the provider's behalf.
    """
    provider = _provider
    if provider is None:
        return None
    try:
        result = provider(session, source_kind, source_id)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:  # noqa: BLE001 - a failing provider is reported on the document, not raised through it
        logger.exception("certificate tax provider failed for %s %s", source_kind, source_id)
        return held_result("provider_failed", error=type(exc).__name__)
    if result is None:
        return None
    if not isinstance(result, PaymentTaxResult):
        logger.error(
            "certificate tax provider returned %s for %s %s, expected a PaymentTaxResult",
            type(result).__name__,
            source_kind,
            source_id,
        )
        return held_result("provider_failed", error=type(result).__name__)
    return result


__all__ = [
    "CertificateTaxProvider",
    "collect_certificate_taxes",
    "held_result",
    "register_certificate_tax_provider",
    "unregister_certificate_tax_provider",
]
