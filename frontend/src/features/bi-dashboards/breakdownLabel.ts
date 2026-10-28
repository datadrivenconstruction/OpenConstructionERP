// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Reading a breakdown that is keyed by an id - issue #441.
 *
 * A custom KPI grouped by `boq_id` comes back keyed by uuids, because a
 * uuid is what the database can group by. Two things turn that into an
 * answer a person can read, and both of them live here so the screen and
 * the form give the same account of them.
 */

import type { KpiSpecEntity } from './api';

/**
 * The key a breakdown gives a group that has nothing to call itself.
 *
 * Reserved by the backend rather than translated there, because it is a
 * dict key: a word in that slot cannot be told apart from a real group
 * value like `m3`. It stands both for a group whose value was absent and
 * for a name that is empty or all whitespace, and mapping it to something
 * readable is the consumer's job. The report writers do it; the screen
 * did not, and printed the token at the reader.
 */
export const NULL_GROUP_KEY = '__null__';

/**
 * Render one drill-down field.
 *
 * A breakdown group can be a `{label, value}` record rather than a bare
 * number - the `top_by` aggregation has always returned them, and a
 * breakdown that names its groups now does too - and `String()` on one
 * prints "[object Object]" at the reader. The report writer already
 * spells this shape "label: value"; this is the same sentence on screen.
 *
 * @param v - The field's value, as the drill-down API returned it.
 * @param unnamed - What the reserved key reads as, already translated.
 * @returns The text to put in the cell.
 */
export function drillFieldText(v: unknown, unnamed: string): string {
  if (v !== null && typeof v === 'object' && !Array.isArray(v)) {
    const rec = v as Record<string, unknown>;
    const keys = Object.keys(rec);
    if (keys.length === 2 && keys.includes('label') && keys.includes('value')) {
      return `${drillFieldText(rec['label'], unnamed)}: ${drillFieldText(rec['value'], unnamed)}`;
    }
    return JSON.stringify(v);
  }
  return v === NULL_GROUP_KEY ? unnamed : String(v);
}

/**
 * The field the server will name a breakdown's groups by, given the field
 * it is keyed by.
 *
 * The catalog declares which of an entity's fields names which of its
 * ids, and the server fills `label_field` in from that map when the spec
 * leaves it out. The form reads the same map so that what the picker
 * shows is what gets stored, rather than offering to leave a column of
 * ids alone while the server names them anyway.
 *
 * @param entity - The catalog entry the spec is written against.
 * @param groupBy - The field the breakdown is keyed by, `''` for none.
 * @returns The field that names it, or `''` when nothing names it.
 */
export function defaultLabelField(entity: KpiSpecEntity | undefined, groupBy: string): string {
  if (!entity || groupBy === '') return '';
  return entity.display_name_for?.[groupBy] ?? '';
}
