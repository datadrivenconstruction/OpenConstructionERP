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
  /** i18next's lookup chain for the current language (`pt-BR`, `pt`, `en`). */
  languages?: readonly string[];
  getResource: (lng: string, ns: string, key: string) => unknown;
}

/**
 * The language a translation key is shown in: the first language in the
 * lookup chain that has it, else English, which every `defaultValue` in this
 * product is. The chain matters for regional locales: `pt-BR` carries only its
 * differences from `pt`, so a key missing from `pt-BR` but present in `pt` is
 * still shown in Portuguese and must not be tagged as English.
 */
export function keyLanguage(i18n: ResourceReader, key: string, ns = 'translation'): string {
  const ui = i18n.language || i18n.resolvedLanguage || 'en';
  const chain = i18n.languages && i18n.languages.length > 0 ? i18n.languages : [ui, baseLanguage(ui)];
  for (const lng of chain) {
    const value = i18n.getResource(lng, ns, key);
    if (typeof value === 'string' && value.length > 0) return lng;
  }
  return 'en';
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

/** The tags a card's tiles carry, each once, in first-seen order, for the
 *  legend that explains them. Tiles in the UI language (null) are skipped. */
export function distinctTags(tags: readonly (string | null | undefined)[]): string[] {
  const out: string[] = [];
  for (const tag of tags) if (tag && !out.includes(tag)) out.push(tag);
  return out;
}
