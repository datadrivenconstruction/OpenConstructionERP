// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
//
// Resource depth panel (T3.1). A self-contained view mode mounted in
// SchedulePage, modelled on the sibling schedule panels. Two in-panel tabs
// (local state), each over a different backend and id-space (see the derived
// contract in features/schedule-advanced/api.ts):
//
//   - Resource histogram: pick a resource from the tenant resources list and a
//     date window, then read its time-phased demand / availability / cost
//     histogram (GET /v1/resources/{resource_id}/histogram). Bucket demand is
//     drawn as CSS bars with an availability/capacity reference line; the peak
//     demand and over-allocated bucket count are surfaced. This is keyed by a
//     Resource *entity* id, not the schedule.
//
//   - Leveling: edit per-resource max-concurrent limits (keyed by the resource
//     *name* string carried on the schedule's activities), Preview a read-only
//     leveling run (base vs leveled finish, the shifted activities, per-resource
//     peak before/after, and any unresolvable single-activity overloads), then
//     Apply it to commit the shifted activity dates.
//
// Activity ids arrive as raw UUID strings; an optional ``activitiesById`` name
// map (the caller already holds the Gantt rows) renders readable labels.
//
// deferred (v1): authoring multi-rate rate rows, authoring per-assignment
// spreading curves, and saving named leveling scenarios. The rate/curve write
// endpoints exist on the backend but are out of scope for this first panel.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  BarChart3,
  Scale,
  Plus,
  Trash2,
  Loader2,
  Play,
  Check,
  AlertTriangle,
  Users,
  TrendingUp,
} from 'lucide-react';

import {
  Button,
  Card,
  Badge,
  EmptyState,
  RecoveryCard,
  SkeletonTable,
  SearchableSelect,
  type SearchableSelectOption,
} from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage, type Page } from '@/shared/lib/api';
import { compareNames } from '@/shared/lib/collator';
import {
  listResources,
  resourceHistogram,
  levelPreview,
  levelApply,
  type ResourceListItem,
  type ResourceHistogram,
  type HistogramBucket,
  type HistogramRateType,
  type LevelPreviewResult,
  type LevelApplyResult,
} from '@/features/schedule-advanced/api';

interface ScheduleResourcePanelProps {
  scheduleId: string;
  projectId: string;
  /** Optional id -> display name map so shifts show names, not UUIDs. */
  activitiesById?: Record<string, string>;
}

type TabKey = 'histogram' | 'leveling';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

const BUCKETS: HistogramBucket[] = ['week', 'month'];
const RATE_TYPES: HistogramRateType[] = ['cost', 'billing', 'overtime'];

/** Today and today + ~90 days as YYYY-MM-DD, the default histogram window. */
function defaultWindow(): { start: string; end: string } {
  const start = new Date();
  const end = new Date();
  end.setDate(end.getDate() + 90);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

export function ScheduleResourcePanel({
  scheduleId,
  projectId,
  activitiesById,
}: ScheduleResourcePanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [tab, setTab] = useState<TabKey>('histogram');

  const toastError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  const tabs: { key: TabKey; label: string; icon: typeof BarChart3 }[] = [
    {
      key: 'histogram',
      label: t('schedule.resources.tab_histogram', { defaultValue: 'Resource histogram' }),
      icon: BarChart3,
    },
    {
      key: 'leveling',
      label: t('schedule.resources.tab_leveling', { defaultValue: 'Leveling' }),
      icon: Scale,
    },
  ];

  return (
    <div className="space-y-4" data-testid="schedule-resource-panel">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2">
        <Users size={18} className="text-content-secondary" />
        <h3 className="text-base font-semibold text-content-primary">
          {t('schedule.resources.title', { defaultValue: 'Resource depth' })}
        </h3>
      </div>
      <p className="-mt-2 text-xs text-content-secondary">
        {t('schedule.resources.subtitle', {
          defaultValue:
            'See a resource time-phased demand against its availability and cost, then level the schedule to a set of per-resource limits and preview the honest finish-date impact before committing.',
        })}
      </p>

      {/* Tab switcher */}
      <div className="flex items-center gap-1 rounded-lg border border-border-light p-0.5">
        {tabs.map((tb) => {
          const Icon = tb.icon;
          const active = tab === tb.key;
          return (
            <button
              key={tb.key}
              type="button"
              aria-pressed={active}
              onClick={() => setTab(tb.key)}
              className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                active ? 'bg-oe-blue text-white' : 'text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              <Icon size={13} />
              {tb.label}
            </button>
          );
        })}
      </div>

      {tab === 'histogram' ? (
        <HistogramTab projectId={projectId} />
      ) : (
        <LevelingTab
          scheduleId={scheduleId}
          projectId={projectId}
          activitiesById={activitiesById}
          onError={toastError}
        />
      )}
    </div>
  );
}

/* ── Tab 1: Resource histogram ───────────────────────────────────────────── */

function HistogramTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  const win = useMemo(defaultWindow, []);
  const [resourceId, setResourceId] = useState<string>('');
  const [start, setStart] = useState(win.start);
  const [end, setEnd] = useState(win.end);
  const [bucket, setBucket] = useState<HistogramBucket>('week');
  const [rateType, setRateType] = useState<HistogramRateType>('cost');

  // Narrowed to the project the schedule belongs to: the crews homed here plus
  // the unhomed company pool. Tenant-wide, the picker listed every project's
  // roster and defaulted to whoever sorted first across all of them, so the
  // histogram opened on a resource that has never worked on this schedule.
  const resourcesQ = useQuery<Page<ResourceListItem>>({
    queryKey: ['schedule', 'resources', 'list', projectId],
    queryFn: () => listResources({ limit: 500, project_id: projectId }),
  });

  // Once the list loads, default the picker to the first resource so the
  // histogram has something to show without an extra click. Chained through
  // rather than guarded on the length, because reading the first element after
  // a length test asks the compiler to carry a narrowing across two separate
  // reads of a property on the query result, and an empty page then resolves
  // to '' either way.
  const resolvedResourceId = resourceId || (resourcesQ.data?.items?.[0]?.id ?? '');

  const datesValid = !!start && !!end && start < end;

  const histogramQ = useQuery<ResourceHistogram>({
    queryKey: ['schedule', 'resources', 'histogram', resolvedResourceId, start, end, bucket, rateType],
    queryFn: () =>
      resourceHistogram(resolvedResourceId, {
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        bucket,
        rate_type: rateType,
      }),
    enabled: !!resolvedResourceId && datesValid,
  });

  const histo = histogramQ.data;
  const maxBar = useMemo(() => {
    if (!histo) return 0;
    let m = histo.peak_demand;
    for (const c of histo.cells) {
      if (c.available != null && c.available > m) m = c.available;
    }
    return m > 0 ? m : 1;
  }, [histo]);

  // Grouped by kind and carrying the code, because the flat "Name (kind)" list
  // this replaces could not answer either half of the report behind it: there
  // was no way to type what you were after, and two resources with the same
  // name were two identical rows. The code is what tells those two apart, so it
  // is on the row and it is searchable.
  const resourceTypeLabel = (v: string): string =>
    ({
      person: t('resources.type_person', { defaultValue: 'Person' }),
      crew: t('resources.type_crew', { defaultValue: 'Crew' }),
      equipment: t('resources.type_equipment', { defaultValue: 'Equipment' }),
      subcontractor: t('resources.type_subcontractor', { defaultValue: 'Subcontractor' }),
    })[v] ?? v;

  const resourceOptions = useMemo<SearchableSelectOption[]>(() => {
    const list = resourcesQ.data?.items ?? [];
    const order: Record<string, number> = { crew: 0, person: 1, equipment: 2, subcontractor: 3 };
    return [...list]
      .sort((a, b) => {
        const byKind = (order[a.resource_type] ?? 9) - (order[b.resource_type] ?? 9);
        if (byKind !== 0) return byKind;
        return compareNames(a.name, b.name);
      })
      .map((r) => ({
        value: r.id,
        label: r.name,
        hint: r.code || undefined,
        group: resourceTypeLabel(r.resource_type),
        // Searchable but not drawn: someone who knows the raw kind can still
        // type "equipment" even though the row shows the translated heading.
        keywords: r.resource_type,
        meta:
          r.status && r.status !== 'active'
            ? t('resources.status_' + r.status, { defaultValue: r.status })
            : undefined,
      }));
    // resourceTypeLabel closes over t, which is stable per language change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourcesQ.data, t]);

  const bucketLabel = (b: HistogramBucket): string =>
    ({
      week: t('schedule.resources.bucket_week', { defaultValue: 'Weekly' }),
      month: t('schedule.resources.bucket_month', { defaultValue: 'Monthly' }),
    })[b];

  const rateLabel = (r: HistogramRateType): string =>
    ({
      cost: t('schedule.resources.rate_cost', { defaultValue: 'Cost' }),
      billing: t('schedule.resources.rate_billing', { defaultValue: 'Billing' }),
      overtime: t('schedule.resources.rate_overtime', { defaultValue: 'Overtime' }),
    })[r];

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card padding="md">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className="lg:col-span-2">
            <label htmlFor="res-histo-resource" className={labelCls}>
              {t('schedule.resources.resource', { defaultValue: 'Resource' })}
            </label>
            <SearchableSelect
              id="res-histo-resource"
              value={resolvedResourceId}
              onChange={setResourceId}
              options={resourceOptions}
              loading={resourcesQ.isLoading}
              placeholder={t('schedule.resources.pick_resource', {
                defaultValue: 'Pick a resource',
              })}
              searchPlaceholder={t('schedule.resources.search_resource', {
                defaultValue: 'Search by name, code or kind…',
              })}
            />
            {resourceOptions.length === 0 && !resourcesQ.isLoading && (
              <p className="mt-1 text-2xs text-content-tertiary">
                {t('schedule.resources.none_defined', {
                  defaultValue: 'No resources are defined yet. Add them on the Resources page.',
                })}
              </p>
            )}
          </div>
          <div>
            <label htmlFor="res-histo-start" className={labelCls}>
              {t('schedule.resources.start', { defaultValue: 'Start' })}
            </label>
            <input
              id="res-histo-start"
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="res-histo-end" className={labelCls}>
              {t('schedule.resources.end', { defaultValue: 'End' })}
            </label>
            <input
              id="res-histo-end"
              type="date"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              className={inputCls}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 lg:col-span-1 sm:col-span-2">
            <div>
              <label htmlFor="res-histo-bucket" className={labelCls}>
                {t('schedule.resources.bucket', { defaultValue: 'Bucket' })}
              </label>
              <select
                id="res-histo-bucket"
                value={bucket}
                onChange={(e) => setBucket(e.target.value as HistogramBucket)}
                className={inputCls}
              >
                {BUCKETS.map((b) => (
                  <option key={b} value={b}>
                    {bucketLabel(b)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="res-histo-rate" className={labelCls}>
                {t('schedule.resources.rate_type', { defaultValue: 'Rate' })}
              </label>
              <select
                id="res-histo-rate"
                value={rateType}
                onChange={(e) => setRateType(e.target.value as HistogramRateType)}
                className={inputCls}
              >
                {RATE_TYPES.map((r) => (
                  <option key={r} value={r}>
                    {rateLabel(r)}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        {!datesValid && (
          <p className="mt-2 flex items-center gap-1.5 text-2xs text-semantic-warning">
            <AlertTriangle size={12} className="shrink-0" />
            {t('schedule.resources.dates_invalid', {
              defaultValue: 'The end date must be after the start date.',
            })}
          </p>
        )}
      </Card>

      {/* Histogram */}
      {resourcesQ.isError ? (
        <Card padding="md">
          <RecoveryCard error={resourcesQ.error} onRetry={() => resourcesQ.refetch()} />
        </Card>
      ) : /* total rather than items.length: the empty state means the project
             has no resources, not that this page happened to carry none. The
             two agree at offset 0 and only one of them stays true if this
             panel ever pages. */
      !resourcesQ.isLoading && (resourcesQ.data?.total ?? 0) === 0 ? (
        <Card padding="md">
          <EmptyState
            icon={<Users size={28} strokeWidth={1.5} />}
            title={t('schedule.resources.no_resources', { defaultValue: 'No resources yet' })}
            description={t('schedule.resources.no_resources_desc', {
              defaultValue:
                'Add resources and assign them to activities in the Resources module to see a time-phased demand histogram here.',
            })}
          />
        </Card>
      ) : histogramQ.isLoading ? (
        <Card padding="md" data-testid="resource-histogram-loading">
          <SkeletonTable rows={6} columns={3} />
        </Card>
      ) : histogramQ.isError ? (
        <Card padding="md">
          <RecoveryCard error={histogramQ.error} onRetry={() => histogramQ.refetch()} />
        </Card>
      ) : histo ? (
        <Card padding="md" data-testid="resource-histogram">
          {/* Headline stats */}
          <dl className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat
              label={t('schedule.resources.peak_demand', { defaultValue: 'Peak demand (units)' })}
              value={formatUnits(histo.peak_demand)}
            />
            <Stat
              label={t('schedule.resources.capacity', { defaultValue: 'Capacity (units)' })}
              value={
                histo.capacity_units != null
                  ? formatUnits(histo.capacity_units)
                  : t('schedule.resources.capacity_unknown', { defaultValue: 'Unknown' })
              }
            />
            <Stat
              label={t('schedule.resources.over_allocated', { defaultValue: 'Over-allocated buckets' })}
              value={String(histo.over_allocated_buckets)}
              tone={histo.over_allocated_buckets > 0 ? 'warning' : 'neutral'}
            />
          </dl>

          {histo.cells.length === 0 ? (
            <EmptyState
              icon={<BarChart3 size={28} strokeWidth={1.5} />}
              title={t('schedule.resources.no_demand', { defaultValue: 'No demand in this window' })}
              description={t('schedule.resources.no_demand_desc', {
                defaultValue:
                  'This resource has no bookings in the selected window. Widen the date range or pick another resource.',
              })}
            />
          ) : (
            <div className="space-y-1.5" data-testid="resource-histogram-bars">
              {histo.cells.map((c) => {
                const demandPct = Math.min(100, (c.demand_units / maxBar) * 100);
                const availPct =
                  c.available != null ? Math.min(100, (c.available / maxBar) * 100) : null;
                return (
                  <div key={c.bucket_index} className="flex items-center gap-3">
                    <span className="w-28 shrink-0 truncate text-2xs tabular-nums text-content-tertiary">
                      {c.label}
                    </span>
                    <div className="relative h-6 flex-1 rounded-md bg-surface-secondary/60">
                      {/* Availability / capacity reference line */}
                      {availPct != null && (
                        <div
                          className="absolute top-0 bottom-0 z-10 w-px bg-content-secondary"
                          style={{ left: `${availPct}%` }}
                          title={t('schedule.resources.available_units', {
                            defaultValue: 'Available: {{units}}',
                            units: formatUnits(c.available ?? 0),
                          })}
                        />
                      )}
                      {/* Demand bar */}
                      <div
                        className={`h-full rounded-md transition-all ${
                          c.over_allocated ? 'bg-semantic-error/70' : 'bg-oe-blue/70'
                        }`}
                        style={{ width: `${Math.max(2, demandPct)}%` }}
                      />
                      <span className="absolute inset-y-0 left-2 flex items-center text-2xs font-medium tabular-nums text-content-primary">
                        {formatUnits(c.demand_units)}
                      </span>
                    </div>
                    <span className="w-16 shrink-0 text-right text-2xs tabular-nums text-content-tertiary">
                      {c.demand_cost != null && String(c.demand_cost) !== '0'
                        ? formatUnits(Number(c.demand_cost))
                        : '-'}
                    </span>
                  </div>
                );
              })}
              <div className="flex items-center gap-3 pt-2 text-2xs text-content-tertiary">
                <span className="w-28 shrink-0">{bucketLabel(bucket)}</span>
                <span className="flex flex-1 items-center gap-3">
                  <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-sm bg-oe-blue/70" />
                    {t('schedule.resources.legend_demand', { defaultValue: 'Demand' })}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-px bg-content-secondary" />
                    {t('schedule.resources.legend_available', { defaultValue: 'Available' })}
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <span className="inline-block h-2 w-2 rounded-sm bg-semantic-error/70" />
                    {t('schedule.resources.legend_over', { defaultValue: 'Over-allocated' })}
                  </span>
                </span>
                <span className="w-16 shrink-0 text-right">
                  {t('schedule.resources.cost_col', { defaultValue: 'Cost' })}
                </span>
              </div>
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}

/* ── Tab 2: Leveling ─────────────────────────────────────────────────────── */

interface LimitRow {
  /** Stable local key so React keeps focus across edits. */
  key: string;
  name: string;
  max: string;
}

let limitRowSeq = 0;
const newLimitRow = (name = '', max = ''): LimitRow => ({
  key: `lim-${limitRowSeq++}`,
  name,
  max,
});

function LevelingTab({
  scheduleId,
  projectId: _projectId,
  activitiesById,
  onError,
}: {
  scheduleId: string;
  projectId: string;
  activitiesById?: Record<string, string>;
  onError: (e: unknown) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const queryClient = useQueryClient();

  const [rows, setRows] = useState<LimitRow[]>([newLimitRow()]);
  const [preview, setPreview] = useState<LevelPreviewResult | null>(null);
  const [applied, setApplied] = useState<LevelApplyResult | null>(null);

  const nameFor = (id: string): string => (id ? (activitiesById?.[id] ?? id) : '-');

  /** Build the request body from the limit rows (name + integer max). */
  const buildBody = () => {
    const resource_limits: Record<string, number> = {};
    for (const r of rows) {
      const name = r.name.trim();
      const max = Number(r.max);
      if (name && r.max.trim() !== '' && Number.isFinite(max) && max >= 0) {
        resource_limits[name] = max;
      }
    }
    return { resource_limits, splittable: [] as string[] };
  };

  const hasLimits = Object.keys(buildBody().resource_limits).length > 0;

  const previewMut = useMutation({
    mutationFn: () => levelPreview(scheduleId, buildBody()),
    onSuccess: (data) => {
      setPreview(data);
      setApplied(null);
    },
    onError,
  });

  const applyMut = useMutation({
    mutationFn: () => levelApply(scheduleId, buildBody()),
    onSuccess: (data) => {
      setApplied(data);
      // The committed dates change the schedule, so refresh the Gantt and any
      // schedule lists the sibling panels read.
      queryClient.invalidateQueries({ queryKey: ['gantt', scheduleId] });
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      addToast({
        type: 'success',
        title: t('schedule.resources.applied', { defaultValue: 'Leveling applied' }),
        message: t('schedule.resources.applied_detail', {
          defaultValue: '{{applied}} activity date(s) updated; finish moved {{delta}} day(s).',
          applied: data.num_applied,
          delta: data.finish_delta_days,
        }),
      });
    },
    onError,
  });

  const onApply = () => {
    const ok = window.confirm(
      t('schedule.resources.apply_confirm', {
        defaultValue:
          'Apply leveling? This shifts the start and end dates of the affected activities in this schedule.',
      }),
    );
    if (ok) applyMut.mutate();
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
      {/* Left: limits editor */}
      <div className="space-y-4">
        <Card padding="md">
          <h4 className="mb-1 text-sm font-semibold text-content-primary">
            {t('schedule.resources.limits', { defaultValue: 'Resource limits' })}
          </h4>
          <p className="mb-3 text-2xs text-content-tertiary">
            {t('schedule.resources.limits_hint', {
              defaultValue:
                'Name a resource exactly as it appears on the activities and cap its concurrent units. Resources you leave out stay unconstrained.',
            })}
          </p>

          <div className="space-y-2" data-testid="resource-limit-rows">
            {rows.map((r) => (
              <div key={r.key} className="flex items-center gap-2">
                <input
                  type="text"
                  value={r.name}
                  onChange={(e) =>
                    setRows((prev) =>
                      prev.map((x) => (x.key === r.key ? { ...x, name: e.target.value } : x)),
                    )
                  }
                  placeholder={t('schedule.resources.limit_name_ph', { defaultValue: 'Resource name' })}
                  aria-label={t('schedule.resources.limit_name', { defaultValue: 'Resource name' })}
                  className={`${inputCls} flex-1`}
                />
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={r.max}
                  onChange={(e) =>
                    setRows((prev) =>
                      prev.map((x) => (x.key === r.key ? { ...x, max: e.target.value } : x)),
                    )
                  }
                  placeholder={t('schedule.resources.limit_max_ph', { defaultValue: 'Max' })}
                  aria-label={t('schedule.resources.limit_max', { defaultValue: 'Max units' })}
                  className={`${inputCls} w-20`}
                />
                <button
                  type="button"
                  onClick={() => setRows((prev) => (prev.length > 1 ? prev.filter((x) => x.key !== r.key) : prev))}
                  disabled={rows.length <= 1}
                  aria-label={t('schedule.resources.remove_limit', { defaultValue: 'Remove limit' })}
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-semantic-error disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRows((prev) => [...prev, newLimitRow()])}
              icon={<Plus size={14} />}
            >
              {t('schedule.resources.add_limit', { defaultValue: 'Add resource' })}
            </Button>
          </div>

          <div className="mt-4 flex flex-wrap gap-2 border-t border-border-light pt-4">
            <Button
              variant="primary"
              size="sm"
              onClick={() => previewMut.mutate()}
              disabled={previewMut.isPending || !hasLimits}
              icon={
                previewMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Play size={14} />
                )
              }
            >
              {t('schedule.resources.preview', { defaultValue: 'Preview' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={onApply}
              disabled={applyMut.isPending || !hasLimits}
              icon={
                applyMut.isPending ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )
              }
            >
              {t('schedule.resources.apply', { defaultValue: 'Apply' })}
            </Button>
          </div>
        </Card>
      </div>

      {/* Right: preview / result */}
      <div className="min-w-0 space-y-4">
        {applied && (
          <Card padding="md" data-testid="resource-level-applied">
            <div className="mb-3 flex items-center gap-2">
              <Check size={16} className="text-semantic-success" />
              <h4 className="text-sm font-semibold text-content-primary">
                {t('schedule.resources.apply_result', { defaultValue: 'Leveling applied' })}
              </h4>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat
                label={t('schedule.resources.shifted', { defaultValue: 'Shifted' })}
                value={String(applied.num_shifted)}
              />
              <Stat
                label={t('schedule.resources.updated', { defaultValue: 'Dates updated' })}
                value={String(applied.num_applied)}
              />
              <Stat
                label={t('schedule.resources.skipped', { defaultValue: 'Skipped' })}
                value={String(applied.num_skipped)}
                tone={applied.num_skipped > 0 ? 'warning' : 'neutral'}
              />
              <Stat
                label={t('schedule.resources.finish_delta', { defaultValue: 'Finish delta (days)' })}
                value={formatDelta(applied.finish_delta_days)}
                tone={applied.finish_delta_days > 0 ? 'warning' : 'neutral'}
              />
            </dl>
          </Card>
        )}

        {previewMut.isPending ? (
          <Card padding="md" data-testid="resource-level-loading">
            <SkeletonTable rows={5} columns={4} />
          </Card>
        ) : preview ? (
          <PreviewResult preview={preview} nameFor={nameFor} />
        ) : (
          <Card padding="md">
            <EmptyState
              icon={<Scale size={28} strokeWidth={1.5} />}
              title={t('schedule.resources.preview_empty', { defaultValue: 'No preview yet' })}
              description={t('schedule.resources.preview_empty_desc', {
                defaultValue:
                  'Enter one or more resource limits on the left and run Preview to see the shifted activities, the per-resource peak before and after, and the honest finish-date impact before you commit.',
              })}
            />
          </Card>
        )}
      </div>
    </div>
  );
}

function PreviewResult({
  preview,
  nameFor,
}: {
  preview: LevelPreviewResult;
  nameFor: (id: string) => string;
}) {
  const { t } = useTranslation();

  // Union of resources named in either peak map, for the before/after table.
  const peakResources = useMemo(() => {
    const names = new Set<string>([
      ...Object.keys(preview.peak_before),
      ...Object.keys(preview.peak_after),
    ]);
    // These are resource names, not keys: a bare sort would order them by
    // UTF-16 code unit and push every accented name to the bottom.
    return Array.from(names).sort(compareNames);
  }, [preview.peak_before, preview.peak_after]);

  return (
    <div className="space-y-4" data-testid="resource-level-preview">
      {/* Headline */}
      <Card padding="md">
        <h4 className="mb-3 text-sm font-semibold text-content-primary">
          {t('schedule.resources.preview_result', { defaultValue: 'Leveling preview' })}
        </h4>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat
            label={t('schedule.resources.base_finish', { defaultValue: 'Base finish (work-day)' })}
            value={String(preview.base_finish_workday)}
          />
          <Stat
            label={t('schedule.resources.leveled_finish', { defaultValue: 'Leveled finish (work-day)' })}
            value={String(preview.leveled_finish_workday)}
          />
          <Stat
            label={t('schedule.resources.finish_delta', { defaultValue: 'Finish delta (days)' })}
            value={formatDelta(preview.finish_delta_days)}
            tone={preview.finish_delta_days > 0 ? 'warning' : 'neutral'}
          />
          <Stat
            label={t('schedule.resources.shifted', { defaultValue: 'Shifted' })}
            value={String(preview.num_shifted)}
          />
        </dl>
      </Card>

      {/* Per-resource peak before/after */}
      {peakResources.length > 0 && (
        <Card padding="none">
          <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
            <TrendingUp size={16} className="text-content-secondary" />
            <h4 className="text-sm font-semibold text-content-primary">
              {t('schedule.resources.peak_title', { defaultValue: 'Peak demand: before vs after' })}
            </h4>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="resource-peak-table">
              <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('schedule.resources.resource', { defaultValue: 'Resource' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('schedule.resources.peak_before_col', { defaultValue: 'Before' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('schedule.resources.peak_after_col', { defaultValue: 'After' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {peakResources.map((name) => {
                  const before = preview.peak_before[name] ?? 0;
                  const after = preview.peak_after[name] ?? 0;
                  return (
                    <tr key={name} className="border-t border-border-light">
                      <td className="px-3 py-2">{name}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {formatUnits(before)}
                      </td>
                      <td
                        className={`px-3 py-2 text-right font-mono tabular-nums ${
                          after < before ? 'text-semantic-success' : ''
                        }`}
                      >
                        {formatUnits(after)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Shifted activities */}
      <Card padding="none">
        <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
          <h4 className="text-sm font-semibold text-content-primary">
            {t('schedule.resources.shifts', { defaultValue: 'Shifted activities' })}
          </h4>
          <Badge variant="neutral" size="sm">
            {preview.shifts.length}
          </Badge>
        </div>
        {preview.shifts.length === 0 ? (
          <div className="px-4 py-6 text-sm text-content-tertiary">
            {t('schedule.resources.no_shifts', {
              defaultValue: 'Nothing moved - the schedule already fits the limits you set.',
            })}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="resource-shifts-table">
              <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('schedule.resources.activity', { defaultValue: 'Activity' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('schedule.resources.base_es', { defaultValue: 'Base start' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('schedule.resources.new_es', { defaultValue: 'New start' })}
                  </th>
                  <th className="px-3 py-2 text-right">
                    {t('schedule.resources.delta_col', { defaultValue: 'Delta' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {preview.shifts.map((s) => (
                  <tr key={s.activity_id} className="border-t border-border-light">
                    <td className="px-3 py-2">
                      <span className="truncate" title={s.activity_id}>
                        {nameFor(s.activity_id)}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{s.base_es}</td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">{s.new_es}</td>
                    <td className="px-3 py-2 text-right font-mono font-semibold tabular-nums text-semantic-warning">
                      {formatDelta(s.delta)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Unresolvable overloads */}
      {preview.unresolvable.length > 0 && (
        <Card padding="none">
          <div className="flex items-center gap-2 border-b border-border-light px-4 py-3">
            <AlertTriangle size={16} className="text-semantic-warning" />
            <h4 className="text-sm font-semibold text-content-primary">
              {t('schedule.resources.unresolvable', { defaultValue: 'Unresolvable overloads' })}
            </h4>
            <Badge variant="warning" size="sm">
              {preview.unresolvable.length}
            </Badge>
          </div>
          <p className="px-4 pt-3 text-2xs text-content-tertiary">
            {t('schedule.resources.unresolvable_hint', {
              defaultValue:
                'These activities demand more of a resource on their own than its limit allows, so shifting cannot clear the overload. Raise the limit or split the activity.',
            })}
          </p>
          <ul className="divide-y divide-border-light px-1 py-2" data-testid="resource-unresolvable">
            {preview.unresolvable.map((u, i) => (
              <li key={`${u.activity_id}-${u.resource}-${i}`} className="px-3 py-2 text-sm">
                <span className="font-medium text-content-primary" title={u.activity_id}>
                  {nameFor(u.activity_id)}
                </span>
                <span className="text-content-tertiary">
                  {' - '}
                  {t('schedule.resources.unresolvable_row', {
                    defaultValue: '{{resource}} needs {{required}} but the limit is {{limit}}',
                    resource: u.resource,
                    required: formatUnits(u.required),
                    limit: formatUnits(u.limit),
                  })}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────────── */

/** Trim a float to a short, tabular-friendly string (drops trailing zeros). */
function formatUnits(n: number): string {
  if (!Number.isFinite(n)) return '0';
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, '');
}

/** A signed day count with an explicit + for positive slip. */
function formatDelta(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'warning';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd
        className={
          'mt-0.5 text-xl font-bold tabular-nums ' +
          (tone === 'warning' ? 'text-semantic-warning' : 'text-content-primary')
        }
      >
        {value}
      </dd>
    </div>
  );
}

export default ScheduleResourcePanel;
