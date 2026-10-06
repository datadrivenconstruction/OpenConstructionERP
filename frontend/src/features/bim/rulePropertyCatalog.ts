// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Suggestions for the Quantity Rule editor, read from a model's property
 * catalog (GET /v1/bim_hub/smart-views/properties).
 *
 * The catalog serves the Smart View builder and names fields by canonical
 * path (`properties.Phase Created`, `quantities.Area`, `identity.*`). A
 * quantity rule addresses `element.properties[key]` and `element.quantities
 * [key]` directly, so only the `properties.*` rows are property-filter keys
 * and only the `quantities.*` rows are quantity sources, each with its
 * prefix cut off (by length, not by splitting on dots: Revit and IFC names
 * carry dots of their own, such as `Pset_WallCommon.FireRating`).
 */

import type { BIMDataframeColumn, SmartViewPropertyCatalog } from './api';
import { columnLabel } from './propertySearch';

export interface RulePropertyOption {
  /** The property name exactly as the model stores it; what the rule saves. */
  key: string;
  /** What the picker shows next to the name. */
  label: string;
  /** Distinct values seen in the model, capped by the server. */
  samples: string[];
  /** More distinct values exist than `samples` holds. */
  truncated: boolean;
}

const PROPERTIES_PREFIX = 'properties.';
const QUANTITIES_PREFIX = 'quantities.';
/** The catalog's stand-in for a nested value; not something a filter can name. */
const COMPLEX_SAMPLE = '<complex>';

/** Property key -> display label, from the model's dataframe schema.
 *
 * A DDC import stores element properties under lowercased keys ("phase
 * created") and keeps the header the converter wrote ("Phase Created") as
 * the column label of the Parquet sidecar. Column names and property keys
 * are the same strings there, so the label the property search shows
 * (`columnLabel`) is the label the rule editor shows too. A column without a
 * stored label maps to its own name. */
export function propertyLabelMap(columns: readonly BIMDataframeColumn[] | null | undefined): Map<string, string> {
  const labels = new Map<string, string>();
  for (const column of columns ?? []) labels.set(column.name, columnLabel(column));
  return labels;
}

/**
 * Display label for a property key: the model's own header when the schema
 * has one (exact key first, then case-insensitive), otherwise the key. It is
 * shown beside the key, never instead of it: the key is what the rule saves
 * and what the engine matches.
 */
export function propertyDisplayLabel(key: string, labels?: ReadonlyMap<string, string>): string {
  if (!labels || labels.size === 0) return key;
  const exact = labels.get(key);
  if (exact) return exact;
  const lower = key.toLowerCase();
  for (const [name, label] of labels) if (name.toLowerCase() === lower) return label;
  return key;
}

/** Property-filter key suggestions, sorted by name. */
export function rulePropertyOptions(
  catalog: SmartViewPropertyCatalog | null | undefined,
  labels?: ReadonlyMap<string, string>,
): RulePropertyOption[] {
  const out: RulePropertyOption[] = [];
  for (const entry of catalog?.entries ?? []) {
    if (entry.group !== 'properties' || !entry.field.startsWith(PROPERTIES_PREFIX)) continue;
    const key = entry.field.slice(PROPERTIES_PREFIX.length);
    if (!key || key === 'classification') continue;
    const samples = entry.sample_values.filter((v) => v !== COMPLEX_SAMPLE && v !== '');
    // Present only as a nested structure: nothing a key = value filter can match.
    if (samples.length === 0 && entry.sample_values.includes(COMPLEX_SAMPLE)) continue;
    out.push({ key, label: propertyDisplayLabel(key, labels), samples, truncated: entry.truncated });
  }
  return out.sort((a, b) => a.key.localeCompare(b.key, undefined, { sensitivity: 'base' }));
}

/** Custom quantity-source suggestions: the element's own quantity keys, then
 *  numeric properties as `property:<name>`. */
export function ruleQuantitySourceOptions(catalog: SmartViewPropertyCatalog | null | undefined): string[] {
  const quantities: string[] = [];
  const numericProps: string[] = [];
  for (const entry of catalog?.entries ?? []) {
    if (entry.group === 'quantities' && entry.field.startsWith(QUANTITIES_PREFIX)) {
      const key = entry.field.slice(QUANTITIES_PREFIX.length);
      if (key) quantities.push(key);
    } else if (
      entry.group === 'properties' &&
      entry.data_type === 'number' &&
      entry.field.startsWith(PROPERTIES_PREFIX)
    ) {
      const key = entry.field.slice(PROPERTIES_PREFIX.length);
      if (key) numericProps.push(`property:${key}`);
    }
  }
  const byName = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: 'base' });
  return [...quantities.sort(byName), ...numericProps.sort(byName)];
}

/** A value the model really carries that contains `*` or `?`. Rule matching
 *  reads both as wildcards, on the server and in the preview, and has no
 *  escape for them, so picking such a value matches more than that value. */
export function isWildcardSample(value: string, samples: readonly string[]): boolean {
  return /[*?]/.test(value) && samples.includes(value);
}
