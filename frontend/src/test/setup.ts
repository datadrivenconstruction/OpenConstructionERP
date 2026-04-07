// @ts-nocheck
import '@testing-library/jest-dom';


// Mock i18next. We expose the same surface that production code imports
// from `react-i18next` — `useTranslation`, `Trans`, AND `initReactI18next`
// (a noop plugin shape). Components that pull `t(key)` get sensible
// English fallbacks via `defaultValue`; components that import
// `initReactI18next` (because they live downstream of `app/i18n.ts`) get
// a no-op plugin so the import side-effect doesn't crash.
const noopPlugin = { type: '3rdParty', init: () => {} };
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (typeof opts === 'object' && opts !== null && 'defaultValue' in opts) {
        return opts.defaultValue as string;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: noopPlugin,
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// Mock react-router-dom navigation
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });
