// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// DaysInCourtBadge — "days with reviewer" SLA-breach indicator.
//
// The submittal lifecycle in service.py moves ``ball_in_court`` between
// the submitter and the reviewer at each FSM transition. Once the
// submittal is ``submitted`` or ``under_review`` the reviewer is the
// holder and ``date_submitted`` is the moment the clock started ticking.
//
// This badge surfaces that elapsed time to the GC/owner watching the
// queue: nothing under 3d (a healthy submittal cycle), neutral 3-7d,
// warning 8-14d (SLA pressure), error 15d+ (breach). Defaults match the
// AIA G714 industry guideline of 14-day review turnaround.
//
// Only shown while the submittal is actively in the reviewer's court —
// once it returns (revise, reject, approve) the clock is moot.

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import { Hourglass } from 'lucide-react';

interface Props {
  dateSubmitted: string | null | undefined;
  status: string;
  /**
   * The server's own count of days in review, when it sent one. It is
   * measured on the server's calendar and matches the printed register, so
   * it is used as given and the date is not subtracted here at all.
   */
  days?: number | null;
}

const IN_COURT = new Set(['submitted', 'under_review']);

// Thresholds in days. Tuned to the AIA G714 14-day review SLA: a
// healthy review fits in a week, two weeks is the contractual deadline,
// anything beyond is a breach worth surfacing.
const NEUTRAL_DAYS = 3;
const WARNING_DAYS = 7;
const BREACH_DAYS = 14;

function daysSinceUtc(isoYmd: string): number | null {
  // Parse YYYY-MM-DD as UTC midnight; current "now" projected to its
  // own UTC midnight. Difference in calendar days, never negative for
  // past submissions.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const submitted = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const diff = Math.round((today - submitted) / 86_400_000);
  return diff < 0 ? 0 : diff;
}

export function DaysInCourtBadge({ dateSubmitted, status, days: serverDays }: Props) {
  const { t } = useTranslation();

  if (!dateSubmitted || !IN_COURT.has(status)) return null;

  const days = typeof serverDays === 'number' ? serverDays : daysSinceUtc(dateSubmitted);
  if (days === null) return null;
  // Suppress the chip entirely for fast / fresh reviews — the column
  // would otherwise glow with "1d in court" noise on every row.
  if (days < NEUTRAL_DAYS) return null;

  const label = t('submittals.days_in_court', {
    defaultValue: '{{days}}d in court',
    days,
  });

  let variant: 'neutral' | 'warning' | 'error' = 'neutral';
  if (days >= BREACH_DAYS) {
    variant = 'error';
  } else if (days > WARNING_DAYS) {
    variant = 'warning';
  }

  // Screen-reader-only suffix that names the SLA breach explicitly so
  // assistive tech surfaces the urgency, not just the day count.
  const srSuffix =
    days >= BREACH_DAYS
      ? t('submittals.days_in_court_sla_breach', {
          defaultValue: ' - SLA breached',
        })
      : '';

  return (
    <Badge variant={variant} size="sm">
      <Hourglass size={10} className="me-1 inline-block" aria-hidden />
      {label}
      {srSuffix && <span className="sr-only">{srSuffix}</span>}
    </Badge>
  );
}
