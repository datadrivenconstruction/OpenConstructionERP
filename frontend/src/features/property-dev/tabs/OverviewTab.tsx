// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Overview tab — at-a-glance landing dashboard.
 *
 * Aggregates dashboard tiles across every development so a new visitor
 * lands on something useful instead of an empty grid. Each tile is
 * clickable and jumps to the relevant sub-tab. Recent activity is
 * sourced from the cross-module ``/api/v1/activity`` endpoint via
 * ``ActivityFeed``.
 *
 * The aggregate fetches happen in parallel via ``useQueries`` — a
 * single hook call that internally manages a dynamic array of
 * queries. This is the idiomatic, hook-safe way to fan out N parallel
 * queries; calling ``useQuery`` inside a ``.map`` over ``developments``
 * would violate the rules-of-hooks if the list ever reordered between
 * renders. We cap at 12 developments to keep the network fan-out
 * predictable; tenants with more should narrow via the Developments
 * tab. ``staleTime: 60_000`` matches DashboardsHub.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueries } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  AlertOctagon,
  ArrowRight,
  Building2,
  FileSignature,
  Grid3X3,
  Key,
  LayoutDashboard,
  ShieldAlert,
  Users,
  Wallet,
} from 'lucide-react';
import {
  ActivityFeed,
  Badge,
  Card,
  EmptyState,
} from '@/shared/ui';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { getDevelopmentDashboard, type Development } from '../api';
import { type Tab, toNumber } from './_shared';

// English fallbacks for the computed `propdev.development.sales_phase.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const SALES_PHASE_LABELS: Record<string, string> = {
  planning: 'Planning', launch: 'Launch', sales: 'Sales', handover: 'Handover', closed: 'Closed'
};


export function OverviewTab({
  developments,
  onJumpTo,
  onJumpToDevelopment,
  onCreate,
}: {
  developments: Development[];
  onJumpTo: (tab: Tab, filter?: { warrantyStatus?: string }) => void;
  onJumpToDevelopment: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (developments.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Building2 size={22} />}
          title={t('propdev.empty_developments', {
            defaultValue: 'No developments yet',
          })}
          description={t('propdev.empty_developments_desc', {
            defaultValue:
              'Create your first development to start tracking plots, buyers and handovers.',
          })}
          action={{
            label: t('propdev.new_development', {
              defaultValue: 'New Development',
            }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <OverviewKpiRow
        developments={developments.slice(0, 12)}
        onJumpTo={onJumpTo}
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card padding="md" className="lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('propdev.recent_activity', {
                defaultValue: 'Recent activity',
              })}
            </h3>
            <Badge variant="neutral">
              {t('propdev.last_n', { defaultValue: 'Last {{n}}', n: 10 })}
            </Badge>
          </div>
          <ActivityFeed limit={10} />
        </Card>

        <Card padding="md">
          <h3 className="mb-3 text-sm font-semibold text-content-primary">
            {t('propdev.quick_links', { defaultValue: 'Quick links' })}
          </h3>
          <ul className="space-y-2">
            <li>
              <button
                type="button"
                onClick={() => navigate('/property-dev/dashboards')}
                className="group flex w-full items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-sm text-left hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              >
                <span className="flex items-center gap-2">
                  <LayoutDashboard
                    size={14}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                  <span>
                    {t('propdev.dashboards_link', {
                      defaultValue: 'Analytics dashboards',
                    })}
                  </span>
                </span>
                <ArrowRight
                  size={13}
                  className="text-content-tertiary group-hover:text-oe-blue"
                />
              </button>
            </li>
            <li>
              <button
                type="button"
                onClick={() => onJumpTo('buyers')}
                className="group flex w-full items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-sm text-left hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              >
                <span className="flex items-center gap-2">
                  <Users
                    size={14}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                  <span>
                    {t('propdev.buyers_pipeline', {
                      defaultValue: 'Buyers pipeline',
                    })}
                  </span>
                </span>
                <ArrowRight
                  size={13}
                  className="text-content-tertiary group-hover:text-oe-blue"
                />
              </button>
            </li>
            <li>
              <button
                type="button"
                onClick={() => onJumpTo('handovers')}
                className="group flex w-full items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-sm text-left hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              >
                <span className="flex items-center gap-2">
                  <Key
                    size={14}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                  <span>
                    {t('propdev.handovers_short', {
                      defaultValue: 'Upcoming handovers',
                    })}
                  </span>
                </span>
                <ArrowRight
                  size={13}
                  className="text-content-tertiary group-hover:text-oe-blue"
                />
              </button>
            </li>
            <li>
              <button
                type="button"
                onClick={() => onJumpTo('warranty')}
                className="group flex w-full items-center justify-between gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2.5 text-sm text-left hover:border-oe-blue hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
              >
                <span className="flex items-center gap-2">
                  <ShieldAlert
                    size={14}
                    className="text-content-tertiary group-hover:text-oe-blue"
                  />
                  <span>
                    {t('propdev.warranty_short', {
                      defaultValue: 'Warranty claims',
                    })}
                  </span>
                </span>
                <ArrowRight
                  size={13}
                  className="text-content-tertiary group-hover:text-oe-blue"
                />
              </button>
            </li>
          </ul>
        </Card>
      </div>

      <Card padding="none">
        <div className="px-4 py-3 border-b border-border-light flex items-center justify-between">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.developments_snapshot', {
              defaultValue: 'Developments snapshot',
            })}
          </h3>
          <button
            type="button"
            onClick={() => onJumpTo('developments')}
            className="text-xs text-oe-blue hover:underline focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          >
            {t('propdev.view_all', { defaultValue: 'View all' })} →
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.development', { defaultValue: 'Development' })}
                </th>
                <th className="px-4 py-2.5 text-left">
                  {t('propdev.phase', { defaultValue: 'Phase' })}
                </th>
                <th className="px-4 py-2.5 text-right">
                  {t('propdev.sold_pct', { defaultValue: 'Sold %' })}
                </th>
                <th className="px-4 py-2.5 text-right">
                  {t('propdev.contracted', { defaultValue: 'Contracted' })}
                </th>
                <th className="px-4 py-2.5 text-right">
                  {t('propdev.open_snags', { defaultValue: 'Open snags' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {developments.slice(0, 12).map((d) => (
                <OverviewDevRow
                  key={d.id}
                  dev={d}
                  onSelect={() => onJumpToDevelopment(d.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/**
 * Row for the overview snapshot table. Pulls the per-development
 * dashboard so KPIs stay live. Loading state is a thin shimmer rather
 * than a full skeleton — the row is only ~24px tall.
 */
function OverviewDevRow({
  dev,
  onSelect,
}: {
  dev: Development;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const dashQ = useQuery({
    queryKey: ['propdev', 'dashboard', dev.id],
    queryFn: () => getDevelopmentDashboard(dev.id),
    staleTime: 60_000,
  });
  const dash = dashQ.data;
  const total = dash?.total_plots ?? dev.total_plots ?? 0;
  const sold =
    dash != null
      ? (dash.plots_by_status['sold'] ?? 0) +
        (dash.plots_by_status['handed_over'] ?? 0)
      : 0;
  const pct = total > 0 ? Math.round((sold / total) * 100) : 0;
  return (
    <tr
      onClick={onSelect}
      className="border-t border-border-light hover:bg-surface-secondary cursor-pointer focus-within:bg-surface-secondary"
    >
      <td className="px-4 py-2">
        <div className="font-medium">{dev.name || dev.code}</div>
        <div className="text-xs font-mono text-content-tertiary">{dev.code}</div>
      </td>
      <td className="px-4 py-2 text-xs">
        <Badge
          variant={
            dev.status === 'active'
              ? 'success'
              : dev.status === 'paused'
                ? 'warning'
                : 'neutral'
          }
        >
          {t(`propdev.development.sales_phase.${dev.sales_phase}`, {
            defaultValue: SALES_PHASE_LABELS[dev.sales_phase] ?? dev.sales_phase,
          })}
        </Badge>
      </td>
      <td className="px-4 py-2 text-right">
        <span className="inline-flex items-center gap-2">
          <span className="font-medium tabular-nums">{pct}%</span>
          <span className="hidden sm:inline-block h-1.5 w-16 overflow-hidden rounded-full bg-surface-secondary">
            <span
              className="block h-full bg-oe-blue"
              style={{ width: `${pct}%` }}
            />
          </span>
        </span>
      </td>
      <td className="px-4 py-2 text-right font-medium">
        {dashQ.isLoading ? (
          <span className="inline-block h-3 w-16 rounded bg-surface-secondary animate-pulse" />
        ) : dash ? (
          // Buyers in a development may contract in different currencies,
          // so render the honest per-currency breakdown rather than
          // summing into one figure stamped with the dev currency.
          <MultiCurrencyTotal
            variant="inline"
            compact
            className="justify-end"
            items={Object.entries(dash.contracted_value_by_currency ?? {}).map(
              ([currency, amount]) => ({ amount, currency }),
            )}
          />
        ) : (
          '—'
        )}
      </td>
      <td className="px-4 py-2 text-right">
        {dashQ.isLoading ? '—' : dash ? dash.open_snags : '—'}
      </td>
    </tr>
  );
}

/**
 * Top row of KPI tiles. Aggregates per-development dashboards in
 * parallel. While any dashboard is still loading the tile shows a dash
 * rather than a transient 0 (which would read as truth).
 */
function OverviewKpiRow({
  developments,
  onJumpTo,
}: {
  developments: Development[];
  onJumpTo: (tab: Tab, filter?: { warrantyStatus?: string }) => void;
}) {
  const { t } = useTranslation();
  const dashQs = useQueries({
    queries: developments.map((d) => ({
      queryKey: ['propdev', 'dashboard', d.id],
      queryFn: () => getDevelopmentDashboard(d.id),
      staleTime: 60_000,
    })),
  });
  const allLoaded = dashQs.every((q) => !q.isLoading);
  const anyError = dashQs.some((q) => q.isError);

  const dataFingerprint = dashQs.map((q) => q.dataUpdatedAt).join(',');
  const totals = useMemo(() => {
    let availablePlots = 0;
    let openLeads = 0;
    let pendingReservations = 0;
    let openSnags = 0;
    let openWarranty = 0;
    let scheduledHandovers = 0;
    // Wave-10 fix: track contracted value as {amount, currency} pairs so
    // the KPI tile can split rather than collapsing mixed currencies to a
    // misleading first-seen-code total. The backend now reports a
    // per-currency breakdown (buyers within one development may contract
    // in different currencies), so we expand every code rather than
    // pairing one blended figure with the development currency.
    const contractedItems: { amount: number; currency: string | null }[] = [];
    dashQs.forEach((q) => {
      const d = q.data;
      if (!d) return;
      availablePlots +=
        (d.plots_by_status['planned'] ?? 0) +
        (d.plots_by_status['ready'] ?? 0) +
        (d.plots_by_status['under_construction'] ?? 0);
      openLeads += d.buyers_by_status['lead'] ?? 0;
      pendingReservations += d.buyers_by_status['reserved'] ?? 0;
      openSnags += d.open_snags ?? 0;
      openWarranty += d.open_warranty_claims ?? 0;
      scheduledHandovers += d.scheduled_handovers ?? 0;
      for (const [currency, amount] of Object.entries(
        d.contracted_value_by_currency ?? {},
      )) {
        contractedItems.push({ amount: toNumber(amount), currency });
      }
    });
    return {
      availablePlots,
      openLeads,
      pendingReservations,
      openSnags,
      openWarranty,
      scheduledHandovers,
      contractedItems,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataFingerprint]);

  const dashOrDash = (n: number) => (allLoaded ? n : '—');

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <KpiTile
        icon={<Users size={14} />}
        label={t('propdev.kpi_open_leads', { defaultValue: 'Open leads' })}
        value={dashOrDash(totals.openLeads)}
        onClick={() => onJumpTo('buyers')}
        accent="neutral"
        loading={!allLoaded}
        error={anyError}
      />
      <KpiTile
        icon={<FileSignature size={14} />}
        label={t('propdev.kpi_reservations', { defaultValue: 'Reservations' })}
        value={dashOrDash(totals.pendingReservations)}
        onClick={() => onJumpTo('buyers')}
        accent="warning"
        loading={!allLoaded}
        error={anyError}
      />
      <KpiTile
        icon={<Grid3X3 size={14} />}
        label={t('propdev.kpi_available_plots', {
          defaultValue: 'Available plots',
        })}
        value={dashOrDash(totals.availablePlots)}
        onClick={() => onJumpTo('plots')}
        accent="success"
        loading={!allLoaded}
        error={anyError}
      />
      <KpiTile
        icon={<Key size={14} />}
        label={t('propdev.kpi_handovers', {
          defaultValue: 'Scheduled handovers',
        })}
        value={dashOrDash(totals.scheduledHandovers)}
        onClick={() => onJumpTo('handovers')}
        accent="blue"
        loading={!allLoaded}
        error={anyError}
      />
      <KpiTile
        icon={<ShieldAlert size={14} />}
        label={t('propdev.kpi_warranty', { defaultValue: 'Open warranty' })}
        value={dashOrDash(totals.openWarranty)}
        // "Open warranty" = raised; under_review / accepted variants
        // are reachable from the in-tab filter dropdown. Picking the
        // most actionable bucket up-front matches the tile semantics.
        onClick={() => onJumpTo('warranty', { warrantyStatus: 'raised' })}
        accent={totals.openWarranty > 0 ? 'error' : 'neutral'}
        loading={!allLoaded}
        error={anyError}
      />
      <KpiTile
        icon={<Wallet size={14} />}
        label={t('propdev.kpi_contracted', {
          defaultValue: 'Contracted value',
        })}
        value={
          allLoaded ? (
            <MultiCurrencyTotal
              variant="kpi"
              primaryCurrency={developments[0]?.currency || undefined}
              items={totals.contractedItems}
              compact
            />
          ) : (
            '—'
          )
        }
        onClick={() => onJumpTo('buyers')}
        accent="blue"
        loading={!allLoaded}
        error={anyError}
      />
    </div>
  );
}

/**
 * Small reusable KPI tile. Renders as a button so keyboard nav reaches
 * every tile; ``aria-label`` mirrors the label/value pair so screen
 * readers announce "Open leads, 12" rather than just "12".
 */
function KpiTile({
  icon,
  label,
  value,
  onClick,
  accent,
  loading,
  error,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  onClick?: () => void;
  accent?: 'neutral' | 'success' | 'warning' | 'error' | 'blue';
  loading?: boolean;
  error?: boolean;
}) {
  const valueText =
    typeof value === 'string' || typeof value === 'number' ? String(value) : '';
  const accentRing: Record<NonNullable<typeof accent>, string> = {
    neutral: 'hover:border-content-secondary',
    blue: 'hover:border-oe-blue',
    success: 'hover:border-emerald-500',
    warning: 'hover:border-amber-500',
    error: 'hover:border-rose-500',
  };
  const iconColor: Record<NonNullable<typeof accent>, string> = {
    neutral: 'text-content-secondary',
    blue: 'text-oe-blue',
    success: 'text-emerald-600',
    warning: 'text-amber-600',
    error: 'text-rose-600',
  };
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      aria-label={valueText ? `${label}: ${valueText}` : label}
      className={clsx(
        'group rounded-xl border border-border-light bg-surface-primary p-3 text-left transition-all',
        'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
        onClick && 'cursor-pointer',
        accent && accentRing[accent],
        'min-h-[88px] flex flex-col justify-between',
      )}
    >
      <div className="flex items-center justify-between text-xs text-content-tertiary">
        <span
          className={clsx(
            'flex items-center gap-1.5',
            accent && iconColor[accent],
          )}
        >
          {icon}
          <span className="line-clamp-1">{label}</span>
        </span>
        {error && (
          <AlertOctagon
            size={11}
            className="text-rose-500 shrink-0"
            aria-label="error"
          />
        )}
      </div>
      <div className="mt-2 text-xl font-semibold text-content-primary leading-none">
        {loading ? (
          <span className="inline-block h-5 w-12 rounded bg-surface-secondary animate-pulse" />
        ) : (
          value
        )}
      </div>
    </button>
  );
}
