// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The column mapping a user edits in the import preview, and what of it is sent.
 *
 * The preview shows what the importer read each column as, keyed by the column's
 * index in `metadata.original_columns`, and the user can change any of them. Only
 * the changed columns go to the server, as the `column_mapping` form field: an
 * unchanged column keeps the importer's own reading, which for a bill priced as
 * material plus fee is a split the dropdown cannot express, so sending the whole
 * mapping back would flatten both halves into one rate column.
 */

/** Column index (as a string) -> target field; `''` leaves the column out. */
export type ColumnMapping = Record<string, string>;

/**
 * The mapping with `column` set to `target`. A field is fed by one column, so
 * any other column mapped to the same field is left out, which the user sees
 * in the dropdowns at once rather than as a refusal from the server.
 *
 * Putting a column back to what the importer read it as clears nothing: the
 * two halves of a split rate both read as `unit_rate`, and restoring one half
 * must not take the other away, or the bill imports at half its price.
 */
export function chooseColumn(
  read: ColumnMapping,
  mapping: ColumnMapping,
  column: string,
  target: string,
): ColumnMapping {
  const next: ColumnMapping = { ...mapping, [column]: target };
  if (!target || (read[column] ?? '') === target) return next;
  for (const [other, value] of Object.entries(next)) {
    if (other !== column && value === target) next[other] = '';
  }
  return next;
}

/** The columns whose choice differs from what the importer read them as. */
export function changedColumns(read: ColumnMapping, chosen: ColumnMapping): ColumnMapping {
  const changed: ColumnMapping = {};
  for (const [column, value] of Object.entries(chosen)) {
    if ((read[column] ?? '') !== value) changed[column] = value;
  }
  return changed;
}

/** The form field for the changed columns, or `null` when nothing changed. */
export function columnMappingField(read: ColumnMapping, chosen: ColumnMapping): string | null {
  const changed = changedColumns(read, chosen);
  return Object.keys(changed).length > 0 ? JSON.stringify(changed) : null;
}
