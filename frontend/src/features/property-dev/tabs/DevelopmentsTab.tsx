// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Developments tab — grid of development cards. Drives the primary
 * "drill into plots" path from the top-level Developments view.
 *
 * Renamed in spirit to ``DevelopmentsTab`` for naming parity with the
 * other tab modules; the exported component retains the original
 * ``DevelopmentsGrid`` identifier to avoid a rename in callers and
 * tests. ``DevelopmentCard`` is co-located here — only this tab
 * renders it.
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Building2,
  LayoutDashboard,
} from 'lucide-react';
import { Badge, Card, EmptyState } from '@/shared/ui';
import { MultiCurrencyTotal } from '@/shared/ui/MultiCurrencyTotal';
import { getDevelopmentDashboard, type Development } from '../api';

export function DevelopmentsGrid({
  rows,
  onSelect,
  onCreate,
}: {
  rows: Development[];
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Building2 size={22} />}
          title={t('propdev.empty_developments', { defaultValue: 'No developments yet' })}
          description={t('propdev.empty_developments_desc', {
            defaultValue: 'Create your first development to start tracking plots, buyers and handovers.',
          })}
          action={{
            label: t('propdev.new_development', { defaultValue: 'New Development' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {rows.map((d) => (
        <DevelopmentCard key={d.id} dev={d} onSelect={onSelect} />
      ))}
    </div>
  );
}

function DevelopmentCard({
  dev,
  onSelect,
}: {
  dev: Development;
  onSelect: (id: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const dashQ = useQuery({
    queryKey: ['propdev', 'dashboard', dev.id],
    queryFn: () => getDevelopmentDashboard(dev.id),
    staleTime: 60_000,
  });
  const dash = dashQ.data;
  const sold = dash
    ? (dash.plots_by_status['sold'] ?? 0) + (dash.plots_by_status['handed_over'] ?? 0)
    : 0;
  const total = dash?.total_plots ?? dev.total_plots ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((sold / total) * 100)) : 0;
  // Use a card-with-footer layout: the main body navigates to the
  // plots tab for this development (primary CTA), while the small
  // footer carries a secondary "Open dashboards" deep link. Footer
  // ``stopPropagation`` prevents bubbling up into the body's onClick.
  return (
    <Card padding="md" hoverable>
      <button
        type="button"
        onClick={() => onSelect(dev.id)}
        className="text-left w-full focus:outline-none"
        aria-label={t('propdev.open_development_aria', {
          defaultValue: 'Open development {{name}}',
          name: dev.name || dev.code,
        })}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3
              className="font-semibold text-content-primary truncate"
              title={dev.name || dev.code}
            >
              {dev.name || dev.code}
            </h3>
            <p className="mt-0.5 text-xs font-mono text-content-tertiary">
              {dev.code}
            </p>
          </div>
          <Badge
            variant={
              dev.status === 'active'
                ? 'success'
                : dev.status === 'paused'
                  ? 'warning'
                  : 'neutral'
            }
            dot
          >
            {dev.sales_phase}
          </Badge>
        </div>
        {dev.location_address && (
          <p className="mt-1 text-xs text-content-secondary line-clamp-1">
            {dev.location_address}
          </p>
        )}
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-content-secondary mb-1">
            <span>
              {t('propdev.plots_sold', {
                defaultValue: '{{sold}}/{{total}} plots sold',
                sold,
                total,
              })}
            </span>
            <span className="font-medium tabular-nums">{pct}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary">
            <div
              className="h-full bg-oe-blue transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
        {dash && (
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
            <div>
              <p className="text-content-tertiary">
                {t('propdev.contracted', { defaultValue: 'Contracted' })}
              </p>
              <p className="font-medium">
                {/* Buyers in a development may contract in different
                    currencies, so render the honest per-currency breakdown
                    rather than a single blended figure (mirrors OverviewTab). */}
                <MultiCurrencyTotal
                  variant="inline"
                  compact
                  items={Object.entries(
                    dash.contracted_value_by_currency ?? {},
                  ).map(([currency, amount]) => ({ amount, currency }))}
                />
              </p>
            </div>
            <div>
              <p className="text-content-tertiary">
                {t('propdev.open_snags', { defaultValue: 'Open snags' })}
              </p>
              <p className="font-medium">{dash.open_snags}</p>
            </div>
          </div>
        )}
      </button>
      <div className="mt-3 -mx-3 -mb-3 border-t border-border-light bg-surface-secondary/40 px-3 py-2 flex items-center justify-end gap-2 text-xs">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            navigate('/property-dev/dashboards');
          }}
          className="inline-flex items-center gap-1 rounded text-content-tertiary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
          aria-label={t('propdev.open_dashboards_for', {
            defaultValue: 'Open analytics dashboards',
          })}
        >
          <LayoutDashboard size={12} />
          {t('propdev.dashboards_short', { defaultValue: 'Dashboards' })}
        </button>
      </div>
    </Card>
  );
}
