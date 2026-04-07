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

i18n
  .use(initReactI18next)
  .init({
    resources: fallbackResources,
    lng: localStorage.getItem('i18nextLng') || (() => {
      // Auto-detect browser language for first-time users
      const browserLang = (navigator.language || 'en').split('-')[0];
      const supported = SUPPORTED_LANGUAGES.map((l) => l.code);
      return supported.includes(browserLang ?? '') ? browserLang : 'en';
    })(),
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
