/**
 * Quick-Insight Panel (T02).
 *
 * Renders a small grid of auto-generated charts for a snapshot. The
 * backend picks chart types and ranks them by an "interestingness"
 * score; this component is responsible only for rendering each chart
 * type with Recharts and exposing a Refresh button + a per-card "Pin"
 * action.
 *
 * Pin-to-dashboard is wired to a callback that the parent supplies —
 * the dashboards-collection endpoint (T05) does not exist yet, so the
 * default no-op shows a toast explaining that the wiring lands later.
 */
import { useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { RefreshCw, Pin, BarChart3, LineChart as LineIcon, ScatterChart as ScatterIcon, PieChart as PieIcon } from 'lucide-react';

import { Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';

import {
  createDashboardPreset,
  getQuickInsights,
  type QuickInsightChart,
} from './api';
import { PresetPicker } from './PresetPicker';

const CHART_HEIGHT = 200;
const PIE_PALETTE = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#14b8a6', // teal
  '#a3e635', // lime
];

export interface QuickInsightPanelProps {
  snapshotId: string;
  /** Optional callback fired when the user pins a chart. */
  onPinChart?: (chart: QuickInsightChart) => void;
  /** How many charts to request from the backend (default 6, max 24). */
  limit?: number;
  /**
   * Project the snapshot belongs to. When supplied, pinning a chart
   * creates a preset on that project (T05). Without it the pin still
   * shows a toast, but no preset is saved.
   */
  projectId?: string | null;
}

export function QuickInsightPanel({
  snapshotId,
  onPinChart,
  limit = 6,
  projectId,
}: QuickInsightPanelProps) {
  const { t } = useTranslation();
  const toast = useToastStore((s) => s.addToast);

  const insightsQuery = useQuery({
    queryKey: ['dashboards-quick-insights', snapshotId, limit],
    queryFn: () => getQuickInsights(snapshotId, { limit }),
    enabled: !!snapshotId,
    // Don't refetch when the user just clicks around — auto-charts
    // shouldn't change unless the snapshot data changes.
    staleTime: 5 * 60 * 1000,
  });

  const handleRefresh = useCallback(() => {
    insightsQuery.refetch();
  }, [insightsQuery]);

  const handlePin = useCallback(
    async (chart: QuickInsightChart) => {
      if (onPinChart) {
        onPinChart(chart);
        return;
      }
      // T05: pinning a chart now creates a private preset.
      try {
        await createDashboardPreset({
          name: chart.title.slice(0, 200),
          description: t('dashboards.pin_default_description', {
            defaultValue: 'Pinned from Quick Insights',
          }),
          kind: 'preset',
          project_id: projectId ?? null,
          config_json: {
            snapshot_id: snapshotId,
            charts: [chart],
            filters: {},
          },
          shared_with_project: false,
        });
        toast({
          type: 'success',
          title: t('dashboards.pin_saved_title', {
            defaultValue: 'Pinned to dashboard',
          }),
          message: t('dashboards.pin_saved_msg', {
            defaultValue: 'Open the Presets dropdown to load it back.',
          }),
        });
      } catch (err) {
        toast({
          type: 'error',
          title: t('dashboards.pin_failed_title', {
            defaultValue: 'Could not pin chart',
          }),
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [onPinChart, toast, t, projectId, snapshotId],
  );

  const dashboardSnapshot = useCallback(
    () => ({
      snapshot_id: snapshotId,
      filters: {},
      charts: charts,
    }),
    // Recomputed when the chart list changes — that's the whole point.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [snapshotId, insightsQuery.data?.charts],
  );

  const charts = insightsQuery.data?.charts ?? [];

  return (
    <Card data-testid="quick-insight-panel">
      <div className="flex items-center justify-between border-b border-border-light px-4 py-2">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboards.quick_insights_title', {
              defaultValue: 'Quick insights',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('dashboards.quick_insights_subtitle', {
              defaultValue: 'Auto-generated charts surfacing patterns in this snapshot.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <PresetPicker projectId={projectId} snapshot={dashboardSnapshot} />
          <Button
            variant="ghost"
            size="sm"
            onClick={handleRefresh}
            disabled={insightsQuery.isFetching}
            data-testid="quick-insights-refresh"
          >
            <RefreshCw
              className={`mr-1 h-3 w-3 ${insightsQuery.isFetching ? 'animate-spin' : ''}`}
            />
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        </div>
      </div>

      <div className="p-3">
        {insightsQuery.isLoading && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-56" />
            ))}
          </div>
        )}

        {insightsQuery.isError && (
          <div className="rounded border border-rose-400/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            {t('dashboards.quick_insights_error', {
              defaultValue: 'Could not load auto-charts for this snapshot.',
            })}
          </div>
        )}

        {!insightsQuery.isLoading && !insightsQuery.isError && charts.length === 0 && (
          <EmptyState
            icon={<BarChart3 className="h-8 w-8 text-neutral-500" />}
            title={t('dashboards.no_insights_title', {
              defaultValue: 'No automatic insights available',
            })}
            description={t('dashboards.no_insights_desc', {
              defaultValue:
                'The snapshot has no columns with enough variance to chart automatically.',
            })}
          />
        )}

        {charts.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {charts.map((chart, idx) => (
              <ChartCard
                key={`${chart.chart_type}-${chart.x_field}-${chart.y_field}-${idx}`}
                chart={chart}
                onPin={() => handlePin(chart)}
              />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

/* ── Per-chart card ─────────────────────────────────────────────────────── */

interface ChartCardProps {
  chart: QuickInsightChart;
  onPin: () => void;
}

function ChartCard({ chart, onPin }: ChartCardProps) {
  const { t } = useTranslation();

  return (
    <div
      className="flex flex-col gap-2 rounded border border-border-light bg-surface-secondary p-2"
      data-testid={`quick-insight-card-${chart.chart_type}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-content-secondary">
          <ChartTypeIcon type={chart.chart_type} />
          <span className="truncate" title={chart.title}>
            {chart.title}
          </span>
        </div>
        <button
          type="button"
          onClick={onPin}
          className="rounded p-1 text-content-tertiary hover:bg-surface-primary hover:text-oe-blue"
          aria-label={t('dashboards.pin_chart', { defaultValue: 'Pin to dashboard' })}
          title={t('dashboards.pin_chart', { defaultValue: 'Pin to dashboard' })}
          data-testid={`quick-insight-pin-${chart.chart_type}`}
        >
          <Pin className="h-3 w-3" />
        </button>
      </div>
      <div className="h-[200px] w-full">
        <ChartBody chart={chart} />
      </div>
    </div>
  );
}

function ChartTypeIcon({ type }: { type: QuickInsightChart['chart_type'] }) {
  switch (type) {
    case 'histogram':
    case 'bar':
      return <BarChart3 className="h-3 w-3" />;
    case 'line':
      return <LineIcon className="h-3 w-3" />;
    case 'scatter':
      return <ScatterIcon className="h-3 w-3" />;
    case 'donut':
      return <PieIcon className="h-3 w-3" />;
    default:
      return null;
  }
}

/* ── Body renderer ──────────────────────────────────────────────────────── */

function ChartBody({ chart }: { chart: QuickInsightChart }) {
  const data = useMemo(() => chart.data ?? [], [chart.data]);

  if (data.length === 0) {
    return <EmptyChart />;
  }

  switch (chart.chart_type) {
    case 'histogram':
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <BarChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3a3a3a" vertical={false} />
            <XAxis dataKey={chart.x_field} fontSize={10} tickLine={false} />
            <YAxis fontSize={10} tickLine={false} />
            <Tooltip />
            <Bar dataKey={chart.y_field} fill="#3b82f6" />
          </BarChart>
        </ResponsiveContainer>
      );
    case 'bar':
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <BarChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3a3a3a" vertical={false} />
            <XAxis dataKey={chart.x_field} fontSize={10} tickLine={false} />
            <YAxis fontSize={10} tickLine={false} />
            <Tooltip />
            <Bar dataKey={chart.y_field} fill="#10b981" />
          </BarChart>
        </ResponsiveContainer>
      );
    case 'line':
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <LineChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3a3a3a" vertical={false} />
            <XAxis dataKey={chart.x_field} fontSize={10} tickLine={false} />
            <YAxis fontSize={10} tickLine={false} />
            <Tooltip />
            <Line type="monotone" dataKey={chart.y_field} stroke="#3b82f6" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      );
    case 'scatter':
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <ScatterChart margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#3a3a3a" />
            <XAxis dataKey={chart.x_field} fontSize={10} type="number" />
            <YAxis dataKey={chart.y_field} fontSize={10} type="number" />
            <Tooltip cursor={{ strokeDasharray: '3 3' }} />
            <Scatter data={data} fill="#8b5cf6" />
          </ScatterChart>
        </ResponsiveContainer>
      );
    case 'donut':
      return (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <PieChart>
            <Pie
              data={data}
              dataKey={chart.y_field}
              nameKey={chart.x_field}
              innerRadius={40}
              outerRadius={70}
              paddingAngle={1}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={PIE_PALETTE[i % PIE_PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 10 }} />
          </PieChart>
        </ResponsiveContainer>
      );
    default:
      return <EmptyChart />;
  }
}

function EmptyChart() {
  return (
    <div className="flex h-full items-center justify-center text-xs text-content-tertiary">
      —
    </div>
  );
}
