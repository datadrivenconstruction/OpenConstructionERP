import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { useTranslation as useI18nTranslation } from 'react-i18next';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇬🇧', country: 'gb' },
  { code: 'de', name: 'Deutsch', english: 'German', flag: '🇩🇪', country: 'de' },
  { code: 'fr', name: 'Français', english: 'French', flag: '🇫🇷', country: 'fr' },
  { code: 'es', name: 'Español', english: 'Spanish', flag: '🇪🇸', country: 'es' },
  { code: 'pt', name: 'Português', english: 'Portuguese', flag: '🇧🇷', country: 'br' },
  { code: 'ru', name: 'Русский', english: 'Russian', flag: '🇷🇺', country: 'ru' },
  { code: 'zh', name: '简体中文', english: 'Chinese (Simplified)', flag: '🇨🇳', country: 'cn' },
  { code: 'ar', name: 'العربية', english: 'Arabic', flag: '🇸🇦', country: 'sa', dir: 'rtl' },
  { code: 'hi', name: 'हिन्दी', english: 'Hindi', flag: '🇮🇳', country: 'in' },
  { code: 'tr', name: 'Türkçe', english: 'Turkish', flag: '🇹🇷', country: 'tr' },
  { code: 'it', name: 'Italiano', english: 'Italian', flag: '🇮🇹', country: 'it' },
  { code: 'nl', name: 'Nederlands', english: 'Dutch', flag: '🇳🇱', country: 'nl' },
  { code: 'pl', name: 'Polski', english: 'Polish', flag: '🇵🇱', country: 'pl' },
  { code: 'cs', name: 'Čeština', english: 'Czech', flag: '🇨🇿', country: 'cz' },
  { code: 'ja', name: '日本語', english: 'Japanese', flag: '🇯🇵', country: 'jp' },
  { code: 'ko', name: '한국어', english: 'Korean', flag: '🇰🇷', country: 'kr' },
  { code: 'sv', name: 'Svenska', english: 'Swedish', flag: '🇸🇪', country: 'se' },
  { code: 'no', name: 'Norsk', english: 'Norwegian', flag: '🇳🇴', country: 'no' },
  { code: 'da', name: 'Dansk', english: 'Danish', flag: '🇩🇰', country: 'dk' },
  { code: 'fi', name: 'Suomi', english: 'Finnish', flag: '🇫🇮', country: 'fi' },
  { code: 'bg', name: 'Български', english: 'Bulgarian', flag: '🇧🇬', country: 'bg' },
  { code: 'hr', name: 'Hrvatski', english: 'Croatian', flag: '🇭🇷', country: 'hr' },
  { code: 'id', name: 'Bahasa Indonesia', english: 'Indonesian', flag: '🇮🇩', country: 'id' },
  { code: 'ro', name: 'Română', english: 'Romanian', flag: '🇷🇴', country: 'ro' },
  { code: 'th', name: 'ไทย', english: 'Thai', flag: '🇹🇭', country: 'th' },
  { code: 'vi', name: 'Tiếng Việt', english: 'Vietnamese', flag: '🇻🇳', country: 'vn' },
  { code: 'mn', name: 'Монгол', english: 'Mongolian', flag: '🇲🇳', country: 'mn' },
];

export function getLanguageByCode(code: string): (typeof SUPPORTED_LANGUAGES)[number] {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code) ?? SUPPORTED_LANGUAGES[0]!;
}

// Re-export useTranslation for convenience
export const useTranslation = useI18nTranslation;

// English ships in the main bundle as the i18next fallback. Every other
// locale lives in its own per-language chunk and is fetched on demand —
// see ``loadLocaleResource`` below.
import enResource from './locales/en';

// Module translations applied at runtime
const moduleTranslations: Record<string, Record<string, Record<string, string>>> = {};

// Track which non-English locales have been hydrated so we don't fetch
// the same chunk twice (e.g. on every ``languageChanged`` round trip).
const loadedLocales = new Set<string>(['en']);

/**
 * Load a per-locale resource chunk and merge it into i18next.
 *
 * Vite turns the dynamic ``import(`./locales/${code}.ts`)`` literal into
 * one chunk per matching file under ``src/app/locales/``, so a French
 * user only downloads ``fr.ts`` (~50 KB gzip) instead of the previous
 * ~1.28 MB monolithic ``i18n-data`` chunk.
 *
 * Idempotent. Safe to call repeatedly. Failures are logged and treated
 * as non-fatal — i18next's ``fallbackLng: 'en'`` keeps the UI usable.
 */
export async function loadLocaleResource(code: string): Promise<void> {
  if (loadedLocales.has(code)) return;
  if (!SUPPORTED_LANGUAGES.some((l) => l.code === code)) return;
  try {
    const mod = await import(`./locales/${code}.ts`);
    const resource = (mod.default ?? mod) as { translation: Record<string, string> };
    // ``deep=false`` keeps the resource bundle as a flat dictionary —
    // critical because every locale file ships dotted keys like
    // ``"match_elements.title"`` and a deep merge auto-nests them under
    // ``match_elements.title``, which then can't be found by the flat
    // lookup the rest of the app expects (and breaks Header/Sidebar
    // translations for any locale loaded after init).
    i18n.addResourceBundle(code, 'translation', resource.translation, false, true);
    loadedLocales.add(code);
    // Force every ``useTranslation`` subscriber to re-render with the
    // freshly merged bundle. ``addResourceBundle`` already emits
    // ``store#added``, but components mounted outside Suspense (Header,
    // Sidebar) sometimes miss that event when StrictMode re-mounts them
    // mid-flight. Explicitly re-emitting ``languageChanged`` is the
    // signal react-i18next listens to unconditionally — every
    // useTranslation hook re-resolves its t() and re-renders.
    if (i18n.language === code) {
      i18n.emit('languageChanged', code);
    }
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(`i18n: failed to load locale "${code}", falling back to English`, err);
  }
}

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

  // 3. Host-level default for dedicated localized deployments.
  // Any .mn TLD domain defaults to Mongolian.
  try {
    const hostname = window.location.hostname.toLowerCase();
    if ((hostname.endsWith('.mn') || hostname === 'mn') && isValid('mn')) {
      return 'mn';
    }
  } catch {
    // hostname access failure — fall through.
  }

  // 4. Browser locale (strip region: "de-CH" → "de").
  const browserLang = (navigator.language || 'en').split('-')[0];
  if (isValid(browserLang)) return browserLang;

  // 5. Final fallback.
  return 'en';
}

const initialLanguage = resolveInitialLanguage();

i18n
  .use(initReactI18next)
  .init({
    // Only English is bundled synchronously — every other locale is
    // lazy-loaded by ``loadLocaleResource`` below. ``fallbackLng: 'en'``
    // means missing keys (e.g. while the locale chunk is still in
    // flight) render in English instead of as raw key strings.
    resources: { en: enResource },
    lng: initialLanguage,
    fallbackLng: 'en',
    // All translation keys are stored as flat strings with literal dots
    // (e.g. "match_elements.title"). Disable the dot-as-namespace
    // separator so lookups don't try to walk a nested object path that
    // doesn't exist in the resource shape. Without this, keys lazy-loaded
    // via ``addResourceBundle(..., deep=true)`` get auto-nested and become
    // unreachable from headers/sidebars rendered before the chunk arrives,
    // while the synchronously bundled EN resource stays flat — yielding a
    // silent EN-only fallback for every dotted key once a non-EN locale
    // is active.
    keySeparator: false,
    nsSeparator: false,
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
      // Re-render useTranslation subscribers when a resource bundle is
      // added (e.g. when a non-EN locale chunk lazy-loads via
      // ``loadLocaleResource``). Without this, components rendered
      // before the chunk arrives (Header, Sidebar) stay stuck on the
      // English fallback for their lifetime — visible only for keys
      // first painted by such early components, since later-mounting
      // components re-render naturally on every state change.
      bindI18nStore: 'added',
    },
  });

// Persist language choice to localStorage so it survives page reloads,
// AND fetch the corresponding locale chunk if it isn't loaded yet.
i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem('i18nextLng', lng);
  } catch {
    // localStorage not available (private browsing, etc.)
  }
  // Fire-and-forget; i18next will trigger a re-render when addResourceBundle
  // resolves. UI flashes English for the in-flight ms then re-paints.
  void loadLocaleResource(lng);
});

// If the user's resolved language isn't English, kick off the lazy-load
// straight away so the UI doesn't sit in English longer than necessary.
if (initialLanguage !== 'en') {
  void loadLocaleResource(initialLanguage);
}

// Merge module-bundled translations (nav keys for regional modules, etc.)
import { getModuleTranslations } from '@/modules/_registry';
const moduleTrans = getModuleTranslations();
for (const [lng, keys] of Object.entries(moduleTrans)) {
  if (keys && typeof keys === 'object') {
    i18n.addResourceBundle(lng, 'translation', keys, true, true);
  }
}

export default i18n;
