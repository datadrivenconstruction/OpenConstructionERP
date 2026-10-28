/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Resolving the name a backend module wears on screen.
 *
 * The module registry page used to render `display_name` straight from the
 * manifest, so all 185 module names showed in English to every reader in every
 * language. `ModuleManifest` did carry a `display_name_i18n` dict and the page
 * did declare it in its type, but nothing ever read it, which is why no gate
 * could see the hole: from the model side the field exists, and from the page
 * side the type says it exists.
 *
 * There are two legitimate sources and they cover different modules, so both
 * stay, in a fixed order:
 *
 *   1. `modules.catalog.<name>` in the locale files. This is where a bundled
 *      module's name belongs, because the locale files are the only place the
 *      existing i18n gates can see a string at all.
 *   2. `display_name_i18n` from the manifest. A module installed at runtime by
 *      the module builder cannot add keys to a compiled locale bundle, so for
 *      those modules this dict is the only translation path there is.
 *   3. `display_name`, the English wording, as the last resort.
 *
 * Note the order is by *quality of the answer*, not by source: a curated locale
 * value beats a hand-written manifest entry, but an English fallback does not.
 * That distinction is why this asks whether translation actually happened
 * rather than whether a key exists. `i18n.exists()` answers the second
 * question, and it returns true for a key present only in English, which would
 * let an English fallback shadow a manifest translation that is genuinely
 * better.
 */

export interface TranslatableModule {
  name: string;
  display_name: string;
  display_name_i18n?: Record<string, string> | null;
}

/** Translate function shape, narrowed to what this file uses. */
type Translate = (key: string, options: { defaultValue: string }) => string;

/**
 * The locale key that carries a module's name.
 *
 * Manifests name themselves `oe_<dir>` and the prefix carries no meaning for a
 * reader, so it is dropped: `oe_dwg_takeoff` becomes `modules.catalog.dwg_takeoff`.
 * `scripts/check_module_display_names.py` derives the key the same way, so the
 * gate and the page cannot drift apart.
 */
export function moduleDisplayNameKey(moduleName: string): string {
  return `modules.catalog.${moduleName.replace(/^oe_/, '')}`;
}

/**
 * Pick a manifest translation for a language, accepting a regional tag against
 * a bare entry: `de-AT` and `es-MX` fall back to `de` and `es`, which is what
 * the manifests actually carry.
 */
function fromManifest(
  dict: Record<string, string> | null | undefined,
  language: string,
): string | undefined {
  if (!dict || !language) return undefined;
  const exact = dict[language];
  if (exact && exact.trim()) return exact;
  const base = language.split('-')[0];
  const wide = !base || base === language ? undefined : dict[base];
  return wide && wide.trim() ? wide : undefined;
}

/**
 * The name to show for a module in the current language.
 *
 * `language` is `i18n.language`. Pass it explicitly rather than reading it off
 * a singleton so this stays a pure function and the test can name a language
 * without standing up i18next.
 */
export function resolveModuleDisplayName(
  mod: TranslatableModule,
  t: Translate,
  language: string,
): string {
  const english = mod.display_name;
  const translated = t(moduleDisplayNameKey(mod.name), { defaultValue: english });
  // A value that differs from the English one is a real translation. A value
  // equal to it means either this locale has no such key and i18next handed
  // back the fallback, or the language renders the term identically; both cases
  // want the manifest consulted next, and in the second case both answers agree
  // anyway.
  if (translated && translated !== english) return translated;
  return fromManifest(mod.display_name_i18n, language) ?? english;
}
