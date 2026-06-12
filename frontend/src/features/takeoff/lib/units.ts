/**
 * Frontend unit canonicalization for takeoff → BOQ flows.
 *
 * Mirrors the backend `_UNIT_ALIASES` / `_normalize_unit`
 * (`backend/app/modules/takeoff/service.py`) so quantities pushed into
 * BOQ positions carry the canonical unit vocabulary
 * (`m` / `m2` / `m3` / `kg` / `t` / `pcs` / `lsum`) instead of whatever
 * raw string a PDF table extraction or a German LV produced
 * (`Stück`, `lfm`, `m³`, `psch`, `''`). Downstream BOQ validation,
 * cost matching and bim_hub quantity sync all key on the canonical
 * form, so leaving `Stück` / `lfm` verbatim made those rows invisible
 * to pricing and compliance (D-TKC-021).
 *
 * Keep the alias table in sync with the backend; the backend is the
 * ultimate authority but normalizing client-side gives the user a
 * correct unit immediately and avoids a verbatim round-trip.
 */

/** Case-folded, dot-stripped, whitespace-collapsed alias → canonical. */
const UNIT_ALIASES: Readonly<Record<string, string>> = {
  // Length
  m: 'm',
  rmt: 'm',
  rm: 'm',
  runningmetre: 'm',
  runningmeter: 'm',
  lm: 'm',
  lfm: 'm', // German "laufende Meter"
  ml: 'm',
  rft: 'm',
  // (mm / cm kept distinct — they are real, different units)
  mm: 'mm',
  cm: 'cm',
  // Area
  m2: 'm2',
  'm²': 'm2',
  sqm: 'm2',
  'sq m': 'm2',
  squaremetre: 'm2',
  squaremeter: 'm2',
  qm: 'm2', // German "Quadratmeter"
  sft: 'sft',
  sqft: 'sft',
  'sq ft': 'sft',
  squarefeet: 'sft',
  squarefoot: 'sft',
  // Volume
  m3: 'm3',
  'm³': 'm3',
  cum: 'm3',
  'cu m': 'm3',
  cubicmetre: 'm3',
  cubicmeter: 'm3',
  cbm: 'm3', // German "Kubikmeter"
  cft: 'cft',
  cuft: 'cft',
  'cu ft': 'cft',
  cubicfeet: 'cft',
  // Weight
  kg: 'kg',
  g: 'g',
  t: 't',
  mt: 't',
  to: 't', // German "Tonne"
  tonne: 't',
  ton: 't',
  // Count
  pcs: 'pcs',
  pc: 'pcs',
  nos: 'pcs',
  no: 'pcs',
  number: 'pcs',
  qty: 'pcs',
  ea: 'pcs',
  stück: 'pcs',
  stk: 'pcs', // German "Stück"
  // Lump sum
  lsum: 'lsum',
  ls: 'lsum',
  lumpsum: 'lsum',
  psch: 'lsum', // German "pauschal"
  pausch: 'lsum',
  pauschal: 'lsum',
};

/**
 * Map an arbitrary unit string to the canonical BOQ form.
 *
 * Empty / nullish input → `'pcs'` (matches the backend default — a
 * countable line is the safest neutral assumption). Unknown units pass
 * through lower-cased rather than being rejected: a real-world unit we
 * have not catalogued yet is better surfaced and editable than dropped.
 */
export function canonicalizeUnit(raw: string | null | undefined): string {
  if (raw == null) return 'pcs';
  const text = String(raw).trim();
  if (!text) return 'pcs';
  const key = text
    .toLowerCase()
    .replace(/\./g, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (key in UNIT_ALIASES) return UNIT_ALIASES[key]!;
  const nospace = key.replace(/ /g, '');
  if (nospace in UNIT_ALIASES) return UNIT_ALIASES[nospace]!;
  return key;
}

/* ── Dimension guard (mirrors the backend push_quantity guard) ──────────
 *
 * `link_measurement_to_boq(..., push_quantity=True)` refuses to copy a
 * measurement value into a BOQ position whose unit measures a different
 * dimension (`_UNIT_DIMENSION` / `_MEASUREMENT_TYPE_DIMENSION` in
 * `backend/app/modules/takeoff/service.py`) - but it refuses SILENTLY
 * (HTTP 200, quantity untouched, warning only in the server log). These
 * mirrors let the UI detect the same mismatch up front and surface it as
 * a clear toast instead of a quietly-unchanged BOQ total. Unknown units
 * on either side return null so custom/legacy units stay permissive,
 * exactly like the backend. */

export type MeasureDimension =
  | 'length'
  | 'area'
  | 'volume'
  | 'mass'
  | 'count'
  | 'lsum'
  | 'time';

/** Unit code → dimension group. Mirror of backend `_UNIT_DIMENSION`. */
const UNIT_DIMENSION: Readonly<Record<string, MeasureDimension>> = {
  m: 'length',
  lm: 'length',
  ml: 'length',
  m2: 'area',
  m3: 'volume',
  kg: 'mass',
  t: 'mass',
  pcs: 'count',
  ea: 'count',
  stk: 'count',
  lsum: 'lsum',
  h: 'time',
};

/** Measurement `type` → dimension. Mirror of backend
 *  `_MEASUREMENT_TYPE_DIMENSION` - the geometric type is the
 *  authoritative dimension; the unit is only a fallback. */
const MEASUREMENT_TYPE_DIMENSION: Readonly<Record<string, MeasureDimension>> = {
  distance: 'length',
  polyline: 'length',
  area: 'area',
  volume: 'volume',
  count: 'count',
};

/** Map a unit code to its dimension group, or null when unknown.
 *  Folds superscripts (`m²` → `m2`) and case like the backend. */
export function unitDimension(unit: string | null | undefined): MeasureDimension | null {
  if (!unit) return null;
  const cleaned = unit
    .trim()
    .toLowerCase()
    .replace(/²/g, '2')
    .replace(/³/g, '3')
    .replace(/\^/g, '')
    .replace(/\*\*/g, '');
  return UNIT_DIMENSION[cleaned] ?? null;
}

/** Dimension of a takeoff measurement from its `type`, then unit.
 *  Returns null when neither maps so callers stay permissive. */
export function measurementDimension(
  type: string | null | undefined,
  unit: string | null | undefined,
): MeasureDimension | null {
  const mtype = (type ?? '').trim().toLowerCase();
  return MEASUREMENT_TYPE_DIMENSION[mtype] ?? unitDimension(unit);
}
