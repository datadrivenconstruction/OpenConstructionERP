// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The state of one payment-plan instalment as the client reads it: upcoming,
// due, invoiced, paid or overdue. The builder's panel and the client portal
// show the same word for the same state, so both read it from here.
//
// The status always comes from the server. Overdue depends on the payment
// terms, the day the milestone was reached and today's date on the server, and
// a second calculation in the browser would sooner or later disagree with the
// invoice the client is holding.

import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Badge, type BadgeVariant } from './Badge';

export type PaymentPlanStatus = 'upcoming' | 'due' | 'invoiced' | 'paid' | 'overdue';

const VARIANT: Record<PaymentPlanStatus, BadgeVariant> = {
  upcoming: 'neutral',
  due: 'warning',
  invoiced: 'blue',
  paid: 'success',
  overdue: 'error',
};

function isPaymentPlanStatus(status: string): status is PaymentPlanStatus {
  return Object.prototype.hasOwnProperty.call(VARIANT, status);
}

/** The translated word for a status; an unknown code is shown as it came. */
export function paymentPlanStatusLabel(t: TFunction, status: string): string {
  switch (status) {
    case 'upcoming':
      return t('payment_plan.status_upcoming', { defaultValue: 'Upcoming' });
    case 'due':
      return t('payment_plan.status_due', { defaultValue: 'Due' });
    case 'invoiced':
      return t('payment_plan.status_invoiced', { defaultValue: 'Invoiced' });
    case 'paid':
      return t('payment_plan.status_paid', { defaultValue: 'Paid' });
    case 'overdue':
      return t('payment_plan.status_overdue', { defaultValue: 'Overdue' });
    default:
      return status;
  }
}

export function PaymentPlanStatusBadge({
  status,
  size,
}: {
  status: string;
  size?: 'sm' | 'md';
}) {
  const { t } = useTranslation();
  const variant = isPaymentPlanStatus(status) ? VARIANT[status] : 'neutral';
  return (
    <Badge variant={variant} size={size} dot>
      {paymentPlanStatusLabel(t, status)}
    </Badge>
  );
}
