// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// @ts-nocheck
// Pin the test process to UTC so any test that formats dates with local-time
// getters (e.g. buildExportFilename) is timezone-stable, regardless of the
// machine running it or how the fixture Date was constructed. Set before any
// module reads the timezone.
process.env.TZ = 'UTC';

// The assignment above lands in a worker process, where Node re-reads the zone
// after it changes. It does NOT land in a worker thread: `--pool=threads`
// shares one process, the zone is already resolved by the time this file runs,
// and the write is accepted and ignored. The symptom is a handful of date
// tests failing by exactly the host's offset while every other test passes,
// which reads like a bug in the code under test rather than in how the run was
// invoked. Measured on this repo at +0200: default pool 39 passed, the same
// file under `--pool=threads` 5 failed, and `TZ=UTC` in the environment before
// node starts made those 5 pass again.
//
// So say it out loud instead of letting five assertions imply it. Anyone who
// reaches for `--pool=threads` as a load workaround gets one sentence naming
// the cause rather than a date arithmetic mystery.
const resolvedZone = new Intl.DateTimeFormat().resolvedOptions().timeZone;
if (process.env.TZ === 'UTC' && resolvedZone !== 'UTC' && new Date().getTimezoneOffset() !== 0) {
  throw new Error(
    `Tests must run in UTC, but this worker resolved ${resolvedZone}. Setting process.env.TZ ` +
      'here cannot move a worker thread. Drop --pool=threads, or put TZ=UTC in the environment ' +
      'before node starts.',
  );
}

import '@testing-library/jest-dom';
import { configure } from '@testing-library/dom';

// Cancel timers that would otherwise outlive the jsdom environment.
//
// When a test file finishes, vitest deletes the jsdom globals. A timer armed
// during that file is a plain Node timer and is NOT deleted with them, so it
// still fires afterwards, into a world where `window` no longer exists. AG
// Grid arms exactly such a timer: `sizeColumnsToFit` retries on a 0/100/500 ms
// chain while the grid measures 0 px wide. Stubbing layout does not settle it -
// both grid tests that stub `clientWidth` still drove ag-grid to its zero-width
// warning on CI, because the retry lands once `cleanup()` has detached the
// element and the stubbed getters no longer describe an attached box. The
// 500 ms link lands after teardown, reaches React's `getCurrentEventPriority`,
// which reads `window`, and the run dies with `ReferenceError: window is not
// defined` raised outside any test. vitest counts no failed test and still
// exits 1, so the summary reads 634 files / 7271 passed above a red exit code.
//
// Unmounting does not help: measured on BOQGrid, the retry survives
// `cleanup()` untouched, because ag-grid armed it and nothing in the React
// tree owns it. Whether it also becomes visible is a race the worker usually
// wins by exiting first, which is why this reddens ubuntu and not macOS or
// Windows, and why it lands on commits that touch only backend files.
//
// So track what a file arms and cancel whatever is still pending once its last
// test has run. Inside a file nothing changes: timers keep working normally,
// and only the ones that would have crossed the teardown boundary are dropped.
type TimerHandle = ReturnType<typeof setTimeout>;
type TimerHandler = (...args: unknown[]) => void;
type TimerFn = (handler: TimerHandler | string, delay?: number, ...args: unknown[]) => TimerHandle;
type ClearFn = (handle?: TimerHandle) => void;

const pendingTimers = new Set<TimerHandle>();
const realSetTimeout = globalThis.setTimeout as unknown as TimerFn;
const realSetInterval = globalThis.setInterval as unknown as TimerFn;
const realClearTimeout = globalThis.clearTimeout as unknown as ClearFn;
const realClearInterval = globalThis.clearInterval as unknown as ClearFn;

function trackTimers(real: TimerFn, repeating: boolean): TimerFn {
  return function tracked(
    handler: TimerHandler | string,
    delay?: number,
    ...args: unknown[]
  ): TimerHandle {
    // `setTimeout("code string")` has no callback to wrap; pass it straight
    // through rather than guessing at its shape.
    if (typeof handler !== 'function') {
      const raw = real.call(globalThis, handler, delay, ...args);
      pendingTimers.add(raw);
      return raw;
    }
    let handle: TimerHandle | undefined;
    const wrapped = (...inner: unknown[]): void => {
      // A one-shot timer is spent once it fires; an interval stays armed.
      if (!repeating && handle !== undefined) pendingTimers.delete(handle);
      handler(...inner);
    };
    handle = real.call(globalThis, wrapped, delay, ...args);
    pendingTimers.add(handle);
    return handle;
  };
}

globalThis.setTimeout = trackTimers(realSetTimeout, false) as unknown as typeof globalThis.setTimeout;
globalThis.setInterval = trackTimers(realSetInterval, true) as unknown as typeof globalThis.setInterval;
globalThis.clearTimeout = ((handle?: TimerHandle): void => {
  if (handle !== undefined) pendingTimers.delete(handle);
  realClearTimeout(handle);
}) as typeof globalThis.clearTimeout;
globalThis.clearInterval = ((handle?: TimerHandle): void => {
  if (handle !== undefined) pendingTimers.delete(handle);
  realClearInterval(handle);
}) as typeof globalThis.clearInterval;

// Runs once the file's last test has finished and before vitest tears the
// environment down, which is the only boundary this needs to beat.
afterAll(() => {
  for (const handle of pendingTimers) {
    realClearTimeout(handle);
    realClearInterval(handle);
  }
  pendingTimers.clear();
});

// Under full-suite parallel load (worker starvation on 2-core CI runners and
// local runs) the default 1s `findBy*`/`waitFor` budget intermittently expires
// before chained React Query mocks resolve and re-render. 5s only raises the
// upper bound — fast tests stay exactly as fast.
configure({ asyncUtilTimeout: 5000 });

// Node's `undici`-backed `fetch` rejects an `AbortSignal` created via the
// jsdom-provided `AbortController` ("Expected signal to be an instance of
// AbortSignal") because the two constructors come from different realms.
// jsdom replaces the global classes, leaving production code (which calls
// `new AbortController()` against the active global) with signals that
// undici treats as foreign. Wrap `fetch` so any non-native signal is silently
// dropped — tests don't exercise abort behaviour and MSW intercepts requests
// regardless of the signal field.
{
  const originalFetch = globalThis.fetch;
  if (typeof originalFetch === 'function') {
    globalThis.fetch = ((input, init) => {
      if (init && 'signal' in init) {
        // Drop the realm-mismatched signal; keep the rest of the init.
        const { signal: _signal, ...rest } = init;
        return originalFetch(input, rest);
      }
      return originalFetch(input, init);
    }) as typeof fetch;
  }
}


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
        // Mirror the two i18next behaviours real components rely on:
        // (1) pick the ``_other`` plural default whenever ``count`` is
        // present and not 1 (English plural rule), and (2) interpolate
        // ``{{var}}`` placeholders from the options. Without this the mock
        // returned templates like "{{count}} record" verbatim.
        let template = opts.defaultValue as string;
        if (
          'count' in opts &&
          opts.count !== 1 &&
          typeof opts.defaultValue_other === 'string'
        ) {
          template = opts.defaultValue_other as string;
        }
        return template.replace(/\{\{(\w+)\}\}/g, (_match, name) =>
          name in opts ? String(opts[name]) : `{{${name}}}`,
        );
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: noopPlugin,
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
}));

// react-router-dom: stub the navigation hooks ONLY where no Router is mounted.
//
// This mock used to replace useNavigate / useParams / useSearchParams for the
// whole suite. Components rendered without a Router need that, otherwise the
// real hooks throw "may be used only in the context of a <Router>". But 126
// test files mount a real <MemoryRouter>, 43 of them with initialEntries that
// name a route or a query string, and every one of those was reading the stub:
// useParams answered {} whatever the path said, useSearchParams was always
// empty, and a click that should have navigated called a vi.fn(). Deep-link
// and search-param tests were therefore testing the mock, and passing.
//
// The hooks below ask the real module whether a Router is above them
// (useInRouterContext is a plain useContext read, stable for the life of a
// component) and delegate to the real hook when there is one. A test that
// mounts a Router gets real routing; a test that does not keeps the stubs.
// A file that needs a stub inside a Router still mocks the module itself, as
// 33 files already do; a per-file vi.mock overrides this one.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => (actual.useInRouterContext() ? actual.useNavigate() : vi.fn()),
    useParams: () => (actual.useInRouterContext() ? actual.useParams() : {}),
    useSearchParams: (init?: Parameters<typeof actual.useSearchParams>[0]) =>
      actual.useInRouterContext() ? actual.useSearchParams(init) : [new URLSearchParams(), vi.fn()],
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
