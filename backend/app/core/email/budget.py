# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily send budget for automatic notification mail.

Every de-duplication rule in the notification path is local: one entity, one
window, one table. None of them bounds the total, so when one of them is
switched off (a store cleared under it, a sweeper with a new source, a
subscriber that fires in a loop) nothing stops the instance from mailing the
same people all day. In September 2026 that took outbound mail away from the
whole account, including the password resets and verification mails that
have nothing to do with notifications.

This is the bound that does not depend on any of them: at most
``notification_email_daily_cap_per_recipient`` automatic mails per address
and ``notification_email_daily_cap_per_instance`` in total per UTC day. A
mail over either cap is logged and dropped; the in-app notification it
belongs to is already stored and stays.

Only the notification dispatcher asks. Mail a person triggers on purpose
(verification, password reset, portal sign-in links, tender invitations,
documents sent from a record) goes straight through ``EmailService`` and is
never counted or refused here.

Counts are held in process memory and start again at a restart. That is
deliberate: a table would share the fate of the one whose loss this guards
against, and the cap only has to make a runaway day bounded, not exact.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

DEFAULT_PER_RECIPIENT = 20
DEFAULT_PER_INSTANCE = 300


def _utc_today() -> date:
    return datetime.now(UTC).date()


class NotificationMailBudget:
    """Per-recipient and per-instance daily counters. A cap of 0 means no cap."""

    def __init__(
        self,
        *,
        per_recipient: int,
        per_instance: int,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self.per_recipient = max(0, per_recipient)
        self.per_instance = max(0, per_instance)
        self._today = today
        self._day: date | None = None
        self._by_recipient: dict[str, int] = {}
        self._total = 0
        self._dropped = 0

    def _roll(self) -> None:
        day = self._today()
        if day != self._day:
            if self._dropped:
                logger.warning(
                    "notification mail budget: %d automatic mail(s) dropped on %s over the daily caps",
                    self._dropped,
                    self._day,
                )
            self._day = day
            self._by_recipient = {}
            self._total = 0
            self._dropped = 0

    def admit(self, recipient: str, *, event_type: str = "") -> bool:
        """Count one mail to ``recipient`` and say whether it may go.

        No await inside, so on the event loop the check and the count cannot
        be split by another send.
        """
        self._roll()
        key = (recipient or "").strip().lower()
        sent_to_them = self._by_recipient.get(key, 0)
        if self.per_instance and self._total >= self.per_instance:
            reason = f"instance cap {self.per_instance}/day reached"
        elif self.per_recipient and sent_to_them >= self.per_recipient:
            reason = f"recipient cap {self.per_recipient}/day reached"
        else:
            self._by_recipient[key] = sent_to_them + 1
            self._total += 1
            return True
        self._dropped += 1
        logger.warning(
            "notification mail dropped: %s: to=%s event=%s (in-app notification kept)",
            reason,
            recipient,
            event_type,
        )
        return False

    @property
    def sent_today(self) -> int:
        self._roll()
        return self._total

    @property
    def dropped_today(self) -> int:
        self._roll()
        return self._dropped


_budget: NotificationMailBudget | None = None


def notification_mail_budget() -> NotificationMailBudget:
    """The process-wide budget, built from settings on first use."""
    global _budget  # noqa: PLW0603
    if _budget is None:
        from app.config import get_settings

        settings = get_settings()
        # getattr: a stand-in settings object without the fields keeps the defaults, never no cap.
        _budget = NotificationMailBudget(
            per_recipient=getattr(settings, "notification_email_daily_cap_per_recipient", DEFAULT_PER_RECIPIENT),
            per_instance=getattr(settings, "notification_email_daily_cap_per_instance", DEFAULT_PER_INSTANCE),
        )
    return _budget


def reset_notification_mail_budget() -> None:
    """Forget the counters and the caps - used by tests that change settings."""
    global _budget  # noqa: PLW0603
    _budget = None
