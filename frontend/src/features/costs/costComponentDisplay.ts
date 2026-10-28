// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// costComponentDisplay - coerce a cost item's resource/component numbers for
// display in the expanded Cost Database row.
//
// Why this exists: a cost item's `components` are stored as free-form JSON
// (backend `list[dict[str, Any]]`), so the numeric fields ride the wire as
// Decimal-serialized STRINGS ("1.02", "58") and the `cost` field is frequently
// absent - starter-seed and manually created rows carry only `quantity` and
// `unit_rate`. The expanded row used to render `comp.quantity.toFixed(2)`,
// which throws `TypeError: comp.quantity.toFixed is not a function` on a string
// and crashed the page whenever the user opened a rate that had a breakdown.
// Coerce every read through Number() (relational operators and `*` coerce, but
// `.toFixed` does not) and derive the line cost as quantity × unit_rate when it
// is not supplied so the "Cost" column shows a real figure instead of a dash.

/** The numeric shape of one component as it may arrive from the backend. */
export interface RawCostComponentNumbers {
  quantity?: number | string | null;
  unit_rate?: number | string | null;
  cost?: number | string | null;
}

/** Display-ready component numbers: always finite, never NaN. */
export interface CostComponentDisplayNumbers {
  /** Quantity per one item unit (0 when absent / unparseable). */
  qty: number;
  /** Resource unit rate (0 when absent / unparseable). */
  unitRate: number;
  /** Line cost - the supplied `cost` when positive, else quantity × unit_rate. */
  lineCost: number;
}

/** Coerce a component's Decimal-string numbers to finite numbers for display,
 *  deriving the line cost when the backend did not stamp one. */
export function componentDisplayNumbers(
  comp: RawCostComponentNumbers,
): CostComponentDisplayNumbers {
  const qty = Number(comp.quantity) || 0;
  const unitRate = Number(comp.unit_rate) || 0;
  const rawCost = Number(comp.cost);
  const lineCost =
    Number.isFinite(rawCost) && rawCost > 0 ? rawCost : qty * unitRate;
  return { qty, unitRate, lineCost };
}
