# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Broker licence rules of the ``property_dev`` rule set.

A broker on a reservation or a sale must hold a licence that is valid on the
deal date, and a licence about to lapse is flagged ahead of time. Nothing here
names a country: whether the rule applies, which authority issues the licence
and what it is called come from the country profile
(:func:`app.core.regional_packages.broker_licence_policy`), and a development
can override the default with ``metadata["broker_licence_required"]``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.regional_packages import broker_licence_policy
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale, _ok, _propdev_context

DEFAULT_EXPIRY_WARNING_DAYS = (60, 30)
_OPEN_CONTRACT_STATUSES = ("draft", "sent_for_signature", "partially_signed")


def licence_held_on(licences: Iterable[Any], on_date: date, authority_code: str = "") -> Any | None:
    """The licence that covers ``on_date`` (latest end first), or ``None``.

    Only ``active`` licences count. An open start or end date does not limit the window.
    """
    wanted = authority_code.upper()
    covering = [
        lic
        for lic in licences
        if lic.status == "active"
        and (not wanted or (lic.authority_code or "").upper() == wanted)
        and (lic.valid_from is None or lic.valid_from <= on_date)
        and (lic.valid_to is None or lic.valid_to >= on_date)
    ]
    if not covering:
        return None
    return max(covering, key=lambda lic: lic.valid_to or date.max)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def expiry_tiers(policy: dict[str, Any]) -> tuple[int, int]:
    """(notice window, warning window) in days; one number means both are equal."""
    raw = policy.get("expiry_warning_days", DEFAULT_EXPIRY_WARNING_DAYS)
    values = raw if isinstance(raw, list | tuple) else [raw]
    try:
        days = sorted({int(v) for v in values if v is not None})
    except (TypeError, ValueError):
        days = []
    if not days:
        days = sorted(DEFAULT_EXPIRY_WARNING_DAYS)
    return days[-1], days[0]


def _today(context: ValidationContext) -> date:
    meta = context.metadata if isinstance(context.metadata, dict) else {}
    return _as_date(meta.get("today")) or datetime.now(UTC).date()


async def _policy(session: Any, dev_id: uuid.UUID) -> dict[str, Any] | None:
    """The licence policy in force for the development, or ``None`` when the rule is off."""
    from app.modules.property_dev.models import Development

    dev = await session.get(Development, dev_id)
    if dev is None:
        return None
    policy = broker_licence_policy(dev.country_code)
    override = (dev.metadata_ or {}).get("broker_licence_required")
    enabled = override if isinstance(override, bool) else bool(policy.get("enabled_by_default"))
    return policy if enabled else None


async def _deals(session: Any, dev_id: uuid.UUID, *, open_only: bool) -> list[dict[str, Any]]:
    """Reservations and sales of the development that carry a broker (through the lead)."""
    from sqlalchemy import select

    from app.modules.property_dev.models import Lead, Plot, Reservation, SalesContract

    deals: list[dict[str, Any]] = []
    res_status = ("active",) if open_only else ("active", "converted")
    rows = (
        await session.execute(
            select(Reservation, Lead.broker_id)
            .join(Plot, Plot.id == Reservation.plot_id)
            .join(Lead, Lead.id == Reservation.lead_id)
            .where(Plot.development_id == dev_id, Lead.broker_id.is_not(None), Reservation.status.in_(res_status))
        )
    ).all()
    for res, broker_id in rows:
        deals.append(
            {
                "kind": "reservation",
                "id": res.id,
                "label": res.reservation_number,
                "broker_id": broker_id,
                "date": _as_date(res.deposit_paid_at) or _as_date(res.created_at),
            }
        )
    stmt = (
        select(SalesContract, Lead.broker_id)
        .join(Plot, Plot.id == SalesContract.plot_id)
        .join(Reservation, Reservation.id == SalesContract.reservation_id)
        .join(Lead, Lead.id == Reservation.lead_id)
        .where(Plot.development_id == dev_id, Lead.broker_id.is_not(None), SalesContract.status != "cancelled")
    )
    if open_only:
        stmt = stmt.where(SalesContract.status.in_(_OPEN_CONTRACT_STATUSES))
    for contract, broker_id in (await session.execute(stmt)).all():
        deals.append(
            {
                "kind": "sales_contract",
                "id": contract.id,
                "label": contract.contract_number,
                "broker_id": broker_id,
                "date": _as_date(contract.signing_date) or _as_date(contract.created_at),
            }
        )
    return deals


async def _brokers_and_licences(session: Any, broker_ids: set[Any]) -> tuple[dict[Any, Any], dict[Any, list[Any]]]:
    from sqlalchemy import select

    from app.modules.property_dev.models import Broker, BrokerLicence

    if not broker_ids:
        return {}, {}
    brokers = {b.id: b for b in (await session.execute(select(Broker).where(Broker.id.in_(broker_ids)))).scalars()}
    held: dict[Any, list[Any]] = {}
    lic_rows = await session.execute(select(BrokerLicence).where(BrokerLicence.broker_id.in_(broker_ids)))
    for lic in lic_rows.scalars():
        held.setdefault(lic.broker_id, []).append(lic)
    return brokers, held


def _passed(rule: ValidationRule, locale: str) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=True,
        message=_ok(locale),
    )


def _label(policy: dict[str, Any], locale: str) -> str:
    return str(policy.get("licence_label") or translate("property_dev.broker_licence_default_label", locale=locale))


class PropDevBrokerLicenceValidOnDealDate(ValidationRule):
    """ERROR: the broker on a reservation or sale must hold a licence valid on the deal date."""

    rule_id = "property_dev.broker_licence_valid_on_deal_date"
    name = "Broker licence valid on deal date"
    standard = "property_dev"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "Every reservation and sale that names a broker needs an active broker licence "
        "whose validity window covers the deal date. Applies where the country profile "
        "or the development enables it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        policy = await _policy(session, dev_id)
        if policy is None:
            return []
        locale = _get_locale(context)
        deals = await _deals(session, dev_id, open_only=False)
        brokers, held = await _brokers_and_licences(session, {d["broker_id"] for d in deals})
        authority = str(policy.get("authority_code") or "")
        label = _label(policy, locale)
        results: list[RuleResult] = []
        for deal in deals:
            when = deal["date"]
            if when is None or licence_held_on(held.get(deal["broker_id"], []), when, authority) is not None:
                continue
            broker = brokers.get(deal["broker_id"])
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "property_dev.broker_licence_valid_on_deal_date.fail",
                        locale=locale,
                        broker=broker.name if broker else str(deal["broker_id"]),
                        label=label,
                        date=when.isoformat(),
                        deal=deal["label"],
                    ),
                    element_ref=f"property_dev:{deal['kind']}:{deal['id']}",
                    details={
                        "broker_id": str(deal["broker_id"]),
                        "deal_date": when.isoformat(),
                        "authority": authority,
                    },
                    suggestion=translate("property_dev.broker_licence_valid_on_deal_date.suggestion", locale=locale),
                )
            )
        return results or [_passed(self, locale)]


class PropDevBrokerLicenceExpiringSoon(ValidationRule):
    """WARNING within the short window (30 days), INFO within the long one (60 days)."""

    rule_id = "property_dev.broker_licence_expiring_soon"
    name = "Broker licence expiring soon"
    standard = "property_dev"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = (
        "A broker on an active reservation or an unsigned sale whose latest valid licence "
        "ends within 60 days (notice) or 30 days (warning); the country profile may change both."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ctx = _propdev_context(context)
        if ctx is None:
            return []
        session, dev_id = ctx
        policy = await _policy(session, dev_id)
        if policy is None:
            return []
        locale = _get_locale(context)
        today = _today(context)
        window, urgent = expiry_tiers(policy)
        deals = await _deals(session, dev_id, open_only=True)
        brokers, held = await _brokers_and_licences(session, {d["broker_id"] for d in deals})
        authority = str(policy.get("authority_code") or "")
        label = _label(policy, locale)
        results: list[RuleResult] = []
        for broker_id in sorted({d["broker_id"] for d in deals}, key=str):
            current = licence_held_on(held.get(broker_id, []), today, authority)
            if current is None or current.valid_to is None or current.valid_to > today + timedelta(days=window):
                continue
            broker = brokers.get(broker_id)
            days_left = (current.valid_to - today).days
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=Severity.WARNING if days_left <= urgent else Severity.INFO,
                    category=self.category,
                    passed=False,
                    message=translate(
                        "property_dev.broker_licence_expiring_soon.fail",
                        locale=locale,
                        broker=broker.name if broker else str(broker_id),
                        label=label,
                        date=current.valid_to.isoformat(),
                        days=str(days_left),
                    ),
                    element_ref=f"property_dev:broker:{broker_id}",
                    details={"broker_id": str(broker_id), "valid_to": current.valid_to.isoformat()},
                    suggestion=translate("property_dev.broker_licence_expiring_soon.suggestion", locale=locale),
                )
            )
        return results or [_passed(self, locale)]


BROKER_LICENCE_RULES: list[ValidationRule] = [
    PropDevBrokerLicenceValidOnDealDate(),
    PropDevBrokerLicenceExpiringSoon(),
]
