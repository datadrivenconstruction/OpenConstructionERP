// DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ContractExpiryBadge — small inline badge that flags an expired or
// near-expiry contract end_date. UTC-day arithmetic on the
// ``YYYY-MM-DD`` end_date string, matching DeliveryCountdownBadge to
// keep the visual / behavioural convention consistent across modules.
//
// Suppression rules (intentional):
//   * end_date null      → render nothing (no column noise on open-ended
//                          contracts).
//   * status terminal    → render nothing for ``completed`` and
//                          ``terminated``. An expired-completed contract
//                          is fine; the expiry signal is operational, not
//                          historical.
//   * status draft       → suppressed: a draft contract isn't live yet,
//                          and an expired-draft is a data-entry artefact,
//                          not an emergency.
//   * window             → red = expired, amber = within 30 days, hidden
//                          otherwise. 30d window matches industry-typical
//                          notice periods on construction agreements.

import { useTranslation } from 'react-i18next';
import { AlertTriangle, Clock } from 'lucide-react';

import { Badge } from '@/shared/ui';
import type { ContractStatus } from './api';

interface Props {
  endDate: string | null | undefined;
  status: ContractStatus | string;
}

const TERMINAL = new Set<string>(['completed', 'terminated', 'draft']);

function diffDaysUtc(isoYmd: string): number | null {
  // Parse YYYY-MM-DD as UTC midnight to avoid local TZ skew — same logic
  // as DeliveryCountdownBadge so a 2 AM EU page-load doesn't shift the
  // bucket boundary.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const target = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate(),
  );
  return Math.round((target - today) / 86_400_000);
}

export function ContractExpiryBadge({ endDate, status }: Props) {
  const { t } = useTranslation();

  if (!endDate || TERMINAL.has(status)) return null;

  const days = diffDaysUtc(endDate);
  if (days === null) return null;

  if (days < 0) {
    const overdueBy = Math.abs(days);
    return (
      <Badge variant="error" size="sm" dot>
        <AlertTriangle size={10} className="me-1 inline-block" aria-hidden />
        {t('contracts.expired_by', {
          defaultValue: 'Expired {{days}}d',
          days: overdueBy,
        })}
      </Badge>
    );
  }
  if (days <= 30) {
    return (
      <Badge variant="warning" size="sm">
        <Clock size={10} className="me-1 inline-block" aria-hidden />
        {t('contracts.expires_in', {
          defaultValue: 'Expires {{days}}d',
          days,
        })}
      </Badge>
    );
  }
  return null;
}
