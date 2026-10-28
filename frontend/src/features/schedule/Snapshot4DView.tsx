// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// 4D snapshot view - a date scrubber over the existing 4D snapshot endpoint.
// For a chosen data date (and optional BIM model) it shows the derived status
// of every linked BIM element (not started / in progress / completed / delayed
// / ahead of schedule) and lets the user jump into the BIM viewer with a given
// status isolated. Surfaces existing backend data only; no new compute.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { CalendarClock, Box, Layers, Info } from 'lucide-react';
import { Card, Badge, SkeletonText, RecoveryCard, ViewInBIMButton } from '@/shared/ui';
import { fetchBIMModels } from '@/features/bim/api';
import { scheduleApi } from './api';
import {
  tallySnapshot,
  snapshotTotal,
  clampDateIso,
  deriveScrubberRange,
  daysBetweenIso,
  addDaysIso,
  type SnapshotStatus,
} from './evm';

interface Snapshot4DViewProps {
  scheduleId: string;
  projectId: string;
  /** Schedule planned start (ISO) - lower bound of the scrubber. */
  scheduleStart?: string | null;
  /** Schedule planned end (ISO) - upper bound of the scrubber. */
  scheduleEnd?: string | null;
}

/** Tailwind dot + badge styling for each canonical 4D status. */
const STATUS_STYLE: Record<
  SnapshotStatus | string,
  { dot: string; badge: 'neutral' | 'blue' | 'success' | 'warning' | 'error' }
> = {
  delayed: { dot: 'bg-semantic-error', badge: 'error' },
  in_progress: { dot: 'bg-oe-blue', badge: 'blue' },
  not_started: { dot: 'bg-content-tertiary', badge: 'neutral' },
  ahead_of_schedule: { dot: 'bg-semantic-success', badge: 'success' },
  completed: { dot: 'bg-semantic-success', badge: 'success' },
};

export function Snapshot4DView({
  scheduleId,
  projectId,
  scheduleStart,
  scheduleEnd,
}: Snapshot4DViewProps) {
  const { t } = useTranslation();

  // Today (ISO) once per render - drives the default scrubber position.
  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);
  const range = useMemo(
    () => deriveScrubberRange(scheduleStart, scheduleEnd, todayIso),
    [scheduleStart, scheduleEnd, todayIso],
  );

  // Default the scrubber to today clamped into the schedule span.
  const [asOf, setAsOf] = useState<string>(() => clampDateIso(todayIso, range.min, range.max));
  const [modelId, setModelId] = useState<string>('');

  // Available BIM models (the snapshot resolves element status per model).
  const { data: modelsData } = useQuery({
    queryKey: ['bim-models', projectId],
    queryFn: () => fetchBIMModels(projectId),
    enabled: Boolean(projectId),
    staleTime: 300_000,
  });
  const models = useMemo(
    () => (modelsData?.items ?? []).filter((m) => (m.element_count ?? 0) > 0),
    [modelsData],
  );

  const {
    data: snapshot,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['schedule', scheduleId, 'snapshot', asOf, modelId || 'all'],
    queryFn: () =>
      scheduleApi.getSnapshot(scheduleId, {
        asOfDate: asOf,
        modelVersionId: modelId || undefined,
      }),
    enabled: Boolean(scheduleId),
  });

  const tally = useMemo(() => tallySnapshot(snapshot), [snapshot]);
  const total = snapshotTotal(snapshot);

  // Element ids for a given status - feeds the per-status "View in BIM" link.
  const idsByStatus = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const [elementId, status] of Object.entries(snapshot?.elements ?? {})) {
      const list = map.get(status) ?? [];
      list.push(elementId);
      map.set(status, list);
    }
    return map;
  }, [snapshot]);

  const statusLabel = (status: string): string =>
    t(`schedule.snapshot.status_${status}`, {
      defaultValue: status
        .split('_')
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' '),
    });

  return (
    <Card padding="md" className="mt-4">
      <div className="mb-3 flex items-center gap-2">
        <CalendarClock size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('schedule.snapshot.title', { defaultValue: '4D Snapshot' })}
        </h3>
        <span className="text-2xs text-content-tertiary">
          {t('schedule.snapshot.subtitle', {
            defaultValue: 'Element status on a chosen date',
          })}
        </span>
      </div>

      {/* Scrubber + model picker */}
      <div className="flex flex-col gap-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label
            htmlFor="snapshot-date-range"
            className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-content-tertiary"
          >
            {t('schedule.snapshot.data_date', { defaultValue: 'Data date' })}
          </label>
          <div className="flex items-center gap-3">
            <input
              id="snapshot-date-range"
              type="range"
              min={0}
              max={Math.max(0, daysBetweenIso(range.min, range.max))}
              step={1}
              value={Math.max(0, daysBetweenIso(range.min, asOf))}
              onChange={(e) => setAsOf(addDaysIso(range.min, Number(e.target.value)))}
              aria-label={t('schedule.snapshot.scrubber', {
                defaultValue: 'Scrub the data date between {{start}} and {{end}}',
                start: range.min,
                end: range.max,
              })}
              className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-surface-secondary accent-oe-blue [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-oe-blue [&::-webkit-slider-thumb]:shadow"
            />
            <input
              type="date"
              value={asOf}
              min={range.min}
              max={range.max}
              onChange={(e) => setAsOf(clampDateIso(e.target.value, range.min, range.max))}
              aria-label={t('schedule.snapshot.data_date', { defaultValue: 'Data date' })}
              className="h-9 rounded-lg border border-border bg-surface-primary px-2.5 text-sm tabular-nums focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            />
          </div>
          <div className="mt-1 flex justify-between text-2xs text-content-quaternary tabular-nums">
            <span>{range.min}</span>
            <span>{range.max}</span>
          </div>
        </div>

        <div className="sm:w-56">
          <label
            htmlFor="snapshot-model"
            className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-content-tertiary"
          >
            <span className="inline-flex items-center gap-1">
              <Box size={11} />
              {t('schedule.snapshot.bim_model', { defaultValue: 'BIM model' })}
            </span>
          </label>
          <select
            id="snapshot-model"
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
          >
            <option value="">
              {t('schedule.snapshot.all_models', { defaultValue: 'All linked elements' })}
            </option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Body */}
      <div className="mt-3">
        {isLoading ? (
          <SkeletonText lines={3} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : total === 0 ? (
          <div className="flex items-start gap-3 rounded-xl border border-border-light bg-surface-secondary/30 p-4">
            <Info size={15} className="mt-0.5 shrink-0 text-content-tertiary" />
            <div>
              <p className="text-sm font-medium text-content-primary">
                {t('schedule.snapshot.empty_title', { defaultValue: 'No linked elements' })}
              </p>
              <p className="mt-0.5 max-w-xl text-xs text-content-secondary">
                {t('schedule.snapshot.empty_hint', {
                  defaultValue:
                    'No BIM elements are linked to this schedule for the chosen date and model. Link activities to model elements to drive a 4D sequence, then scrub the date to see status change over time.',
                })}
              </p>
            </div>
          </div>
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs text-content-secondary">
                {t('schedule.snapshot.elements_on', {
                  defaultValue: '{{count}} element(s) on {{date}}',
                  count: total,
                  date: asOf,
                })}
              </span>
              {isFetching && (
                <span className="text-2xs text-content-tertiary">
                  {t('common.updating', { defaultValue: 'Updating...' })}
                </span>
              )}
            </div>

            {/* Stacked status bar */}
            <div
              className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-secondary"
              role="img"
              aria-label={t('schedule.snapshot.bar_label', {
                defaultValue: 'Element status distribution on {{date}}',
                date: asOf,
              })}
            >
              {tally.map((bucket) => (
                <div
                  key={bucket.status}
                  className={STATUS_STYLE[bucket.status]?.dot ?? 'bg-content-tertiary'}
                  style={{ width: `${(bucket.count / total) * 100}%` }}
                  title={`${statusLabel(bucket.status)}: ${bucket.count}`}
                />
              ))}
            </div>

            {/* Legend rows */}
            <ul className="mt-3 space-y-1.5">
              {tally.map((bucket) => {
                const style = STATUS_STYLE[bucket.status];
                const pct = Math.round((bucket.count / total) * 100);
                return (
                  <li
                    key={bucket.status}
                    className="flex items-center justify-between gap-3 rounded-lg px-1 py-1 hover:bg-surface-secondary/40"
                  >
                    <span className="flex items-center gap-2 text-sm text-content-primary">
                      <span
                        className={`h-2.5 w-2.5 shrink-0 rounded-full ${style?.dot ?? 'bg-content-tertiary'}`}
                        aria-hidden
                      />
                      {statusLabel(bucket.status)}
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge variant={style?.badge ?? 'neutral'} size="sm">
                        {bucket.count} - {pct}%
                      </Badge>
                      <ViewInBIMButton
                        elementIds={idsByStatus.get(bucket.status) ?? []}
                        iconSize={11}
                        label={t('schedule.snapshot.view_in_bim', { defaultValue: 'View in 3D' })}
                      />
                    </span>
                  </li>
                );
              })}
            </ul>

            <p className="mt-3 flex items-center gap-1.5 text-2xs text-content-tertiary">
              <Layers size={11} className="shrink-0" />
              {t('schedule.snapshot.footer_hint', {
                defaultValue:
                  'Status is derived from each linked activity at the data date. Drag the scrubber to replay the build sequence.',
              })}
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
