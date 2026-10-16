// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Property Development — Dashboard full-view route (task #140).
 *
 * Renders one dashboard at a time based on the URL slug (e.g.
 * /property-dev/dashboards/inventory-heatmap) and a development selector.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Building2 } from 'lucide-react';
import { Breadcrumb, EmptyState } from '@/shared/ui';
import { listDevelopments, type Development } from '../api';
import { InventoryHeatmap } from './InventoryHeatmap';
import { SalesVelocity } from './SalesVelocity';
import { CashFlowWaterfall } from './CashFlowWaterfall';
import { InventoryAgeing } from './InventoryAgeing';
import { FunnelConversion } from './FunnelConversion';
import { CohortRetentionWidget } from './CohortRetentionWidget';
import { TimeToCloseWidget } from './TimeToCloseWidget';
import { LeadSourceAttributionWidget } from './LeadSourceAttributionWidget';
import { ConversionFunnelWidget } from './ConversionFunnelWidget';
import { BrokerPerformanceWidget } from './BrokerPerformanceWidget';
import {
  DashboardEmpty,
  DashboardError,
  DashboardSkeleton,
} from './_shared';

const VALID_KEYS = new Set([
  'inventory-heatmap',
  'sales-velocity',
  'cashflow-waterfall',
  'inventory-ageing',
  'funnel-conversion',
  'insights',
]);


export function FullViewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ key?: string }>();
  const key = params.key ?? '';
  const [developmentId, setDevelopmentId] = useState<string>('');

  const {
    data: developments,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['propdev-developments'],
    queryFn: () => listDevelopments({ limit: 100 }),
  });

  // Seed local state from async query data via useEffect — assigning
  // during render trips StrictMode's "setState during render" warning.
  useEffect(() => {
    if (!developmentId && developments && developments.length > 0) {
      const first = developments[0];
      if (first) setDevelopmentId(first.id);
    }
  }, [developments, developmentId]);

  if (!VALID_KEYS.has(key)) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.full.unknown_title', {
          defaultValue: 'Unknown dashboard',
        })}
        description={t('propdev.dashboards.full.unknown_desc', {
          defaultValue:
            'The dashboard you tried to open doesn\'t exist.',
        })}
      />
    );
  }
  if (isLoading) return <DashboardSkeleton variant="bars" rows={8} />;
  if (isError) {
    return (
      <DashboardError
        title={t('propdev.dashboards.load_developments_error', {
          defaultValue: 'Could not load developments',
        })}
        message={error instanceof Error ? error.message : undefined}
        onRetry={() => refetch()}
      />
    );
  }
  if (!developments || developments.length === 0) {
    return (
      <EmptyState
        icon={<Building2 size={22} />}
        title={t('propdev.dashboards.hub.no_developments_title', {
          defaultValue: 'No developments yet',
        })}
        description={t('propdev.dashboards.hub.no_developments_desc', {
          defaultValue:
            'Create your first development to populate this dashboard.',
        })}
        action={{
          label: t('propdev.new_development', { defaultValue: 'New Development' }),
          onClick: () => navigate('/property-dev'),
        }}
      />
    );
  }

  const renderActive = () => {
    if (!developmentId) return null;
    switch (key) {
      case 'inventory-heatmap':
        return <InventoryHeatmap developmentId={developmentId} />;
      case 'sales-velocity':
        return <SalesVelocity developmentId={developmentId} />;
      case 'cashflow-waterfall':
        return <CashFlowWaterfall developmentId={developmentId} />;
      case 'inventory-ageing':
        return <InventoryAgeing developmentId={developmentId} />;
      case 'funnel-conversion':
        return <FunnelConversion developmentId={developmentId} />;
      case 'insights':
        return <InsightsGrid developmentId={developmentId} />;
      default:
        return null;
    }
  };

  const dashboardTitle = t(
    `propdev.dashboards.full.${key.replace(/-/g, '_')}`,
    { defaultValue: key.replace(/-/g, ' ') },
  );

  return (
    <div className="space-y-5">
      <Breadcrumb
        items={[
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            to: '/property-dev',
          },
          {
            label: t('propdev.dashboards.hub.title', {
              defaultValue: 'Property Development Dashboards',
            }),
            to: '/property-dev/dashboards',
          },
          { label: dashboardTitle },
        ]}
      />
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <Link
            to="/property-dev/dashboards"
            className="flex items-center gap-1 text-2xs text-content-tertiary hover:text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          >
            <ArrowLeft size={12} />
            {t('propdev.dashboards.full.back_to_hub', {
              defaultValue: 'Back to hub',
            })}
          </Link>
          <h1 className="text-lg font-semibold text-content-primary capitalize">
            {dashboardTitle}
          </h1>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-content-secondary">
            {t('propdev.dashboards.hub.development', {
              defaultValue: 'Development',
            })}
          </span>
          <select
            value={developmentId}
            onChange={(e) => setDevelopmentId(e.target.value)}
            className="rounded border border-border-light bg-surface-elevated px-2 py-1"
          >
            {developments.map((d: Development) => (
              <option key={d.id} value={d.id}>
                {d.code} — {d.name}
              </option>
            ))}
          </select>
        </label>
      </header>
      <div>{renderActive()}</div>
    </div>
  );
}

/**
 * Uniform-height card wrapper for the Insights grid. Mirrors the hub's
 * ``DashboardTile`` (``min-h`` + ``flex flex-col``) so the grid keeps a
 * stable shape no matter which state a widget is in.
 *
 * Each widget manages its own loading / empty / error state internally
 * (skeleton, ``DashboardEmpty``); the wrapper centres that state inside
 * the card's reserved height so a single widget failing or coming back
 * empty no longer collapses to a thin strip and leaves a ragged column
 * next to its taller neighbour.
 */
function InsightCard({
  children,
  fullWidth = false,
}: {
  children: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div
      className={`flex min-h-[280px] flex-col justify-center rounded-lg border border-divider bg-surface-primary p-3 ${
        fullWidth ? 'md:col-span-2' : ''
      }`}
    >
      {children}
    </div>
  );
}

/**
 * Insights tab — the 5 v3124 sales-analytics widgets in a 2-col grid
 * (1-col on mobile). Each widget is independently cached (React Query
 * staleTime 60s) so swapping tabs or window-filter changes only
 * re-fetches the widgets the user actually scrolls to.
 *
 * Each widget owns its failure independently: it renders its own
 * skeleton while loading and a ``DashboardEmpty`` on error or empty,
 * and the ``InsightCard`` wrapper keeps every card the same height so
 * one widget's failure can't reflow or unbalance the rest of the grid.
 *
 * The Insights grid intentionally drops the development_id scope —
 * these analytics are tenant-wide (cohort retention, lead-source CPA,
 * broker leaderboard all make more sense across the full portfolio).
 * The Conversion-funnel widget takes ``devId`` to keep the per-dev
 * drilldown available without adding a second selector.
 */
function InsightsGrid({ developmentId }: { developmentId: string }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <InsightCard>
        <CohortRetentionWidget />
      </InsightCard>
      <InsightCard>
        <TimeToCloseWidget />
      </InsightCard>
      <InsightCard fullWidth>
        <LeadSourceAttributionWidget />
      </InsightCard>
      <InsightCard>
        <ConversionFunnelWidget devId={developmentId} />
      </InsightCard>
      <InsightCard>
        <BrokerPerformanceWidget />
      </InsightCard>
    </div>
  );
}
