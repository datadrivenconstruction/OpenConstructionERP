// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - market/region display helpers shared by the catalogue (CasesPage)
// and the case detail page (PlaybookRunner). One definition, so the two
// surfaces can never disagree about how a market is named.

/**
 * Localized display name for an ISO region code ("DE" reads as Deutschland
 * in a German UI) straight from Intl, so a new market never needs a locale
 * key of its own. Falls back to the raw code where DisplayNames is missing
 * (older WebKit, JSDOM).
 */
export function regionDisplayName(code: string, lang: string): string {
  try {
    return new Intl.DisplayNames([lang], { type: 'region' }).of(code) ?? code;
  } catch {
    return code;
  }
}
