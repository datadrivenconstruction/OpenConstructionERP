import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { User, Users, Truck, Building2, AlertTriangle, CalendarRange, Scale } from 'lucide-react';

import {
  Button,
  Card,
  CardContent,
  Badge,
  EmptyState,
  Skeleton,
  Breadcrumb,
  DismissibleInfo,
  IntroRichText,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { getErrorMessage } from '@/shared/lib/api';
import {
  portfolioApi,
  type PortfolioCell,
  type PortfolioResourceRow,
} from './api';

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

/** Map an allocation percentage to a heatmap cell colour. */
function cellClasses(cell: PortfolioCell | undefined): string {
  if (!cell || cell.allocation_percent <= 0) {
    return 'bg-surface-secondary/40 text-content-tertiary';
  }
  const a = cell.allocation_percent;
  if (cell.over_allocated) {
    return 'bg-rose-500/90 text-white font-semibold';
  }
  if (a > 80) return 'bg-amber-400/80 text-amber-950';
  if (a > 50) return 'bg-emerald-500/70 text-emerald-950';
  return 'bg-emerald-300/50 text-emerald-900';
}

export function CapacityPlanningPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [bucket, setBucket] = useState<'week' | 'month'>('week');
  const range = useMemo(() => rangeFor(bucket), [bucket]);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio', 'capacity', range.start, range.end, bucket],
    queryFn: () => portfolioApi.getCapacity({ start: range.start, end: range.end, bucket }),
    retry: false,
  });

  const buckets = data?.buckets ?? [];
  const resources = data?.resources ?? [];
  const gridCols = `minmax(180px, 1.4fr) repeat(${Math.max(buckets.length, 1)}, minmax(44px, 1fr))`;

  const cellByIndex = (row: PortfolioResourceRow): Map<number, PortfolioCell> => {
    const m = new Map<number, PortfolioCell>();
    for (const c of row.cells) m.set(c.bucket_index, c);
    return m;
  };

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb — single-item trail auto-hides; module name + icon live
          in the global top app bar (canon §2). */}
      <Breadcrumb
        items={[{ label: t('nav.capacity_planning', { defaultValue: 'Capacity Planning' }) }]}
      />

      {/* Canonical header row — no in-page H1; the bucket toggle is a view
          switch in the actions slot, on the same h-9 midline. */}
      <PageHeader
        srTitle={t('capacity.title', { defaultValue: 'Capacity Planning' })}
        subtitle={t('capacity.subtitle', {
          defaultValue:
            'See how your people, crews and equipment are booked across every project, and spot where two projects are competing for the same resource.',
        })}
        actions={
          <>
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
                    ? t('capacity.by_week', { defaultValue: 'Weeks' })
                    : t('capacity.by_month', { defaultValue: 'Months' })}
                </button>
              ))}
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<Scale size={14} />}
              onClick={() => navigate('/portfolio/leveling')}
            >
              {t('capacity.open_leveling', { defaultValue: 'Open Resource Leveling' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="capacity"
        title={t('capacity.intro_title', {
          defaultValue: 'Spot resource conflicts across every project',
        })}
        more={
          t('capacity.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('capacity.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('capacity.intro_link_leveling', { defaultValue: 'Resource Leveling' }),
            onClick: () => navigate('/portfolio/leveling'),
          },
          {
            label: t('capacity.intro_link_resources', { defaultValue: 'Resources & Crew' }),
            onClick: () => navigate('/resources'),
          },
          {
            label: t('capacity.intro_link_schedule', { defaultValue: '4D Schedule' }),
            onClick: () => navigate('/schedule'),
          },
        ]}
      >
        {t('capacity.intro_body', {
          defaultValue:
            'This heatmap shows how your people, crews and equipment are booked across all projects so you can see where two projects are competing for the same resource before it becomes a delay.',
        })}
      </DismissibleInfo>

      {/* ── Summary chips ───────────────────────────────────────────────── */}
      {data && (
        <div className="flex flex-wrap gap-3">
          <SummaryChip
            label={t('capacity.summary_resources', { defaultValue: 'Resources booked' })}
            value={data.total_resources}
          />
          <SummaryChip
            label={t('capacity.summary_floating', { defaultValue: 'Shared (floating)' })}
            value={data.floating_resources}
          />
          <SummaryChip
            label={t('capacity.summary_conflicts', { defaultValue: 'Over-allocated' })}
            value={data.conflict_resources}
            tone={data.conflict_resources > 0 ? 'danger' : 'ok'}
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
              title={t('capacity.error_title', { defaultValue: 'Could not load capacity' })}
              description={getErrorMessage(error)}
            />
          )}

          {data && !isLoading && resources.length === 0 && (
            <EmptyState
              icon={<CalendarRange size={36} className="text-content-tertiary" />}
              title={t('capacity.empty_title', { defaultValue: 'No resource bookings yet' })}
              description={t('capacity.empty_desc', {
                defaultValue:
                  'Once resources are assigned to project activities, their utilization across all projects will show up here.',
              })}
            />
          )}

          {data && !isLoading && resources.length > 0 && (
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                {/* Header row: bucket labels */}
                <div
                  className="grid items-end gap-1 pb-2"
                  style={{ gridTemplateColumns: gridCols }}
                >
                  <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('capacity.resource', { defaultValue: 'Resource' })}
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
                        {/* Resource label — links to the resource detail in
                            Resources & Crew so a red over-allocated row can be
                            opened where its bookings are managed. */}
                        <div className="flex min-w-0 items-center gap-2 pr-2">
                          <Icon size={15} className="shrink-0 text-content-tertiary" />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() =>
                                  navigate(
                                    `/resources?resourceId=${encodeURIComponent(row.resource_id)}`,
                                  )
                                }
                                className="truncate rounded text-left text-sm font-medium text-content-primary hover:text-oe-blue hover:underline focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                                title={t('capacity.open_resource', {
                                  defaultValue: 'Open in Resources & Crew',
                                })}
                              >
                                {row.name}
                              </button>
                              {row.is_floating && (
                                <Badge variant="blue" size="sm" className="shrink-0">
                                  {t('capacity.floating', { defaultValue: 'Shared' })}
                                </Badge>
                              )}
                              {row.has_conflict && (
                                <Badge variant="error" size="sm" className="shrink-0">
                                  {t('capacity.conflict', { defaultValue: 'Conflict' })}
                                </Badge>
                              )}
                            </div>
                            <span className="block truncate text-[11px] text-content-tertiary">
                              {row.code}
                            </span>
                          </div>
                        </div>

                        {/* Bucket cells — an over-allocated cell becomes a
                            button that jumps to Resource Leveling, the tool
                            that resolves the clash, instead of dead-ending. */}
                        {buckets.map((b) => {
                          const cell = cells.get(b.index);
                          const tip = cell
                            ? `${cell.allocation_percent}%\n` +
                              cell.projects
                                .map((p) => `• ${p.project_name}: ${p.allocation_percent}%`)
                                .join('\n')
                            : t('capacity.no_booking', { defaultValue: 'No booking' });
                          const value =
                            cell && cell.allocation_percent > 0
                              ? `${cell.allocation_percent}%`
                              : '';
                          const cellCls = `relative flex h-9 items-center justify-center rounded-md text-[11px] tabular-nums ${cellClasses(
                            cell,
                          )} ${cell?.cross_project ? 'ring-2 ring-inset ring-rose-700' : ''}`;
                          if (cell?.over_allocated) {
                            return (
                              <button
                                key={b.index}
                                type="button"
                                title={`${tip}\n${t('capacity.resolve_in_leveling', {
                                  defaultValue: 'Resolve in Resource Leveling',
                                })}`}
                                onClick={() => navigate('/portfolio/leveling')}
                                className={`${cellCls} cursor-pointer hover:ring-2 hover:ring-inset hover:ring-rose-800 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-rose-800`}
                                aria-label={t('capacity.resolve_in_leveling', {
                                  defaultValue: 'Resolve in Resource Leveling',
                                })}
                              >
                                {value}
                              </button>
                            );
                          }
                          return (
                            <div key={b.index} title={tip} className={cellCls}>
                              {value}
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
              <LegendSwatch className="bg-emerald-300/50" label={t('capacity.legend_low', { defaultValue: '≤ 50%' })} />
              <LegendSwatch className="bg-emerald-500/70" label={t('capacity.legend_mid', { defaultValue: '51-80%' })} />
              <LegendSwatch className="bg-amber-400/80" label={t('capacity.legend_high', { defaultValue: '81-100%' })} />
              <LegendSwatch className="bg-rose-500/90" label={t('capacity.legend_over', { defaultValue: 'Over 100%' })} />
              <span className="inline-flex items-center gap-1.5">
                <span className="h-3.5 w-3.5 rounded-md ring-2 ring-inset ring-rose-700" />
                {t('capacity.legend_cross', { defaultValue: 'Two or more projects compete' })}
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryChip({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: number;
  tone?: 'neutral' | 'ok' | 'danger';
}) {
  const toneClass =
    tone === 'danger'
      ? 'text-rose-600 dark:text-rose-400'
      : tone === 'ok'
        ? 'text-emerald-600 dark:text-emerald-400'
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

export default CapacityPlanningPage;
