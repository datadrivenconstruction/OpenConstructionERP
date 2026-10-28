// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Site Inventory's contribution to the Module Insights panel. It turns the two
 * ledgers the page already loaded into charts client-side: the stock-on-hand
 * snapshot (what is on site right now) and the movement log (every inbound,
 * consumption, waste and transfer). When a project has nothing yet both datasets
 * come back empty and the panel shows nothing, which is the honest answer.
 *
 * Two datasets, not one, because stock-on-hand is a point-in-time snapshot with
 * no date on it, so the "over time" chart can only come from the movement log
 * (which carries `occurred_at`). Money is genuine here: stock value is quantity
 * on hand times the item's standard unit cost, movement value is quantity moved
 * times its unit cost, so both read as currency; quantities and the low-stock
 * flag are plain counts. Movement-type slices reuse the same
 * `site_inventory.movement_type_*` keys the ledger and the record form use, so
 * a slice reads exactly like the badge on the row it came from. The stock item
 * has no category field, so material name and unit stand in as the groupable
 * dimensions.
 */
import { useTranslation } from 'react-i18next';
import type { InsightDataset, InsightDef } from '@/features/insights';

type Translate = ReturnType<typeof useTranslation>['t'];

/**
 * Minimal shapes the builder needs. The page's real `StockOnHandRow`,
 * `StockItem` and `StockMovement` types structurally satisfy these (money and
 * quantities stay `number | string` on the wire) so the raw records are
 * assignable without a cast.
 */
interface StockRowLite {
  item_id: string;
  name: string;
  unit: string;
  on_hand: number | string;
}
interface ItemMetaLite {
  id: string;
  standard_unit_cost?: number | string | null;
  reorder_point?: number | string | null;
}
interface MovementLite {
  item_id: string;
  movement_type: string;
  quantity: number | string;
  unit_cost?: number | string | null;
  occurred_at: string;
}

/** English fallbacks matching the ledger's own movement-type labels. */
const MOVEMENT_TYPE_LABELS: Record<string, string> = {
  inbound: 'Inbound',
  consumption: 'Consumption',
  waste: 'Waste',
  transfer: 'Transfer',
};

/** Coerce a decimal-as-string cell to a finite number (0 when absent/invalid). */
function toNum(v: number | string | null | undefined): number {
  if (v === null || v === undefined) return 0;
  const n = typeof v === 'string' ? Number(v) : v;
  return Number.isFinite(n) ? n : 0;
}

/** Sortable YYYY-MM key so the time series stays chronological. */
function monthKey(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Reuse the ledger's `site_inventory.movement_type_*` keys for slice labels. */
function movementTypeLabel(code: string, t: Translate): string {
  const key = (code || '').toLowerCase();
  return t(`site_inventory.movement_type_${key}`, {
    defaultValue: MOVEMENT_TYPE_LABELS[key] ?? (key ? key.charAt(0).toUpperCase() + key.slice(1) : ''),
  });
}

// Resolved stock line: quantity, unit cost and reorder point already coerced to
// numbers once the snapshot has been joined to the item meta, so the row builder
// only ever sees numbers.
interface StockResolved {
  name: string;
  unit: string;
  on_hand: number;
  unit_cost: number;
  reorder: number;
}

interface StockRow {
  // Index signature so a Row is directly a valid InsightDataset row (a plain
  // record of string/number cells) with no cast.
  [key: string]: string | number;
  material: string;
  unit: string;
  quantity: number;
  value: number;
  low: number;
}

function toStockRow(s: StockResolved, noUnit: string): StockRow {
  return {
    material: (s.name || '').trim() || noUnit,
    unit: (s.unit || '').trim() || noUnit,
    quantity: s.on_hand,
    value: s.on_hand * s.unit_cost,
    low: s.reorder > 0 && s.on_hand <= s.reorder ? 1 : 0,
  };
}

interface MoveRow {
  [key: string]: string | number;
  item: string;
  type: string;
  month: string;
  quantity: number;
  value: number;
}

function toMoveRow(m: MovementLite, itemName: string, t: Translate): MoveRow {
  const qty = toNum(m.quantity);
  return {
    item: itemName,
    type: movementTypeLabel(m.movement_type, t),
    month: monthKey(m.occurred_at),
    quantity: qty,
    value: qty * toNum(m.unit_cost),
  };
}

export interface SiteInventoryInsights {
  datasets: InsightDataset[];
  builtins: InsightDef[];
}

export function buildSiteInventoryInsights(
  stock: StockRowLite[],
  movements: MovementLite[],
  items: ItemMetaLite[],
  currency: string,
  t: Translate,
): SiteInventoryInsights {
  const noUnit = t('site_inventory.insights.no_unit', { defaultValue: 'No unit' });
  const unknownItem = t('site_inventory.unknown_item', { defaultValue: 'Unknown item' });

  const metaById = new Map(items.map((i) => [i.id, i] as const));
  // Movements carry only item_id, so the display name comes from the stock
  // snapshot (which pairs item_id with the material name); item meta has no name.
  const nameById = new Map(stock.map((s) => [s.item_id, s.name] as const));

  const stockRows: StockRow[] = stock.map((s) => {
    const meta = metaById.get(s.item_id);
    return toStockRow(
      {
        name: s.name,
        unit: s.unit,
        on_hand: toNum(s.on_hand),
        unit_cost: toNum(meta?.standard_unit_cost),
        reorder: toNum(meta?.reorder_point),
      },
      noUnit,
    );
  });

  const moveRows: MoveRow[] = [...movements]
    .sort((a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime())
    .map((m) => toMoveRow(m, nameById.get(m.item_id) ?? unknownItem, t));

  const stockDataset: InsightDataset = {
    id: 'stock',
    label: t('site_inventory.insights.ds_stock', { defaultValue: 'Stock on hand' }),
    currency: currency || '',
    fields: [
      { key: 'material', label: t('site_inventory.insights.f_material', { defaultValue: 'Material' }), kind: 'dimension' },
      { key: 'unit', label: t('site_inventory.insights.f_unit', { defaultValue: 'Unit' }), kind: 'dimension' },
      { key: 'quantity', label: t('site_inventory.insights.f_quantity', { defaultValue: 'Quantity on hand' }), kind: 'measure', format: 'number' },
      { key: 'value', label: t('site_inventory.insights.f_value', { defaultValue: 'Stock value' }), kind: 'measure', format: 'currency' },
      { key: 'low', label: t('site_inventory.insights.f_low', { defaultValue: 'Low stock' }), kind: 'measure', format: 'number' },
    ],
    rows: stockRows,
  };

  const movementsDataset: InsightDataset = {
    id: 'movements',
    label: t('site_inventory.insights.ds_movements', { defaultValue: 'Stock movements' }),
    currency: currency || '',
    fields: [
      { key: 'item', label: t('site_inventory.insights.f_mv_item', { defaultValue: 'Item' }), kind: 'dimension' },
      { key: 'type', label: t('site_inventory.insights.f_mv_type', { defaultValue: 'Movement type' }), kind: 'dimension' },
      { key: 'month', label: t('site_inventory.insights.f_mv_month', { defaultValue: 'Month' }), kind: 'dimension' },
      { key: 'quantity', label: t('site_inventory.insights.f_mv_quantity', { defaultValue: 'Quantity moved' }), kind: 'measure', format: 'number' },
      { key: 'value', label: t('site_inventory.insights.f_mv_value', { defaultValue: 'Movement value' }), kind: 'measure', format: 'currency' },
    ],
    rows: moveRows,
  };

  const stockBase = { datasetId: 'stock', builtin: true } as const;
  const mvBase = { datasetId: 'movements', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...stockBase, id: 'kpi-items', title: t('site_inventory.insights.k_items', { defaultValue: 'Items tracked' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...stockBase, id: 'kpi-stock-value', title: t('site_inventory.insights.k_stock_value', { defaultValue: 'Stock value' }), chart: 'kpi', measure: 'value', agg: 'sum', color: 4 },
    { ...stockBase, id: 'kpi-low', title: t('site_inventory.insights.k_low', { defaultValue: 'Low stock' }), chart: 'kpi', measure: 'low', agg: 'sum', color: 1 },
    { ...mvBase, id: 'kpi-movements', title: t('site_inventory.insights.k_movements', { defaultValue: 'Movements' }), chart: 'kpi', agg: 'count', color: 5 },
    { ...stockBase, id: 'bar-value-by-material', title: t('site_inventory.insights.c_value_by_material', { defaultValue: 'Stock value by material' }), chart: 'bar', dimension: 'material', measure: 'value', agg: 'sum', color: 4 },
    { ...stockBase, id: 'bar-qty-by-unit', title: t('site_inventory.insights.c_qty_by_unit', { defaultValue: 'Quantity by unit' }), chart: 'bar', dimension: 'unit', measure: 'quantity', agg: 'sum', color: 2 },
    { ...mvBase, id: 'donut-mv-by-type', title: t('site_inventory.insights.c_mv_by_type', { defaultValue: 'Movements by type' }), chart: 'donut', dimension: 'type', agg: 'count', color: 1 },
    { ...mvBase, id: 'area-mv-over-time', title: t('site_inventory.insights.c_mv_over_time', { defaultValue: 'Movements over time' }), chart: 'area', dimension: 'month', agg: 'count', color: 5 },
  ];

  return { datasets: [stockDataset, movementsDataset], builtins };
}
