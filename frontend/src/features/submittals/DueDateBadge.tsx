// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DueDateBadge — small inline badge that flags overdue submittals (red)
// or hints at how many days remain until ``date_required`` (warning).
//
// Pure UTC-day arithmetic on the ``YYYY-MM-DD`` date_required string the
// submittal model exposes. Submittals whose date_required is null render
// NOTHING (no "Unscheduled" noise — the column already shows a dash).
//
// Terminal statuses (``approved`` / ``approved_as_noted`` / ``rejected``
// / ``closed``) also suppress the badge: once the review is closed the
// countdown is irrelevant and only adds noise. For a submittal that
// already came back as ``revise_and_resubmit`` the countdown is also
// suppressed because the ball is back with the submitter and the date
// will reset on resubmit.

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { AlertTriangle, Clock } from 'lucide-react';

interface Props {
  dateRequired: string | null | undefined;
  status: string;
}

function diffDaysUtc(isoYmd: string): number | null {
  // Parse the YYYY-MM-DD string as UTC midnight to avoid local TZ skew —
  // a 2 AM EU run must not count a "today" deadline as +1 because the
  // browser midnight is offset from UTC.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const target = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target - today) / 86_400_000);
}

const TERMINAL = new Set([
  'approved',
  'approved_as_noted',
  'rejected',
  'closed',
  // Revise: ball is back with submitter, the deadline is meaningless
  // until they resubmit — suppress to avoid alarming overdue flags on
  // an item that's no longer in court.
  'revise_and_resubmit',
]);

export function DueDateBadge({ dateRequired, status }: Props) {
  const { t } = useTranslation();

  if (!dateRequired || TERMINAL.has(status)) return null;

  const days = diffDaysUtc(dateRequired);
  if (days === null) return null;

  if (days < 0) {
    const overdueBy = Math.abs(days);
    return (
      <Badge variant="error" size="sm" dot>
        <AlertTriangle size={10} className="me-1 inline-block" aria-hidden />
        {t('submittals.due_overdue', {
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
        {t('submittals.due_today', { defaultValue: 'Due today' })}
      </Badge>
    );
  }
  if (days <= 7) {
    return (
      <Badge variant="warning" size="sm">
        <Clock size={10} className="me-1 inline-block" aria-hidden />
        {t('submittals.due_in', {
          defaultValue: 'Due in {{days}}d',
          days,
        })}
      </Badge>
    );
  }
  return null;
}
