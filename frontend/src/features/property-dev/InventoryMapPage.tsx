// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inventory Map page (task #142) - sales-floor block / floor / unit grid.
 *
 * The sales desk's daily index of every Plot in a Development. Replaces
 * the flat-table scroll with a colour-coded tile grid, KPI ribbon, bulk
 * filters and a hold/release floating action bar.
 *
 * Distinct from /dashboards/inventory-heatmap (task #140) - that one is
 * an analytics phase-grouped view; this is the sales-floor workflow view
 * with bulk actions.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Building2,
  ChevronDown,
  ChevronRight,
  Filter,
  Loader2,
  Lock,
  RefreshCw,
  Unlock,
  X,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  IntroRichText,
  SideDrawer,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import {
  bulkHoldInventory,
  bulkReleaseInventory,
  getInventoryMap,
  type InventoryMapBlock,
  type InventoryMapPlot,
  type InventoryMapSummary,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ──────────────────────────────────────────────────────────────────────
 * Status palette - sales-desk colours match the task spec:
 *   available  green-500    reserved   amber-500
 *   sold       gray-500     handed_over slate-700
 *   held       purple-500   blocked    red-500
 *
 * We re-derive ``available`` from ``planned`` / ``ready`` so the wire
 * format stays canonical.
 * ──────────────────────────────────────────────────────────────────── */

const STATUS_FILL: Record<string, string> = {
  available: '#22c55e', // green-500
  planned: '#22c55e',
  ready: '#22c55e',
  reserved: '#f59e0b', // amber-500
  sold: '#6b7280', // gray-500
  handed_over: '#334155', // slate-700
  held: '#a855f7', // purple-500
  blocked: '#ef4444', // red-500
  under_construction: '#fb923c', // orange-400
};

const ALL_FILTER_STATUSES: (keyof InventoryMapSummary | 'all')[] = [
  'all',
  'available',
  'reserved',
  'sold',
  'handed_over',
  'held',
  'blocked',
];

function statusForFilterKey(plot: InventoryMapPlot): string {
  // The ribbon's ``available`` filter must match both planned + ready
  // plots (canonical statuses on the wire).
  if (plot.status === 'planned' || plot.status === 'ready') return 'available';
  return plot.status;
}

interface FilterState {
  statusKey: string; // 'all' | keyof summary
  plotTypes: Set<string>;
  floors: Set<number>;
  priceMin: number;
  priceMax: number;
  areaMin: number;
  areaMax: number;
}

const EMPTY_FILTER: FilterState = {
  statusKey: 'all',
  plotTypes: new Set(),
  floors: new Set(),
  priceMin: 0,
  priceMax: Number.POSITIVE_INFINITY,
  areaMin: 0,
  areaMax: Number.POSITIVE_INFINITY,
};

function num(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  if (typeof v === 'number') return Number.isFinite(v) ? v : 0;
  const parsed = Number(v);
  return Number.isFinite(parsed) ? parsed : 0;
}

/* ────────────────────────────────────────────────────────────────────── */

export function InventoryMapPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ devId: string }>();
  const devId = params.devId ?? '';
  const queryClient = useQueryClient();
  const pushToast = useToastStore((s) => s.addToast);

  // ── Data ────────────────────────────────────────────────────────────
  const query = useQuery({
    queryKey: ['property-dev', 'inventory-map', devId],
    queryFn: () => getInventoryMap(devId),
    enabled: Boolean(devId),
    staleTime: 30_000,
  });

  // ── Filters ─────────────────────────────────────────────────────────
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTER);

  const allPlots = useMemo<InventoryMapPlot[]>(() => {
    if (!query.data) return [];
    return query.data.blocks.flatMap((b) =>
      b.floors.flatMap((f) => f.plots),
    );
  }, [query.data]);

  const plotTypeOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const p of allPlots) {
      if (p.plot_type) seen.add(p.plot_type);
    }
    return Array.from(seen).sort();
  }, [allPlots]);

  const floorOptions = useMemo(() => {
    const seen = new Set<number>();
    for (const p of allPlots) {
      if (p.floor !== null && p.floor !== undefined) seen.add(p.floor);
    }
    return Array.from(seen).sort((a, b) => b - a);
  }, [allPlots]);

  const priceBounds = useMemo(() => {
    if (allPlots.length === 0) return { min: 0, max: 0 };
    const prices = allPlots.map((p) => num(p.base_price));
    return { min: Math.min(...prices), max: Math.max(...prices) };
  }, [allPlots]);

  const filterPlot = useCallback(
    (plot: InventoryMapPlot): boolean => {
      if (
        filters.statusKey !== 'all' &&
        statusForFilterKey(plot) !== filters.statusKey
      ) {
        return false;
      }
      if (
        filters.plotTypes.size > 0 &&
        (!plot.plot_type || !filters.plotTypes.has(plot.plot_type))
      ) {
        return false;
      }
      if (
        filters.floors.size > 0 &&
        (plot.floor === null || !filters.floors.has(plot.floor))
      ) {
        return false;
      }
      const price = num(plot.base_price);
      if (price < filters.priceMin || price > filters.priceMax) return false;
      const area = num(plot.area_m2);
      if (area < filters.areaMin || area > filters.areaMax) return false;
      return true;
    },
    [filters],
  );

  const visibleBlocks = useMemo<InventoryMapBlock[]>(() => {
    if (!query.data) return [];
    return query.data.blocks
      .map((b) => ({
        ...b,
        floors: b.floors
          .map((f) => ({ ...f, plots: f.plots.filter(filterPlot) }))
          .filter((f) => f.plots.length > 0),
      }))
      .filter((b) => b.floors.length > 0);
  }, [query.data, filterPlot]);

  // ── Selection ───────────────────────────────────────────────────────
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const lastClickedRef = useRef<string | null>(null);

  // Flat list of visible plot ids (used for shift-range selection).
  const flatVisibleIds = useMemo(
    () => visibleBlocks.flatMap((b) => b.floors.flatMap((f) => f.plots.map((p) => p.id))),
    [visibleBlocks],
  );

  const toggleSelection = useCallback(
    (plotId: string, modifiers: { shift: boolean; meta: boolean }) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (modifiers.shift && lastClickedRef.current) {
          // Shift-range selection across the flat visible list.
          const ids = flatVisibleIds;
          const a = ids.indexOf(lastClickedRef.current);
          const b = ids.indexOf(plotId);
          if (a !== -1 && b !== -1) {
            const [lo, hi] = a < b ? [a, b] : [b, a];
            for (let i = lo; i <= hi; i += 1) {
              const id = ids[i];
              if (id) next.add(id);
            }
            return next;
          }
        }
        if (next.has(plotId)) {
          next.delete(plotId);
        } else {
          next.add(plotId);
        }
        return next;
      });
      if (!modifiers.shift) {
        lastClickedRef.current = plotId;
      }
    },
    [flatVisibleIds],
  );

  const clearSelection = useCallback(() => {
    setSelected(new Set());
    lastClickedRef.current = null;
  }, []);

  // Drop selections that became invisible after a filter change.
  useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(flatVisibleIds);
      const next = new Set<string>();
      for (const id of prev) if (visible.has(id)) next.add(id);
      return next.size === prev.size ? prev : next;
    });
  }, [flatVisibleIds]);

  // ── Drawer ──────────────────────────────────────────────────────────
  const [drawerPlotId, setDrawerPlotId] = useState<string | null>(null);
  const drawerPlot = useMemo(
    () => allPlots.find((p) => p.id === drawerPlotId) ?? null,
    [allPlots, drawerPlotId],
  );

  // ── Hold modal ──────────────────────────────────────────────────────
  const [holdModalOpen, setHoldModalOpen] = useState(false);
  const [holdReason, setHoldReason] = useState('');
  const [holdUntil, setHoldUntil] = useState('');

  const holdMutation = useMutation({
    mutationFn: () =>
      bulkHoldInventory(
        devId,
        Array.from(selected),
        holdReason.trim(),
        holdUntil.trim() || null,
      ),
    onSuccess: (result) => {
      pushToast({
        type: 'success',
        title: t('propdev.inventory_map.hold_done', {
          defaultValue: '{{count}} plots held',
          count: result.updated_count,
        }),
      });
      setHoldModalOpen(false);
      setHoldReason('');
      setHoldUntil('');
      clearSelection();
      queryClient.invalidateQueries({
        queryKey: ['property-dev', 'inventory-map', devId],
      });
    },
    onError: (err) => {
      pushToast({
        type: 'error',
        title: t('propdev.inventory_map.hold_failed', {
          defaultValue: 'Hold failed',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const releaseMutation = useMutation({
    mutationFn: () => bulkReleaseInventory(devId, Array.from(selected)),
    onSuccess: (result) => {
      pushToast({
        type: 'success',
        title: t('propdev.inventory_map.release_done', {
          defaultValue: '{{count}} plots released',
          count: result.updated_count,
        }),
      });
      clearSelection();
      queryClient.invalidateQueries({
        queryKey: ['property-dev', 'inventory-map', devId],
      });
    },
    onError: (err) => {
      pushToast({
        type: 'error',
        title: t('propdev.inventory_map.release_failed', {
          defaultValue: 'Release failed',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  // ── Keyboard navigation ─────────────────────────────────────────────
  const handleTileKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, plotId: string) => {
      if (e.key === ' ' || e.key === 'Spacebar') {
        e.preventDefault();
        toggleSelection(plotId, { shift: e.shiftKey, meta: e.metaKey });
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        setDrawerPlotId(plotId);
        return;
      }
      if (e.key.startsWith('Arrow')) {
        e.preventDefault();
        const ids = flatVisibleIds;
        const idx = ids.indexOf(plotId);
        if (idx === -1) return;
        const targetIdx =
          e.key === 'ArrowRight' || e.key === 'ArrowDown'
            ? Math.min(idx + 1, ids.length - 1)
            : Math.max(idx - 1, 0);
        const targetId = ids[targetIdx];
        if (!targetId) return;
        const el = document.querySelector<HTMLButtonElement>(
          `[data-plot-id="${CSS.escape(targetId)}"]`,
        );
        el?.focus();
      }
    },
    [flatVisibleIds, toggleSelection],
  );

  /* ── Render ──────────────────────────────────────────────────────── */

  if (!devId) {
    return (
      <EmptyState
        title={t('propdev.inventory_map.no_dev', {
          defaultValue: 'No development selected',
        })}
      />
    );
  }

  const summary = query.data?.summary;

  return (
    <div className="space-y-5 animate-fade-in" data-testid="inventory-map-page">
      <Breadcrumb
        items={[
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            to: '/property-dev',
          },
          {
            label: t('propdev.inventory_map.title', {
              defaultValue: 'Inventory Map',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('propdev.inventory_map.title', {
          defaultValue: 'Inventory Map',
        })}
        subtitle={t('propdev.inventory_map.subtitle', {
          defaultValue:
            'Block, floor and unit grid for the sales floor. Click tiles to inspect, cmd/shift-click to select, then hold or release in bulk.',
        })}
        actions={
          <Button
            variant="ghost"
            icon={<RefreshCw size={14} />}
            onClick={() => query.refetch()}
            disabled={query.isFetching}
            aria-label={t('common.refresh', { defaultValue: 'Refresh' })}
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="propdev-inventory-map"
        title={t('propdev_inventory_map.intro_title', {
          defaultValue: 'See the whole sales floor at a glance',
        })}
        more={t('propdev_inventory_map.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('propdev_inventory_map.intro_more')} /> : undefined}
        links={[
          ...(devId
            ? [
                {
                  label: t('propdev.pricing.title', {
                    defaultValue: 'Pricing engine',
                  }),
                  onClick: () =>
                    navigate(`/property-dev/developments/${devId}/pricing`),
                },
              ]
            : []),
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            onClick: () => navigate('/property-dev'),
          },
        ]}
      >
        {t('propdev_inventory_map.intro_body', {
          defaultValue:
            'A block, floor and unit grid showing the live status of every plot in a development, with a KPI ribbon to filter and shift-click to select. Click a tile to inspect a unit or select several to hold or release them in bulk, feeding straight back into reservations and pricing.',
        })}
      </DismissibleInfo>

      {/* ── KPI ribbon ─────────────────────────────────────────────── */}
      {summary && (
        <SummaryRibbon
          summary={summary}
          activeKey={filters.statusKey}
          onPick={(key) =>
            setFilters((prev) => ({ ...prev, statusKey: key }))
          }
        />
      )}

      {/* ── Filters ────────────────────────────────────────────────── */}
      <FilterBar
        filters={filters}
        setFilters={setFilters}
        plotTypes={plotTypeOptions}
        floors={floorOptions}
        priceBounds={priceBounds}
      />

      {/* ── Body ───────────────────────────────────────────────────── */}
      {query.isLoading && <InventoryMapSkeleton />}
      {query.isError && (
        <Card className="border-semantic-error/40 bg-semantic-error/5 p-4">
          <p className="text-sm font-medium text-semantic-error">
            {t('propdev.inventory_map.load_error', {
              defaultValue: 'Failed to load inventory map.',
            })}
          </p>
          <p className="mt-1 text-xs text-content-secondary">
            {getErrorMessage(query.error)}
          </p>
          <Button
            variant="secondary"
            className="mt-3"
            onClick={() => query.refetch()}
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </Card>
      )}
      {!query.isLoading && !query.isError && allPlots.length === 0 && (
        <EmptyState
          icon={<Building2 size={20} />}
          title={t('propdev.inventory_map.empty_title', {
            defaultValue: 'No plots in this development yet',
          })}
          description={t('propdev.inventory_map.empty_desc', {
            defaultValue:
              'Import plots from CSV or add the first one to see the inventory grid.',
          })}
          action={
            <Link to="/property-dev">
              <Button variant="primary">
                {t('propdev.inventory_map.empty_cta', {
                  defaultValue: 'Add first plot',
                })}
              </Button>
            </Link>
          }
        />
      )}

      {!query.isLoading &&
        !query.isError &&
        allPlots.length > 0 &&
        visibleBlocks.length === 0 && (
          <EmptyState
            title={t('propdev.inventory_map.filtered_empty_title', {
              defaultValue: 'No plots match these filters',
            })}
            description={t('propdev.inventory_map.filtered_empty_desc', {
              defaultValue:
                'Clear or relax your filters to see plots again.',
            })}
            action={
              <Button
                variant="secondary"
                onClick={() => setFilters(EMPTY_FILTER)}
              >
                {t('propdev.inventory_map.clear_filters', {
                  defaultValue: 'Clear filters',
                })}
              </Button>
            }
          />
        )}

      {!query.isLoading && visibleBlocks.length > 0 && (
        <div className="space-y-4">
          {visibleBlocks.map((block) => (
            <BlockCard
              key={`${block.block_code}-${block.block_id ?? 'unassigned'}`}
              block={block}
              selected={selected}
              onTileClick={toggleSelection}
              onTileOpen={setDrawerPlotId}
              onTileKeyDown={handleTileKeyDown}
            />
          ))}
        </div>
      )}

      {/* ── Floating action bar ────────────────────────────────────── */}
      {selected.size > 0 && (
        <FloatingActionBar
          count={selected.size}
          onHold={() => setHoldModalOpen(true)}
          onRelease={() => releaseMutation.mutate()}
          onClear={clearSelection}
          releasing={releaseMutation.isPending}
        />
      )}

      {/* ── Plot drawer ────────────────────────────────────────────── */}
      <SideDrawer
        open={Boolean(drawerPlot)}
        onClose={() => setDrawerPlotId(null)}
        title={
          drawerPlot
            ? t('propdev.inventory_map.drawer_title', {
                defaultValue: 'Plot {{code}}',
                code: drawerPlot.unit_code,
              })
            : ''
        }
      >
        {drawerPlot && <PlotDrawerBody plot={drawerPlot} />}
      </SideDrawer>

      {/* ── Hold modal ─────────────────────────────────────────────── */}
      {holdModalOpen && (
        <HoldModal
          count={selected.size}
          reason={holdReason}
          until={holdUntil}
          submitting={holdMutation.isPending}
          onReasonChange={setHoldReason}
          onUntilChange={setHoldUntil}
          onCancel={() => setHoldModalOpen(false)}
          onSubmit={() => holdMutation.mutate()}
        />
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

interface SummaryRibbonProps {
  summary: InventoryMapSummary;
  activeKey: string;
  onPick: (key: string) => void;
}

function SummaryRibbon({ summary, activeKey, onPick }: SummaryRibbonProps) {
  const { t } = useTranslation();
  return (
    <div
      className="flex flex-wrap gap-2"
      role="group"
      aria-label={t('propdev.inventory_map.kpi_aria', {
        defaultValue: 'Inventory KPI ribbon - click a card to filter',
      })}
      data-testid="inventory-map-kpi"
    >
      {ALL_FILTER_STATUSES.map((key) => {
        const count =
          key === 'all'
            ? summary.total
            : (summary[key as keyof InventoryMapSummary] ?? 0);
        const fill = key === 'all' ? '#0ea5e9' : STATUS_FILL[key] ?? '#94a3b8';
        const isActive = activeKey === key;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onPick(key)}
            aria-pressed={isActive}
            data-testid={`kpi-${key}`}
            className={clsx(
              'flex min-w-[110px] flex-col items-start rounded-xl border px-3 py-2 text-left transition-colors',
              isActive
                ? 'border-oe-blue bg-oe-blue/10'
                : 'border-divider/60 bg-surface-primary hover:bg-surface-secondary/40',
            )}
            style={{ borderLeft: `4px solid ${fill}` }}
          >
            <span className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t(`propdev.inventory_map.kpi.${key}`, {
                defaultValue: key.replace(/_/g, ' '),
              })}
            </span>
            <span className="text-lg font-semibold text-content-primary">
              {count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

interface FilterBarProps {
  filters: FilterState;
  setFilters: (next: FilterState) => void;
  plotTypes: string[];
  floors: number[];
  priceBounds: { min: number; max: number };
}

function FilterBar({
  filters,
  setFilters,
  plotTypes,
  floors,
  priceBounds,
}: FilterBarProps) {
  const { t } = useTranslation();
  const togglePlotType = (val: string) => {
    const next = new Set(filters.plotTypes);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    setFilters({ ...filters, plotTypes: next });
  };
  const toggleFloor = (val: number) => {
    const next = new Set(filters.floors);
    if (next.has(val)) next.delete(val);
    else next.add(val);
    setFilters({ ...filters, floors: next });
  };

  const hasActive =
    filters.statusKey !== 'all' ||
    filters.plotTypes.size > 0 ||
    filters.floors.size > 0 ||
    filters.priceMin > 0 ||
    Number.isFinite(filters.priceMax) ||
    filters.areaMin > 0 ||
    Number.isFinite(filters.areaMax);

  return (
    <Card className="p-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 text-sm text-content-secondary">
          <Filter size={14} />
          <span>
            {t('propdev.inventory_map.filters', { defaultValue: 'Filters' })}
          </span>
        </div>
        {plotTypes.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-2xs uppercase text-content-tertiary">
              {t('propdev.inventory_map.filter_type', {
                defaultValue: 'Type',
              })}
            </span>
            {plotTypes.map((pt) => (
              <button
                key={pt}
                type="button"
                onClick={() => togglePlotType(pt)}
                aria-pressed={filters.plotTypes.has(pt)}
                className={clsx(
                  'rounded-full border px-2 py-0.5 text-2xs transition-colors',
                  filters.plotTypes.has(pt)
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-divider/60 text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {pt}
              </button>
            ))}
          </div>
        )}
        {floors.length > 0 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-2xs uppercase text-content-tertiary">
              {t('propdev.inventory_map.filter_floor', {
                defaultValue: 'Floor',
              })}
            </span>
            {floors.map((fl) => (
              <button
                key={fl}
                type="button"
                onClick={() => toggleFloor(fl)}
                aria-pressed={filters.floors.has(fl)}
                className={clsx(
                  'rounded-full border px-2 py-0.5 text-2xs transition-colors',
                  filters.floors.has(fl)
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-divider/60 text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {fl}
              </button>
            ))}
          </div>
        )}
        <RangeInput
          label={t('propdev.inventory_map.filter_price', {
            defaultValue: 'Price',
          })}
          min={filters.priceMin}
          max={filters.priceMax}
          bounds={priceBounds}
          onMinChange={(v) => setFilters({ ...filters, priceMin: v })}
          onMaxChange={(v) => setFilters({ ...filters, priceMax: v })}
        />
        <RangeInput
          label={t('propdev.inventory_map.filter_area', {
            defaultValue: 'Area m²',
          })}
          min={filters.areaMin}
          max={filters.areaMax}
          bounds={{ min: 0, max: 1000 }}
          onMinChange={(v) => setFilters({ ...filters, areaMin: v })}
          onMaxChange={(v) => setFilters({ ...filters, areaMax: v })}
        />
        {hasActive && (
          <Button
            variant="ghost"
            size="sm"
            icon={<X size={12} />}
            onClick={() => setFilters(EMPTY_FILTER)}
          >
            {t('propdev.inventory_map.clear_filters', {
              defaultValue: 'Clear',
            })}
          </Button>
        )}
      </div>
    </Card>
  );
}

interface RangeInputProps {
  label: string;
  min: number;
  max: number;
  bounds: { min: number; max: number };
  onMinChange: (v: number) => void;
  onMaxChange: (v: number) => void;
}

function RangeInput({
  label,
  min,
  max,
  bounds,
  onMinChange,
  onMaxChange,
}: RangeInputProps) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-2xs uppercase text-content-tertiary">{label}</span>
      <input
        type="number"
        min={bounds.min}
        max={bounds.max}
        value={min === 0 ? '' : min}
        placeholder={String(bounds.min)}
        onChange={(e) => onMinChange(Number(e.target.value) || 0)}
        className="w-20 rounded border border-divider/60 px-1.5 py-0.5 text-xs"
        aria-label={`${label} min`}
      />
      <span className="text-2xs text-content-tertiary">—</span>
      <input
        type="number"
        min={bounds.min}
        max={bounds.max}
        value={Number.isFinite(max) ? max : ''}
        placeholder={String(bounds.max)}
        onChange={(e) =>
          onMaxChange(Number(e.target.value) || Number.POSITIVE_INFINITY)
        }
        className="w-20 rounded border border-divider/60 px-1.5 py-0.5 text-xs"
        aria-label={`${label} max`}
      />
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

interface BlockCardProps {
  block: InventoryMapBlock;
  selected: Set<string>;
  onTileClick: (
    plotId: string,
    modifiers: { shift: boolean; meta: boolean },
  ) => void;
  onTileOpen: (plotId: string) => void;
  onTileKeyDown: (e: KeyboardEvent<HTMLButtonElement>, plotId: string) => void;
}

function BlockCard({
  block,
  selected,
  onTileClick,
  onTileOpen,
  onTileKeyDown,
}: BlockCardProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(false);
  const unitCount = block.floors.reduce((acc, f) => acc + f.plots.length, 0);
  return (
    <Card className="p-3">
      <header className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-2 text-left"
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <ChevronRight size={14} className="text-content-tertiary" />
          ) : (
            <ChevronDown size={14} className="text-content-tertiary" />
          )}
          <Badge variant="neutral">{block.block_code}</Badge>
          <span className="text-sm font-semibold text-content-primary">
            {block.name || block.block_code}
          </span>
        </button>
        <span className="text-2xs text-content-tertiary">
          {t('propdev.inventory_map.units_count', {
            defaultValue: '{{count}} units',
            count: unitCount,
          })}
        </span>
      </header>
      {!collapsed && (
        <div
          role="grid"
          aria-label={t('propdev.inventory_map.grid_aria', {
            defaultValue: 'Plot grid for block {{code}}',
            code: block.block_code,
          })}
          className="space-y-1.5"
        >
          {block.floors.map((floor) => (
            <div
              key={floor.floor}
              role="row"
              className="flex items-center gap-2"
            >
              <span
                className="w-10 shrink-0 text-right text-2xs text-content-tertiary"
                aria-label={t('propdev.inventory_map.floor_aria', {
                  defaultValue: 'Floor {{floor}}',
                  floor: floor.floor,
                })}
              >
                F{floor.floor}
              </span>
              <div className="flex flex-wrap gap-1">
                {floor.plots.map((p) => (
                  <PlotTile
                    key={p.id}
                    plot={p}
                    selected={selected.has(p.id)}
                    onClick={onTileClick}
                    onOpen={onTileOpen}
                    onKeyDown={onTileKeyDown}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

interface PlotTileProps {
  plot: InventoryMapPlot;
  selected: boolean;
  onClick: (
    plotId: string,
    modifiers: { shift: boolean; meta: boolean },
  ) => void;
  onOpen: (plotId: string) => void;
  onKeyDown: (e: KeyboardEvent<HTMLButtonElement>, plotId: string) => void;
}

function PlotTile({
  plot,
  selected,
  onClick,
  onOpen,
  onKeyDown,
}: PlotTileProps) {
  const { t } = useTranslation();
  const displayStatus = statusForFilterKey(plot);
  const fill = STATUS_FILL[displayStatus] ?? STATUS_FILL[plot.status] ?? '#94a3b8';

  const label = t('propdev.inventory_map.tile_aria', {
    defaultValue:
      'Plot {{code}}, {{type}}, {{status}}, {{price}}',
    code: plot.unit_code,
    type: plot.plot_type ?? '—',
    status: t(`propdev.inventory_map.kpi.${displayStatus}`, {
      defaultValue: displayStatus.replace(/_/g, ' '),
    }),
    price: `${num(plot.base_price).toLocaleString(getNumberLocale())} ${plot.currency}`,
  });

  const style: CSSProperties = {
    backgroundColor: fill,
    borderColor: selected ? '#0ea5e9' : 'rgba(0,0,0,0.1)',
  };

  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    // Cmd / Ctrl / Shift modify selection; plain click opens the drawer.
    if (e.shiftKey || e.metaKey || e.ctrlKey) {
      onClick(plot.id, { shift: e.shiftKey, meta: e.metaKey || e.ctrlKey });
      return;
    }
    onOpen(plot.id);
  };

  return (
    <button
      type="button"
      role="gridcell"
      data-plot-id={plot.id}
      data-testid={`plot-tile-${plot.id}`}
      aria-label={label}
      aria-selected={selected}
      title={label}
      onClick={handleClick}
      onKeyDown={(e) => onKeyDown(e, plot.id)}
      className={clsx(
        'h-16 w-16 cursor-pointer rounded-md border-2 text-2xs font-medium text-white',
        'flex flex-col items-center justify-center',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue focus-visible:ring-offset-1',
        selected && 'ring-2 ring-oe-blue ring-offset-1',
      )}
      style={style}
    >
      <span className="leading-tight">{plot.unit_code.split('-').pop()}</span>
      {plot.plot_type && (
        <span className="mt-0.5 opacity-90 leading-none">{plot.plot_type}</span>
      )}
    </button>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

function InventoryMapSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      {[0, 1, 2].map((i) => (
        <Card key={i} className="p-3">
          <div className="mb-3 h-4 w-32 animate-pulse rounded bg-surface-secondary" />
          <div className="space-y-1.5">
            {[0, 1, 2].map((row) => (
              <div key={row} className="flex items-center gap-2">
                <div className="h-3 w-10 animate-pulse rounded bg-surface-secondary" />
                <div className="flex flex-wrap gap-1">
                  {Array.from({ length: 6 }).map((_, c) => (
                    <div
                      key={c}
                      className="h-16 w-16 animate-pulse rounded-md bg-surface-secondary"
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

interface FloatingActionBarProps {
  count: number;
  onHold: () => void;
  onRelease: () => void;
  onClear: () => void;
  releasing: boolean;
}

function FloatingActionBar({
  count,
  onHold,
  onRelease,
  onClear,
  releasing,
}: FloatingActionBarProps) {
  const { t } = useTranslation();
  return (
    <div
      role="toolbar"
      aria-label={t('propdev.inventory_map.action_bar_aria', {
        defaultValue: 'Bulk actions on selected plots',
      })}
      className={clsx(
        'fixed inset-x-0 bottom-4 z-40 mx-auto flex w-fit max-w-full items-center gap-2',
        'rounded-xl bg-surface-primary px-3 py-2 shadow-lg ring-1 ring-divider/60',
        'md:bottom-6',
      )}
      data-testid="inventory-map-action-bar"
    >
      <span className="px-2 text-sm font-medium text-content-primary">
        {t('propdev.inventory_map.selected_count', {
          defaultValue: '{{count}} selected',
          count,
        })}
      </span>
      <Button
        variant="primary"
        size="sm"
        icon={<Lock size={12} />}
        onClick={onHold}
      >
        {t('propdev.inventory_map.hold_btn', {
          defaultValue: 'Hold {{count}}',
          count,
        })}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        icon={<Unlock size={12} />}
        onClick={onRelease}
        disabled={releasing}
      >
        {releasing ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          t('propdev.inventory_map.release_btn', {
            defaultValue: 'Release {{count}}',
            count,
          })
        )}
      </Button>
      <Button variant="ghost" size="sm" icon={<X size={12} />} onClick={onClear}>
        {t('common.clear', { defaultValue: 'Clear' })}
      </Button>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

function PlotDrawerBody({ plot }: { plot: InventoryMapPlot }) {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  const area = dq.convert(num(plot.area_m2), 'm²');
  return (
    <div className="space-y-3 p-4">
      <div>
        <p className="text-2xs uppercase text-content-tertiary">
          {t('propdev.inventory_map.drawer_status', {
            defaultValue: 'Status',
          })}
        </p>
        <p className="text-sm font-semibold text-content-primary">
          {plot.status}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <p className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.drawer_price', {
              defaultValue: 'Base price',
            })}
          </p>
          <MoneyDisplay
            amount={plot.base_price}
            currency={plot.currency}
          />
        </div>
        <div>
          <p className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.drawer_area', {
              defaultValue: 'Area',
            })}
          </p>
          <p className="text-sm">{fmtFixed(area.value, 2)} {area.unit}</p>
        </div>
        <div>
          <p className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.drawer_bedrooms', {
              defaultValue: 'Bedrooms',
            })}
          </p>
          <p className="text-sm">{plot.bedrooms}</p>
        </div>
        <div>
          <p className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.drawer_bathrooms', {
              defaultValue: 'Bathrooms',
            })}
          </p>
          <p className="text-sm">{plot.bathrooms}</p>
        </div>
      </div>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────── */

interface HoldModalProps {
  count: number;
  reason: string;
  until: string;
  submitting: boolean;
  onReasonChange: (v: string) => void;
  onUntilChange: (v: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}

function HoldModal({
  count,
  reason,
  until,
  submitting,
  onReasonChange,
  onUntilChange,
  onCancel,
  onSubmit,
}: HoldModalProps) {
  const { t } = useTranslation();
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="hold-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      data-testid="hold-modal"
    >
      <Card className="w-full max-w-md space-y-3 p-4">
        <h2
          id="hold-modal-title"
          className="text-base font-semibold text-content-primary"
        >
          {t('propdev.inventory_map.hold_modal_title', {
            defaultValue: 'Hold {{count}} plots',
            count,
          })}
        </h2>
        <p className="text-xs text-content-tertiary">
          {t('propdev.inventory_map.hold_modal_desc', {
            defaultValue:
              'Plots will be marked Held and pulled off the public board until released.',
          })}
        </p>
        <label className="block">
          <span className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.hold_reason', {
              defaultValue: 'Reason',
            })}
          </span>
          <input
            type="text"
            value={reason}
            onChange={(e) => onReasonChange(e.target.value)}
            maxLength={500}
            className="mt-1 w-full rounded border border-divider/60 px-2 py-1.5 text-sm"
            placeholder={t('propdev.inventory_map.hold_reason_placeholder', {
              defaultValue: 'e.g. broker viewing this week',
            })}
            data-testid="hold-modal-reason"
          />
        </label>
        <label className="block">
          <span className="text-2xs uppercase text-content-tertiary">
            {t('propdev.inventory_map.hold_until', {
              defaultValue: 'Hold until (optional)',
            })}
          </span>
          <input
            type="date"
            value={until}
            onChange={(e) => onUntilChange(e.target.value)}
            className="mt-1 w-full rounded border border-divider/60 px-2 py-1.5 text-sm"
            data-testid="hold-modal-until"
          />
        </label>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onCancel} disabled={submitting}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={onSubmit}
            disabled={submitting}
            data-testid="hold-modal-submit"
          >
            {submitting ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              t('propdev.inventory_map.hold_modal_submit', {
                defaultValue: 'Hold',
              })
            )}
          </Button>
        </div>
      </Card>
    </div>
  );
}
