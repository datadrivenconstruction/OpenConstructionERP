// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * partnerPackVocabulary — merge a partner pack's own locale file over the app's.
 *
 * A pack ships more than a language preference. It ships the words its market
 * actually uses: uk-jct calls the coordination screen a "Coordination Centre",
 * batimatech-ca calls the bill of quantities a "Bordereau de quantités" rather
 * than the metropolitan-French "Devis quantitatif". Those strings live in JSON
 * files inside the pack and the backend streams them from
 * ``/api/v1/partner-pack/locale/{code}``. Nothing ever fetched that endpoint,
 * so every one of those files was dead on disk.
 *
 * Two codes are in play and they are NOT the same code, which is the whole
 * reason this is a separate module from the language switch:
 *
 * - the **pack locale code** (``fr-CA``, ``en-GB``, ``pt``) is a key of the
 *   manifest's ``additional_locales`` map and the only thing the endpoint
 *   answers to. Fetch with this.
 * - the **UI language** is what ``normalizePackLocale`` resolves that code to
 *   (``fr-CA`` -> ``fr``, because there is no ``fr-CA`` in
 *   ``SUPPORTED_LANGUAGES``). Merge into this.
 *
 * Collapsing the two is what kills the feature: fetching ``/locale/fr`` for
 * batimatech-ca 404s, and merging ``fr-CA`` strings into a nonexistent ``fr-CA``
 * bundle renders nothing. The normalization itself is correct and stays —
 * a pack that names a region the UI does not ship must still inherit the base
 * language.
 *
 * The overlay follows the *current* language rather than the one forced at
 * activation. india-cpwd declares ``default_locale: "en"`` and ships only
 * ``hi``; batimatech-ca ships ``fr-CA`` and ``en-CA``. Under an
 * apply-once-at-activation model neither pack's second file could ever load.
 */

import i18n, { normalizePackLocale } from '@/app/i18n';
import { apiGet } from '@/shared/lib/api';

import type { PartnerPackManifest } from './usePartnerPack';

/**
 * One language's live overlay, and what the store held before we wrote it.
 *
 * ``previous`` records a key only when the value we replaced was not already
 * our own — see ``mergeOverlay``. A key absent from the map was never
 * overwritten by us and must be left exactly as it is on revert; a key mapped
 * to ``undefined`` did not exist before us and has to be deleted, not restored.
 */
interface LanguageOverlay {
  slug: string;
  code: string;
  entries: Record<string, string>;
  previous: Map<string, string | undefined>;
}

/** Live overlays, keyed by the i18next language they were merged into. */
const overlays = new Map<string, LanguageOverlay>();

/** Parsed locale files, keyed ``slug:code`` so a language toggle re-uses them. */
const fetched = new Map<string, Record<string, string>>();

/** Slug of the pack whose words are currently on screen, across all languages. */
let activeSlug: string | null = null;

/** Re-entrancy guard: our own merge emits the store event we listen to. */
let merging = false;

/** The store listener is installed on first use, not on import. */
let listening = false;

/**
 * Pull the translatable strings out of a pack locale file.
 *
 * Packs ship three shapes and all three are in the tree today: a
 * ``{_meta, translation: {...}}`` envelope (uk-jct, batimatech-ca), a flat map
 * of dotted keys next to a ``_meta`` block (bimhessen-de, india-cpwd), and a
 * flat map next to ``$``-prefixed header fields (doker-formwork). Bookkeeping
 * keys are skipped under both spellings, and non-string values are dropped so
 * a stray nested object cannot reach ``addResourceBundle``.
 */
export function packVocabularyFrom(payload: unknown): Record<string, string> {
  if (payload === null || typeof payload !== 'object') return {};
  const root = payload as Record<string, unknown>;
  const nested = root.translation;
  const source =
    nested !== null && typeof nested === 'object'
      ? (nested as Record<string, unknown>)
      : root;

  const entries: Record<string, string> = {};
  for (const [key, value] of Object.entries(source)) {
    if (key.startsWith('_') || key.startsWith('$')) continue;
    if (typeof value === 'string') entries[key] = value;
  }
  return entries;
}

/**
 * Pick which locale file, if any, belongs to the language now on screen.
 *
 * ``codes`` is the manifest's ``additional_locales`` list exactly as the
 * backend sorted it. A pack may ship several files that normalize to the same
 * UI language, so the tie is broken deterministically: an exact code match
 * first, then the pack's declared default, then the first sorted candidate.
 */
export function resolvePackVocabularyCode(
  codes: readonly string[],
  defaultLocale: string,
  language: string,
): string | null {
  const matches = codes.filter((code) => normalizePackLocale(code) === language);
  if (matches.length === 0) return null;
  return (
    matches.find((code) => code === language) ??
    matches.find((code) => code === defaultLocale) ??
    matches[0] ??
    null
  );
}

/** The flat ``translation`` bundle i18next currently holds for a language. */
function currentBundle(language: string): Record<string, string> {
  const stored = i18n.store.data[language];
  const bundle = stored === undefined ? undefined : stored.translation;
  if (bundle === undefined || typeof bundle !== 'object') return {};
  // Every bundle in this app is merged with ``deep=false``, so the namespace is
  // a flat dictionary of dotted keys to strings.
  return bundle as Record<string, string>;
}

/**
 * Write the overlay over a language, recording what it displaced.
 *
 * Called both on the first apply and again whenever a locale chunk lands on
 * top of us: ``loadLocaleResource`` merges with ``overwrite=true``, so a
 * language switch that fetches its chunk after we ran would otherwise silently
 * erase the pack's words. Re-running is safe because a key whose current value
 * is already ours is skipped — that keeps the *original*, pack-free value in
 * ``previous`` instead of overwriting the snapshot with our own strings.
 */
function mergeOverlay(language: string, overlay: LanguageOverlay): void {
  const bundle = currentBundle(language);
  for (const [key, value] of Object.entries(overlay.entries)) {
    const present = Object.prototype.hasOwnProperty.call(bundle, key);
    const existing = present ? bundle[key] : undefined;
    if (existing === value) continue;
    overlay.previous.set(key, existing);
  }

  merging = true;
  try {
    i18n.addResourceBundle(language, 'translation', overlay.entries, false, true);
  } finally {
    merging = false;
  }
  if (i18n.language === language) {
    i18n.emit('languageChanged', language);
  }
}

/**
 * Put one language back the way the pack found it.
 *
 * Keys we introduced are deleted from the store directly and keys we displaced
 * are written back. ``removeResourceBundle`` is not usable here — it drops the
 * whole namespace and would take the base locale with it.
 */
function restoreLanguage(language: string, overlay: LanguageOverlay): void {
  const bundle = currentBundle(language);
  const restore: Record<string, string> = {};
  for (const [key, value] of overlay.previous) {
    if (value === undefined) delete bundle[key];
    else restore[key] = value;
  }
  if (Object.keys(restore).length === 0) return;
  merging = true;
  try {
    i18n.addResourceBundle(language, 'translation', restore, false, true);
  } finally {
    merging = false;
  }
}

/** Re-assert the overlay when something else writes the same language. */
function handleStoreAdded(language: string, namespace: string): void {
  if (merging || namespace !== 'translation') return;
  const overlay = overlays.get(language);
  if (overlay === undefined) return;
  mergeOverlay(language, overlay);
}

function startListening(): void {
  if (listening) return;
  listening = true;
  i18n.store.on('added', handleStoreAdded);
}

/**
 * Fetch and apply the active pack's vocabulary for the language now on screen.
 *
 * A no-op when no pack is active, when the pack ships nothing for this
 * language, or when that overlay is already in place. Every failure path is
 * non-fatal and leaves the base locale untouched. That mattered concretely
 * while china-gbt50500 declared ``locales/zh.json`` without shipping it and
 * the endpoint genuinely 404d; the declaration is gone and
 * backend/tests/unit/test_community_packs_ship.py now refuses to let a pack in
 * this repository name a file it does not carry. The catch below stays,
 * because that gate only covers the packs we ship: a pack dropped into the
 * data directory or installed from PyPI by somebody else can still declare a
 * locale file that is not there, and it must not take the language down.
 *
 * Swapping packs is handled here rather than in the apply flow, because
 * applying a pack does not reload the app: the previous pack's overlay is
 * still live in the store when the next pack's manifest arrives.
 */
export async function syncPackVocabulary(
  manifest: PartnerPackManifest | undefined,
  language: string,
): Promise<void> {
  if (manifest === undefined) return;

  // A different pack than the one whose words are on screen: take the outgoing
  // pack's vocabulary off every language before doing anything else. This has
  // to come before the code lookup rather than after it, because the incoming
  // pack usually ships nothing for the language being read right now —
  // applying uk-jct while the UI is in French resolves to no file at all — and
  // returning early on that would strand the previous pack's words with no
  // language switch left to dislodge them.
  if (manifest.slug !== activeSlug) {
    revertPackVocabulary();
    activeSlug = manifest.slug;
  }

  const code = resolvePackVocabularyCode(
    manifest.additional_locales,
    manifest.default_locale,
    language,
  );
  if (code === null) return;

  const seen = overlays.get(language);
  if (seen !== undefined && seen.slug === manifest.slug && seen.code === code) {
    return;
  }

  const cacheKey = `${manifest.slug}:${code}`;
  let entries = fetched.get(cacheKey);
  if (entries === undefined) {
    try {
      const payload = await apiGet<unknown>(
        `/v1/partner-pack/locale/${encodeURIComponent(code)}`,
      );
      entries = packVocabularyFrom(payload);
    } catch {
      // A pack that declares a locale file it does not ship, or a backend that
      // cannot read it, must not take the language down with it.
      entries = {};
    }
    fetched.set(cacheKey, entries);
  }
  if (Object.keys(entries).length === 0) return;

  // Re-read rather than reuse the pre-fetch snapshot: a second call for this
  // same pack and language can land while the request is in flight, and
  // merging twice would snapshot our own words as the originals.
  const existing = overlays.get(language);
  if (existing !== undefined && existing.slug === manifest.slug && existing.code === code) {
    return;
  }

  startListening();
  const overlay: LanguageOverlay = {
    slug: manifest.slug,
    code,
    entries,
    previous: new Map<string, string | undefined>(),
  };
  overlays.set(language, overlay);
  mergeOverlay(language, overlay);
}

/**
 * Put every language back the way the pack found it.
 *
 * Deactivation has to undo the words as well as the language, or a user who
 * removes the UK pack keeps reading "Coordination Centre" until a full reload.
 */
export function revertPackVocabulary(): void {
  const touched: string[] = [];
  for (const [language, overlay] of overlays) {
    restoreLanguage(language, overlay);
    touched.push(language);
  }
  overlays.clear();
  fetched.clear();
  activeSlug = null;
  if (touched.includes(i18n.language)) {
    i18n.emit('languageChanged', i18n.language);
  }
}

/** Test seam: forget every overlay without touching the i18next store. */
export function __resetPackVocabularyForTests(): void {
  overlays.clear();
  fetched.clear();
  activeSlug = null;
  if (listening) {
    i18n.store.off('added', handleStoreAdded);
    listening = false;
  }
}
