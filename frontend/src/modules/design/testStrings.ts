// Design module (ERP side of the design editor link).
/** Strings for the module's tests: the app locale bundles are the only source. */
import de from '@/app/locales/de';
import en from '@/app/locales/en';
import ru from '@/app/locales/ru';

export const EN: Record<string, string> = en.translation;
export const RU: Record<string, string> = ru.translation;
export const DE: Record<string, string> = de.translation;

const fill = (s: string, o?: Record<string, unknown>) =>
  s.replace(/\{\{\s*(\w+)\s*\}\}/g, (m, n: string) => (o && n in o ? String(o[n]) : m));

/** English from the app bundle, as the running app shows it; stable across renders. */
export function tEn(key: string, o?: Record<string, unknown>): string {
  const count = typeof o?.count === 'number' ? o.count : null;
  const plural = count === null ? undefined : EN[`${key}_${count === 1 ? 'one' : 'other'}`];
  const raw = plural ?? EN[key] ?? (typeof o?.defaultValue === 'string' ? o.defaultValue : key);
  return fill(raw, o);
}

/** `vi.mock('react-i18next', async () => (await import('./testStrings')).i18nMock())` in a module test. */
export function i18nMock() {
  const value = { t: tEn, i18n: { language: 'en', resolvedLanguage: 'en', changeLanguage: async () => undefined } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children?: unknown }) => children,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children,
  };
}
