// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// <BudgetLineThresholdEditor> — Gap D cost-overrun alert configuration.
//
// A compact slider (0-50%) that arms the cost-overrun alert threshold on a
// single budget line. When the line's actual cost later breaches
// planned * (1 + threshold/100), the backend notifies the project owner.
// Setting the slider to 0 disables alerting on the line.

import { useState, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { BellRing, BellOff, Loader2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { costModelApi } from './api';

/** Slider bounds. The design caps the UI at +50% even though the API accepts up to 100%. */
const MIN_PCT = 0;
const MAX_PCT = 50;

function clampPct(value: number): number {
  if (Number.isNaN(value)) return MIN_PCT;
  return Math.min(MAX_PCT, Math.max(MIN_PCT, Math.round(value)));
}

/**
 * Parse the Decimal-encoded threshold string the backend stores. Defaults to 0
 * (disabled) for null/blank/unparseable values.
 */
export function parseThreshold(raw: string | undefined | null): number {
  if (raw == null || raw === '') return 0;
  const n = Number(raw);
  return Number.isFinite(n) ? clampPct(n) : 0;
}

export function BudgetLineThresholdEditor({
  lineId,
  initialThresholdPct,
}: {
  lineId: string;
  /** Current stored threshold as a Decimal string (e.g. '10', '12.5', '0'). */
  initialThresholdPct: string | undefined | null;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const initial = parseThreshold(initialThresholdPct);
  const [pct, setPct] = useState<number>(initial);

  // Keep local state in sync when the persisted value changes underneath us
  // (e.g. another edit invalidated the query and refetched a new threshold).
  useEffect(() => {
    setPct(parseThreshold(initialThresholdPct));
  }, [initialThresholdPct]);

  const mutation = useMutation({
    mutationFn: (threshold: number) => costModelApi.setOverrunAlertThreshold(lineId, threshold),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
      addToast({
        type: 'success',
        title:
          pct > 0
            ? t('costmodel.overrun_threshold_saved', { defaultValue: 'Cost-overrun alert armed' })
            : t('costmodel.overrun_threshold_disabled', {
                defaultValue: 'Cost-overrun alert disabled',
              }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costmodel.overrun_threshold_failed', {
          defaultValue: 'Failed to update cost-overrun alert',
        }),
        message: err.message,
      });
    },
  });

  const save = useCallback(() => {
    mutation.mutate(clampPct(pct));
  }, [mutation, pct]);

  const dirty = clampPct(pct) !== initial;
  const armed = pct > 0;

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-content-secondary">
          {armed ? (
            <BellRing size={13} className="text-amber-500" />
          ) : (
            <BellOff size={13} className="text-content-tertiary" />
          )}
          {t('costmodel.overrun_threshold_label', { defaultValue: 'Cost-overrun alert' })}
        </span>
        <span className="text-xs font-bold tabular-nums text-content-primary">
          {armed
            ? t('costmodel.overrun_threshold_value', {
                defaultValue: 'Alert @ +{{pct}}%',
                pct,
              })
            : t('costmodel.overrun_threshold_off', { defaultValue: 'Off' })}
        </span>
      </div>
      <input
        type="range"
        min={MIN_PCT}
        max={MAX_PCT}
        step={1}
        value={pct}
        onChange={(e) => setPct(clampPct(parseFloat(e.target.value)))}
        aria-label={t('costmodel.overrun_threshold_label', { defaultValue: 'Cost-overrun alert' })}
        className="w-full accent-oe-blue"
      />
      <div className="flex items-center justify-between">
        <p className="text-2xs text-content-tertiary">
          {armed
            ? t('costmodel.overrun_threshold_hint', {
                defaultValue: 'Notify the project owner when actual exceeds planned by {{pct}}%.',
                pct,
              })
            : t('costmodel.overrun_threshold_hint_off', {
                defaultValue: 'Slide above 0 to be alerted when this line goes over budget.',
              })}
        </p>
        <Button size="sm" variant="secondary" onClick={save} disabled={!dirty || mutation.isPending}>
          {mutation.isPending ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            t('common.save', { defaultValue: 'Save' })
          )}
        </Button>
      </div>
    </div>
  );
}
