import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  User,
  Users,
  Truck,
  Building2,
  AlertTriangle,
  Scale,
  Move,
  Split,
  HelpCircle,
  Check,
  ExternalLink,
  CalendarDays,
  ArrowUpRight,
} from 'lucide-react';

import {
  Card,
  CardContent,
  Badge,
  EmptyState,
  Skeleton,
  SideDrawer,
  Breadcrumb,
  DismissibleInfo,
  IntroRichText,
  ConfirmDialog,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { PlanningCrossLinks } from '@/features/schedule/PlanningCrossLinks';
import { useToastStore } from '@/stores/useToastStore';
import { apiPatch, getErrorMessage } from '@/shared/lib/api';
import {
  portfolioApi,
  type LevelingBooking,
  type LevelingCell,
  type LevelingResourceRow,
  type LevelingSuggestion,
} from './api';

/**
 * Map a leveling suggestion to the assignment PATCH body that applies it.
 *
 * The backend leveling engine only proposes two deterministic actions:
 *
 *   - "spread": reduce the largest contributing booking to
 *     ``suggested_allocation_percent`` so the over-allocated bucket fits the
 *     resource's declared capacity. This is fully defined by the payload, so we
 *     can apply it with a single PATCH on ``allocation_percent`` against the
 *     existing /v1/resources/assignments/{id} endpoint.
 *   - "shift": move a booking to another period. The engine does NOT compute a
 *     target period (it would be fabricated data), so there is nothing safe to
 *     PATCH. We return null and the UI offers a "Review booking" deep link
 *     instead, leaving the reschedule to a human.
 *
 * Returns null when the suggestion is not safely auto-appliable.
 */
export function buildApplyPatch(
  suggestion: LevelingSuggestion,
): { allocation_percent: number } | null {
  if (suggestion.action !== 'spread') return null;
  const pct = suggestion.suggested_allocation_percent;
  if (typeof pct !== 'number' || pct < 0 || pct > 100) return null;
  return { allocation_percent: pct };
}

/** Bucket horizon presets: how many buckets to show per bucket size. */
const HORIZON: Record<'week' | 'month', number> = { week: 12, month: 6 };

function rangeFor(bucket: 'week' | 'month'): { start: string; end: string } {
  // Anchor on today at midnight UTC and extend forward by the horizon.
  const now = new Date();
  const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const days = bucket === 'month' ? HORIZON.month * 30 : HORIZON.week * 7;
  const end = new Date(start.getTime() + days * 24 * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

const TYPE_ICON: Record<string, typeof User> = {
  person: User,
  crew: Users,
  equipment: Truck,
  subcontractor: Building2,
};

/**
 * Map a leveling cell to a heatmap colour. The grid is capacity-aware:
 * "capacity unknown" is rendered neutral (NOT red) because we never fabricate
 * a ceiling; over-allocation (known capacity exceeded) is red.
 */
export function cellClasses(cell: LevelingCell | undefined): string {
  if (!cell || cell.allocation_percent <= 0) {
    return 'bg-surface-secondary/40 text-content-tertiary';
  }
  if (cell.capacity_unknown) {
    // Allocation present but no capacity declared: slate/neutral, never a
    // false "overload" colour.
    return 'bg-slate-300/50 text-slate-800 dark:bg-slate-600/40 dark:text-slate-100';
  }
  if (cell.over_allocated) {
    return 'bg-rose-500/90 text-white font-semibold';
  }
  const cap = cell.capacity_percent ?? 100;
  const ratio = cap > 0 ? cell.allocation_percent / cap : 1;
  if (ratio > 0.8) return 'bg-amber-400/80 text-amber-950';
  if (ratio > 0.5) return 'bg-emerald-500/70 text-emerald-950';
  return 'bg-emerald-300/50 text-emerald-900';
}

interface DrawerState {
  row: LevelingResourceRow;
}

export function ResourceLevelingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useToastStore((s) => s.addToast);
  const [bucket, setBucket] = useState<'week' | 'month'>('week');
  const [drawer, setDrawer] = useState<DrawerState | null>(null);
  // Suggestion pending human confirmation before its assignment PATCH fires.
  const [pendingApply, setPendingApply] = useState<LevelingSuggestion | null>(null);
  const range = useMemo(() => rangeFor(bucket), [bucket]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio', 'leveling', range.start, range.end, bucket],
    queryFn: () => portfolioApi.getLeveling({ start: range.start, end: range.end, bucket }),
    retry: false,
  });

  // CONN-35: apply a leveling suggestion. Human-confirmed (ConfirmDialog), the
  // only mutation maps "spread" to a single allocation_percent PATCH on the
  // existing assignment endpoint; "shift" is never auto-applied (no fabricated
  // target period). On success we invalidate so the heatmap recomputes.
  const applyMutation = useMutation({
    mutationFn: (suggestion: LevelingSuggestion) => {
      const patch = buildApplyPatch(suggestion);
      if (!patch) {
        return Promise.reject(
          new Error(
            t('leveling.apply_not_supported', {
              defaultValue: 'This suggestion cannot be applied automatically.',
            }),
          ),
        );
      }
      return apiPatch(`/v1/resources/assignments/${suggestion.target_assignment_id}`, patch);
    },
    onSuccess: () => {
      pushToast({
        type: 'success',
        title: t('leveling.apply_done', { defaultValue: 'Booking updated' }),
        message: t('leveling.apply_done_desc', {
          defaultValue: 'The allocation was reduced to fit capacity.',
        }),
      });
      setPendingApply(null);
      setDrawer(null);
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'leveling'] });
      queryClient.invalidateQueries({ queryKey: ['portfolio', 'capacity'] });
    },
    onError: (err) => {
      pushToast({
        type: 'error',
        title: t('leveling.apply_failed', { defaultValue: 'Could not apply suggestion' }),
        message: getErrorMessage(err),
      });
      setPendingApply(null);
    },
  });

  const buckets = data?.buckets ?? [];
  const resources = data?.resources ?? [];
  const gridCols = `minmax(190px, 1.4fr) repeat(${Math.max(buckets.length, 1)}, minmax(46px, 1fr))`;

  const cellByIndex = (row: LevelingResourceRow): Map<number, LevelingCell> => {
    const m = new Map<number, LevelingCell>();
    for (const c of row.cells) m.set(c.bucket_index, c);
    return m;
  };

  const bucketLabel = (index: number): string => {
    const b = buckets.find((x) => x.index === index);
    return b ? b.label : `#${index}`;
  };

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb — single-item trail auto-hides; module name + icon live
          in the global top app bar (canon §2). */}
      <Breadcrumb
        items={[{ label: t('nav.resource_leveling', { defaultValue: 'Resource Leveling' }) }]}
      />

      {/* CONN-37: planning section cross-links so the leveling tool sits in the
          same connected chain as Capacity, Schedule and the rest. */}
      <PlanningCrossLinks active="leveling" />

      {/* Canonical header row — no in-page H1; the bucket toggle is a view
          switch in the actions slot, on the same h-9 midline. */}
      <PageHeader
        srTitle={t('leveling.title', { defaultValue: 'Resource Leveling' })}
        subtitle={t('leveling.subtitle', {
          defaultValue:
            'Across every project, see where a crew or machine is booked beyond its capacity, and review suggestions for which booking to shift or spread. Nothing moves until you confirm it.',
        })}
        actions={
          <div className="inline-flex shrink-0 rounded-xl border border-border bg-surface-secondary/50 p-1">
            {(['week', 'month'] as const).map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBucket(b)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  bucket === b
                    ? 'bg-surface-primary text-content-primary shadow-sm'
                    : 'text-content-tertiary hover:text-content-secondary'
                }`}
              >
                {b === 'week'
                  ? t('leveling.by_week', { defaultValue: 'Weeks' })
                  : t('leveling.by_month', { defaultValue: 'Months' })}
              </button>
            ))}
          </div>
        }
      />

      <DismissibleInfo
        storageKey="leveling"
        title={t('leveling.intro_title', {
          defaultValue: 'Smooth out over-booked crews and machines',
        })}
        links={[
          {
            label: t('leveling.link_capacity', { defaultValue: 'Capacity Planning' }),
            onClick: () => navigate('/portfolio/capacity'),
          },
          {
            label: t('leveling.link_resources', { defaultValue: 'Resources & Crew' }),
            onClick: () => navigate('/resources'),
          },
          {
            label: t('leveling.link_schedule', { defaultValue: '4D Schedule' }),
            onClick: () => navigate('/schedule'),
          },
        ]}
        more={
          t('leveling.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('leveling.intro_more')} />
            : undefined
        }
      >
        {t('leveling.intro_body', {
          defaultValue:
            'See where a crew or machine is booked beyond its capacity across all projects, then review suggestions for which booking to shift or spread. Nothing moves until you confirm it.',
        })}
      </DismissibleInfo>

      {/* ── Summary chips ───────────────────────────────────────────────── */}
      {data && (
        <div className="flex flex-wrap gap-3">
          <SummaryChip
            label={t('leveling.summary_resources', { defaultValue: 'Resources booked' })}
            value={data.total_resources}
          />
          <SummaryChip
            label={t('leveling.summary_overloaded', { defaultValue: 'Over capacity' })}
            value={data.overloaded_resources}
            tone={data.overloaded_resources > 0 ? 'danger' : 'ok'}
          />
          <SummaryChip
            label={t('leveling.summary_unknown', { defaultValue: 'Capacity unknown' })}
            value={data.capacity_unknown_resources}
            tone={data.capacity_unknown_resources > 0 ? 'warn' : 'neutral'}
          />
          <SummaryChip
            label={t('leveling.summary_suggestions', { defaultValue: 'Suggestions' })}
            value={data.total_suggestions}
          />
        </div>
      )}

      {/* ── Heatmap ─────────────────────────────────────────────────────── */}
      <Card>
        <CardContent>
          {isLoading && (
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} height={36} className="w-full" rounded="lg" />
              ))}
            </div>
          )}

          {isError && (
            <EmptyState
              icon={<AlertTriangle size={36} className="text-semantic-error" />}
              title={t('leveling.error_title', { defaultValue: 'Could not load leveling' })}
              description={getErrorMessage(error)}
            />
          )}

          {data && !isLoading && resources.length === 0 && (
            <EmptyState
              icon={<Scale size={36} className="text-content-tertiary" />}
              title={t('leveling.empty_title', { defaultValue: 'No resource bookings yet' })}
              description={t('leveling.empty_desc', {
                defaultValue:
                  'Once resources are assigned to project activities, their cross-project load and any over-capacity periods will show up here.',
              })}
            />
          )}

          {data && !isLoading && resources.length > 0 && (
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                {/* Header row: bucket labels */}
                <div className="grid items-end gap-1 pb-2" style={{ gridTemplateColumns: gridCols }}>
                  <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('leveling.resource', { defaultValue: 'Resource' })}
                  </div>
                  {buckets.map((b) => (
                    <div
                      key={b.index}
                      className="text-center text-[11px] font-medium text-content-tertiary"
                      title={`${b.start.slice(0, 10)} → ${b.end.slice(0, 10)}`}
                    >
                      {b.label}
                    </div>
                  ))}
                </div>

                {/* Resource rows */}
                <div className="space-y-1">
                  {resources.map((row) => {
                    const cells = cellByIndex(row);
                    const Icon = TYPE_ICON[row.resource_type] ?? User;
                    return (
                      <div
                        key={row.resource_id}
                        className="grid items-center gap-1"
                        style={{ gridTemplateColumns: gridCols }}
                      >
                        {/* Resource label — opens the suggestion drawer */}
                        <button
                          type="button"
                          onClick={() => setDrawer({ row })}
                          className="flex min-w-0 items-center gap-2 rounded-md py-1 pr-2 text-left hover:bg-surface-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                          title={t('leveling.open_drawer', {
                            defaultValue: 'View bookings and leveling suggestions',
                          })}
                        >
                          <Icon size={15} className="shrink-0 text-content-tertiary" />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="truncate text-sm font-medium text-content-primary">
                                {row.name}
                              </span>
                              {row.capacity_unknown && (
                                <Badge variant="warning" size="sm" className="shrink-0">
                                  {t('leveling.capacity_unknown', { defaultValue: 'No capacity' })}
                                </Badge>
                              )}
                              {row.has_overload && (
                                <Badge variant="error" size="sm" className="shrink-0">
                                  {t('leveling.overloaded', { defaultValue: 'Over capacity' })}
                                </Badge>
                              )}
                            </div>
                            <span className="block truncate text-[11px] text-content-tertiary">
                              {row.code}
                              {row.capacity_percent != null
                                ? ` · ${t('leveling.cap', { defaultValue: 'cap' })} ${row.capacity_percent}%`
                                : ''}
                            </span>
                          </div>
                        </button>

                        {/* Bucket cells */}
                        {buckets.map((b) => {
                          const cell = cells.get(b.index);
                          const capTip =
                            cell && cell.capacity_percent != null
                              ? ` / ${cell.capacity_percent}%`
                              : cell?.capacity_unknown
                                ? ` (${t('leveling.no_cap_short', { defaultValue: 'no capacity set' })})`
                                : '';
                          const tip = cell
                            ? `${cell.allocation_percent}%${capTip}\n` +
                              cell.bookings
                                .map((bk) => `• ${bk.project_name}: ${bk.allocation_percent}%`)
                                .join('\n')
                            : t('leveling.no_booking', { defaultValue: 'No booking' });
                          return (
                            <div
                              key={b.index}
                              title={tip}
                              className={`relative flex h-9 items-center justify-center rounded-md text-[11px] tabular-nums ${cellClasses(
                                cell,
                              )} ${cell?.cross_project ? 'ring-2 ring-inset ring-rose-700' : ''}`}
                            >
                              {cell && cell.allocation_percent > 0 ? `${cell.allocation_percent}%` : ''}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Legend */}
          {data && !isLoading && resources.length > 0 && (
            <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border pt-4 text-xs text-content-tertiary">
              <LegendSwatch
                className="bg-emerald-300/50"
                label={t('leveling.legend_low', { defaultValue: '≤ 50% of capacity' })}
              />
              <LegendSwatch
                className="bg-emerald-500/70"
                label={t('leveling.legend_mid', { defaultValue: '51-80%' })}
              />
              <LegendSwatch
                className="bg-amber-400/80"
                label={t('leveling.legend_high', { defaultValue: '81-100%' })}
              />
              <LegendSwatch
                className="bg-rose-500/90"
                label={t('leveling.legend_over', { defaultValue: 'Over capacity' })}
              />
              <LegendSwatch
                className="bg-slate-300/50"
                label={t('leveling.legend_unknown', { defaultValue: 'Capacity unknown' })}
              />
              <span className="inline-flex items-center gap-1.5">
                <span className="h-3.5 w-3.5 rounded-md ring-2 ring-inset ring-rose-700" />
                {t('leveling.legend_cross', { defaultValue: 'Two or more projects compete' })}
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Suggestion drawer ───────────────────────────────────────────── */}
      <SideDrawer
        open={drawer !== null}
        onClose={() => setDrawer(null)}
        title={drawer ? drawer.row.name : ''}
        subtitle={
          drawer
            ? `${drawer.row.code}${
                drawer.row.capacity_percent != null
                  ? ` · ${t('leveling.cap', { defaultValue: 'cap' })} ${drawer.row.capacity_percent}%`
                  : ` · ${t('leveling.capacity_unknown', { defaultValue: 'No capacity' })}`
              }`
            : undefined
        }
        widthClass="max-w-md"
      >
        {drawer && (
          <div className="space-y-5 p-5">
            {/* Capacity-unknown notice */}
            {drawer.row.capacity_unknown && (
              <div className="flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50/60 p-3 text-xs text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
                <HelpCircle size={15} className="mt-0.5 shrink-0" />
                <span>
                  {t('leveling.unknown_notice', {
                    defaultValue:
                      'This resource has no capacity set, so over-allocation cannot be detected. Set a capacity on the resource to enable leveling.',
                  })}
                </span>
              </div>
            )}

            {/* Suggestions */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-content-primary">
                {t('leveling.suggestions_heading', { defaultValue: 'Leveling suggestions' })}
              </h3>
              {drawer.row.suggestions.length === 0 ? (
                <p className="text-sm text-content-tertiary">
                  {drawer.row.capacity_unknown
                    ? t('leveling.no_suggestions_unknown', {
                        defaultValue: 'No suggestions - capacity is unknown.',
                      })
                    : t('leveling.no_suggestions', {
                        defaultValue: 'No over-capacity periods in this window.',
                      })}
                </p>
              ) : (
                <ul className="space-y-2">
                  {drawer.row.suggestions.map((s, i) => (
                    <SuggestionItem
                      key={`${s.target_assignment_id}-${s.bucket_index}-${i}`}
                      suggestion={s}
                      bucketLabel={bucketLabel(s.bucket_index)}
                      onApply={() => setPendingApply(s)}
                      applying={
                        applyMutation.isPending &&
                        pendingApply?.target_assignment_id === s.target_assignment_id &&
                        pendingApply?.bucket_index === s.bucket_index
                      }
                      onOpenProject={
                        s.target_project_id
                          ? () => navigate(`/projects/${s.target_project_id}`)
                          : undefined
                      }
                      onOpenSchedule={
                        s.target_project_id
                          ? () => navigate(`/schedule?project_id=${s.target_project_id}`)
                          : undefined
                      }
                    />
                  ))}
                </ul>
              )}
            </div>

            {/* Per-bucket booking breakdown */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-content-primary">
                {t('leveling.bookings_heading', { defaultValue: 'Bookings by period' })}
              </h3>
              <ul className="space-y-2">
                {drawer.row.cells.map((cell) => (
                  <li
                    key={cell.bucket_index}
                    className="rounded-lg border border-border-light p-3 text-xs"
                  >
                    <div className="mb-1 flex items-center justify-between">
                      <span className="font-medium text-content-secondary">
                        {bucketLabel(cell.bucket_index)}
                      </span>
                      <span
                        className={`tabular-nums font-semibold ${
                          cell.over_allocated ? 'text-rose-600 dark:text-rose-400' : 'text-content-primary'
                        }`}
                      >
                        {cell.allocation_percent}%
                        {cell.capacity_percent != null ? ` / ${cell.capacity_percent}%` : ''}
                      </span>
                    </div>
                    <ul className="space-y-0.5">
                      {cell.bookings.map((bk) => (
                        <BookingRow
                          key={bk.assignment_id}
                          booking={bk}
                          onOpenProject={
                            bk.project_id ? () => navigate(`/projects/${bk.project_id}`) : undefined
                          }
                        />
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </SideDrawer>

      {/* CONN-35: confirm before mutating a real assignment. */}
      <ConfirmDialog
        open={pendingApply !== null}
        variant="warning"
        title={t('leveling.apply_confirm_title', { defaultValue: 'Apply this suggestion?' })}
        message={
          pendingApply
            ? t('leveling.apply_confirm_msg', {
                defaultValue:
                  'This reduces the booking on {{project}} to {{pct}}% so the period fits capacity. You can change it back at any time.',
                project: pendingApply.target_project_name,
                pct: pendingApply.suggested_allocation_percent,
              })
            : ''
        }
        confirmLabel={t('leveling.apply', { defaultValue: 'Apply' })}
        loading={applyMutation.isPending}
        onCancel={() => setPendingApply(null)}
        onConfirm={() => {
          if (pendingApply) applyMutation.mutate(pendingApply);
        }}
      />
    </div>
  );
}

function BookingRow({
  booking,
  onOpenProject,
}: {
  booking: LevelingBooking;
  onOpenProject?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="flex items-center justify-between text-content-tertiary">
      {onOpenProject ? (
        <button
          type="button"
          onClick={onOpenProject}
          title={t('leveling.open_project', { defaultValue: 'Open project' })}
          className="group inline-flex min-w-0 items-center gap-1 truncate text-left text-oe-blue-text hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue rounded"
        >
          <span className="truncate">{booking.project_name}</span>
          <ArrowUpRight size={11} className="shrink-0 opacity-60 group-hover:opacity-100" />
        </button>
      ) : (
        <span className="truncate">{booking.project_name}</span>
      )}
      <span className="tabular-nums">{booking.allocation_percent}%</span>
    </li>
  );
}

function SuggestionItem({
  suggestion,
  bucketLabel,
  onApply,
  applying,
  onOpenProject,
  onOpenSchedule,
}: {
  suggestion: LevelingSuggestion;
  bucketLabel: string;
  onApply: () => void;
  applying: boolean;
  onOpenProject?: () => void;
  onOpenSchedule?: () => void;
}) {
  const { t } = useTranslation();
  const isShift = suggestion.action === 'shift';
  const ActionIcon = isShift ? Move : Split;
  // Only "spread" maps to a deterministic assignment PATCH (see buildApplyPatch).
  const canApply = buildApplyPatch(suggestion) !== null;
  return (
    <li className="rounded-lg border border-rose-200/70 bg-rose-50/50 p-3 dark:border-rose-500/30 dark:bg-rose-500/10">
      <div className="flex items-center gap-2">
        <ActionIcon size={14} className="shrink-0 text-rose-600 dark:text-rose-400" />
        <span className="text-xs font-semibold uppercase tracking-wide text-rose-700 dark:text-rose-300">
          {isShift
            ? t('leveling.action_shift', { defaultValue: 'Shift' })
            : t('leveling.action_spread', { defaultValue: 'Spread' })}
        </span>
        <Badge variant="neutral" size="sm" className="ml-auto">
          {bucketLabel}
        </Badge>
      </div>
      <p className="mt-1.5 text-xs text-content-secondary">{suggestion.rationale}</p>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-content-tertiary">
        <span>
          {t('leveling.target_project', { defaultValue: 'Project' })}:{' '}
          {onOpenProject ? (
            <button
              type="button"
              onClick={onOpenProject}
              className="inline-flex items-center gap-0.5 text-oe-blue-text hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue rounded"
              title={t('leveling.open_project', { defaultValue: 'Open project' })}
            >
              {suggestion.target_project_name}
              <ArrowUpRight size={10} className="shrink-0 opacity-70" />
            </button>
          ) : (
            suggestion.target_project_name
          )}
        </span>
        <span>
          {t('leveling.overflow', { defaultValue: 'Over by' })} {suggestion.overflow_percent}%
        </span>
        {!isShift && (
          <span>
            {t('leveling.suggested_alloc', { defaultValue: 'Suggested' })}:{' '}
            {suggestion.suggested_allocation_percent}%
          </span>
        )}
      </div>

      {/* CONN-35 / CONN-36: apply control + deep links. "spread" can be applied
          in place; "shift" has no computed target period, so we route the
          planner to the booking instead of fabricating a date. */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2">
        {canApply ? (
          <button
            type="button"
            onClick={onApply}
            disabled={applying}
            className="inline-flex items-center gap-1.5 rounded-lg bg-oe-blue px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1 disabled:opacity-50"
          >
            <Check size={12} />
            {t('leveling.apply', { defaultValue: 'Apply' })}
          </button>
        ) : (
          onOpenSchedule && (
            <button
              type="button"
              onClick={onOpenSchedule}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface-primary px-2.5 py-1 text-[11px] font-medium text-content-secondary transition-colors hover:border-oe-blue/40 hover:text-oe-blue-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
            >
              <CalendarDays size={12} />
              {t('leveling.review_booking', { defaultValue: 'Review in 4D Schedule' })}
            </button>
          )
        )}
        {canApply && onOpenSchedule && (
          <button
            type="button"
            onClick={onOpenSchedule}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-oe-blue-text hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue rounded"
            title={t('leveling.view_in_schedule', { defaultValue: 'View in 4D Schedule' })}
          >
            <ExternalLink size={11} />
            {t('leveling.view_in_schedule', { defaultValue: 'View in 4D Schedule' })}
          </button>
        )}
      </div>
    </li>
  );
}

function SummaryChip({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  tone?: 'neutral' | 'ok' | 'danger' | 'warn';
}) {
  const toneClass =
    tone === 'danger'
      ? 'text-rose-600 dark:text-rose-400'
      : tone === 'ok'
        ? 'text-emerald-600 dark:text-emerald-400'
        : tone === 'warn'
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-content-primary';
  return (
    <div className="rounded-xl border border-border bg-surface-primary px-4 py-2.5">
      <div className={`text-xl font-bold tabular-nums ${toneClass}`}>{value}</div>
      <div className="text-xs text-content-tertiary">{label}</div>
    </div>
  );
}

function LegendSwatch({ className, label }: { className: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-3.5 w-3.5 rounded-md ${className}`} />
      {label}
    </span>
  );
}

export default ResourceLevelingPage;
