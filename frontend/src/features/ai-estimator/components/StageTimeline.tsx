// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Compact per-stage status strip driven by ProgressResponse.stages. Shows
// each of the four stages with a pending / active / complete / error dot
// so the right monitor reflects exactly where the run is and surfaces a
// per-stage failure when one happens.

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, Loader2, AlertCircle, Circle } from 'lucide-react';
import type { StageState, StageStatus } from '../api';
import { STAGES } from './StageRail';

function StatusIcon({ status }: { status: StageStatus }) {
  switch (status) {
    case 'complete':
      return <Check className="h-3.5 w-3.5 text-emerald-500" />;
    case 'active':
      return <Loader2 className="h-3.5 w-3.5 animate-spin text-oe-blue" />;
    case 'error':
      return <AlertCircle className="h-3.5 w-3.5 text-rose-500" />;
    default:
      return <Circle className="h-3 w-3 text-content-tertiary" />;
  }
}

export function StageTimeline({
  stages,
  failureReason,
}: {
  stages: StageState[];
  failureReason: string | null;
}) {
  const { t } = useTranslation();

  // Fall back to the static stage list when the backend has not emitted a
  // stages array yet (e.g. the very first poll of a fresh run).
  const rows: StageState[] =
    stages.length > 0
      ? stages
      : STAGES.map((s) => ({
          stage: s.id,
          title: s.titleFallback,
          status: 'pending' as StageStatus,
          accepted_at: null,
        }));

  return (
    <ol className="space-y-1.5" aria-label={t('aiest.timeline.label', { defaultValue: 'Stage status' })}>
      {rows.map((row) => {
        const def = STAGES.find((s) => s.id === row.stage);
        const title = def ? t(def.titleKey, { defaultValue: def.titleFallback }) : row.title;
        const isError = row.status === 'error';
        return (
          <li key={row.stage} className="flex items-center gap-2">
            <StatusIcon status={row.status} />
            <span
              className={clsx(
                'text-xs',
                row.status === 'active'
                  ? 'font-medium text-oe-blue'
                  : isError
                    ? 'font-medium text-rose-600 dark:text-rose-400'
                    : row.status === 'complete'
                      ? 'text-content-secondary'
                      : 'text-content-tertiary',
              )}
            >
              {title}
            </span>
          </li>
        );
      })}
      {failureReason && (
        <li className="mt-1 rounded border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-200">
          {failureReason}
        </li>
      )}
    </ol>
  );
}
