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

A result alone does not say enough for a certificate. It cannot say whether a
person has confirmed the figures, and it cannot say what they were computed
on, which is what tells a certificate that its own amount has moved since. So
the provider may answer with a :class:`CertificateTaxes`, the result together
with the stored header it came from, and :func:`collect_certificate_tax_state`
hands that on. :func:`collect_certificate_taxes` keeps answering with the
result alone.

The second half is the way in. A certificate knows its own base amounts, so
it is the certificate that asks for its taxes to be computed and stored, on
exactly those amounts, through :func:`save_certificate_taxes`. The module that
owns the taxes registers the writer; without one the request is refused with
:class:`CertificateTaxesUnavailableError` rather than dropped.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.payment_taxes import Choice, Figure, PaymentTaxResult

logger = logging.getLogger(__name__)

#: The taxes a person decides on, as the keys of ``choices`` below.
TAX_CHOICE_KINDS: tuple[str, ...] = ("vat_withholding", "income_withholding", "stamp_duty")


@dataclass(frozen=True)
class CertificateTaxes:
    """The stored taxes of one certificate source, with what they were computed from.

    Attributes:
        result: The five figures.
        status: ``draft`` or ``confirmed``; empty when the provider answered
            with a bare result and nobody can say.
        net_amount: The amount the VAT and the income withholding were
            computed on.
        stamp_duty_base: The amount the stamp duty was computed on, when it
            was stated apart from the net amount.
        stamp_duty_base_same_as_net: A person's (or the certificate's)
            statement that the stamp duty base is the net amount.
        vat_rate_pct: The VAT rate the figures were computed with.
        document_date: The date the rate rows were looked up for.
        currency: Currency of every amount here.
        choices: What was decided per tax, keyed by :data:`TAX_CHOICE_KINDS`.
        buyer_is_designated: Whether the buyer is one the law designates to
            withhold; ``None`` when nobody has said.
        work_value_incl_vat: Value of the whole work, VAT included.
        work_value_note: The person's description of what that value is.
    """

    result: PaymentTaxResult
    status: str = ""
    net_amount: Decimal | None = None
    stamp_duty_base: Decimal | None = None
    stamp_duty_base_same_as_net: bool = False
    vat_rate_pct: Decimal | None = None
    document_date: date | None = None
    currency: str = ""
    choices: Mapping[str, Choice] = field(default_factory=dict)
    buyer_is_designated: bool | None = None
    work_value_incl_vat: Decimal | None = None
    work_value_note: str = ""


@dataclass(frozen=True)
class CertificateTaxRequest:
    """What a certificate asks the tax module to compute and store.

    The amounts are the certificate's own: ``net_amount`` is the amount of
    this certificate before VAT and ``stamp_duty_base`` the amount its stamp
    duty line is charged on, ``None`` when that base is not known yet (the
    line it depends on is held). Nothing here is typed by a person except the
    choices and the two facts about the buyer.

    ``choices`` left ``None`` keeps what is stored, which is how a certificate
    asks for a recalculation on its new amounts. The same holds for
    ``buyer_is_designated``, ``work_value_incl_vat`` and ``work_value_note``
    when ``keep_buyer_facts`` is set.
    """

    project_id: uuid.UUID
    source_kind: str
    source_id: uuid.UUID
    source_reference: str
    direction: str
    country_code: str
    currency: str
    document_date: date
    net_amount: Decimal
    stamp_duty_base: Decimal | None
    vat_rate_pct: Decimal | None
    user_id: str
    choices: Mapping[str, Choice] | None = None
    buyer_is_designated: bool | None = None
    work_value_incl_vat: Decimal | None = None
    work_value_note: str = ""
    keep_buyer_facts: bool = False


class CertificateTaxesUnavailableError(RuntimeError):
    """No module that stores certificate taxes is installed."""


class CertificateTaxRefusalError(Exception):
    """The tax module refused to store what the certificate asked for.

    Carries what the route needs to answer with: a machine ``code``, the
    sentence, the HTTP status the tax module would have used itself, and its
    details.
    """

    def __init__(self, code: str, message: str, *, http_status: int = 409, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = dict(details or {})


#: ``provider(session, source_kind, source_id)`` returns the taxes of one
#: certificate source (``progress_claim`` or ``sub_payment_application``), or
#: ``None`` when it has none for that source. It may be sync or async, and it
#: may answer with the result alone or with a :class:`CertificateTaxes`.
CertificateTaxProvider = Callable[
    [AsyncSession, str, Any],
    PaymentTaxResult | CertificateTaxes | None | Awaitable[PaymentTaxResult | CertificateTaxes | None],
]

#: ``writer(session, request)`` computes and stores the taxes of one
#: certificate source and returns them as stored.
CertificateTaxWriter = Callable[[AsyncSession, CertificateTaxRequest], Awaitable[CertificateTaxes]]

_FIGURE_KINDS: tuple[str, ...] = ("vat_computed", "vat_withheld", "vat_payable", "income_withheld", "stamp_duty")

_provider: CertificateTaxProvider | None = None
_writer: CertificateTaxWriter | None = None


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


def provider_registered() -> bool:
    """Whether a module that stores certificate taxes is installed.

    The difference a certificate needs to print: with no provider the tax
    lines are held because the module is absent, with one they are held
    because nothing has been stored for this certificate yet.
    """
    return _provider is not None


def register_certificate_tax_writer(writer: CertificateTaxWriter) -> None:
    """Make ``writer`` the way a certificate has its taxes computed and stored.

    Registering again replaces it, like the provider.
    """
    global _writer  # noqa: PLW0603 - see register_certificate_tax_provider
    _writer = writer


def unregister_certificate_tax_writer() -> None:
    """Remove the writer; with none registered this does nothing."""
    global _writer  # noqa: PLW0603 - see register_certificate_tax_provider
    _writer = None


async def save_certificate_taxes(session: AsyncSession, request: CertificateTaxRequest) -> CertificateTaxes:
    """Have the taxes of one certificate computed on its own amounts and stored.

    Raises:
        CertificateTaxesUnavailableError: No writer is registered.
        CertificateTaxRefusalError: The tax module refused the request.
    """
    writer = _writer
    if writer is None:
        raise CertificateTaxesUnavailableError("no certificate tax writer is registered")
    return await writer(session, request)


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


async def collect_certificate_tax_state(
    session: AsyncSession, source_kind: str, source_id: Any
) -> CertificateTaxes | None:
    """The taxes of one certificate source with the header they were stored under.

    Returns:
        ``None`` when no provider is registered or the provider has nothing
        for this source. Otherwise a :class:`CertificateTaxes`: the provider's
        own, or its bare result wrapped with an empty status. When the
        provider raises, or answers with something that is neither, the
        result inside has every figure held for ``provider_failed``. It never
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
        return CertificateTaxes(held_result("provider_failed", error=type(exc).__name__))
    if result is None:
        return None
    if isinstance(result, CertificateTaxes) and isinstance(result.result, PaymentTaxResult):
        return result
    if isinstance(result, PaymentTaxResult):
        return CertificateTaxes(result)
    logger.error(
        "certificate tax provider returned %s for %s %s, expected a PaymentTaxResult",
        type(result).__name__,
        source_kind,
        source_id,
    )
    return CertificateTaxes(held_result("provider_failed", error=type(result).__name__))


async def collect_certificate_taxes(session: AsyncSession, source_kind: str, source_id: Any) -> PaymentTaxResult | None:
    """The taxes of one certificate source, from whoever registered to compute them.

    Returns:
        ``None`` when no provider is registered or the provider has nothing
        for this source; the provider's result otherwise; and when the
        provider raises, or answers with something that is not a tax result,
        a result with every figure held for ``provider_failed``. It never
        raises on the provider's behalf.
    """
    state = await collect_certificate_tax_state(session, source_kind, source_id)
    return state.result if state is not None else None


__all__ = [
    "TAX_CHOICE_KINDS",
    "CertificateTaxProvider",
    "CertificateTaxRefusalError",
    "CertificateTaxRequest",
    "CertificateTaxWriter",
    "CertificateTaxes",
    "CertificateTaxesUnavailableError",
    "collect_certificate_tax_state",
    "collect_certificate_taxes",
    "held_result",
    "provider_registered",
    "register_certificate_tax_provider",
    "register_certificate_tax_writer",
    "save_certificate_taxes",
    "unregister_certificate_tax_provider",
    "unregister_certificate_tax_writer",
]
