// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Named stages of a CAD/BIM conversion with the current one highlighted,
 * finished ones ticked and, for the long step, the elapsed time against the
 * server's time limit. Used by the BIM upload dock, the model overlay and the
 * DWG takeoff card so all three read the same way.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, Loader2 } from 'lucide-react';
import clsx from 'clsx';
import { formatDuration } from '@/shared/lib/duration';
import { limitMinutes, stageStates, stageText, type ConversionStageId } from '@/shared/lib/conversionStages';

export interface ConversionStagesProps {
  stages: readonly ConversionStageId[];
  current: ConversionStageId;
  /** Upper-case file format, for example `RVT`. */
  format?: string;
  /** When the conversion began (ms since epoch); drives the elapsed line. */
  startedAt?: number | null;
  /** Server time limit for one conversion, in seconds. */
  limitS?: number | null;
  /** Real upload percent, shown while the upload stage is current. */
  uploadPercent?: number | null;
  /** `compact` is one line for a small dock; `full` lists every stage. */
  variant?: 'full' | 'compact';
}

export function ConversionStages({
  stages,
  current,
  format,
  startedAt,
  limitS,
  uploadPercent,
  variant = 'full',
}: ConversionStagesProps) {
  const { t } = useTranslation();
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const iv = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(iv);
  }, [startedAt]);

  const states = stageStates(stages, current);
  const at = Math.max(0, stages.indexOf(current));
  const minutes = limitMinutes(limitS);
  const elapsedS = startedAt ? Math.max(0, Math.round((Date.now() - startedAt) / 1000)) : 0;
  const elapsed = startedAt ? formatDuration(t, elapsedS, 's', { parts: 2, empty: '0s' }) : '';
  const share = Math.min(100, (elapsedS / (minutes * 60)) * 100);
  const isUpload = current === 'upload';
  const percent = Math.max(0, Math.min(100, Math.round(uploadPercent ?? 0)));
  const longStep = current === 'convert' || current === 'model3d' || current === 'table' || current === 'entities';

  const timeLine = startedAt && !isUpload ? (
    <p className="text-[11px] text-content-tertiary tabular-nums" data-testid="conversion-elapsed">
      {t('conv.elapsed_of_limit', {
        defaultValue: 'Running for {{elapsed}}. One conversion may take up to {{minutes}} minutes.',
        elapsed,
        minutes,
      })}
    </p>
  ) : null;

  const bar = (
    <div
      className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={isUpload ? percent : undefined}
      aria-label={t('conv.progress_label', { defaultValue: 'Conversion progress' })}
    >
      {isUpload ? (
        <div className="h-full rounded-full bg-oe-blue transition-all duration-300" style={{ width: `${percent}%` }} />
      ) : (
        <div
          className={clsx(
            'h-full rounded-full transition-all duration-1000',
            share > 80 ? 'bg-amber-500' : 'bg-oe-blue/70',
          )}
          style={{ width: `${Math.max(4, share)}%` }}
        />
      )}
    </div>
  );

  if (variant === 'compact') {
    const text = stageText(t, current, { format });
    return (
      <div className="space-y-1" data-testid="conversion-stages-compact">
        {bar}
        <p className="text-[10px] font-medium text-content-secondary">
          {t('conv.step_of', { defaultValue: 'Step {{step}} of {{total}}', step: at + 1, total: stages.length })}
          {' · '}
          {text.label}
          {isUpload ? ` · ${percent}%` : ''}
        </p>
        {startedAt && !isUpload && (
          <p className="text-[10px] text-content-quaternary tabular-nums">
            {t('conv.elapsed_short', { defaultValue: '{{elapsed}} of up to {{minutes}} min', elapsed, minutes })}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="conversion-stages">
      <ol className="space-y-1.5">
        {stages.map((id, i) => {
          const state = states[i]!;
          const text = stageText(t, id, { format });
          return (
            <li
              key={id}
              data-state={state}
              aria-current={state === 'current' ? 'step' : undefined}
              className={clsx(
                'flex items-start gap-3 rounded-lg border px-3 py-2 text-start transition-colors',
                state === 'current' ? 'border-oe-blue/25 bg-oe-blue/5' : 'border-transparent',
              )}
            >
              <span
                className={clsx(
                  'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                  state === 'done' && 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
                  state === 'current' && 'bg-oe-blue/15 text-oe-blue',
                  state === 'pending' && 'bg-surface-secondary text-content-quaternary',
                )}
              >
                {state === 'done' ? (
                  <Check size={12} aria-hidden="true" />
                ) : state === 'current' ? (
                  <Loader2 size={12} className="animate-spin" aria-hidden="true" />
                ) : (
                  i + 1
                )}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={clsx(
                    'block text-xs font-medium leading-tight',
                    state === 'pending' ? 'text-content-quaternary' : 'text-content-primary',
                  )}
                >
                  {text.label}
                  <span className="sr-only">
                    {' - '}
                    {state === 'done'
                      ? t('conv.state_done', { defaultValue: 'done' })
                      : state === 'current'
                        ? t('conv.state_current', { defaultValue: 'in progress' })
                        : t('conv.state_pending', { defaultValue: 'waiting' })}
                  </span>
                  {state === 'current' && isUpload && (
                    <span className="ms-2 text-oe-blue tabular-nums">{percent}%</span>
                  )}
                </span>
                {state === 'current' && (
                  <span className="mt-1 block space-y-1.5">
                    <span className="block text-[11px] leading-snug text-content-tertiary">{text.hint}</span>
                    {(isUpload || longStep) && bar}
                    {timeLine}
                  </span>
                )}
              </span>
            </li>
          );
        })}
      </ol>
      <p
        className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-[11px] leading-relaxed text-content-secondary"
        data-testid="conversion-note"
      >
        {isUpload
          ? t('conv.note_keep_open', {
              defaultValue: 'Keep this browser tab open until the upload reaches 100%. After that the server works on its own.',
            })
          : t('conv.note_may_leave', {
              defaultValue:
                'Large models can take many minutes. You can leave this page: the server keeps converting and the model appears in your project when it is done.',
            })}
      </p>
    </div>
  );
}
