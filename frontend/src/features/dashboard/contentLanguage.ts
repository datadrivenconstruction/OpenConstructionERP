// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which language a piece of dashboard content is actually shown in.
 *
 * Cases and videos carry text that may or may not exist in the reader's
 * language. A case title falls back to English through `defaultValue`, a video
 * is spoken in one language. Either way the reader deserves to know before
 * opening it, so the card prints a small language tag ("EN") on content that
 * does not match the UI language, and nothing on content that does.
 */

/** The base subtag of a BCP 47 tag, lower-cased: `pt-BR` reads `pt`. */
export function baseLanguage(tag: string | null | undefined): string {
  return (tag ?? '').split(/[-_]/)[0]?.toLowerCase() ?? '';
}

/** The tag to print beside content in `contentLanguage`, or null when it
 *  matches the UI language and no tag is needed. */
export function languageTag(contentLanguage: string, uiLanguage: string): string | null {
  const content = baseLanguage(contentLanguage);
  if (!content || content === baseLanguage(uiLanguage)) return null;
  return content.toUpperCase();
}

/** The slice of i18next this module reads, so tests can pass a plain object. */
export interface ResourceReader {
  language: string;
  resolvedLanguage?: string;
  getResource: (lng: string, ns: string, key: string) => unknown;
}

/**
 * The language a translation key is shown in: the UI language when the key
 * exists there, else English, which every `defaultValue` in this product is.
 */
export function keyLanguage(i18n: ResourceReader, key: string, ns = 'translation'): string {
  const ui = i18n.resolvedLanguage ?? i18n.language;
  const value = i18n.getResource(ui, ns, key);
  return typeof value === 'string' && value.length > 0 ? ui : 'en';
}

/**
 * Stable reorder that puts content in the reader's language first. Nothing is
 * dropped: a reader whose language has no video still gets the English ones,
 * tagged, rather than an empty strip.
 */
export function preferLanguage<T>(items: readonly T[], languageOf: (item: T) => string, uiLanguage: string): T[] {
  const ui = baseLanguage(uiLanguage);
  const own = items.filter((item) => baseLanguage(languageOf(item)) === ui);
  const rest = items.filter((item) => baseLanguage(languageOf(item)) !== ui);
  return [...own, ...rest];
}
