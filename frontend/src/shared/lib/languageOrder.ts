// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { compareNames } from './collator';

/**
 * Order a language list alphabetically by the name the reader sees in the
 * picker (the native `name`), so a language added anywhere in
 * `SUPPORTED_LANGUAGES` lands in place without hand reordering. The registry
 * itself keeps its order because `SUPPORTED_LANGUAGES[0]` is the fallback.
 *
 * The collation locale is fixed rather than the reader's on purpose: this is
 * the list a reader uses to CHANGE the language, and a picker that reshuffles
 * the moment a language is picked loses the reader's place in it.
 */
export function sortLanguagesByName<T extends { readonly name: string }>(languages: readonly T[]): T[] {
  return [...languages].sort((a, b) => compareNames(a.name, b.name, 'en'));
}
