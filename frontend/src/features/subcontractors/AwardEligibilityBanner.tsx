// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Award-eligibility banner (TOP-30 #20).
 *
 * Surfaces, up front, whether a subcontractor may be awarded live work so the
 * user is not surprised by a 409 when activating an agreement or claiming a
 * payment. Mirrors the backend gate in
 * ``SubcontractorService.subcontractor_award_block``:
 *
 *   - Approved & not blocked  → green  "Eligible for award"
 *   - Pending prequalification → amber "Prequalification pending"
 *   - Rejected / suspended     → red   "Not approved for award"
 *   - Administratively blocked → red   "Blocked"  (+ reason)
 *
 * Reads ``GET /subcontractors/{id}/award-eligibility`` so the verdict matches
 * the server exactly (the same reasons array drives the 409 detail).
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CheckCircle2, ShieldAlert, Ban, Clock } from 'lucide-react';
import { getAwardEligibility, type PrequalStatus } from './api';
import { describeComplianceReasons } from './complianceReasons';

interface AwardEligibilityBannerProps {
  subcontractorId: string;
  /** Current prequalification status — used for the pending/eligible nuance. */
  prequalStatus: PrequalStatus;
  isBlocked: boolean;
  blockedReason?: string | null;
}

type Tone = 'success' | 'warning' | 'error';

const TONE_CLS: Record<Tone, string> = {
  success:
    'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-200',
  warning:
    'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200',
  error:
    'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-200',
};

export function AwardEligibilityBanner({
  subcontractorId,
  prequalStatus,
  isBlocked,
  blockedReason,
}: AwardEligibilityBannerProps) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['subcontractors', 'awardEligibility', subcontractorId],
    queryFn: () => getAwardEligibility(subcontractorId),
    enabled: !!subcontractorId,
    retry: false,
  });

  // While loading, fall back to the props so the banner never flickers empty.
  const awardable = q.data ? q.data.awardable : !isBlocked && prequalStatus === 'approved';
  const reasons = q.data?.reasons ?? [];

  let tone: Tone;
  let Icon = CheckCircle2;
  let title: string;
  let desc: string | null = null;

  if (isBlocked || reasons.includes('subcontractor_blocked')) {
    tone = 'error';
    Icon = Ban;
    title = t('subcontractors.award_blocked_title', {
      defaultValue: 'Blocked - not eligible for award',
    });
    desc =
      blockedReason ||
      t('subcontractors.award_blocked_desc', {
        defaultValue:
          'This subcontractor is administratively blocked. Agreements cannot be activated and payments are held.',
      });
  } else if (prequalStatus === 'rejected' || prequalStatus === 'suspended') {
    tone = 'error';
    Icon = ShieldAlert;
    title = t('subcontractors.not_eligible', {
      defaultValue: 'Not approved for award',
    });
    desc = t('subcontractors.award_gate_desc', {
      defaultValue:
        'Prequalification is {{status}}. Agreements cannot be activated and payments are held until it is cleared.',
      status: prequalStatus,
    });
  } else if (!awardable) {
    // Server says not awardable for some other reason — surface it generically.
    tone = 'error';
    Icon = ShieldAlert;
    title = t('subcontractors.not_eligible', {
      defaultValue: 'Not approved for award',
    });
    desc = reasons.length > 0 ? describeComplianceReasons(reasons, t) : null;
  } else if (prequalStatus === 'pending') {
    tone = 'warning';
    Icon = Clock;
    title = t('subcontractors.award_pending_title', {
      defaultValue: 'Prequalification pending',
    });
    desc = t('subcontractors.award_pending_desc', {
      defaultValue:
        'This subcontractor can be awarded, but completing prequalification is recommended before going live.',
    });
  } else {
    tone = 'success';
    Icon = CheckCircle2;
    title = t('subcontractors.eligible', {
      defaultValue: 'Eligible for award',
    });
    desc = t('subcontractors.award_eligible_desc', {
      defaultValue: 'Prequalification is approved. This subcontractor can be awarded live work.',
    });
  }

  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs',
        TONE_CLS[tone],
      )}
      role="status"
      aria-label={t('subcontractors.award_eligibility', {
        defaultValue: 'Award eligibility',
      })}
    >
      <Icon size={14} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="font-semibold">{title}</p>
        {desc && <p className="opacity-90">{desc}</p>}
      </div>
    </div>
  );
}
