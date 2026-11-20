// Design module (ERP side of the design editor link).
/** Take-off delta of a revision (ddc-procurement-impact/1): quantities by element group, per tender package. */

export type TakeoffBasis = 'length_m' | 'area_m2' | 'volume_m3' | 'weight_kg' | 'count';

export interface TakeoffRow {
  group_key: string;
  label: string;
  ifc_class: string;
  basis: TakeoffBasis;
  unit: string;
  new_line: boolean;
  current_quantity: string;
  model_quantity_now: string | null;
  model_quantity_new: string;
  new_quantity: string;
  quantity_delta: string;
  override: boolean;
  override_quantity: string | null;
  elements: { before: number; after: number };
  package: { id: string; name: string; status: string } | null;
  new_package: boolean;
  flags: string[];
}

export interface ProcurementImpact {
  schema: 'ddc-procurement-impact/1';
  revision_id: string;
  /** False when the project has no take-off: there is nothing to compare. */
  procurement: boolean;
  follow?: boolean;
  group_by?: 'type_key' | 'ifc_class';
  rows?: TakeoffRow[];
  totals?: {
    lines_changed: number;
    lines_added: number;
    lines_removed: number;
    overrides_kept: number;
    packages_affected: number;
    packages_new: number;
    issued_packages_affected: number;
    unpriced_lines: number;
  };
  basis_note?: string;
  price_note?: string;
}

/** Rows a person should see: a new line, a changed quantity, a kept override, or a group that left the model. */
export function changedRows(rows: TakeoffRow[]): TakeoffRow[] {
  return rows.filter((r) => r.new_line || Number(r.quantity_delta) !== 0 || r.override || r.flags.includes('no_match'));
}

/** A quantity with its sign: +3.5, -2, 0. */
export function signed(value: string): string {
  const n = Number(value);
  const s = String(Math.round(n * 10000) / 10000);
  return n > 0 ? `+${s}` : s;
}
