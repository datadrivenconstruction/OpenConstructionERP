// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Order a language list alphabetically by the name the reader sees in the
 * picker (the native `name`), so a language added anywhere in
 * `SUPPORTED_LANGUAGES` lands in place without hand reordering. The registry
 * itself keeps its order because `SUPPORTED_LANGUAGES[0]` is the fallback.
 */
export function sortLanguagesByName<T extends { readonly name: string }>(languages: readonly T[]): T[] {
  return [...languages].sort((a, b) => a.name.localeCompare(b.name, 'en', { sensitivity: 'base' }));
}
