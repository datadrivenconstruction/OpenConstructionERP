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
 * (`BOQGrid.tsx`). Adding a new value here makes it editable inline
 * AND in the dialog.
 */
export const RESOURCE_TYPES: ResourceTypeOption[] = [
  { value: 'material', i18nKey: 'boq.resource_type_material', fallback: 'Material' },
  { value: 'labor', i18nKey: 'boq.resource_type_labor', fallback: 'Labor' },
  { value: 'equipment', i18nKey: 'boq.resource_type_equipment', fallback: 'Equipment' },
  { value: 'subcontractor', i18nKey: 'boq.resource_type_subcontractor', fallback: 'Subcontractor' },
  { value: 'other', i18nKey: 'boq.resource_type_other', fallback: 'Other' },
];

/** Tiny escape hatch used in tests when full i18n isn't wired up. */
export function getResourceTypeLabel(
  value: string,
  t?: (key: string, opts?: Record<string, string>) => string,
): string {
  const opt = RESOURCE_TYPES.find((r) => r.value === value);
  if (!opt) return value;
  if (t) return t(opt.i18nKey, { defaultValue: opt.fallback });
  return opt.fallback;
}
