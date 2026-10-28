// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plots tab — grid view of plot tiles with status filter chips.
 * Extracted from the monolithic ``PropertyDevPage.tsx``. Tile colours
 * come from the shared ``PLOT_STATUS_COLOR`` map so other surfaces
 * (legend chip, plot button) stay in lock-step.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Grid3X3, Plus } from 'lucide-react';
import { Button, Card, EmptyState } from '@/shared/ui';
import type { HouseType, Plot, PlotStatus } from '../api';
import { PLOT_STATUS_COLOR } from './_shared';

export function PlotsTab({
  plots,
  houseTypes,
  onSelect,
  onCreate,
}: {
  plots: Plot[];
  houseTypes: HouseType[];
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const [statusFilter, setStatusFilter] = useState<PlotStatus | null>(null);
  // Status counts drive the legend chip badges so the operator can
  // see at-a-glance how many plots sit in each state. Clicking a chip
  // toggles a filter that narrows the grid below; clicking again
  // (or "Clear") restores the full view.
  const statusCounts = useMemo(() => {
    const out = {} as Record<PlotStatus, number>;
    for (const s of Object.keys(PLOT_STATUS_COLOR) as PlotStatus[]) out[s] = 0;
    for (const p of plots) out[p.status] = (out[p.status] ?? 0) + 1;
    return out;
  }, [plots]);
  const visiblePlots = useMemo(
    () => (statusFilter ? plots.filter((p) => p.status === statusFilter) : plots),
    [plots, statusFilter],
  );

  if (plots.length === 0) {
    return (
      <Card padding="md">
        <EmptyState
          icon={<Grid3X3 size={22} />}
          title={t('propdev.empty_plots', { defaultValue: 'No plots' })}
          description={t('propdev.empty_plots_desc', {
            defaultValue: 'Add plots to the selected development to start the sales pipeline.',
          })}
          action={{
            label: t('propdev.new_plot', { defaultValue: 'New Plot' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  const htMap = new Map(houseTypes.map((h) => [h.id, h]));
  return (
    <Card padding="md">
      {/* Filterable status legend. Each chip doubles as a filter
          toggle + counter, so the user can drill in to "show only
          reserved plots" with one click and read the funnel
          distribution at the same time. */}
      <div
        className="flex flex-wrap items-center gap-2 mb-3"
        role="toolbar"
        aria-label={t('propdev.plot_status_filter', { defaultValue: 'Filter plots by status' })}
      >
        {(Object.keys(PLOT_STATUS_COLOR) as PlotStatus[]).map((s) => {
          const active = statusFilter === s;
          const count = statusCounts[s] ?? 0;
          return (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(active ? null : s)}
              aria-pressed={active}
              disabled={count === 0 && !active}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue/40',
                active
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:border-border-light disabled:hover:text-content-tertiary',
              )}
            >
              <span className={clsx('h-2.5 w-2.5 rounded-sm border', PLOT_STATUS_COLOR[s])} />
              <span>{t(`propdev.plot.status.${s}`, { defaultValue: s.replace('_', ' ') })}</span>
              <span className="font-mono tabular-nums text-content-tertiary">{count}</span>
            </button>
          );
        })}
        {statusFilter != null && (
          <button
            type="button"
            onClick={() => setStatusFilter(null)}
            className="text-xs text-content-tertiary hover:text-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/40 rounded"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
        <div className="ml-auto inline-flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            icon={<Plus size={12} />}
            onClick={onCreate}
            data-testid="plots-tab-add"
          >
            {t('propdev.new_plot', { defaultValue: 'New Plot' })}
          </Button>
        </div>
      </div>
      {visiblePlots.length === 0 ? (
        <p className="px-2 py-6 text-center text-sm text-content-tertiary">
          {t('propdev.no_plots_for_status', {
            defaultValue: 'No plots in this status.',
          })}
        </p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(72px,1fr))] gap-1.5">
          {visiblePlots.map((p) => {
            const ht = p.house_type_id ? htMap.get(p.house_type_id) : null;
            return (
              <button
                key={p.id}
                type="button"
                onClick={() => onSelect(p.id)}
                className={clsx(
                  'flex flex-col items-center justify-center rounded-md border-2 px-1 py-2 text-center transition-all hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-oe-blue',
                  PLOT_STATUS_COLOR[p.status],
                )}
                title={`${p.plot_number} - ${p.status}`}
                data-testid="plot-tile"
              >
                <span className="text-xs font-semibold leading-none">{p.plot_number}</span>
                {ht && <span className="mt-0.5 text-[10px] opacity-80">{ht.code}</span>}
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}
