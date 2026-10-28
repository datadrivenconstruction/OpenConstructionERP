// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client-side quantity summariser for the BIM filter report (B5).
 *
 * Mirrors the backend BOQ exporter's grouping + alias-scan so the on-screen
 * report a user sees matches the Excel file they download byte-for-number.
 * Pure + dependency-free so it is trivially unit tested.
 */
import type { BIMElementData } from '@/shared/ui/BIMViewer';

export interface QuantityField {
  key: string;
  label: string;
  unit: string;
  aliases: string[];
}

/** Quantity columns, each with the alias keys scanned in order. Keep in lock
 *  step with ``backend/app/modules/bim_hub/exporters/boq_xlsx.py``. */
export const QUANTITY_FIELDS: QuantityField[] = [
  { key: 'area_m2', label: 'Area', unit: 'm2', aliases: ['area_m2', 'area', 'NetArea', 'GrossArea', 'net_area', 'gross_area'] },
  { key: 'volume_m3', label: 'Volume', unit: 'm3', aliases: ['volume_m3', 'volume', 'NetVolume', 'GrossVolume', 'net_volume', 'gross_volume'] },
  { key: 'length_m', label: 'Length', unit: 'm', aliases: ['length_m', 'length', 'Length'] },
  { key: 'weight_kg', label: 'Weight', unit: 'kg', aliases: ['weight_kg', 'weight', 'Weight', 'mass', 'Mass'] },
];

export type SummaryGroupBy = 'element_type' | 'storey' | 'discipline';

export interface SummaryRow {
  /** Group label (e.g. an element type or storey name). */
  key: string;
  count: number;
  /** Summed quantity per QUANTITY_FIELDS column, in the same order. */
  quantities: number[];
}

export interface QuantitySummary {
  groupBy: SummaryGroupBy;
  rows: SummaryRow[];
  totals: { count: number; quantities: number[] };
}

const UNCLASSIFIED = 'Unclassified';
const UNASSIGNED = 'Unassigned';

/** First numeric value among ``aliases`` in the quantities blob, else 0.
 *  Rejects booleans (a bool is a JS number-ish truthy but never a quantity)
 *  and coerces numeric strings. */
function readQuantity(
  quantities: Record<string, unknown> | undefined | null,
  aliases: string[],
): number {
  if (!quantities) return 0;
  for (const key of aliases) {
    if (key in quantities) {
      const raw = quantities[key];
      if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
      if (typeof raw === 'string') {
        const n = Number(raw.trim());
        if (Number.isFinite(n)) return n;
      }
    }
  }
  return 0;
}

function groupValue(el: BIMElementData, groupBy: SummaryGroupBy): string {
  if (groupBy === 'storey') return (el.storey && el.storey.trim()) || UNASSIGNED;
  if (groupBy === 'discipline') return (el.discipline && el.discipline.trim()) || UNASSIGNED;
  return (el.element_type && el.element_type.trim()) || UNCLASSIFIED;
}

/** Round to 3 decimals (matches the backend exporter) without float dust. */
export function round3(n: number): number {
  return Math.round((n + Number.EPSILON) * 1000) / 1000;
}

/** Summarise a list of elements into grouped counts + summed quantities. */
export function summariseBimQuantities(
  elements: BIMElementData[],
  groupBy: SummaryGroupBy,
): QuantitySummary {
  const buckets = new Map<string, { count: number; quantities: number[] }>();
  const totals = { count: 0, quantities: QUANTITY_FIELDS.map(() => 0) };

  for (const el of elements) {
    const key = groupValue(el, groupBy);
    let bucket = buckets.get(key);
    if (!bucket) {
      bucket = { count: 0, quantities: QUANTITY_FIELDS.map(() => 0) };
      buckets.set(key, bucket);
    }
    bucket.count += 1;
    totals.count += 1;
    const q = el.quantities as Record<string, unknown> | undefined;
    QUANTITY_FIELDS.forEach((field, i) => {
      const v = readQuantity(q, field.aliases);
      bucket!.quantities[i] = (bucket!.quantities[i] ?? 0) + v;
      totals.quantities[i] = (totals.quantities[i] ?? 0) + v;
    });
  }

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });
  const rows: SummaryRow[] = Array.from(buckets.entries())
    .map(([key, b]) => ({ key, count: b.count, quantities: b.quantities.map(round3) }))
    .sort((a, b) => collator.compare(a.key, b.key));

  return {
    groupBy,
    rows,
    totals: { count: totals.count, quantities: totals.quantities.map(round3) },
  };
}
