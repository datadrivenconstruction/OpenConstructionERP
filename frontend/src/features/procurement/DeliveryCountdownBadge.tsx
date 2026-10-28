// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DeliveryCountdownBadge - small inline badge that flags an overdue PO
// delivery (red) or hints at how many days are left until the scheduled
// delivery date (neutral/warning).
//
// Pure UTC-day arithmetic on the ``YYYY-MM-DD`` delivery_date string the
// PO model exposes. POs whose delivery_date is null render NOTHING (no
// "Unscheduled" badge in the row - the column already shows a dash).
// Terminal statuses (``completed`` / ``cancelled``) also suppress the
// badge: once received or cancelled, the countdown is irrelevant and
// would only add noise.

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { AlertTriangle, Clock } from 'lucide-react';

interface Props {
  deliveryDate: string | null | undefined;
  status: string;
}

function diffDaysUtc(isoYmd: string): number | null {
  // Parse the YYYY-MM-DD string as UTC midnight to avoid local TZ skew -
  // a 2 AM EU run must not count a "today" delivery as +1 because the
  // browser midnight is offset from UTC.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const target = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target - today) / 86_400_000);
}

const TERMINAL = new Set(['completed', 'cancelled']);

export function DeliveryCountdownBadge({ deliveryDate, status }: Props) {
  const { t } = useTranslation();

  if (!deliveryDate || TERMINAL.has(status)) return null;

  const days = diffDaysUtc(deliveryDate);
  if (days === null) return null;

  if (days < 0) {
    const overdueBy = Math.abs(days);
    return (
      <Badge variant="error" size="sm" dot>
        <AlertTriangle size={10} className="me-1 inline-block" aria-hidden />
        {t('procurement.delivery_overdue', {
          defaultValue: 'Overdue {{days}}d',
          days: overdueBy,
        })}
      </Badge>
    );
  }
  if (days === 0) {
    return (
      <Badge variant="warning" size="sm" dot>
        <Clock size={10} className="me-1 inline-block" aria-hidden />
        {t('procurement.delivery_due_today', { defaultValue: 'Due today' })}
      </Badge>
    );
  }
  if (days <= 7) {
    return (
      <Badge variant="warning" size="sm">
        <Clock size={10} className="me-1 inline-block" aria-hidden />
        {t('procurement.delivery_due_in', {
          defaultValue: 'In {{days}}d',
          days,
        })}
      </Badge>
    );
  }
  return null;
}
