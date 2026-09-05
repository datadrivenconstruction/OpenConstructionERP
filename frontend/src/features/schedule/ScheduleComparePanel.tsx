// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Schedule comparison / diff panel (T1.3). Picks a base (a captured baseline)
// and a target (the live schedule by default, or another baseline), runs
// POST /v1/schedule/schedules/{id}/diff and renders:
//   - a summary roll-up (net finish movement, critical-path in/out, cost
//     deltas, and counts by change category)
//   - categorized change tables: activities (added / removed / modified with
//     finish movement), relationships (added / removed / retyped / relagged),
//     and calendars
//
// Baselines come from GET /v1/schedule/baselines/?project_id=. Activity ids
// render through an optional name map the caller already holds.

import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  GitCompare,
  ArrowRight,
  Loader2,
  PlusCircle,
  MinusCircle,
  PencilLine,
  TrendingUp,
  TrendingDown,
} from 'lucide-react';

import { Button, Card, Badge, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency, toNum } from '@/shared/lib/money';
import {
  scheduleApi,
  type ScheduleBaseline,
  type ScheduleDiff,
  type DiffActivityChange,
  type DiffRelationshipChange,
} from './api';

interface ScheduleComparePanelProps {
  scheduleId: string;
  projectId: string;
  /** Project currency for the cost-delta figures (blank renders plain numbers). */
  currency?: string;
  /** Optional id -> display name map so change rows show names, not UUIDs. */
  activitiesById?: Record<string, string>;
}

/** Sentinel for "the live schedule" target option. */
const LIVE = '__live__';

const selectCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

const CHANGE_BADGE: Record<string, 'success' | 'error' | 'warning' | 'blue' | 'neutral'> = {
  added: 'success',
  removed: 'error',
  modified: 'warning',
  retyped: 'blue',
  relagged: 'blue',
};

export function ScheduleComparePanel({
  scheduleId,
  projectId,
  currency,
  activitiesById,
}: ScheduleComparePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [baseId, setBaseId] = useState<string>('');
  const [targetId, setTargetId] = useState<string>(LIVE);
  const [result, setResult] = useState<ScheduleDiff | null>(null);

  const baselinesQ = useQuery<ScheduleBaseline[]>({
    queryKey: ['schedule', 'baselines', projectId],
    queryFn: () => scheduleApi.listBaselines(projectId),
    enabled: !!projectId,
  });

  const baselines = baselinesQ.data ?? [];

  // Default the base to the first baseline once they load. The select's value
  // is derived (``effectiveBaseId``) so it shows a sensible default even before
  // this effect has run, but we still sync state so edits behave normally.
  useEffect(() => {
    if (!baseId && baselines.length > 0) {
      setBaseId(baselines[0]!.id);
    }
  }, [baseId, baselines]);

  // The base id actually used for the diff: the chosen one, or - when the user
  // has not touched the picker yet - the first baseline. This makes "Compare"
  // work on first paint without waiting for the default-sync effect to settle.
  const effectiveBaseId = baseId || (baselines[0]?.id ?? '');

  const nameFor = useMemo(
    () => (id: string) => activitiesById?.[id] ?? id,
    [activitiesById],
  );

  const runMut = useMutation({
    mutationFn: () =>
      scheduleApi.diffSchedule(scheduleId, {
        base_baseline_id: effectiveBaseId,
        ...(targetId !== LIVE ? { target_baseline_id: targetId } : {}),
      }),
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('schedule.compare.run_done', { defaultValue: 'Comparison ready' }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  // Target options exclude whichever baseline is selected as base.
  const targetBaselines = baselines.filter((b) => b.id !== effectiveBaseId);

  if (baselinesQ.isLoading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={3} columns={3} />
      </Card>
    );
  }

  if (baselinesQ.isError) {
    return (
      <Card padding="md">
        <RecoveryCard error={baselinesQ.error} onRetry={() => baselinesQ.refetch()} />
      </Card>
    );
  }

  if (baselines.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<GitCompare size={24} strokeWidth={1.5} />}
          title={t('schedule.compare.no_baselines', { defaultValue: 'No baselines to compare' })}
          description={t('schedule.compare.no_baselines_desc', {
            defaultValue:
              'Capture a baseline of this schedule first. A baseline freezes the activity set and logic so you can compare it against the live schedule or a later baseline and see exactly what changed.',
          })}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="schedule-compare-panel">
      {/* ── Pickers ───────────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center gap-2">
          <GitCompare size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.compare.title', { defaultValue: 'Compare schedules' })}
          </h3>
        </div>
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto]">
          <div>
            <label htmlFor="cmp-base" className={labelCls}>
              {t('schedule.compare.base', { defaultValue: 'Base (from)' })}
            </label>
            <select
              id="cmp-base"
              value={effectiveBaseId}
              onChange={(e) => {
                setBaseId(e.target.value);
                // If target collided with the new base, fall back to live.
                if (e.target.value === targetId) setTargetId(LIVE);
              }}
              className={selectCls}
            >
              {baselines.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          <div className="hidden items-center justify-center pb-2 text-content-tertiary sm:flex">
            <ArrowRight size={18} />
          </div>
          <div>
            <label htmlFor="cmp-target" className={labelCls}>
              {t('schedule.compare.target', { defaultValue: 'Target (to)' })}
            </label>
            <select
              id="cmp-target"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              className={selectCls}
            >
              <option value={LIVE}>
                {t('schedule.compare.live', { defaultValue: 'Live schedule (current)' })}
              </option>
              {targetBaselines.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="primary"
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !effectiveBaseId}
            icon={
              runMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <GitCompare size={16} />
              )
            }
          >
            {runMut.isPending
              ? t('schedule.compare.running', { defaultValue: 'Comparing...' })
              : t('schedule.compare.run', { defaultValue: 'Compare' })}
          </Button>
        </div>
      </Card>

      {/* ── Empty state ───────────────────────────────────────────── */}
      {!result && !runMut.isPending && (
        <Card padding="md">
          <EmptyState
            icon={<GitCompare size={28} strokeWidth={1.5} />}
            title={t('schedule.compare.empty', { defaultValue: 'No comparison run yet' })}
            description={t('schedule.compare.empty_desc', {
              defaultValue:
                'Pick a base baseline and a target, then run the comparison to see the net finish movement, critical-path changes, cost deltas and every added, removed or modified activity, relationship and calendar.',
            })}
          />
        </Card>
      )}

      {result && (
        <>
          <DiffSummaryCard diff={result} currency={currency} />

          <ActivityChangesCard changes={result.activities} nameFor={nameFor} />

          <RelationshipChangesCard changes={result.relationships} nameFor={nameFor} />

          {result.calendars.length > 0 && (
            <Card padding="none">
              <SectionHead
                title={t('schedule.compare.calendars', { defaultValue: 'Calendar changes' })}
                count={result.calendars.length}
              />
              <ul className="divide-y divide-border-light">
                {result.calendars.map((c) => (
                  <li key={`${c.key}-${c.change_type}`} className="flex items-center gap-2 px-4 py-2.5 text-sm">
                    <Badge variant={CHANGE_BADGE[c.change_type] ?? 'neutral'}>
                      {changeTypeLabel(t, c.change_type)}
                    </Badge>
                    <span className="text-content-primary">{c.key}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

/* ── Summary card ────────────────────────────────────────────────────── */

function DiffSummaryCard({ diff, currency }: { diff: ScheduleDiff; currency?: string }) {
  const { t } = useTranslation();
  const s = diff.summary;
  const net = s.net_finish_movement_days;
  const costPlanned = toNum(s.cost_planned_delta);
  const costActual = toNum(s.cost_actual_delta);

  return (
    <Card padding="md">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <TrendingUp size={16} className="text-content-secondary" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('schedule.compare.summary', { defaultValue: 'Summary' })}
        </h3>
        <span className="flex items-center gap-1.5 text-xs text-content-tertiary">
          <span className="rounded bg-surface-secondary px-1.5 py-0.5">{diff.base_label}</span>
          <ArrowRight size={12} />
          <span className="rounded bg-surface-secondary px-1.5 py-0.5">{diff.target_label}</span>
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <SummaryStat
          label={t('schedule.compare.net_finish', { defaultValue: 'Net finish movement' })}
          value={`${net > 0 ? '+' : ''}${net}d`}
          tone={net > 0 ? 'error' : net < 0 ? 'success' : 'neutral'}
        />
        <SummaryStat
          label={t('schedule.compare.cp_in', { defaultValue: 'Onto critical path' })}
          value={String(s.critical_path_in)}
          tone={s.critical_path_in > 0 ? 'warning' : 'neutral'}
        />
        <SummaryStat
          label={t('schedule.compare.cp_out', { defaultValue: 'Off critical path' })}
          value={String(s.critical_path_out)}
          tone={s.critical_path_out > 0 ? 'success' : 'neutral'}
        />
        <SummaryStat
          label={t('schedule.compare.act_changed', { defaultValue: 'Activities changed' })}
          value={String(s.activities_added + s.activities_removed + s.activities_changed)}
          tone="neutral"
        />
        <SummaryStat
          label={t('schedule.compare.cost_planned', { defaultValue: 'Planned cost delta' })}
          value={signedMoney(costPlanned, currency)}
          tone={costPlanned > 0 ? 'error' : costPlanned < 0 ? 'success' : 'neutral'}
        />
        <SummaryStat
          label={t('schedule.compare.cost_actual', { defaultValue: 'Actual cost delta' })}
          value={signedMoney(costActual, currency)}
          tone={costActual > 0 ? 'error' : costActual < 0 ? 'success' : 'neutral'}
        />
      </div>

      {/* Change counts by sub-type */}
      <div className="mt-3 flex flex-wrap gap-2">
        <CountPill label={t('schedule.compare.added', { defaultValue: 'Added' })} value={s.activities_added} tone="success" />
        <CountPill label={t('schedule.compare.removed', { defaultValue: 'Removed' })} value={s.activities_removed} tone="error" />
        <CountPill label={t('schedule.compare.modified', { defaultValue: 'Modified' })} value={s.activities_changed} tone="warning" />
        <CountPill label={t('schedule.compare.rel_added', { defaultValue: 'Links added' })} value={s.relationships_added} tone="success" />
        <CountPill label={t('schedule.compare.rel_removed', { defaultValue: 'Links removed' })} value={s.relationships_removed} tone="error" />
        <CountPill label={t('schedule.compare.rel_retyped', { defaultValue: 'Links retyped' })} value={s.relationships_retyped} tone="blue" />
        <CountPill label={t('schedule.compare.rel_relagged', { defaultValue: 'Links re-lagged' })} value={s.relationships_relagged} tone="blue" />
      </div>

      {/* Largest slips, if the engine surfaced any */}
      {s.largest_slips.length > 0 && (
        <div className="mt-4 border-t border-border-light pt-3">
          <div className="mb-2 text-2xs uppercase tracking-wide text-content-tertiary">
            {t('schedule.compare.largest_slips', { defaultValue: 'Largest slips' })}
          </div>
          <ul className="space-y-1">
            {s.largest_slips.slice(0, 5).map((row, i) => {
              const name = (row.name as string) || (row.key as string) || `#${i + 1}`;
              const move = Number(row.finish_movement_days ?? 0);
              return (
                <li key={i} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate text-content-secondary" title={name}>
                    {name}
                  </span>
                  <span
                    className={
                      'shrink-0 font-mono tabular-nums ' +
                      (move > 0 ? 'text-semantic-error' : move < 0 ? 'text-semantic-success' : 'text-content-tertiary')
                    }
                  >
                    {move > 0 ? '+' : ''}
                    {move}d
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}

/* ── Activity changes ────────────────────────────────────────────────── */

function ActivityChangesCard({
  changes,
  nameFor,
}: {
  changes: DiffActivityChange[];
  nameFor: (id: string) => string;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="none">
      <SectionHead
        title={t('schedule.compare.activities', { defaultValue: 'Activity changes' })}
        count={changes.length}
      />
      {changes.length === 0 ? (
        <div className="px-4 py-6 text-sm text-content-tertiary">
          {t('schedule.compare.no_activity_changes', {
            defaultValue: 'No activity changes between these snapshots.',
          })}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
              <tr>
                <th className="px-4 py-2 text-left">{t('schedule.compare.change', { defaultValue: 'Change' })}</th>
                <th className="px-4 py-2 text-left">{t('schedule.compare.activity', { defaultValue: 'Activity' })}</th>
                <th className="px-4 py-2 text-left">{t('schedule.compare.fields', { defaultValue: 'Fields' })}</th>
                <th className="px-4 py-2 text-right">{t('schedule.compare.finish_move', { defaultValue: 'Finish move' })}</th>
                <th className="px-4 py-2 text-center">{t('schedule.compare.cp', { defaultValue: 'CP' })}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => {
                const move = c.finish_movement_days;
                const fieldNames = Object.keys(c.fields ?? {});
                return (
                  <tr key={`${c.key}-${c.change_type}`} className="border-t border-border-light align-top">
                    <td className="px-4 py-2">
                      <Badge variant={CHANGE_BADGE[c.change_type] ?? 'neutral'}>
                        {changeTypeLabel(t, c.change_type)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <span className="block max-w-xs truncate font-medium text-content-primary" title={c.key}>
                        {c.name || nameFor(c.key)}
                      </span>
                      {c.wbs_code && (
                        <span className="text-2xs text-content-tertiary">{c.wbs_code}</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {fieldNames.length === 0 ? (
                        <span className="text-content-tertiary">-</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {fieldNames.map((f) => (
                            <span
                              key={f}
                              className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary"
                            >
                              {f}
                            </span>
                          ))}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {move === 0 ? (
                        <span className="text-content-tertiary">-</span>
                      ) : (
                        <span
                          className={
                            'inline-flex items-center gap-1 font-mono tabular-nums ' +
                            (move > 0 ? 'text-semantic-error' : 'text-semantic-success')
                          }
                        >
                          {move > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                          {move > 0 ? '+' : ''}
                          {move}d
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-center">
                      {c.critical_path ? (
                        <Badge variant="warning">{t('schedule.compare.cp', { defaultValue: 'CP' })}</Badge>
                      ) : (
                        <span className="text-content-tertiary">-</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* ── Relationship changes ────────────────────────────────────────────── */

function RelationshipChangesCard({
  changes,
  nameFor,
}: {
  changes: DiffRelationshipChange[];
  nameFor: (id: string) => string;
}) {
  const { t } = useTranslation();
  if (changes.length === 0) return null;
  return (
    <Card padding="none">
      <SectionHead
        title={t('schedule.compare.relationships', { defaultValue: 'Relationship changes' })}
        count={changes.length}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
            <tr>
              <th className="px-4 py-2 text-left">{t('schedule.compare.change', { defaultValue: 'Change' })}</th>
              <th className="px-4 py-2 text-left">{t('schedule.compare.link', { defaultValue: 'Link (pred -> succ)' })}</th>
              <th className="px-4 py-2 text-left">{t('schedule.compare.fields', { defaultValue: 'Fields' })}</th>
            </tr>
          </thead>
          <tbody>
            {changes.map((c, i) => {
              const pred = c.key[0] ?? '';
              const succ = c.key[1] ?? '';
              const fieldNames = Object.keys(c.fields ?? {});
              return (
                <tr key={`${pred}-${succ}-${c.change_type}-${i}`} className="border-t border-border-light align-top">
                  <td className="px-4 py-2">
                    <Badge variant={CHANGE_BADGE[c.change_type] ?? 'neutral'}>
                      {changeTypeLabel(t, c.change_type)}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <span className="flex items-center gap-1.5">
                      <span className="max-w-[10rem] truncate" title={pred}>{nameFor(pred)}</span>
                      <ArrowRight size={12} className="shrink-0 text-content-tertiary" />
                      <span className="max-w-[10rem] truncate" title={succ}>{nameFor(succ)}</span>
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    {fieldNames.length === 0 ? (
                      <span className="text-content-tertiary">-</span>
                    ) : (
                      <span className="flex flex-wrap gap-1">
                        {fieldNames.map((f) => (
                          <span
                            key={f}
                            className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs text-content-secondary"
                          >
                            {f}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ── small helpers ───────────────────────────────────────────────────── */

function SectionHead({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
      <h3 className="text-sm font-semibold text-content-primary">{title}</h3>
      <Badge variant="neutral">{count}</Badge>
    </div>
  );
}

function changeTypeLabel(
  t: (k: string, o?: Record<string, unknown>) => string,
  raw: string,
): string {
  const map: Record<string, string> = {
    added: 'Added',
    removed: 'Removed',
    modified: 'Modified',
    retyped: 'Retyped',
    relagged: 'Re-lagged',
  };
  return t(`schedule.compare.change_${raw}`, { defaultValue: map[raw] ?? raw });
}

function signedMoney(n: number, currency?: string): string {
  const formatted = formatCurrency(Math.abs(n), currency, undefined, {
    maximumFractionDigits: 0,
    minimumFractionDigits: 0,
  });
  if (n > 0) return `+${formatted}`;
  if (n < 0) return `-${formatted}`;
  return formatted;
}

type StatTone = 'neutral' | 'success' | 'warning' | 'error';

function SummaryStat({ label, value, tone }: { label: string; value: string; tone: StatTone }) {
  const toneCls: Record<StatTone, string> = {
    neutral: 'text-content-primary',
    success: 'text-semantic-success',
    warning: 'text-semantic-warning',
    error: 'text-semantic-error',
  };
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary" title={label}>
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-bold tabular-nums ${toneCls[tone]}`}>{value}</div>
    </div>
  );
}

type CountTone = 'success' | 'error' | 'warning' | 'blue';

function CountPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: CountTone;
}) {
  if (value === 0) return null;
  const Icon =
    tone === 'success'
      ? PlusCircle
      : tone === 'error'
        ? MinusCircle
        : PencilLine;
  const toneCls: Record<CountTone, string> = {
    success: 'text-semantic-success',
    error: 'text-semantic-error',
    warning: 'text-semantic-warning',
    blue: 'text-oe-blue',
  };
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-secondary/40 px-2.5 py-1 text-xs">
      <Icon size={12} className={toneCls[tone]} />
      <span className="text-content-secondary">{label}</span>
      <span className="font-mono font-semibold tabular-nums text-content-primary">{value}</span>
    </span>
  );
}

export default ScheduleComparePanel;
