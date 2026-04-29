/**
 * Shared resource type definitions for compound BOQ positions.
 *
 * Extracted into its own module so both `BOQGrid.tsx` (manual-add dialog)
 * and `cellRenderers.tsx` (`EditableResourceRow` inline editor) can import
 * the same canonical list. Keep options in sync with backend conventions
 * (see `backend/app/modules/boq/schemas.py`).
 */

export interface ResourceTypeOption {
  /** Stored value — must match backend enum string. */
  value: string;
  /** i18n key used to look up the display label. */
  i18nKey: string;
  /** English fallback used when the i18n key is missing. */
  fallback: string;
}

/**
 * Canonical resource types for compound positions.
 *
 * The list mirrors what the manual-add dialog already supports
 * (`BOQGrid.tsx`) and what the backend persists in
 * `boq.metadata.resources[].type`. Adding a new value here makes it
 * editable inline AND in the dialog.
 */
export const RESOURCE_TYPES: ResourceTypeOption[] = [
  { value: 'material', i18nKey: 'boq.resource_type_material', fallback: 'Material' },
  { value: 'labor', i18nKey: 'boq.resource_type_labor', fallback: 'Labor' },
  { value: 'equipment', i18nKey: 'boq.resource_type_equipment', fallback: 'Equipment' },
  { value: 'operator', i18nKey: 'boq.resource_type_operator', fallback: 'Operator' },
  { value: 'subcontractor', i18nKey: 'boq.resource_type_subcontractor', fallback: 'Subcontractor' },
  { value: 'electricity', i18nKey: 'boq.resource_type_electricity', fallback: 'Electricity' },
  { value: 'composite', i18nKey: 'boq.resource_type_composite', fallback: 'Composite' },
  { value: 'other', i18nKey: 'boq.resource_type_other', fallback: 'Other' },
];

/**
 * Lookup table from resource-type value to its i18n key.
 *
 * Used by call sites that have a raw type string (e.g. coming from the
 * backend or from a catalog API response) and need to render a localised
 * label without mapping through the `RESOURCE_TYPES` array. Falls back
 * to a generic key so unknown values still get an i18n round-trip.
 */
const RESOURCE_TYPE_KEY_MAP: Record<string, string> = Object.freeze(
  Object.fromEntries(RESOURCE_TYPES.map((rt) => [rt.value, rt.i18nKey])),
);

/**
 * Resolve the i18n key for a given resource-type value.
 *
 * Returns the catch-all `boq.resource_type_other` key when the value is
 * not a known canonical type so that translations always succeed.
 */
export function getResourceTypeI18nKey(value: string): string {
  return RESOURCE_TYPE_KEY_MAP[value] ?? 'boq.resource_type_other';
}

/**
 * Render-ready label for a resource-type value.
 *
 * Uses the supplied `t` function when available so the label is
 * translated to the current UI language. When called without a `t`
 * (e.g. in tests, in non-React utility code, or in early bootstrap
 * before i18next is initialised), falls back to the canonical English
 * label registered in `RESOURCE_TYPES`. Unknown values are returned
 * verbatim — this preserves data integrity for legacy resources whose
 * type strings predate the canonical enum.
 */
export function getResourceTypeLabel(
  value: string,
  t?: (key: string, opts?: Record<string, string>) => string,
): string {
  const opt = RESOURCE_TYPES.find((r) => r.value === value);
  if (!opt) return value;
  if (t) return t(opt.i18nKey, { defaultValue: opt.fallback });
  return opt.fallback;
}
