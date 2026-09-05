// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { useTranslation as useI18nTranslation } from 'react-i18next';

export const SUPPORTED_LANGUAGES = [
  { code: 'en', name: 'English', flag: '🇬🇧', country: 'gb' },
  // American English is a regional variant of the entry above, in the same sense
  // es-MX is one of es: the file under `locales/en-US.ts` holds only the words
  // American practice names differently, and every other key is answered by
  // `en.ts` through the fallback chain. The region subtag is upper case because
  // that is how i18next normalises a two-part code, and the bundle has to be
  // registered under the same spelling it looks up.
  { code: 'en-US', name: 'English (US)', english: 'English (United States)', flag: '🇺🇸', country: 'us' },
  { code: 'de', name: 'Deutsch', english: 'German', flag: '🇩🇪', country: 'de' },
  { code: 'fr', name: 'Français', english: 'French', flag: '🇫🇷', country: 'fr' },
  { code: 'es', name: 'Español', english: 'Spanish', flag: '🇪🇸', country: 'es' },
  { code: 'es-MX', name: 'Español (México)', english: 'Spanish (Mexico)', flag: '🇲🇽', country: 'mx' },
  { code: 'es-CL', name: 'Español (Chile)', english: 'Spanish (Chile)', flag: '🇨🇱', country: 'cl' },
  { code: 'es-CO', name: 'Español (Colombia)', english: 'Spanish (Colombia)', flag: '🇨🇴', country: 'co' },
  { code: 'pt', name: 'Português', english: 'Portuguese', flag: '🇵🇹', country: 'pt' },
  { code: 'pt-BR', name: 'Português (Brasil)', english: 'Portuguese (Brazil)', flag: '🇧🇷', country: 'br' },
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
  // Mongolian is deliberately not offered: five invented roots passed every
  // gate in mn.ts and the file needs a native-speaker pass before the
  // language returns. The locale file stays on disk so the work resumes from
  // where it stopped, but nothing loads it while it is off this list.
  { code: 'ky', name: 'Кыргызча', english: 'Kyrgyz', flag: '🇰🇬', country: 'kg' },
  { code: 'et', name: 'Eesti', english: 'Estonian', flag: '🇪🇪', country: 'ee' },
  { code: 'bn', name: 'বাংলা', english: 'Bengali', flag: '🇧🇩', country: 'bd' },
  { code: 'kk', name: 'Қазақша', english: 'Kazakh', flag: '🇰🇿', country: 'kz' },
  { code: 'fil', name: 'Filipino', english: 'Filipino', flag: '🇵🇭', country: 'ph' },
  { code: 'ur', name: 'اردو', english: 'Urdu', flag: '🇵🇰', country: 'pk', dir: 'rtl' },
  { code: 'fa', name: 'فارسی', english: 'Persian', flag: '🇮🇷', country: 'ir', dir: 'rtl' },
  { code: 'he', name: 'עברית', english: 'Hebrew', flag: '🇮🇱', country: 'il', dir: 'rtl' },
  { code: 'el', name: 'Ελληνικά', english: 'Greek', flag: '🇬🇷', country: 'gr' },
  // `uk` is the ISO 639-1 code for Ukrainian, and it is also the string this
  // codebase already uses for the United Kingdom as a *region*: a BoQ preset
  // region, a country-pack id, and the country map in CreateProjectPage all
  // carry `uk` meaning Britain. The two live in different namespaces and must
  // stay that way. Nothing may derive a UI language from a region code, or a
  // British project would come up in Ukrainian.
  { code: 'uk', name: 'Українська', english: 'Ukrainian', flag: '🇺🇦', country: 'ua' },
  // Uzbek is written in Latin script: the Latin alphabet has been the official
  // one since 1993 and is what public and construction documentation uses. The
  // two modifier letters in the language's own name are U+02BB, not an
  // apostrophe, and a straight quote there is a misspelling rather than a
  // typographic preference.
  //
  // The *.insights.* and cases.* bands that had been left in English since
  // 9ac55ac74 (2026-08-17) were closed on 2026-09-01, along with the rest of
  // uz.ts that was still byte-identical to en.ts outside those bands. Offered
  // below.
  { code: 'uz', name: 'Oʻzbekcha', english: 'Uzbek', flag: '🇺🇿', country: 'uz' },
];

export function getLanguageByCode(code: string): (typeof SUPPORTED_LANGUAGES)[number] {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code) ?? SUPPORTED_LANGUAGES[0]!;
}

/**
 * Normalize a partner-pack ``default_locale`` to a supported UI language code.
 *
 * Pack manifests carry BCP-47 locales that often include a region subtag
 * (batimatech-ca ships ``fr-CA`` for French Canada, uk-jct ships ``en-GB``,
 * commercial-denver ships ``en-US``). A regional code the UI actually ships is
 * answered with itself, because a pack that names a region has asked for that
 * region and stripping it would hand a Denver pack British English. Anything
 * else falls back to the base language (``fr-CA`` -> ``fr``), and a locale we do
 * not ship at all returns ``'en'``, so a pack can never force the app into a
 * language that has no strings.
 */
export function normalizePackLocale(locale: string | null | undefined): string {
  return matchSupportedLanguage(locale) ?? 'en';
}

/**
 * The language code we ship that best answers a BCP-47 tag, or ``null`` when
 * we ship nothing for it.
 *
 * Region first, then the base language, spelled the way i18next spells a
 * two-part code so that 'pt-br' and 'PT-BR' both find the 'pt-BR' bundle we
 * actually registered. A three-part tag such as zh-Hans-CN finds no
 * 'zh-HANS' and falls to 'zh', which is the right answer for it.
 *
 * One function because there is one rule, and it is asked in three places:
 * a pack manifest's default_locale, the browser's language at first run, and
 * the language card the onboarding wizard pre-selects. Those were three
 * copies, two of which stripped the region unconditionally, which is how a
 * Brazilian first run opened in European Portuguese with pt-BR.ts sitting
 * unused a few lines away.
 */
export function matchSupportedLanguage(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const parts = raw.trim().split('-');
  if (parts.length >= 2 && parts[1]) {
    const regional = `${parts[0]!.toLowerCase()}-${parts[1]!.toUpperCase()}`;
    if (SUPPORTED_LANGUAGES.some((l) => l.code === regional)) return regional;
  }
  const base = parts[0]!.toLowerCase();
  return SUPPORTED_LANGUAGES.some((l) => l.code === base) ? base : null;
}

/**
 * The country this browser is most likely sitting in, lower-case ISO 3166-1
 * alpha-2, or ``null`` when nothing says.
 *
 * Two sources, and both are needed. The region subtag of
 * ``navigator.language`` is the better one wherever it exists, and it is the
 * ONLY one that can reach Australia, New Zealand or South Africa, because no
 * language we offer names those countries -- ``en`` names Great Britain. But
 * a German, French, Polish or Russian browser commonly sends a bare ``de``,
 * ``fr``, ``pl`` or ``ru`` with no region at all, so a region-only reading
 * returns nothing for most of Europe, which is where most of our cases are.
 * Falling back to the country named by the resolved language covers those,
 * and every one of the SUPPORTED_LANGUAGES entries carries that field.
 *
 * ``en`` maps to ``gb``, so a browser sending a bare ``en`` is read as United
 * Kingdom rather than United States. That is chosen, not overlooked:
 * ``en-US`` is its own entry with its own country, so a reader who wants
 * American English has a browser that already says so, and guessing the
 * larger market from silence would be guessing.
 *
 * This is a hint used to OFFER something, never a gate. Nothing may become
 * unreachable because the guess was wrong, and a wrong guess must always be
 * one click away from the right answer.
 *
 * @param uiLanguage Language to read the fallback country from. Defaults to
 *   the live ``i18n.language``; pass it explicitly when the caller already
 *   knows which language it is rendering in, or when a test needs the
 *   fallback half to be deterministic.
 */
export function detectCountry(uiLanguage?: string): string | null {
  const raw = typeof navigator !== 'undefined' ? navigator.language || '' : '';
  // Scan past the language subtag rather than reading parts[1], so a script
  // subtag does not hide the region: zh-Hans-CN has to answer 'cn'. A UN M49
  // region such as es-419 is deliberately not matched here and falls through
  // to the language's own country.
  for (const part of raw.trim().split('-').slice(1)) {
    if (/^[A-Za-z]{2}$/.test(part)) return part.toLowerCase();
  }
  const code = uiLanguage || i18n.language || 'en';
  const entry =
    SUPPORTED_LANGUAGES.find((l) => l.code === code) ??
    SUPPORTED_LANGUAGES.find((l) => l.code === code.split('-')[0]);
  return entry?.country ?? null;
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
 * Load and register exactly one locale chunk. Never throws.
 *
 * Vite turns the dynamic ``import(`./locales/${code}.ts`)`` literal into
 * one chunk per matching file under ``src/app/locales/``, so a French
 * user only downloads ``fr.ts`` (~50 KB gzip) instead of the previous
 * ~1.28 MB monolithic ``i18n-data`` chunk.
 *
 * Idempotent. Returns whether this call actually put a new bundle in the
 * store, which is what tells the caller a re-render is worth emitting.
 * Failures are logged and treated as non-fatal — i18next's fallback chain
 * keeps the UI usable.
 */
async function loadLocaleChunk(code: string): Promise<boolean> {
  if (loadedLocales.has(code)) return false;
  if (!SUPPORTED_LANGUAGES.some((l) => l.code === code)) return false;
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
    return true;
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(`i18n: failed to load locale "${code}", falling back to English`, err);
    return false;
  }
}

/**
 * Load a locale into i18next, together with the base language it falls back to.
 *
 * A regional variant carries only what its region words differently and leans on
 * its base language for the rest — that is the whole point of ``fallbackLng``
 * above. But ``fallbackLng`` only names a bundle; it does not fetch one. This
 * function used to import ``code`` and nothing else, so for the four variants
 * whose base is itself lazy the chain was configured and inert: an es-MX reader's
 * lookup walked es-MX, then an ``es`` bucket that was never loaded, then landed on
 * English. The ~2700 ``cases.*`` keys that ``es.ts`` has and ``es-MX.ts`` does not
 * rendered in English with a complete Spanish translation sitting in a chunk
 * nobody asked for. Same for es-CL, es-CO and pt-BR.
 *
 * ``en-US`` is why this went unnoticed: its base is ``en``, which ships in the main
 * bundle and is in ``loadedLocales`` from the start, so the one variant with a test
 * was also the one variant that worked.
 *
 * The base is derived from the code rather than special-cased per locale, so the
 * next regional variant added to ``SUPPORTED_LANGUAGES`` is chained by existing
 * code instead of by somebody remembering to copy a branch.
 *
 * Direction matters and is load-bearing: the two bundles go into *separate*
 * per-language buckets, and i18next consults ``es-MX`` before ``es``. So every key
 * the variant defines keeps winning, and only the keys it omits come from the base.
 * It is a fallback, never a replacement — the variants exist because Mexican,
 * Chilean, Colombian and Brazilian practice name things differently from Spain and
 * Portugal (costo not coste, cimbra not encofrado), and overwriting that deliberate
 * wording with the base language would be a regression that nothing on screen would
 * reveal.
 *
 * Both imports are awaited together rather than fired off, because
 * ``initialLocaleReady`` below is what ``main.tsx`` waits on before mounting: a
 * base chunk still in flight when that promise settles would paint the first frame
 * in English for exactly the keys this change is meant to fix. Each chunk keeps its
 * own error handling, so a failed base fetch costs the reader nothing they had
 * before — they still get the variant's own strings.
 */
export async function loadLocaleResource(code: string): Promise<void> {
  const base = code.includes('-') ? code.split('-')[0]! : null;
  const [variantAdded, baseAdded] = await Promise.all([
    loadLocaleChunk(code),
    base ? loadLocaleChunk(base) : Promise.resolve(false),
  ]);
  // Force every ``useTranslation`` subscriber to re-render with the
  // freshly merged bundle. ``addResourceBundle`` already emits
  // ``store#added``, but components mounted outside Suspense (Header,
  // Sidebar) sometimes miss that event when StrictMode re-mounts them
  // mid-flight. Explicitly re-emitting ``languageChanged`` is the
  // signal react-i18next listens to unconditionally — every
  // useTranslation hook re-resolves its t() and re-renders.
  if ((variantAdded || baseAdded) && i18n.language === code) {
    i18n.emit('languageChanged', code);
  }
}

/**
 * Switch the active UI language, guaranteeing its strings are registered
 * *before* the switch is announced. Use this from every language switcher.
 *
 * A bare ``i18n.changeLanguage(code)`` flips i18next to the new language
 * synchronously, but the per-locale chunk is lazy-loaded — so at that instant
 * the store holds no strings for ``code`` and every ``t()`` resolves through
 * the English ``fallbackLng``. The UI then depends on the async chunk landing
 * and firing a *second* re-render to recover, which flashes English and, under
 * StrictMode's mount churn, can be missed entirely (the "lazy-locale Header
 * race") — leaving the interface in English until a manual reload.
 *
 * Loading the chunk first means ``changeLanguage`` emits ``languageChanged``
 * with the resources already in the store, so every ``useTranslation``
 * subscriber re-renders straight into the target language. This mirrors the
 * load-then-switch order already used by ``usePartnerPackLocale``.
 *
 * ``loadLocaleResource`` is idempotent, so re-selecting a loaded language just
 * runs the cheap ``changeLanguage`` call. Failures inside ``loadLocaleResource``
 * are swallowed there (English fallback), so the switch still proceeds.
 */
export async function changeLanguage(code: string): Promise<void> {
  await loadLocaleResource(code);
  await i18n.changeLanguage(code);
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
export function resolveInitialLanguage(): string {
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

  // 3. Browser locale. Asks for the full code BEFORE stripping the region,
  //    because for five of the languages we ship the region is the whole
  //    point: pt-BR and pt are different files and plain "pt" is European
  //    Portuguese. Stripping first meant every Brazilian first run opened in
  //    Portugal's Portuguese and every Mexican one in Spain's Spanish, with
  //    the regional file sitting right there unused. "de-CH" still resolves
  //    to "de", because we ship no de-CH.
  const browserMatch = matchSupportedLanguage(navigator.language);
  if (browserMatch) return browserMatch;

  // 4. Final fallback.
  return 'en';
}

const initialLanguage = resolveInitialLanguage();

i18n
  .use(initReactI18next)
  .init({
    // Initialize synchronously: every resource this init needs is already in
    // memory (the bundled EN object), so deferring init to a timer only opens
    // a boot window where ``t()`` echoes raw keys. With sync init the store
    // is ready the moment this module finishes evaluating, which the
    // ``initialLocaleReady`` mount gate below relies on.
    initImmediate: false,
    // Only English is bundled synchronously — every other locale is
    // lazy-loaded by ``loadLocaleResource`` below. ``fallbackLng: 'en'``
    // means missing keys (e.g. while the locale chunk is still in
    // flight) render in English instead of as raw key strings.
    resources: { en: enResource },
    lng: initialLanguage,
    // The regional variants fall back to their own language before English, so
    // a key not localised for Chile shows Spanish rather than English. That is
    // what lets those files carry only the words that actually differ.
    //
    // en-US needs no line of its own. i18next resolves a two-part code through
    // ['en-US', 'en'] before it ever consults this map, and the `default` branch
    // below names the same fallback again, so a key absent from en-US.ts is
    // answered by en.ts either way. Asserted in enUSFallsBackToEnglish.test.ts
    // rather than assumed, because a missing key and a resolved one look alike
    // on screen when every call site passes a defaultValue.
    fallbackLng: {
      'es-MX': ['es', 'en'],
      'es-CL': ['es', 'en'],
      'es-CO': ['es', 'en'],
      'pt-BR': ['pt', 'en'],
      default: ['en'],
    },
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
      // Re-render useTranslation subscribers on a language switch AND when a
      // lazily loaded bundle finishes loading. ``languageChanged`` is the
      // react-i18next default; ``loaded`` additionally covers a locale chunk
      // that resolves right after the switch. Together with
      // ``bindI18nStore: 'added'`` below (fired by ``addResourceBundle``) this
      // guarantees a re-render however the strings arrive.
      bindI18n: 'languageChanged loaded',
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

/**
 * Resolves once the resources of the *initial* language are in the store,
 * or ``null`` when there is nothing to wait for (English boot).
 *
 * i18next starts with only the bundled English resource; the active locale
 * arrives in a lazy chunk. Merely kicking that fetch off (`void load...`)
 * loses the race against React's first paint every single time — the first
 * frame of every non-English session rendered in English, whatever the cache
 * state, because the paint is synchronous and the chunk resolve never is.
 * ``main.tsx`` therefore awaits this promise (with a hard time cap so a
 * stalled fetch cannot hold the mount hostage) before mounting the app, so
 * the first frame already speaks the saved language.
 *
 * ``loadLocaleResource`` swallows its own failures (English fallback), so
 * this promise always resolves; it never rejects and never blocks forever.
 * The English path stays fully synchronous: no promise, no waiting.
 */
export const initialLocaleReady: Promise<void> | null =
  initialLanguage !== 'en' ? loadLocaleResource(initialLanguage) : null;

// Merge module-bundled translations (nav keys for regional modules, etc.)
import { getModuleTranslations } from '@/modules/_registry';
const moduleTrans = getModuleTranslations();
for (const [lng, keys] of Object.entries(moduleTrans)) {
  if (keys && typeof keys === 'object') {
    i18n.addResourceBundle(lng, 'translation', keys, true, true);
  }
}

export default i18n;
