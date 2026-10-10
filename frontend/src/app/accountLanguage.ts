// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Keep the interface language with the account, not only with the browser.
 *
 * The language lives in the browser's storage for this origin. A new origin
 * starts without it: the desktop window that had to move to another port
 * because a different program held its usual one, a new browser, a cleared
 * cache. The account has carried a ``locale`` all along, but nothing wrote the
 * language a person picked into it and nothing read it back, so on a fresh
 * origin the language silently fell back to the browser's.
 *
 * Now a language picked while signed in is saved to the account, and after a
 * sign-in on an origin that held no choice of its own the account's language
 * is put back. A choice made here, in this browser, always wins over it.
 */
import i18n from 'i18next';

import { API_BASE, apiGet } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

import { SUPPORTED_LANGUAGES, languageChosenHere } from './i18n';

const SUPPORTED_CODES: readonly string[] = SUPPORTED_LANGUAGES.map((l) => l.code);

/**
 * The account language to switch to after a sign-in, or ``null`` to keep the
 * one on screen.
 *
 * ``en`` is never restored: it is the column default every account starts
 * with, so it says nothing about what the person chose, and restoring it would
 * turn a browser that matched their language into an English one.
 */
export function accountLanguageToApply(
  account: string | null | undefined,
  current: string,
  chosenHere: boolean,
  supported: readonly string[] = SUPPORTED_CODES,
): string | null {
  if (chosenHere) return null;
  if (!account || account === 'en') return null;
  if (!supported.includes(account)) return null;
  return account === current ? null : account;
}

let started = false;

/** Start keeping the account's language. Safe to call more than once. */
export function startAccountLanguageSync(): void {
  if (started) return;
  started = true;

  // The language last settled with the account, or the one already on screen
  // at start. Only a change away from it is written, so the language the page
  // simply loaded in is never pushed over what the account holds, and one that
  // came from the account is not written straight back to it.
  let settled: string = i18n.language;
  // A language picked on this page before signing in counts as a choice made
  // here, like one found in storage at load.
  let chosenHere = languageChosenHere;
  let restoreTried = false;
  // While the account is being read, a language event is the page settling,
  // not the person choosing; writing it would race the read it is waiting on.
  let restoring = false;

  const restore = async () => {
    if (restoreTried || chosenHere) return;
    restoreTried = true;
    restoring = true;
    try {
      const me = await apiGet<{ locale?: string | null }>('/v1/users/me/');
      const target = accountLanguageToApply(me.locale, i18n.language, chosenHere);
      if (target) await i18n.changeLanguage(target);
    } catch {
      // The profile could not be read: the language on screen stays.
    } finally {
      settled = i18n.language;
      restoring = false;
    }
  };

  if (useAuthStore.getState().accessToken) void restore();
  useAuthStore.subscribe((state, prev) => {
    if (state.accessToken && !prev.accessToken) void restore();
  });

  i18n.on('languageChanged', (lng: string) => {
    const token = useAuthStore.getState().accessToken;
    if (!token) {
      if (lng !== settled) chosenHere = true;
      settled = lng;
      return;
    }
    if (restoring || lng === settled) return;
    settled = lng;
    // A plain request rather than the api client: this is a side effect of
    // switching the language, not something the person asked to save, so a
    // refusal (the public demonstration refuses every profile write) must not
    // put the client's "not saved" dialog in front of them.
    void fetch(`${API_BASE}/v1/users/me/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ locale: lng }),
    }).catch(() => {
      // Not saved to the account; it is still kept in this browser.
    });
  });
}
