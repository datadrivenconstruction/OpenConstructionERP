import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider, MutationCache, QueryCache } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './app/App';
import { notifyQueryError } from '@/shared/lib/queryErrorToast';
import { notifyMutationError } from '@/shared/lib/mutationErrorToast';
import { initialLocaleReady } from './app/i18n';
import { startAccountLanguageSync } from './app/accountLanguage';
import { applyStoredUiScale } from '@/shared/lib/uiScale';
import { retireStaleCaches } from './pwa/retireStaleCaches';
import './index.css';

// Desktop only: put the saved text size back on the webview as early as
// possible. The mount at the bottom of this file waits for it.
const uiScaleReady = applyStoredUiScale();

(window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL = '/cesium/';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 120_000, // 2min — data considered fresh, reduces redundant refetches on tab switch
      gcTime: 5 * 60_000, // 5min — keep in cache for 5 min after unmount
      // Offline-first: try the cache before spinning a 300s AbortController.
      // `api.ts` falls back to IndexedDB via offlineStore on network errors,
      // so we never want to retry a query that's going to fail for the same
      // reason anyway.
      networkMode: 'offlineFirst',
      retry: (count, error) => {
        if (!navigator.onLine) return false;
        if (error && typeof error === 'object') {
          // A client-side timeout/abort: the backend is already slow, so a
          // retry just times out again ~45s later and shows a second toast.
          if ((error as { isTimeout?: boolean }).isTimeout) return false;
          if ((error as { name?: string }).name === 'AbortError') return false;
          // 4xx responses are deterministic — don't retry.
          if ('status' in error) {
            const status = (error as { status: number }).status;
            if (status >= 400 && status < 500) return false;
          }
        }
        return count < 1;
      },
      refetchOnWindowFocus: false, // opt-in per query; global refetch caused unnecessary re-renders on tab switch
    },
    mutations: {
      // Mutations while offline are queued by offlineStore and replayed on
      // reconnect — no need for react-query-level retry.
      networkMode: 'offlineFirst',
      retry: 0,
    },
  },
  // Queries had no global error handling at all, so a request that came back
  // with nothing showed as an empty screen: components read `data ?? []` and
  // render the same table for "no rows" and "no answer". The handler decides
  // what is worth saying; see `queryErrorToast.ts` for what it stays quiet on.
  queryCache: new QueryCache({
    onError: (error, query) => notifyQueryError(error, query),
  }),
  mutationCache: new MutationCache({
    onSuccess: (_data, _variables, _context, mutation) => {
      // Global: after ANY successful mutation, invalidate related queries
      // This ensures lists refresh immediately after create/update/delete
      const key = mutation.options.mutationKey;
      if (key && Array.isArray(key) && key.length > 0) {
        queryClient.invalidateQueries({ queryKey: [key[0]] });
      }
    },
    // Stays quiet when the screen reports the failure itself; see
    // `mutationErrorToast.ts`.
    onError: (error, _variables, _context, mutation) => notifyMutationError(error, mutation),
  }),
});

// Stamp the root element with an origin token. Survives in the live DOM
// and any saved-page snapshot — looks like a deterministic build id.
// Decodes to "DDC-CWICR-OE-2026" by reversing the hex.
const __rootEl = document.getElementById('root')!;
__rootEl.setAttribute(
  'data-build-rev',
  '4443432d4357494352-4f452d32303236',
);

// When a new build is deployed while a tab stays open, client-side navigation
// to a not-yet-loaded route tries to import a chunk hash that no longer exists
// on the server ("Failed to fetch dynamically imported module"). Vite fires
// `vite:preloadError` for exactly that case. Reload once to pull the fresh
// index.html and the current chunk graph. The timestamp guard caps auto-reloads
// so a genuine outage cannot turn into a reload loop.
window.addEventListener('vite:preloadError', () => {
  const KEY = 'oe_chunk_reload_at';
  const last = Number(sessionStorage.getItem(KEY) || 0);
  if (Date.now() - last > 10_000) {
    sessionStorage.setItem(KEY, String(Date.now()));
    window.location.reload();
  }
});

// Earlier builds let the service worker cache cross-origin images, failures
// included, for 30 days (see pwa/staticAssetRoute.ts). The lane now has a new
// name; dropping the old cache lets those visitors see the real images
// without a hard reload. Fire and forget, it never throws.
void retireStaleCaches();
startAccountLanguageSync();

// The public demo is served under /demo (Caddy strips the prefix before it
// reaches the backend, but the browser URL keeps it), so react-router needs a
// matching basename there. Desktop and localhost serve at the root, where the
// path never starts with /demo, so the basename stays undefined ("/").
const routerBasename =
  window.location.pathname === '/demo' || window.location.pathname.startsWith('/demo/')
    ? '/demo'
    : undefined;

const renderApp = () => {
  ReactDOM.createRoot(__rootEl).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={routerBasename}>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </React.StrictMode>,
  );
};

// A saved non-English language must be IN the i18next store before the first
// paint, or that first frame renders through the English fallback — the
// "English flash" every non-English session used to open with. The cap bounds
// the wait: if the chunk stalls, mount anyway in English and let the existing
// re-render-on-arrival path recover. English boots keep today's fully
// synchronous mount (`initialLocaleReady` is null — no promise, no timer).
//
// What this costs, measured rather than assumed. This comment used to say the
// wait happens "during a window where the user already sees the plain
// index.html shell, so nothing visibly changes". There is no such shell:
// index.html carries an empty `<div id="root">`, so for the whole of this wait
// the document has no app DOM in it at all — no `<main>`, no header, no
// sidebar. The state is route-independent: the wait is over before React, the
// router or any page component exists, so a probe that samples here is
// measuring the boot and not whatever page it thinks it opened.
//
// Width of the window on the Vite dev server, cold loads of /settings, React
// mount timed in-page against navigation start: English 0 of 25 reads landed
// in it, German 24 of 25, Persian 25 of 25 — so it tracks non-English, not
// RTL. Mount lands ~0.5 s after DOMContentLoaded on an English boot and
// ~1.3-2.0 s on a non-English one. Injecting a 5 s stall on the locale module
// pins mount at DCL + ~2.5 s (this cap, plus React's first render) instead of
// DCL + 5 s, which is what proves the wait below is what holds the document
// empty. Production ships the locale as a ~50 KB gzip chunk rather than a 4 MB
// dev module, so the window is far narrower there — narrower, not absent.
const LOCALE_MOUNT_CAP_MS = 2000;
const mountWhenLocaleReady = () => {
  if (initialLocaleReady) {
    let mounted = false;
    const mountOnce = () => {
      if (!mounted) {
        mounted = true;
        renderApp();
      }
    };
    void initialLocaleReady.then(mountOnce);
    window.setTimeout(mountOnce, LOCALE_MOUNT_CAP_MS);
  } else {
    renderApp();
  }
};

// The same reasoning for the saved text size in the desktop app, which is a
// native webview zoom set over IPC (see `uiScale.ts`). The call went out at the
// top of this file; mounting after it answers means the first app frame is
// painted at the chosen size instead of at 100% and then jumping. A local IPC
// round trip is a few milliseconds, so the cap only matters if the shell does
// not answer at all. `uiScaleReady` is null in the browser and at the default
// size, which keeps those boots exactly as they were.
const UI_SCALE_MOUNT_CAP_MS = 300;
if (uiScaleReady) {
  let started = false;
  const startOnce = () => {
    if (!started) {
      started = true;
      mountWhenLocaleReady();
    }
  };
  void uiScaleReady.then(startOnce, startOnce);
  window.setTimeout(startOnce, UI_SCALE_MOUNT_CAP_MS);
} else {
  mountWhenLocaleReady();
}
