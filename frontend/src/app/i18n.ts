import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { useTranslation as useI18nTranslation } from 'react-i18next';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇬🇧', country: 'gb' },
  { code: 'de', name: 'Deutsch', flag: '🇩🇪', country: 'de' },
  { code: 'fr', name: 'Français', flag: '🇫🇷', country: 'fr' },
  { code: 'es', name: 'Español', flag: '🇪🇸', country: 'es' },
  { code: 'pt', name: 'Português', flag: '🇧🇷', country: 'br' },
  { code: 'ru', name: 'Русский', flag: '🇷🇺', country: 'ru' },
  { code: 'zh', name: '简体中文', flag: '🇨🇳', country: 'cn' },
  { code: 'ar', name: 'العربية', flag: '🇸🇦', country: 'sa', dir: 'rtl' },
  { code: 'hi', name: 'हिन्दी', flag: '🇮🇳', country: 'in' },
  { code: 'tr', name: 'Türkçe', flag: '🇹🇷', country: 'tr' },
  { code: 'it', name: 'Italiano', flag: '🇮🇹', country: 'it' },
  { code: 'nl', name: 'Nederlands', flag: '🇳🇱', country: 'nl' },
  { code: 'pl', name: 'Polski', flag: '🇵🇱', country: 'pl' },
  { code: 'cs', name: 'Čeština', flag: '🇨🇿', country: 'cz' },
  { code: 'ja', name: '日本語', flag: '🇯🇵', country: 'jp' },
  { code: 'ko', name: '한국어', flag: '🇰🇷', country: 'kr' },
  { code: 'sv', name: 'Svenska', flag: '🇸🇪', country: 'se' },
  { code: 'no', name: 'Norsk', flag: '🇳🇴', country: 'no' },
  { code: 'da', name: 'Dansk', flag: '🇩🇰', country: 'dk' },
  { code: 'fi', name: 'Suomi', flag: '🇫🇮', country: 'fi' },
  { code: 'bg', name: 'Български', flag: '🇧🇬', country: 'bg' },
];

export function getLanguageByCode(code: string): (typeof SUPPORTED_LANGUAGES)[number] {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code) ?? SUPPORTED_LANGUAGES[0]!;
}

// Re-export useTranslation for convenience
export const useTranslation = useI18nTranslation;

import { fallbackResources } from './i18n-fallbacks';

// Module translations applied at runtime
const moduleTranslations: Record<string, Record<string, Record<string, string>>> = {};

export function applyModuleTranslations(
  moduleId: string,
  translations: Record<string, Record<string, string>>,
) {
  moduleTranslations[moduleId] = translations;
  // Merge into i18next
  for (const [lng, keys] of Object.entries(translations)) {
    if (keys && typeof keys === 'object') {
      i18n.addResourceBundle(lng, 'translation', keys, true, true);
    }
  }
}

/**
 * Resolve the initial UI language.
 *
 * Priority chain (first match wins):
 *   1. ``?lang=`` URL query param (validated against ``SUPPORTED_LANGUAGES``).
 *      If valid we also persist it to ``localStorage`` so the choice survives
 *      a refresh after the param is dropped from the URL.
 *   2. ``localStorage`` (``i18nextLng`` key) — last user choice.
 *   3. ``navigator.language`` — best-effort browser default.
 *   4. ``'en'`` — final fallback.
 *
 * SSR-safe: every ``window`` / ``localStorage`` / ``navigator`` access is
 * guarded so the function returns ``'en'`` when called outside a browser.
 */
function resolveInitialLanguage(): string {
  const supported = SUPPORTED_LANGUAGES.map((l) => l.code);
  const isValid = (code: string | null | undefined): code is string =>
    !!code && supported.includes(code);

  if (typeof window === 'undefined') return 'en';

  // 1. URL ?lang= param wins — useful for shareable localised links.
  try {
    const urlLang = new URLSearchParams(window.location.search).get('lang');
    if (isValid(urlLang)) {
      try {
        window.localStorage.setItem('i18nextLng', urlLang);
      } catch {
        // localStorage unavailable (private browsing) — non-fatal.
      }
      return urlLang;
    }
  } catch {
    // URL parsing failure — fall through to next source.
  }

  // 2. Stored preference from a previous session.
  try {
    const stored = window.localStorage.getItem('i18nextLng');
    if (isValid(stored)) return stored;
  } catch {
    // localStorage unavailable — fall through.
  }

  // 3. Browser locale (strip region: "de-CH" → "de").
  const browserLang = (navigator.language || 'en').split('-')[0];
  if (isValid(browserLang)) return browserLang;

  // 4. Final fallback.
  return 'en';
}

i18n
  .use(initReactI18next)
  .init({
    resources: fallbackResources,
    lng: resolveInitialLanguage(),
    fallbackLng: 'en',
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
  });

// Persist language choice to localStorage so it survives page reloads
i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem('i18nextLng', lng);
  } catch {
    // localStorage not available (private browsing, etc.)
  }
});

// Merge module-bundled translations (nav keys for regional modules, etc.)
import { getModuleTranslations } from '@/modules/_registry';
const moduleTrans = getModuleTranslations();
for (const [lng, keys] of Object.entries(moduleTrans)) {
  if (keys && typeof keys === 'object') {
    i18n.addResourceBundle(lng, 'translation', keys, true, true);
  }
}

export default i18n;
