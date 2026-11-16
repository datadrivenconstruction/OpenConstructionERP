// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The cap meter: certified, committed-not-certified and headroom on one bar, with markers
 * for the minimum, the warning threshold and the cap, and a thin time bar under it.
 * Tone is never the only signal: the percent is always printed beside it.
 */

import clsx from 'clsx';
import { AlertTriangle, CircleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { capMeterGeometry, type CapMeterInput } from './capMeter';

export interface CapMeterProps extends CapMeterInput {
  /** The sentence screen readers hear (the server's headroom sentence). */
  valueText: string;
  compact?: boolean;
  className?: string;
}

const TONE_FILL = {
  neutral: 'bg-oe-blue',
  warning: 'bg-semantic-warning',
  error: 'bg-semantic-error',
} as const;

const TONE_TEXT = {
  neutral: 'text-content-secondary',
  warning: 'text-semantic-warning',
  error: 'text-semantic-error',
} as const;

export function CapMeter({ valueText, compact, className, ...input }: CapMeterProps) {
  const { t, i18n } = useTranslation();
  const g = capMeterGeometry(input);
  const pctText =
    g.pct == null
      ? t('framework.cap.no_cap', { defaultValue: 'No cap' })
      : new Intl.NumberFormat(i18n.language, { style: 'percent', maximumFractionDigits: compact ? 0 : 1 }).format(g.pct / 100);
  const Icon = g.tone === 'error' ? CircleAlert : g.tone === 'warning' ? AlertTriangle : null;
  return (
    <div className={clsx('flex items-center gap-2 min-w-0', className)}>
      <div className="flex-1 min-w-0">
        <div
          role="meter"
          aria-valuemin={0}
          aria-valuemax={Number(input.cap) || 0}
          aria-valuenow={Number(input.committed) || 0}
          aria-valuetext={valueText}
          aria-label={t('framework.cap.meter_label', { defaultValue: 'Use of the agreement cap' })}
          className={clsx('relative w-full overflow-hidden rounded-full bg-surface-secondary', compact ? 'h-1.5' : 'h-3')}
        >
          <div className="absolute inset-y-0 start-0 flex w-full">
            <div className={clsx(TONE_FILL[g.tone])} style={{ width: `${g.certified}%` }} />
            <div className={clsx(TONE_FILL[g.tone], 'opacity-50')} style={{ width: `${g.pending}%` }} />
          </div>
          {!compact && g.minimum != null && (
            <span className="absolute inset-y-0 w-px bg-content-tertiary" style={{ insetInlineStart: `${g.minimum}%` }} />
          )}
          {!compact && g.threshold != null && (
            <span className="absolute inset-y-0 w-px bg-semantic-warning" style={{ insetInlineStart: `${g.threshold}%` }} />
          )}
          {!compact && g.capMark != null && g.capMark < 100 && (
            <span className="absolute inset-y-0 w-0.5 bg-semantic-error" style={{ insetInlineStart: `${g.capMark}%` }} />
          )}
        </div>
        {!compact && g.termElapsed != null && (
          <div className="mt-1 h-0.5 w-full rounded-full bg-surface-secondary" aria-hidden="true">
            <div className="h-full rounded-full bg-content-tertiary" style={{ width: `${g.termElapsed}%` }} />
          </div>
        )}
      </div>
      <span className={clsx('inline-flex shrink-0 items-center gap-1 tabular-nums text-xs font-medium', TONE_TEXT[g.tone])}>
        {Icon && <Icon size={12} aria-hidden="true" />}
        {pctText}
      </span>
    </div>
  );
}
