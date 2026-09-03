// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * usePartnerPackLocale — force the active partner pack's UI language, and load
 * the vocabulary that pack ships for it.
 *
 * A partner pack declares a ``default_locale`` (batimatech-ca ships ``fr-CA``
 * for French Canada). When the pack is active the whole app should present in
 * that language. This hook applies the pack's normalized locale once per
 * activation: it switches i18next, persists the choice, and records a marker so
 * it does not fight a user who later picks a different language from the header.
 *
 * Choosing the language is only half of it. The pack also ships its market's
 * own words as JSON files the backend streams from ``/partner-pack/locale``,
 * and those are keyed by the pack's *unnormalized* code — see
 * ``partnerPackVocabulary``, which owns that half. The vocabulary tracks
 * whatever language is on screen, not just the one forced at activation, so a
 * pack whose extra file is not its default (india-cpwd ships ``hi`` under
 * ``default_locale: "en"``) still reaches the user who selects it.
 *
 * A third thing rides along, and it is deliberately not keyed off the locale:
 * which market's convention the workspace's NUMBERS are grouped in. That
 * follows the pack's COUNTRY, because india-cpwd speaks English and still
 * groups by lakh and crore, so a pack can need one answer for its words and
 * another for its figures. See ``marketNumberLocale``.
 *
 * Deactivation is handled by ``PartnerPackDeactivateDialog`` calling
 * ``resetPackLocale`` (reverts to English, drops the vocabulary, clears the
 * marker and the market), so toggling a pack on then off leaves the language
 * and the grouping exactly where they started.
 */

import { useEffect } from 'react';

import i18n, { loadLocaleResource, normalizePackLocale } from '@/app/i18n';
import { setMarketNumberLocale } from '@/shared/lib/marketNumberLocale';
import { packCountryCode } from '@/shared/lib/regionalPack';
import { numberLocaleForCountry } from '@/stores/usePreferencesStore';

import { revertPackVocabulary, syncPackVocabulary } from './partnerPackVocabulary';
import { usePartnerPack } from './usePartnerPack';

/** localStorage marker: the slug of the pack whose locale we already forced. */
const PACK_LOCALE_MARKER = 'oce-pack-locale-active';

/**
 * Revert the UI language to English and clear the pack-locale marker.
 *
 * Called from the deactivate flow. Safe to call when no pack locale was ever
 * forced (it just sets English). localStorage failures are non-fatal.
 */
export async function resetPackLocale(): Promise<void> {
  try {
    window.localStorage.removeItem(PACK_LOCALE_MARKER);
    window.localStorage.setItem('i18nextLng', 'en');
  } catch {
    // localStorage unavailable (private browsing) — non-fatal.
  }
  // The market's digit grouping goes with the pack that justified it. Nothing
  // persists this tag, so leaving it set would keep an un-applied India pack's
  // lakh grouping for the rest of the session with no control in the UI able
  // to reach it.
  setMarketNumberLocale(null);
  // Drop the pack's words before the language switch. Switching to English is
  // not enough on its own: a pack whose locale normalizes to ``en`` (uk-jct,
  // aus, nzs) merged its overlay straight onto the English bundle, and
  // ``loadLocaleResource('en')`` cannot undo that — English ships in the main
  // bundle, so that call returns immediately without re-reading anything.
  revertPackVocabulary();
  await loadLocaleResource('en');
  await i18n.changeLanguage('en');
}

/**
 * Apply the active pack's language and vocabulary. Mount once, app-wide
 * (AppLayout).
 *
 * The language switch is a no-op when no pack is active, when the pack's locale
 * resolves to English, or when this pack's locale was already forced this
 * session. The vocabulary overlay has none of those exemptions — it runs for
 * every active pack and follows the language the user is actually reading.
 */
export function usePartnerPackLocale(): void {
  const { data } = usePartnerPack();

  useEffect(() => {
    if (!data?.active || !data.manifest) return;
    const slug = data.manifest.slug;
    const target = normalizePackLocale(data.manifest.default_locale);
    // Nothing to force when the pack speaks English.
    if (target === 'en') return;

    let alreadyForced = false;
    try {
      alreadyForced = window.localStorage.getItem(PACK_LOCALE_MARKER) === slug;
    } catch {
      alreadyForced = false;
    }
    // Force once per activation, so a later manual language pick sticks.
    if (alreadyForced) return;

    try {
      window.localStorage.setItem(PACK_LOCALE_MARKER, slug);
      window.localStorage.setItem('i18nextLng', target);
    } catch {
      // localStorage unavailable — the changeLanguage below still applies it
      // for this session.
    }
    void loadLocaleResource(target).then(() => i18n.changeLanguage(target));
  }, [data]);

  // Second, independent concern: keep the pack's vocabulary in step with the
  // language actually on screen. This runs for every active pack, including
  // the ones the effect above returns early on (an English pack still has
  // British or American words to contribute), and it re-runs on every manual
  // language switch rather than once per activation.
  const manifest = data?.active ? data.manifest : undefined;
  useEffect(() => {
    if (manifest === undefined) return;
    void syncPackVocabulary(manifest, i18n.language);

    const onLanguageChanged = (lng: string): void => {
      void syncPackVocabulary(manifest, lng);
    };
    i18n.on('languageChanged', onLanguageChanged);
    return () => {
      i18n.off('languageChanged', onLanguageChanged);
    };
  }, [manifest]);

  // Third, independent concern: which market's convention the workspace's
  // NUMBERS are grouped in, which is not the same question as which language
  // its words are in. India is why the two had to come apart. The pack's UI
  // language is English, so the effect above returns early on it, while the
  // market still writes `47,65,79,722.78` where English writes
  // `476,579,722.78`. Keying this off the pack's country rather than its
  // locale is what lets one pack answer both questions differently.
  //
  // No early return and no marker: unlike the forced language, this is not a
  // choice the user can make in the header, so there is nothing to fight, and
  // an inactive pack has to clear it rather than leave the last market behind.
  useEffect(() => {
    setMarketNumberLocale(manifest ? numberLocaleForCountry(packCountryCode(manifest)) : null);
  }, [manifest]);
}
